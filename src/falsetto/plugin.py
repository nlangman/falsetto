"""The pytest adapter.

For a declared check it runs whole, unlogged pytest protocols (setup, call, teardown):
the positive run, then a control run, then the negative run with the declared change
applied before setup. Every run of a check tears fixtures down to the same boundary,
the one the declaration's scope names, so a verdict never depends on what pytest
happens to run next. Each run is observed through its reports and handed to
:mod:`falsetto.core`, the only place a verdict is computed. The positive run's
reports are logged once, with the verdict attached as one JSON record on the call and
teardown reports, so pytest's own machinery (``-x``, ``--lf``, ``-r``, JUnit, the exit
status) sees a false check as the failure it is.

The plugin is inert unless enabled with ``--falsetto``, ``--falsetto-strict`` or the
``falsetto`` and ``falsetto_strict`` ini keys.
"""

from __future__ import annotations

import contextlib
import json
import traceback
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

try:
    from _pytest.runner import runtestprotocol
except ImportError as e:  # pragma: no cover - a future pytest could move this
    raise ImportError(
        "falsetto supports pytest 8 and 9; this pytest lacks the run protocol it uses"
    ) from e

from . import __version__, core
from .core import Outcome, RunResult
from .declaration import Declaration, get_declaration
from .verdict import Reason, Result, Verdict

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter

PROPERTY = "falsetto.verdict"
EXCLUDED_PROPERTY = "falsetto.excluded"
MARKER = "no_proof"
DEFAULT_EXPECT: tuple[type[BaseException], ...] = (AssertionError, pytest.fail.Exception)
PASSTHROUGH: tuple[type[BaseException], ...] = (
    KeyboardInterrupt,
    SystemExit,
    pytest.exit.Exception,
)
_SCOPE_RANK = {"function": 0, "class": 1, "module": 2, "package": 3, "session": 4}
_EVIDENCE_LINES = 12


@dataclass(frozen=True)
class Settings:
    enabled: bool
    strict: bool
    json_path: str | None


SETTINGS = pytest.StashKey[Settings]()
EXCINFO = pytest.StashKey[Any]()


def _settings(config: pytest.Config) -> Settings:
    return config.stash.get(SETTINGS, Settings(False, False, None))


def _ini(config: pytest.Config, key: str) -> bool:
    return bool(config.getini(key))


def _runs_nothing(config: pytest.Config) -> bool:
    """Modes that collect or set up but never call a check."""
    return any(
        bool(config.getoption(name, False)) for name in ("setuponly", "setupplan", "collectonly")
    )


def _is_xfail(report: pytest.TestReport) -> bool:
    return hasattr(report, "wasxfail")


def _summary(report: pytest.TestReport) -> str:
    """The failure's own message: pytest's ``E`` lines, or the last line as a fallback."""
    lines = [line for line in report.longreprtext.splitlines() if line.strip()]
    messages = [line[1:].strip() for line in lines if line.startswith("E ")]
    text = " ".join(messages[:3]) if messages else (lines[-1] if lines else "")
    return text[:300]


def _location(excinfo: Any) -> str | None:
    try:
        entry = excinfo.traceback[-1]
        return f"{entry.path}:{entry.lineno + 1}"
    except (AttributeError, IndexError, TypeError):
        return None


def _last_property(report: pytest.TestReport, name: str) -> Any:
    for prop_name, value in reversed(report.user_properties):
        if prop_name == name:
            return value
    return None


def verdict_of(report: pytest.TestReport) -> dict[str, Any] | None:
    """The verdict record a call or teardown report carries, or None.

    The record Falsetto attached is the last one, so it wins over anything a test or a
    fixture recorded under the same name.
    """
    if report.when not in ("call", "teardown"):
        return None
    value = _last_property(report, PROPERTY)
    if not isinstance(value, str):
        return None
    try:
        loaded = json.loads(value)
    except ValueError:
        return None
    if isinstance(loaded, dict) and "verdict" in loaded and "reason" in loaded:
        return loaded
    return None


def excluded_reason(report: pytest.TestReport) -> str | None:
    if report.when not in ("call", "teardown"):
        return None
    value = _last_property(report, EXCLUDED_PROPERTY)
    return value if isinstance(value, str) else None


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


