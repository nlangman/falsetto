"""The pytest adapter.

For a declared check it runs whole, unlogged pytest protocols (setup, call, teardown):
the positive run, then the control runs, then the negative run with the declared change
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
import platform
import site
import sysconfig
import traceback
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias, cast

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
GRADABLE_PROPERTY = "falsetto.gradable"
MARKER = "no_proof"
DEFAULT_EXPECT: tuple[type[BaseException], ...] = (AssertionError, pytest.fail.Exception)
PASSTHROUGH: tuple[type[BaseException], ...] = (
    KeyboardInterrupt,
    SystemExit,
    pytest.exit.Exception,
)
_SCOPE_RANK = {"function": 0, "class": 1, "module": 2, "package": 3, "session": 4}
_EVIDENCE_LINES = 12
STOP_NOT_REVERTED = (
    "falsetto: a declared change could not be undone; every later check would run against "
    "a patched subject"
)
_DEBUGGER_PLUGINS = ("pdbinvoke", "pdbtrace")

# What runtestprotocol's teardown tears down to. pytest types it as an Item, but the
# only thing consulted is `.listchain()`, which every node has, so a Collector marks
# "keep this scope and above alive" and None means "everything down".
TeardownTarget: TypeAlias = "pytest.Item | pytest.Collector | None"


@dataclass(frozen=True)
class Settings:
    enabled: bool
    strict: bool
    json_path: str | None
    controls: int = 1


SETTINGS = pytest.StashKey[Settings]()
EXCINFO = pytest.StashKey[Any]()
FIXTURES = pytest.StashKey[tuple[str, ...]]()


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
        return f"{core.report_path(str(entry.path))}:{entry.lineno + 1}"
    except (AttributeError, IndexError, TypeError):
        return None


def _last_property(report: pytest.TestReport, name: str) -> Any:
    for prop_name, value in reversed(report.user_properties):
        if prop_name == name:
            return value
    return None


def verdict_of(report: pytest.TestReport) -> dict[str, Any] | None:
    """The verdict record a call or teardown report carries, or None.

    On a check Falsetto graded, the record it attached is the last one, so it wins over
    anything a test or a fixture recorded under the same name. On an item Falsetto did not
    grade (excluded, skipped, xfail, or one another plugin ran) there is no record of
    Falsetto's to win, and whatever the item recorded is all there is. Every record is
    validated before it is returned, so a malformed one is ignored rather than counted or
    crashed on; a well-formed one cannot be told apart from Falsetto's own.
    """
    if report.when not in ("call", "teardown"):
        return None
    value = _last_property(report, PROPERTY)
    if not isinstance(value, str):
        return None
    try:
        loaded = json.loads(value)
        if not isinstance(loaded, dict):
            return None
        return Result.from_dict(loaded).to_dict()
    except ValueError:
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
    group.addoption(
        "--falsetto-controls",
        default=None,
        dest="falsetto_controls",
        type=int,
        metavar="N",
        help="Control runs before the negative run (default 1; N catches residue up to run N+1).",
    )
    parser.addini("falsetto", "Enable Falsetto grading.", type="bool", default=False)
    parser.addini(
        "falsetto_strict", "Count unproven checks as failures.", type="bool", default=False
    )
    parser.addini("falsetto_controls", "Control runs before the negative run.", default="1")


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
                "falsetto and these plugins both take over the test protocol, and whichever "
                f"pytest calls first wins for each check: {others}. Checks they run are "
                "reported as not graded, never as a pass."
            ),
            stacklevel=2,
        )


def _controls(config: pytest.Config, enabled: bool) -> int:
    """How many control runs precede the negative run.

    The ini value is read only when Falsetto is enabled, so a malformed one never
    touches a run that did not ask for grading, and a malformed one on a run that did
    is a usage error rather than a crash inside configure.
    """
    if not enabled:
        return 1
    given = config.getoption("falsetto_controls")
    if given is not None:
        return max(1, int(given))
    raw = config.getini("falsetto_controls") or 1
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        raise pytest.UsageError("falsetto_controls must be an integer") from None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARKER}(reason): Falsetto does not grade this check; it is counted as excluded, "
        "never as a pass. A reason is required.",
    )
    strict = bool(config.getoption("falsetto_strict") or _ini(config, "falsetto_strict"))
    enabled = bool(config.getoption("falsetto") or _ini(config, "falsetto") or strict)
    controls = _controls(config, enabled)
    settings = Settings(enabled, strict, config.getoption("falsetto_json"), controls)
    config.stash[SETTINGS] = settings
    if enabled:
        config.pluginmanager.register(_Session(settings, config), "falsetto-session")
        _warn_competing_protocols(config)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not _settings(config).enabled:
        return
    for item in items:
        if _gradable(item):
            item.user_properties.append((GRADABLE_PROPERTY, "1"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when == "call" and _settings(item.config).enabled:
        item.stash[EXCINFO] = call.excinfo
        request = getattr(item, "_request", None)
        names = getattr(request, "fixturenames", None) if request else None
        item.stash[FIXTURES] = tuple(names) if names else ()
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
    return core.evidence(report.longreprtext)


def _scope_applies(item: pytest.Item, scope: str) -> str | None:
    """Why the declaration's scope cannot apply to this check, or None when it can."""
    if scope == "class" and not any(isinstance(n, pytest.Class) for n in item.listchain()):
        return "the declaration says scope='class' but the check is not in a class"
    return None


