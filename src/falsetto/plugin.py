"""The pytest adapter.

It runs each graded check as whole, unlogged pytest protocols (setup, call, teardown)
and hands the observations to :mod:`falsetto.core`, which is the only place a verdict
is computed. The positive run's reports are then logged once, so pytest's own
machinery (``-x``, ``--lf``, ``-r``, JUnit, exit status) sees a false check as the
failure it is. Verdicts travel on the call report's ``user_properties`` as one JSON
string, so they survive serialization under xdist and appear in JUnit output.

The plugin is inert unless enabled with ``--falsetto`` or the ``falsetto`` ini key.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from _pytest.runner import runtestprotocol

from . import __version__, core
from .core import Outcome, RunResult
from .declaration import Declaration, get_declaration
from .verdict import Reason, Result, Verdict

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter

PROPERTY = "falsetto"
EXCLUDED_PROPERTY = "falsetto.excluded"
MARKER = "no_proof"
DEFAULT_EXPECT: tuple[type[BaseException], ...] = (AssertionError, pytest.fail.Exception)
PASSTHROUGH: tuple[type[BaseException], ...] = (
    KeyboardInterrupt,
    SystemExit,
    pytest.exit.Exception,
)


@dataclass(frozen=True)
class Settings:
    enabled: bool
    strict: bool
    json_path: str | None


SETTINGS = pytest.StashKey[Settings]()
EXCINFO = pytest.StashKey[Any]()


def _settings(config: pytest.Config) -> Settings:
    return config.stash.get(SETTINGS, Settings(False, False, None))


def _is_xfail(report: pytest.TestReport) -> bool:
    return hasattr(report, "wasxfail")


def _summary(report: pytest.TestReport) -> str:
    lines = [line for line in report.longreprtext.strip().splitlines() if line.strip()]
    return (lines[-1] if lines else "")[:300]


def _location(excinfo: Any) -> str | None:
    try:
        entry = excinfo.traceback[-1]
        return f"{entry.path}:{entry.lineno + 1}"
    except Exception:
        return None


def verdict_of(report: pytest.TestReport) -> dict[str, Any] | None:
    """The verdict record carried by a call-phase report, or None."""
    if report.when != "call":
        return None
    for name, value in report.user_properties:
        if name != PROPERTY or not isinstance(value, str):
            continue
        try:
            loaded = json.loads(value)
        except ValueError:
            continue
        if isinstance(loaded, dict) and "verdict" in loaded and "reason" in loaded:
            return loaded
    return None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("falsetto")
    group.addoption(
        "--falsetto",
        action="store_true",
        default=False,
        dest="falsetto",
        help="Grade every function-based check: proven, failed, false or unproven.",
    )
    group.addoption(
        "--falsetto-strict",
        action="store_true",
        default=False,
        dest="falsetto_strict",
        help="Enable Falsetto and count unproven checks as failures.",
    )
    group.addoption(
        "--falsetto-json",
        default=None,
        dest="falsetto_json",
        metavar="PATH",
        help="Write a JSON report of every verdict to PATH.",
    )
    parser.addini("falsetto", "Enable Falsetto grading.", type="bool", default=False)
    parser.addini(
        "falsetto_strict", "Count unproven checks as failures.", type="bool", default=False
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARKER}(reason): Falsetto does not grade this check; it is counted as excluded, "
        "never as a pass.",
    )
    strict = bool(config.getoption("falsetto_strict") or config.getini("falsetto_strict"))
    enabled = bool(config.getoption("falsetto") or config.getini("falsetto") or strict)
    settings = Settings(enabled, strict, config.getoption("falsetto_json"))
    config.stash[SETTINGS] = settings
    if enabled:
        config.pluginmanager.register(_Session(settings), "falsetto-session")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when == "call":
        item.stash[EXCINFO] = call.excinfo
    return report


def _gradable(item: pytest.Item) -> bool:
    """Falsetto grades function-based checks; doctests and custom items are pytest's."""
    return isinstance(item, pytest.Function)