def _warn_competing_protocols(config: pytest.Config) -> None:
    impls = config.pluginmanager.hook.pytest_runtest_protocol.get_hookimpls()
    others = [
        str(getattr(impl, "plugin_name", "?"))
        for impl in impls
        if not getattr(impl, "hookwrapper", False)
        and not getattr(impl, "wrapper", False)
        and getattr(impl, "plugin_name", "") not in ("runner", "falsetto")
    ]
    if others:
        config.issue_config_time_warning(
            pytest.PytestWarning(
                "falsetto runs the test protocol itself; these plugins also implement "
                f"pytest_runtest_protocol and will not run while falsetto is enabled: {others}"
            ),
            stacklevel=2,
        )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARKER}(reason): Falsetto does not grade this check; it is counted as excluded, "
        "never as a pass. A reason is required.",
    )
    strict = bool(config.getoption("falsetto_strict") or _ini(config, "falsetto_strict"))
    enabled = bool(config.getoption("falsetto") or _ini(config, "falsetto") or strict)
    settings = Settings(enabled, strict, config.getoption("falsetto_json"))
    config.stash[SETTINGS] = settings
    if enabled:
        config.pluginmanager.register(_Session(settings, config), "falsetto-session")
        _warn_competing_protocols(config)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when == "call" and _settings(item.config).enabled:
        item.stash[EXCINFO] = call.excinfo
    return report


def _gradable(item: pytest.Item) -> bool:
    """Falsetto grades function-based checks; doctests and custom items are pytest's."""
    return isinstance(item, pytest.Function)


def _observe(
    item: pytest.Item, reports: list[pytest.TestReport], *, graded_run: bool
) -> RunResult | None:
    """What one protocol run did, or None when the check is not gradable (xfail).

    For the control and negative runs a failed teardown makes the run errored even when
    the call failed, because a change that also broke teardown proves nothing.
    """
    by_when = {r.when: r for r in reports}
    setup, call, teardown = by_when.get("setup"), by_when.get("call"), by_when.get("teardown")
    if setup is None:
        return RunResult(Outcome.ERRORED, summary="no setup report")
    if setup.failed:
        return RunResult(Outcome.ERRORED, summary=_summary(setup), longrepr=_text(setup))
    if setup.skipped:
        return RunResult(Outcome.SKIPPED, summary=_summary(setup))
    if call is None:
        return RunResult(Outcome.ERRORED, summary="no call report")
    if _is_xfail(call):
        return None
    if teardown is not None and teardown.failed and (graded_run or not call.failed):
        return RunResult(Outcome.ERRORED, summary=_summary(teardown), longrepr=_text(teardown))
    if call.failed:
        excinfo = item.stash.get(EXCINFO, None)
        exc = excinfo.value if excinfo is not None else None
        return RunResult(Outcome.FAILED, exc, _location(excinfo), _summary(call), _text(call))
    if call.skipped:
        return RunResult(Outcome.SKIPPED, summary=_summary(call))
    return RunResult(Outcome.PASSED)


def _text(report: pytest.TestReport) -> str:
    return report.longreprtext[-core.EVIDENCE_LIMIT :]


def _boundary(item: pytest.Item, scope: str) -> Any:
    """The node whose chain marks what stays set up between runs of this check."""
    if scope == "session":
        return None
    if scope == "function":
        return item.parent
    kind: type[pytest.Collector] = pytest.Class if scope == "class" else pytest.Module
    for node in reversed(item.listchain()):
        if isinstance(node, kind):
            return node.parent
    return item.parent


def _wider_fixtures(item: pytest.Item, scope: str) -> list[str]:
    """Fixtures the check requests directly whose scope the declaration does not rebuild."""
    info = getattr(item, "_fixtureinfo", None)
    if info is None:
        return []
    limit = _SCOPE_RANK.get(scope, 0)
    found = []
    for name in getattr(info, "argnames", ()):
        defs = getattr(info, "name2fixturedefs", {}).get(name) or ()
        if not defs:
            continue
        fixture_scope = str(getattr(defs[-1], "scope", "function"))
        if _SCOPE_RANK.get(fixture_scope, 0) > limit:
            found.append(f"{name} ({fixture_scope}-scoped)")
    return found


@contextlib.contextmanager
def _coverage_paused() -> Iterator[None]:
    """Keep the control and negative runs out of the user's coverage measurement."""
    try:
        import coverage  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        yield
        return
    cov = coverage.Coverage.current()
    if cov is None:
        yield
        return
    cov.stop()
    try:
        yield
    finally:
        cov.start()


def _marker_reason(item: pytest.Item) -> str | None:
    """The no_proof reason, "" when the marker carries none, None when absent."""
    marker = item.get_closest_marker(MARKER)
    if marker is None:
        return None
    reason = marker.args[0] if marker.args else marker.kwargs.get("reason", "")
    return str(reason).strip()