def _boundary(item: pytest.Item, scope: str) -> TeardownTarget:
    """The node whose chain marks what stays set up between runs of this check."""
    if scope == "session":
        return None
    if scope == "function":
        return cast(TeardownTarget, item.parent)
    kinds: dict[str, type[pytest.Collector]] = {
        "class": pytest.Class,
        "module": pytest.Module,
        "package": pytest.Package,
    }
    kind = kinds[scope]
    for node in reversed(item.listchain()):
        if isinstance(node, kind):
            return cast(TeardownTarget, node.parent)
    return cast(TeardownTarget, item.parent)


def _run_protocol(
    protocol: Callable[..., list[pytest.TestReport]],
    item: pytest.Item,
    boundary: TeardownTarget,
) -> list[pytest.TestReport]:
    """Run one whole protocol, tearing fixtures down to ``boundary`` when it ends.

    The protocol is passed in rather than looked up, so a check whose declared change
    patches ``runtestprotocol`` does not also rewrite how its own graded runs are made.
    pytest types ``nextitem`` as an Item; this is the one place TeardownTarget's wider
    set of nodes is cast to it.
    """
    return protocol(item, log=False, nextitem=cast(Any, boundary))


def _site_dirs() -> tuple[str, ...]:
    dirs: set[str] = set()
    with contextlib.suppress(Exception):
        dirs.update(site.getsitepackages())
    with contextlib.suppress(Exception):
        dirs.add(site.getusersitepackages())
    paths = sysconfig.get_paths()
    dirs.update(paths[k] for k in ("purelib", "platlib", "stdlib", "platstdlib") if k in paths)
    return tuple(str(Path(d).resolve()) for d in dirs if d)


_SITE_DIRS = _site_dirs()


def _is_infrastructure(fixturedef: Any) -> bool:
    """A fixture pytest or an installed plugin defines, not one the suite wrote."""
    func = getattr(fixturedef, "func", None)
    module = str(getattr(func, "__module__", "") or "")
    if module.startswith("_pytest.") or module == "pytest":
        return True
    filename = str(getattr(getattr(func, "__code__", None), "co_filename", "") or "")
    if not filename:
        return False
    return str(Path(filename).resolve()).startswith(_SITE_DIRS)


