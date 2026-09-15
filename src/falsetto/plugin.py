"""The pytest adapter.

It runs nothing of its own: the positive run is pytest's, and the negative run and
every verdict come from :mod:`falsetto.core`. Verdicts travel on the report's
``user_properties`` as a JSON string, so they survive serialization and appear in
JUnit output as one parseable property.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

import pytest

from . import core
from .declaration import Declaration, get_declaration
from .verdict import Result, Verdict

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter

PROPERTY = "falsetto"
_POSITIVE_PASSTHROUGH: tuple[type[BaseException], ...] = (
    pytest.skip.Exception,
    pytest.xfail.Exception,
    pytest.exit.Exception,
    KeyboardInterrupt,
    SystemExit,
)
_NEGATIVE_PASSTHROUGH: tuple[type[BaseException], ...] = (
    pytest.exit.Exception,
    KeyboardInterrupt,
    SystemExit,
)
_STATUS = {
    Verdict.PROVEN.value: ("proven", ".", "PROVEN"),
    Verdict.FALSE.value: ("false", "!", "FALSE"),
    Verdict.UNPROVEN.value: ("unproven", "?", "UNPROVEN"),
}


def _subject(item: pytest.Item) -> Any:
    return getattr(item, "obj", None)  # only function-like items carry a test object


def prove(item: pytest.Item, decl: Declaration | None) -> Result:
    """The negative run for a pytest item, delegated to the core."""
    return core.prove(item.runtest, decl, subject=_subject(item), passthrough=_NEGATIVE_PASSTHROUGH)


def _record(item: pytest.Item, result: Result) -> None:
    item.user_properties.append((PROPERTY, json.dumps(result.to_dict())))


def verdict_of(report: pytest.TestReport) -> dict[str, Any] | None:
    """The verdict record carried by a call-phase report, or None."""
    if report.when != "call":
        return None
    for name, value in report.user_properties:
        if name == PROPERTY and isinstance(value, str):
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else None
    return None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("falsetto")
    group.addoption(
        "--falsetto-strict",
        action="store_true",
        default=False,
        help="Count unproven checks as failures (exit non-zero).",
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, None, None]:
    decl = get_declaration(_subject(item))
    try:
        yield
    except _POSITIVE_PASSTHROUGH:
        raise
    except BaseException:
        declared = decl.description if decl else None
        _record(item, Result(Verdict.FAILED, "positive run failed", declared))
        raise
    _record(item, prove(item, decl))


def pytest_report_teststatus(
    report: pytest.TestReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    info = verdict_of(report)
    if info is None:
        return None
    return _STATUS.get(str(info["verdict"]))


def _counts(stats: dict[str, list[Any]]) -> dict[str, int]:
    return {k: len(stats.get(k, [])) for k in ("proven", "failed", "false", "unproven")}


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(
    terminalreporter: TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    tr = terminalreporter
    n = _counts(tr.stats)
    tr.write_sep("=", "falsetto")
    for key, word in (("false", "FALSE"), ("unproven", "UNPROVEN")):
        for rep in tr.stats.get(key, []):
            info = verdict_of(rep) or {}
            tr.write_line(f"{word} {rep.nodeid}")
            for field in ("declared", "detail", "hint"):
                if info.get(field):
                    tr.write_line(f"    {field}: {info[field]}")
    tr.write_line(
        f"falsetto: {n['proven']} proven, {n['failed']} failed, "
        f"{n['false']} false, {n['unproven']} unproven"
    )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is None:
        return
    n = _counts(tr.stats)
    strict = bool(session.config.getoption("--falsetto-strict"))
    if session.exitstatus == 0 and (n["false"] or (strict and n["unproven"])):
        session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)