def _grade(
    item: pytest.Item,
    reports: list[pytest.TestReport],
    boundary: Any,
    decl: Declaration | None,
    reason: str | None,
) -> Result | None:
    observe, protocol = _observe, runtestprotocol
    positive = observe(item, reports, graded_run=False)
    if positive is None:
        return None
    if reason is not None and not reason:
        return core.misconfigured("the no_proof marker carries no reason", decl)
    if reason is not None and decl is not None:
        return core.misconfigured(
            "the no_proof marker and a declaration contradict each other", decl
        )
    if reason is not None:
        for report in reports:
            if report.when in ("call", "teardown"):
                report.user_properties.append((EXCLUDED_PROPERTY, reason))
        return None
    if decl is None:
        return core.prove(lambda: positive, None, positive)

    def run() -> RunResult:
        with _coverage_paused():
            observed = observe(item, protocol(item, log=False, nextitem=boundary), graded_run=True)
        if observed is None:
            return RunResult(Outcome.ERRORED, summary="the run produced no gradable call report")
        return observed

    return core.prove(
        run,
        decl,
        positive,
        default_expect=DEFAULT_EXPECT,
        passthrough=PASSTHROUGH,
        wider_fixtures=_wider_fixtures(item, decl.scope),
    )


def _teardown_to(item: pytest.Item, nextitem: pytest.Item | None) -> pytest.TestReport | None:
    """Tear the fixture stack down to what the real next item needs, as pytest would have.

    The graded runs tore down only to the declaration's boundary. This is the teardown
    pytest's own hook performs, done directly so per-phase plugin state is not re-entered;
    a failure becomes a teardown report so it is never silent.
    """
    state = getattr(item.session, "_setupstate", None)
    try:
        if state is not None:
            state.teardown_exact(nextitem)
        else:  # pragma: no cover - only if pytest renames its setup state
            item.ihook.pytest_runtest_teardown(item=item, nextitem=nextitem)
    except PASSTHROUGH:
        raise
    except BaseException as e:
        text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        return pytest.TestReport(
            item.nodeid,
            item.location,
            {},
            "failed",
            f"teardown after grading failed:\n{text}",
            "teardown",
            [],
            0.0,
            0.0,
            0.0,
        )
    return None


def _fails_build(result: Result, strict: bool) -> bool:
    if result.reason is Reason.INTERNAL_ERROR or result.verdict is Verdict.FALSE:
        return True
    return strict and result.verdict is Verdict.UNPROVEN


def _longrepr(result: Result, item: pytest.Item) -> str:
    path, lineno, _ = item.location
    where = f"{path}:{lineno + 1}" if lineno is not None else str(path)
    if result.reason is Reason.INTERNAL_ERROR:
        return (
            "falsetto: internal error while grading this check; its verdict is unproven.\n"
            f"{result.evidence or result.detail or ''}"
        )
    head = "FALSE" if result.verdict is Verdict.FALSE else "UNPROVEN (strict)"
    lines = [f"{head}: {result.message}.", f"  at: {where}"]
    if result.declared:
        lines.append(f"  declared: {result.declared}")
    if result.detail:
        lines.append(f"  detail: {result.detail}")
    if result.hint:
        lines.append(f"  hint: {result.hint}")
    return "\n".join(lines)


def _attach_target(reports: list[pytest.TestReport]) -> pytest.TestReport | None:
    """The report that carries a build failure: the call report, else teardown, else setup."""
    by_when = {r.when: r for r in reports}
    return by_when.get("call") or by_when.get("teardown") or by_when.get("setup")


def _combine(existing: str, added: str) -> str:
    return f"{existing}\n\n{added}" if existing else added