def _wider_fixtures(item: pytest.Item, scope: str) -> list[str]:
    """Fixtures the check used, by any route, that the declaration's scope does not rebuild.

    Fixtures defined by pytest or installed plugins are infrastructure and never count. A
    fixture reached dynamically is known only to the fixture manager, and a failure to ask it
    is not survivable: a fixture missed here is a check reported false that Falsetto could not
    grade, so the exception travels to the internal-error verdict instead.
    """
    info = getattr(item, "_fixtureinfo", None)
    if info is None:
        return []
    name2defs = dict(getattr(info, "name2fixturedefs", {}))
    requested = item.stash.get(FIXTURES, cast(tuple[str, ...], ()))
    names = set(getattr(info, "names_closure", ())) | set(requested)
    names |= set(name2defs)
    limit = _SCOPE_RANK.get(scope, 0)
    found = []
    for name in sorted(names):
        defs = name2defs.get(name)
        if not defs:
            defs = item.session._fixturemanager.getfixturedefs(name, item)
        if not defs:
            continue
        fixturedef = defs[-1]
        fixture_scope = str(getattr(fixturedef, "scope", "function"))
        if _SCOPE_RANK.get(fixture_scope, 0) <= limit or _is_infrastructure(fixturedef):
            continue
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
    try:
        cov.stop()
        yield
    finally:
        cov.start()


@contextlib.contextmanager
def _debuggers_paused(config: pytest.Config) -> Iterator[None]:
    """Keep --pdb and --trace from opening on the failure a graded run deliberately causes."""
    pm = config.pluginmanager
    paused = [(name, pm.get_plugin(name)) for name in _DEBUGGER_PLUGINS]
    paused = [(name, plugin) for name, plugin in paused if plugin is not None]
    for _, plugin in paused:
        pm.unregister(plugin)
    try:
        yield
    finally:
        for name, plugin in paused:
            pm.register(plugin, name)


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
    boundary: TeardownTarget,
    decl: Declaration | None,
    reason: str | None,
    settings: Settings,
    scope_problem: str | None,
) -> Result | None:
    # All three seams are bound once, here, before the declared change is applied. A change
    # that patches _observe, _run_protocol or runtestprotocol must reach the runs it declares
    # against without also rewriting how this check's own negative run is performed and
    # observed; a late lookup on any of them would let a check rewrite its own grading.
    observe, protocol, run_protocol = _observe, runtestprotocol, _run_protocol
    if reason is not None and not reason:
        return core.misconfigured("the no_proof marker carries no reason", decl)
    if reason is not None and decl is not None:
        return core.misconfigured(
            "the no_proof marker and a declaration contradict each other", decl
        )
    if scope_problem is not None:
        return core.misconfigured(scope_problem, decl)
    positive = observe(item, reports, graded_run=False)
    if positive is None:
        return None
    if reason is not None:
        for report in reports:
            if report.when in ("call", "teardown"):
                report.user_properties.append((EXCLUDED_PROPERTY, reason))
        return None
    if decl is None:
        return core.prove(lambda: positive, None, positive)

    def run() -> RunResult:
        with _coverage_paused(), _debuggers_paused(item.config):
            reports = run_protocol(protocol, item, boundary)
            observed = observe(item, reports, graded_run=True)
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
        controls=settings.controls,
    )


def _fails_build(result: Result, strict: bool) -> bool:
    always = (
        Reason.INTERNAL_ERROR,
        Reason.OUT_OF_SCOPE,
        Reason.MISCONFIGURED,
        Reason.NOT_REVERTED,
    )
    if result.reason in always or result.verdict is Verdict.FALSE:
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
    if result.verdict is Verdict.FALSE:
        head = "FALSE"
    elif result.reason in (Reason.OUT_OF_SCOPE, Reason.MISCONFIGURED, Reason.NOT_REVERTED):
        head = f"UNPROVEN ({result.reason.value})"
    else:
        head = "UNPROVEN (strict)"
    lines = [f"{head}: {result.message}.", f"  at: {where}"]
    if result.declared:
        lines.append(f"  declared: {result.declared}")
    if result.detail:
        lines.append(f"  detail: {result.detail}")
    if result.hint:
        lines.append(f"  hint: {result.hint}")
    return "\n".join(lines)


