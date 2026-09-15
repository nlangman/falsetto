"""The pytest adapter. It runs nothing of its own: the positive run is pytest's,
the negative run and every verdict come from `falsetto.core`."""
from __future__ import annotations

import pytest

from . import core
from .declaration import get_declaration
from .verdict import Result, Verdict

RESULT = pytest.StashKey[Result]()
_PASSTHROUGH = (pytest.skip.Exception, pytest.xfail.Exception, pytest.exit.Exception, KeyboardInterrupt, SystemExit)
_NEGATIVE_PASSTHROUGH = (pytest.exit.Exception, KeyboardInterrupt, SystemExit)


def prove(item, decl):
    return core.prove(item.runtest, decl, subject=item.obj, passthrough=_NEGATIVE_PASSTHROUGH)


def pytest_addoption(parser):
    group = parser.getgroup("falsetto")
    group.addoption(
        "--falsetto-strict",
        action="store_true",
        default=False,
        help="Count unproven checks as failures (exit non-zero).",
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    decl = get_declaration(item.obj)
    try:
        yield
    except _PASSTHROUGH:
        raise
    except BaseException:
        item.stash[RESULT] = Result(Verdict.FAILED, "positive run failed", decl.description if decl else None)
        raise
    item.stash[RESULT] = prove(item, decl)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if call.when == "call" and RESULT in item.stash:
        report.falsetto = item.stash[RESULT].to_dict()
    return report


def pytest_report_teststatus(report, config):
    info = getattr(report, "falsetto", None)
    if report.when != "call" or info is None:
        return None
    verdict = info["verdict"]
    if verdict == Verdict.PROVEN.value:
        return ("proven", ".", "PROVEN")
    if verdict == Verdict.FALSE.value:
        return ("false", "!", "FALSE")
    if verdict == Verdict.UNPROVEN.value:
        return ("unproven", "?", "UNPROVEN")
    return None


def _counts(stats) -> dict[str, int]:
    return {k: len(stats.get(k, [])) for k in ("proven", "failed", "false", "unproven")}


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tr = terminalreporter
    n = _counts(tr.stats)
    tr.write_sep("=", "falsetto")
    for key, word in (("false", "FALSE"), ("unproven", "UNPROVEN")):
        for rep in tr.stats.get(key, []):
            info = rep.falsetto
            tr.write_line(f"{word} {rep.nodeid}")
            if info.get("declared"):
                tr.write_line(f"    declared: {info['declared']}")
            if info.get("detail"):
                tr.write_line(f"    detail: {info['detail']}")
            if info.get("hint"):
                tr.write_line(f"    hint: {info['hint']}")
    tr.write_line(
        f"falsetto: {n['proven']} proven, {n['failed']} failed, {n['false']} false, {n['unproven']} unproven"
    )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is None:
        return
    n = _counts(tr.stats)
    strict = session.config.getoption("--falsetto-strict")
    if session.exitstatus == 0 and (n["false"] or (strict and n["unproven"])):
        session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)