def _attach(
    item: pytest.Item, reports: list[pytest.TestReport], result: Result | None, settings: Settings
) -> None:
    if result is None:
        return
    record = (PROPERTY, json.dumps(result.to_dict()))
    for report in reports:
        if report.when in ("call", "teardown"):
            report.user_properties.append(record)
    if not _fails_build(result, settings.strict):
        return
    target = _attach_target(reports)
    if target is None:
        return
    existing = target.longreprtext if target.longrepr is not None else ""
    target.outcome = "failed"
    target.longrepr = _combine(existing, _longrepr(result, item))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> bool | None:
    config = item.config
    settings = _settings(config)
    if not settings.enabled or not _gradable(item) or _runs_nothing(config):
        return None
    ihook = item.ihook
    decl = None
    extra: list[pytest.TestReport] = []
    try:
        decl = get_declaration(getattr(item, "obj", None))
        reason = _marker_reason(item)
        declared = decl is not None and reason is None
        boundary = _boundary(item, decl.scope) if declared and decl is not None else nextitem
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        reports = runtestprotocol(item, log=False, nextitem=cast(Any, boundary))
        try:
            result = _grade(item, reports, boundary, decl, reason)
        except PASSTHROUGH:
            raise
        except BaseException as e:
            result = core.internal_error(e, decl)
        if declared:
            failure = _teardown_to(item, nextitem)
            if failure is not None:
                extra.append(failure)
    finally:
        item.stash[EXCINFO] = None
    _attach(item, reports, result, settings)
    for report in [*reports, *extra]:
        ihook.pytest_runtest_logreport(report=report)
    ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True


def pytest_report_teststatus(
    report: pytest.TestReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    if not _settings(config).enabled or report.when != "call" or _is_xfail(report):
        return None
    info = verdict_of(report)
    if info is None:
        if report.passed and excluded_reason(report) is not None:
            return ("passed", "-", "EXCLUDED")
        return None
    return _status_for(info, report)


def _status_for(info: dict[str, Any], report: pytest.TestReport) -> tuple[str, str, str] | None:
    """pytest's category stays a real one (passed or failed); only the word changes."""
    if info["reason"] == Reason.INTERNAL_ERROR.value:
        return ("failed", "!", "FALSETTO-ERROR")
    verdict = info["verdict"]
    if verdict == Verdict.PROVEN.value and report.passed:
        return ("passed", ".", "PROVEN")
    if verdict == Verdict.FALSE.value:
        return ("failed", "!", "FALSE")
    if verdict == Verdict.UNPROVEN.value:
        return ("failed", "?", "UNPROVEN") if report.failed else ("passed", "?", "UNPROVEN")
    return None


@dataclass
class _Entry:
    status: str = "incomplete"
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
            return
        record = verdict_of(report)
        if record is not None:
            entry.record = record
            entry.status = "graded"
            return
        reason = excluded_reason(report)
        if reason is not None:
            entry.excluded = reason
            entry.status = "excluded"
            return
        if report.when == "call":
            if _is_xfail(report):
                entry.status = "xfail"
            elif report.skipped:
                entry.status = "skipped"
            elif entry.status == "incomplete":
                entry.status = "not gradable"
        elif report.failed and entry.status in ("incomplete", "not gradable"):
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

    def line(self) -> str:
        v = self.verdicts()
        extras = ", ".join(
            f"{n} {status}" for status, n in self.statuses().items() if status != "graded" and n
        )
        tail = f"{self.graded} graded of {self.run} run" + (f"; {extras}" if extras else "")
        return (
            f"falsetto: {v['proven']} proven, {v['failed']} failed as written, "
            f"{v['false']} false, {v['unproven']} unproven ({tail})"
        )


class _Session:
    """Session-level accounting and reporting, registered only when enabled."""

    def __init__(self, settings: Settings, config: pytest.Config) -> None:
        self.settings = settings
        self.config = config
        self.tally = Tally()

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.tally.note(report)

    def strict_zero_graded(self) -> bool:
        if _runs_nothing(self.config):
            return False
        return self.settings.strict and self.tally.run > 0 and self.tally.graded == 0

    @pytest.hookimpl(trylast=True)
    def pytest_terminal_summary(self, terminalreporter: TerminalReporter) -> None:
        tally = self.tally
        if tally.run == 0:
            return
        tr = terminalreporter
        tr.write_sep("=", "falsetto")
        for nodeid, entry in tally.items.items():
            if entry.status == "excluded":
                tr.write_line(f"EXCLUDED {nodeid}: {entry.excluded}")
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
            for name in ("declared", "detail", "hint"):
                if record.get(name):
                    tr.write_line(f"    {name}: {record[name]}")
            if record.get("evidence"):
                lines = str(record["evidence"]).strip().splitlines()
                for line in lines[-_EVIDENCE_LINES:]:
                    tr.write_line(f"    | {line}")
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
            try:
                self.write_json(Path(self.settings.json_path))
            except OSError as e:
                tr = session.config.pluginmanager.get_plugin("terminalreporter")
                if tr is not None:
                    tr.write_line(f"falsetto: could not write the JSON report: {e}", red=True)

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