def _observe(item: pytest.Item, reports: list[pytest.TestReport]) -> RunResult | None:
    """What one protocol run did, or None when the check is not gradable (xfail)."""
    by_when = {r.when: r for r in reports}
    setup, call, teardown = by_when.get("setup"), by_when.get("call"), by_when.get("teardown")
    if setup is None:
        return RunResult(Outcome.ERRORED, summary="no setup report")
    if setup.failed:
        return RunResult(Outcome.ERRORED, summary=_summary(setup))
    if setup.skipped:
        return RunResult(Outcome.SKIPPED, summary=_summary(setup))
    if call is None:
        return RunResult(Outcome.ERRORED, summary="no call report")
    if _is_xfail(call):
        return None
    if call.failed:
        excinfo = item.stash.get(EXCINFO, None)
        exc = excinfo.value if excinfo is not None else None
        return RunResult(Outcome.FAILED, exc, _location(excinfo), _summary(call))
    if teardown is not None and teardown.failed:
        return RunResult(Outcome.ERRORED, summary=_summary(teardown))
    if call.skipped:
        return RunResult(Outcome.SKIPPED, summary=_summary(call))
    return RunResult(Outcome.PASSED)


def _grade(
    item: pytest.Item,
    reports: list[pytest.TestReport],
    nextitem: pytest.Item | None,
    decl: Declaration | None,
) -> Result | None:
    marker = item.get_closest_marker(MARKER)
    if marker is not None:
        reason = marker.args[0] if marker.args else marker.kwargs.get("reason", "")
        for report in reports:
            if report.when in ("call", "teardown"):
                report.user_properties.append((EXCLUDED_PROPERTY, str(reason)))
        return None
    # Bound now, before the declared change is applied: a declaration that patches
    # these names must affect the session it targets, never the runs grading it.
    observe, protocol = _observe, runtestprotocol
    positive = observe(item, reports)
    if positive is None:
        return None

    def run() -> RunResult:
        observed = observe(item, protocol(item, log=False, nextitem=nextitem))
        if observed is None:
            return RunResult(Outcome.ERRORED, summary="the run produced no gradable call report")
        return observed

    return core.prove(run, decl, positive, default_expect=DEFAULT_EXPECT, passthrough=PASSTHROUGH)


def _fails_build(result: Result, strict: bool) -> bool:
    if result.reason is Reason.INTERNAL_ERROR:
        return True
    if result.verdict is Verdict.FALSE:
        return True
    return strict and result.verdict is Verdict.UNPROVEN


def _longrepr(result: Result) -> str:
    if result.reason is Reason.INTERNAL_ERROR:
        return (
            "falsetto: internal error while grading this check; its verdict is unproven.\n"
            f"{result.detail or ''}"
        )
    head = "FALSE" if result.verdict is Verdict.FALSE else "UNPROVEN (strict)"
    lines = [f"{head}: {result.message}."]
    if result.declared:
        lines.append(f"  declared: {result.declared}")
    if result.detail:
        lines.append(f"  detail: {result.detail}")
    if result.hint:
        lines.append(f"  hint: {result.hint}")
    return "\n".join(lines)


def _attach(reports: list[pytest.TestReport], result: Result | None, settings: Settings) -> None:
    call = next((r for r in reports if r.when == "call"), None)
    if result is None or call is None:
        return
    # The JUnit writer reads properties from the teardown report; the tally and the
    # status hook read the call report. The record rides both.
    record = (PROPERTY, json.dumps(result.to_dict()))
    for report in reports:
        if report.when in ("call", "teardown"):
            report.user_properties.append(record)
    if _fails_build(result, settings.strict):
        call.outcome = "failed"
        call.longrepr = _longrepr(result)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> bool | None:
    settings = _settings(item.config)
    if not settings.enabled or not _gradable(item):
        return None
    ihook = item.ihook
    ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    reports = runtestprotocol(item, log=False, nextitem=nextitem)
    decl = None
    try:
        decl = get_declaration(getattr(item, "obj", None))
        result = _grade(item, reports, nextitem, decl)
    except PASSTHROUGH:
        raise
    except BaseException as e:
        result = core.internal_error(e, decl)
    _attach(reports, result, settings)
    for report in reports:
        ihook.pytest_runtest_logreport(report=report)
    ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True


_STATUS: dict[str, tuple[str, str, str]] = {
    Verdict.PROVEN.value: ("proven", ".", "PROVEN"),
    Verdict.FALSE.value: ("failed", "!", "FALSE"),
}