def _stop_if_not_reverted(item: pytest.Item, result: Result) -> None:
    """Stop the session when a declared change is still applied: later checks are not graded.

    Everything after this item would run against a patched subject, so a green verdict from
    any of them would mean nothing. Under xdist this stops the worker, not the session.
    """
    if result.reason is Reason.NOT_REVERTED:
        item.session.shouldfail = STOP_NOT_REVERTED


def _attach_target(reports: list[pytest.TestReport]) -> pytest.TestReport | None:
    """The report that carries a build failure: the call report, else teardown, else setup."""
    by_when = {r.when: r for r in reports}
    return by_when.get("call") or by_when.get("teardown") or by_when.get("setup")


def _fail_report(report: pytest.TestReport, text: str) -> None:
    """Fail a report with ``text``, keeping whatever failure text it already carried."""
    existing = report.longreprtext if report.longrepr is not None else ""
    report.outcome = "failed"
    report.longrepr = f"{existing}\n\n{text}" if existing else text


def _attach(
    item: pytest.Item, reports: list[pytest.TestReport], result: Result | None, settings: Settings
) -> None:
    if result is None:
        return
    record = (PROPERTY, json.dumps(result.to_dict()))
    for report in reports:
        if report.when in ("call", "teardown"):
            report.user_properties.append(record)
    _stop_if_not_reverted(item, result)
    if not _fails_build(result, settings.strict):
        return
    target = _attach_target(reports)
    if target is None:
        return
    _fail_report(target, _longrepr(result, item))


def _stopping(item: pytest.Item, reports: list[pytest.TestReport]) -> bool:
    """Whether the session will stop after this item, as pytest decides once it is logged."""
    session = item.session
    if session.shouldstop or session.shouldfail:
        return True
    maxfail = item.config.getvalue("maxfail")
    failures = sum(1 for r in reports if r.failed and not _is_xfail(r))
    return bool(maxfail) and session.testsfailed + failures >= maxfail


def _teardown_to(item: pytest.Item, nextitem: TeardownTarget) -> str | None:
    """Tear the fixture stack down to what the real next item needs, as pytest would have.

    The graded runs tore down only to the declaration's boundary. This is the teardown
    pytest's own hook performs, done directly so per-phase plugin state is not re-entered;
    a failure is returned as text so the caller can put it on the teardown report.
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
        return f"teardown after grading failed:\n{text}"
    return None


def _report_teardown_failure(
    item: pytest.Item, reports: list[pytest.TestReport], text: str
) -> None:
    teardown = next((r for r in reports if r.when == "teardown"), None)
    if teardown is None:
        teardown = pytest.TestReport(
            item.nodeid, item.location, {}, "passed", None, "teardown", [], 0.0, 0.0, 0.0
        )
        reports.append(teardown)
    _fail_report(teardown, text)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> bool | None:
    config = item.config
    settings = _settings(config)
    if not settings.enabled or not _gradable(item) or _runs_nothing(config):
        return None
    ihook = item.ihook
    decl = None
    try:
        decl = get_declaration(getattr(item, "obj", None))
        reason = _marker_reason(item)
        boundary: TeardownTarget = nextitem
        scope_problem: str | None = None
        if decl is not None and reason is None:
            scope_problem = _scope_applies(item, decl.scope)
            if scope_problem is None:
                boundary = _boundary(item, decl.scope)
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        reports = _run_protocol(runtestprotocol, item, boundary)
        try:
            result = _grade(item, reports, boundary, decl, reason, settings, scope_problem)
        except PASSTHROUGH:
            raise
        except BaseException as e:
            result = core.internal_error(e, decl)
        _attach(item, reports, result, settings)
        if boundary is not nextitem:
            final: TeardownTarget = None if _stopping(item, reports) else nextitem
            failure = _teardown_to(item, final)
            if failure is not None:
                _report_teardown_failure(item, reports, failure)
    finally:
        item.stash[EXCINFO] = None
    for report in reports:
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


NOT_GRADED_BY_FALSETTO = "not graded (another plugin ran the protocol)"


def _is_gradable(report: pytest.TestReport) -> bool:
    """Whether the item behind a report was one Falsetto would have graded."""
    return _last_property(report, GRADABLE_PROPERTY) is not None


@dataclass
class _Entry:
    status: str = "incomplete"
    record: dict[str, Any] | None = None
    excluded: str | None = None
    teardown_failed: bool = False


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
        elif excluded_reason(report) is not None:
            entry.excluded = excluded_reason(report)
            entry.status = "excluded"
        elif report.when == "call":
            if _is_xfail(report):
                entry.status = "xfail"
            elif report.skipped:
                entry.status = "skipped"
            elif entry.status == "incomplete":
                entry.status = NOT_GRADED_BY_FALSETTO if _is_gradable(report) else "not gradable"
        if report.when == "teardown" and report.failed:
            if entry.record is not None:
                entry.teardown_failed = True
            elif entry.status in ("incomplete", "not gradable", NOT_GRADED_BY_FALSETTO):
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
        teardowns = sum(1 for e in self.items.values() if e.teardown_failed)
        if teardowns:
            counts["teardown failed after grading"] = teardowns
        return counts

    @property
    def run(self) -> int:
        return len(self.items)

    @property
    def graded(self) -> int:
        return sum(1 for e in self.items.values() if e.record is not None)

    def line(self, stopped: str | None = None) -> str:
        v = self.verdicts()
        extras = ", ".join(
            f"{n} {status}" for status, n in self.statuses().items() if status != "graded" and n
        )
        tail = f"{self.graded} graded of {self.run} run" + (f"; {extras}" if extras else "")
        text = (
            f"falsetto: {v['proven']} proven, {v['failed']} failed as written, "
            f"{v['false']} false, {v['unproven']} unproven ({tail})"
        )
        if stopped:
            text += f" - stopped early: {stopped}"
        return text


REPORT_SCHEMA = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Session:
    """Session-level accounting and reporting, registered only when enabled."""

    def __init__(self, settings: Settings, config: pytest.Config) -> None:
        self.settings = settings
        self.config = config
        self.tally = Tally()
        self.session: pytest.Session | None = None
        self.started = _now()

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self.session = session
        self.started = _now()

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.tally.note(report)

    def stopped(self) -> str | None:
        session = self.session
        if session is None:
            return None
        reason = session.shouldfail or session.shouldstop
        return str(reason) if reason else None

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
            non_green = (Verdict.FALSE.value, Verdict.UNPROVEN.value)
            if record is None or record["verdict"] not in non_green:
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
        tr.write_line(tally.line(self.stopped()))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if hasattr(session.config, "workerinput"):
            return
        if self.strict_zero_graded() and session.exitstatus == 0:
            session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)
        if self.settings.json_path:
            try:
                self.write_json(Path(self.settings.json_path), session)
            except OSError as e:
                tr = session.config.pluginmanager.get_plugin("terminalreporter")
                if tr is not None:
                    tr.write_line(f"falsetto: could not write the JSON report: {e}", red=True)
                if session.exitstatus == 0:
                    session.exitstatus = int(pytest.ExitCode.INTERNAL_ERROR)

    def write_json(self, path: Path, session: pytest.Session) -> None:
        tally = self.tally
        stopped = self.stopped()
        strict = self.settings.strict
        payload = {
            "schema": REPORT_SCHEMA,
            "falsetto": __version__,
            "started": self.started,
            "finished": _now(),
            "rootdir": str(self.config.rootpath),
            "args": list(self.config.invocation_params.args),
            "strict": strict,
            "controls": self.settings.controls,
            "pytest": pytest.__version__,
            "python": platform.python_version(),
            "complete": stopped is None,
            "stopped": stopped,
            "exitstatus": int(session.exitstatus),
            "totals": {
                "verdicts": tally.verdicts(),
                "graded": tally.graded,
                "run": tally.run,
                "statuses": {k: v for k, v in tally.statuses().items() if k != "graded"},
            },
            "line": tally.line(stopped),
            "checks": [
                {
                    "nodeid": nodeid,
                    **entry.record,
                    "fails_build": _fails_build(Result.from_dict(entry.record), strict),
                }
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