def pytest_report_teststatus(
    report: pytest.TestReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    if not _settings(config).enabled or report.when != "call" or _is_xfail(report):
        return None
    info = verdict_of(report)
    if info is None:
        return None
    if info["reason"] == Reason.INTERNAL_ERROR.value:
        return ("failed", "!", "FALSETTO-ERROR")
    if info["verdict"] == Verdict.UNPROVEN.value:
        return ("failed", "?", "UNPROVEN") if report.failed else ("unproven", "?", "UNPROVEN")
    status = _STATUS.get(str(info["verdict"]))
    if status is not None and status[0] == "proven" and not report.passed:
        return None
    return status


@dataclass
class _Entry:
    status: str = "ran"
    record: dict[str, Any] | None = None
    excluded: str | None = None


@dataclass
class Tally:
    """Per-session accounting fed by logged reports, so it is right under xdist too."""

    items: dict[str, _Entry] = field(default_factory=dict)

    def note(self, report: pytest.TestReport) -> None:
        entry = self.items.setdefault(report.nodeid, _Entry())
        if report.when == "setup":
            if report.failed:
                entry.status = "errored"
            elif report.skipped:
                entry.status = "skipped"
        elif report.when == "call":
            for name, value in report.user_properties:
                if name == EXCLUDED_PROPERTY:
                    entry.excluded = str(value)
                    entry.status = "excluded"
            record = verdict_of(report)
            if record is not None:
                entry.record = record
                entry.status = "graded"
            elif entry.status == "excluded":
                pass
            elif _is_xfail(report):
                entry.status = "xfail"
            elif report.skipped:
                entry.status = "skipped"
            elif entry.status == "ran":
                entry.status = "not gradable"
        elif (
            report.when == "teardown" and report.failed and entry.status in ("ran", "not gradable")
        ):
            entry.status = "errored"

    def verdicts(self) -> dict[str, int]:
        counts = {v.value: 0 for v in Verdict}
        for entry in self.items.values():
            if entry.record is not None:
                counts[str(entry.record["verdict"])] += 1
        return counts

    def statuses(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.items.values():
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts

    @property
    def run(self) -> int:
        return len(self.items)

    @property
    def graded(self) -> int:
        return sum(1 for e in self.items.values() if e.record is not None)

    @property
    def gradable(self) -> int:
        return sum(1 for e in self.items.values() if e.status != "not gradable")

    def line(self) -> str:
        v = self.verdicts()
        extras = ", ".join(
            f"{n} {status}"
            for status, n in self.statuses().items()
            if status not in ("graded", "ran") and n
        )
        tail = f"{self.graded} graded of {self.run} run" + (f"; {extras}" if extras else "")
        return (
            f"falsetto: {v['proven']} proven, {v['failed']} failed, {v['false']} false, "
            f"{v['unproven']} unproven ({tail})"
        )


class _Session:
    """Session-level accounting and reporting, registered only when enabled."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tally = Tally()

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.tally.note(report)

    def strict_zero_graded(self) -> bool:
        return self.settings.strict and self.tally.gradable > 0 and self.tally.graded == 0

    @pytest.hookimpl(trylast=True)
    def pytest_terminal_summary(self, terminalreporter: TerminalReporter) -> None:
        tally = self.tally
        if tally.run == 0:
            return
        tr = terminalreporter
        tr.write_sep("=", "falsetto")
        for nodeid, entry in tally.items.items():
            record = entry.record
            if record is None or record["verdict"] not in (
                Verdict.FALSE.value,
                Verdict.UNPROVEN.value,
            ):
                continue
            word = "FALSE" if record["verdict"] == Verdict.FALSE.value else "UNPROVEN"
            if record["reason"] == Reason.INTERNAL_ERROR.value:
                word = "FALSETTO-ERROR"
            tr.write_line(f"{word} {nodeid}: {record['message']}")
            if record.get("declared"):
                tr.write_line(f"    declared: {record['declared']}")
            if record.get("detail") and record["reason"] != Reason.INTERNAL_ERROR.value:
                tr.write_line(f"    detail: {record['detail']}")
            if record.get("hint"):
                tr.write_line(f"    hint: {record['hint']}")
        if self.strict_zero_graded():
            tr.write_line("falsetto: strict: no check was graded", red=True)
        tr.write_line(tally.line())

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if hasattr(session.config, "workerinput"):
            return
        if self.strict_zero_graded() and session.exitstatus == 0:
            session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)
        if self.settings.json_path:
            self.write_json(Path(self.settings.json_path))

    def write_json(self, path: Path) -> None:
        tally = self.tally
        payload = {
            "falsetto": __version__,
            "totals": {
                **tally.verdicts(),
                "graded": tally.graded,
                "run": tally.run,
                **tally.statuses(),
            },
            "line": tally.line(),
            "checks": [
                {"nodeid": nodeid, **entry.record}
                for nodeid, entry in tally.items.items()
                if entry.record is not None
            ],
            "not_graded": [
                {"nodeid": nodeid, "status": entry.status, "excluded": entry.excluded}
                for nodeid, entry in tally.items.items()
                if entry.record is None
            ],
        }
        path.write_text(json.dumps(payload, indent=2))
