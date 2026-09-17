"""What round three found: indirect fixtures, the run count, isolation, and the edges."""

from __future__ import annotations

import contextlib
import json

import pytest

import falsetto
import falsetto.core as core
import falsetto.plugin as plugin
from falsetto import Patch
from tests.helpers import RUN, boundary_is_the_item, line

INDIRECT = """
import falsetto
import pytest

CONFIG = {"limit": 10}

@pytest.fixture(scope="session")
def session_limit():
    return CONFIG["limit"]

@pytest.fixture
def wrapper(session_limit):
    return {"limit": session_limit}

@pytest.fixture(scope="module", autouse=True)
def module_snapshot():
    return CONFIG["limit"]

@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "limit", 0))
def test_transitive(wrapper):
    assert wrapper["limit"] == 10

@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "limit", 0))
def test_dynamic(request):
    assert request.getfixturevalue("session_limit") == 10

@pytest.mark.usefixtures("session_limit")
@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "limit", 0))
def test_usefixtures():
    # always true: this check must still pass under the change, so its verdict is out of scope
    assert CONFIG["limit"] == 10 or True
"""


def every_fixture_is_in_scope(m: Patch) -> None:
    m.setattr(plugin, "_wider_fixtures", lambda item, scope: [])


@falsetto.must_fail_when(every_fixture_is_in_scope)
def test_wider_fixtures_reached_indirectly_are_out_of_scope_not_false(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(INDIRECT)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 3) in out
    assert "FALSE" not in out.replace("UNPROVEN", "")
    assert "session_limit (session-scoped)" in out
    assert result.ret == 1


TAUTOLOGY_WITH_BUILTINS = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_tautology_with_pytestconfig(pytestconfig, tmp_path):
    expected = VALUE["key"]
    assert VALUE["key"] == expected
"""


def everything_is_the_suites_own(m: Patch) -> None:
    m.setattr(plugin, "_is_infrastructure", lambda fixturedef: False)


@falsetto.must_fail_when(everything_is_the_suites_own)
def test_pytests_own_session_fixtures_do_not_shield_a_false_check(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(TAUTOLOGY_WITH_BUILTINS)
    result = pytester.runpytest(*RUN)
    assert line(0, 0, 1, 0) in result.stdout.str()


OUT_OF_SCOPE = """
import falsetto
import pytest

CONFIG = {"prefix": "id-"}

@pytest.fixture(scope="module")
def ident():
    return CONFIG["prefix"] + "42"

@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "prefix", "BROKEN-"))
def test_reads_a_module_fixture(ident):
    assert ident.startswith("id-")
"""


def out_of_scope_is_a_pass(m: Patch) -> None:
    original = plugin._fails_build
    m.setattr(
        plugin,
        "_fails_build",
        lambda result, strict: (
            original(result, strict) and result.reason is not falsetto.Reason.OUT_OF_SCOPE
        ),
    )


@falsetto.must_fail_when(out_of_scope_is_a_pass)
def test_out_of_scope_fails_the_build_without_strict(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(OUT_OF_SCOPE)
    result = pytester.runpytest(*RUN)
    assert result.ret == 1
    assert "UNPROVEN (out-of-scope)" in result.stdout.str()


PERIOD_THREE = """
import falsetto

STATE = {"n": 0}

@falsetto.must_fail_when(lambda m: None, describe="a change that changes nothing")
def test_fails_from_its_third_execution():
    STATE["n"] += 1
    assert STATE["n"] < 3
"""


def one_control_only(m: Patch) -> None:
    original = core.prove

    def prove(run, decl, positive, **kw):  # type: ignore[no-untyped-def]
        kw["controls"] = 1
        return original(run, decl, positive, **kw)

    m.setattr(core, "prove", prove)


@falsetto.must_fail_when(one_control_only)
def test_two_control_runs_catch_residue_that_appears_on_the_third_execution(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(PERIOD_THREE)
    result = pytester.runpytest(*RUN, "--falsetto-controls=2")
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "control run 2 failed" in out


class _ResolvingPatch(Patch):
    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        old = getattr(target, name)
        setattr(target, name, value)
        self._undo.append(lambda: setattr(target, name, old))


PatchUnderTest: type[Patch] = Patch


def resolve_descriptors(m: Patch) -> None:
    import tests.test_round_three as here

    m.setattr(here, "PatchUnderTest", _ResolvingPatch)


@falsetto.must_fail_when(resolve_descriptors)
def test_patch_restores_static_and_class_methods_as_descriptors() -> None:
    class Subject:
        @staticmethod
        def helper(x: int) -> int:
            return x

        @classmethod
        def build(cls) -> type:
            return cls

    class Child(Subject):
        pass

    with PatchUnderTest() as p:
        p.setattr(Subject, "helper", staticmethod(lambda x: -x))
        p.setattr(Subject, "build", classmethod(lambda cls: None))
    assert isinstance(vars(Subject)["helper"], staticmethod)
    assert isinstance(vars(Subject)["build"], classmethod)
    assert Subject().helper(1) == 1
    assert Child.build() is Child


STOP_WITH_MODULE_TEARDOWN = """
import falsetto
import pytest

VALUE = {"key": "k1"}

@pytest.fixture(scope="module", autouse=True)
def module_resource():
    yield
    raise RuntimeError("module teardown failed")

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_false():
    expected = VALUE["key"]
    assert VALUE["key"] == expected

def test_never_reached():
    assert True
"""


def never_stopping(m: Patch) -> None:
    m.setattr(plugin, "_stopping", lambda item, reports: False)


@falsetto.must_fail_when(never_stopping)
def test_stopping_early_still_prints_the_summary_and_the_teardown_error(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(STOP_WITH_MODULE_TEARDOWN)
    result = pytester.runpytest(*RUN, "-x")
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "out-of-scope" in out
    assert "module teardown failed" in out
    assert "stopping after" in out


TEARDOWN_AFTER_GRADING = """
import falsetto
import pytest

VALUE = {"key": "k1"}

@pytest.fixture(scope="module")
def module_resource():
    yield "r"
    raise RuntimeError("module teardown failed after grading")

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_proven(module_resource):
    assert VALUE["key"] == "k1"
"""


def teardown_failures_are_dropped(m: Patch) -> None:
    m.setattr(plugin, "_report_teardown_failure", lambda item, reports, text: None)


@falsetto.must_fail_when(teardown_failures_are_dropped)
def test_a_teardown_failure_after_grading_is_one_error_on_the_same_testcase(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(TEARDOWN_AFTER_GRADING)
    xml = pytester.path / "junit.xml"
    result = pytester.runpytest(*RUN, f"--junitxml={xml}")
    out = result.stdout.str()
    assert "1 teardown failed after grading" in out
    assert "module teardown failed after grading" in out
    assert 'tests="1"' in xml.read_text()
    assert result.ret == 1


FAKE_DEBUGGER_CONFTEST = """
import pytest

class FakeDebugger:
    def __init__(self):
        self.calls = 0
    def pytest_exception_interact(self, node, call, report):
        self.calls += 1
    def pytest_terminal_summary(self, terminalreporter):
        print("DEBUGGER_OPENED", self.calls)

def pytest_configure(config):
    config.pluginmanager.register(FakeDebugger(), "pdbinvoke")
"""

PROVEN_ONLY = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_proven():
    assert VALUE["key"] == "k1"
"""


def debuggers_stay_armed(m: Patch) -> None:
    m.setattr(plugin, "_debuggers_paused", lambda config: contextlib.nullcontext())


@falsetto.must_fail_when(debuggers_stay_armed)
def test_the_debugger_never_opens_on_a_deliberate_failure(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(FAKE_DEBUGGER_CONFTEST)
    pytester.makepyfile(PROVEN_ONLY)
    result = pytester.runpytest(*RUN, "-s")
    assert "DEBUGGER_OPENED 0" in result.stdout.str()


def package_scope_is_proven(pytester: pytest.Pytester) -> pytest.RunResult:
    pytester.makepyfile(**{"pkg/__init__.py": ""})
    pytester.makepyfile(
        **{
            "pkg/conftest.py": """
import pytest
CONFIG = {"prefix": "id-"}

@pytest.fixture(scope="package")
def pkg_ident():
    return CONFIG["prefix"] + "42"
""",
            "pkg/test_pkg.py": """
import falsetto
import pkg.conftest as c

@falsetto.must_fail_when(lambda m: m.setitem(c.CONFIG, "prefix", "BROKEN-"), scope="package")
def test_pkg_fixture(pkg_ident):
    assert pkg_ident.startswith("id-")
""",
        }
    )
    return pytester.runpytest(*RUN)


@falsetto.must_fail_when(boundary_is_the_item)
def test_package_scope_rebuilds_a_package_fixture(pytester: pytest.Pytester) -> None:
    result = package_scope_is_proven(pytester)
    assert line(1, 0, 0, 0) in result.stdout.str()


CLASS_SCOPE_WITHOUT_A_CLASS = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None), scope="class")
def test_not_in_a_class():
    assert VALUE["key"] == "k1"
"""


def any_scope_applies(m: Patch) -> None:
    m.setattr(plugin, "_scope_applies", lambda item, scope: None)


@falsetto.must_fail_when(any_scope_applies)
def test_class_scope_on_a_module_level_check_is_misconfigured(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(CLASS_SCOPE_WITHOUT_A_CLASS)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "UNPROVEN (misconfigured)" in out
    assert "not in a class" in out
    assert result.ret == 1


XFAIL_WITH_BAD_MARKER = """
import pytest

@pytest.mark.xfail
@pytest.mark.no_proof
def test_x():
    assert False
"""


def markers_are_ignored(m: Patch) -> None:
    m.setattr(plugin, "_marker_reason", lambda item: None)


@falsetto.must_fail_when(markers_are_ignored)
def test_a_misconfigured_marker_is_reported_even_on_an_xfail_check(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(XFAIL_WITH_BAD_MARKER)
    result = pytester.runpytest(*RUN)
    assert "carries no reason" in result.stdout.str()


COMPETING_TRYFIRST_CONFTEST = """
import pytest
from _pytest.runner import runtestprotocol

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    runtestprotocol(item, nextitem=nextitem)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
"""


def gradable_items_are_not_marked(m: Patch) -> None:
    m.setattr(plugin, "_is_gradable", lambda report: False)


@falsetto.must_fail_when(gradable_items_are_not_marked)
def test_a_check_another_plugin_ran_is_reported_as_not_graded(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(COMPETING_TRYFIRST_CONFTEST)
    pytester.makepyfile(PROVEN_ONLY)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "1 not graded (another plugin ran the protocol)" in out
    assert "not gradable" not in out


FALSE_THEN_MORE = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_a_false():
    expected = VALUE["key"]
    assert VALUE["key"] == expected

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_b_proven():
    assert VALUE["key"] == "k1"
"""


def sessions_never_stop(m: Patch) -> None:
    m.setattr(plugin._Session, "stopped", lambda self: None)


@falsetto.must_fail_when(sessions_never_stop)
def test_the_json_report_says_when_the_session_stopped_early(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_MORE)
    path = pytester.path / "falsetto.json"
    result = pytester.runpytest(*RUN, "-x", f"--falsetto-json={path}")
    payload = json.loads(path.read_text())
    assert payload["complete"] is False
    assert "stopping after 1 failures" in str(payload["stopped"])
    assert "stopped early" in result.stdout.str()


TYPO_IN_THE_CHANGE = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setattr(VALUE, "nope", None))
def test_x():
    assert VALUE["key"] == "k1"
"""


def locations_point_into_falsetto(m: Patch) -> None:
    import traceback

    def last_frame(exc):  # type: ignore[no-untyped-def]
        frames = traceback.extract_tb(exc.__traceback__)
        return f"{frames[-1].filename}:{frames[-1].lineno}" if frames else None

    m.setattr(core, "location_of", last_frame)


@falsetto.must_fail_when(locations_point_into_falsetto)
def test_a_change_that_cannot_apply_points_at_the_authors_line(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(TYPO_IN_THE_CHANGE)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "could not be applied" in out
    assert "test_a_change_that_cannot_apply_points_at_the_authors_line.py:" in out
    assert "patching.py" not in out


def json_failures_are_quiet(m: Patch) -> None:
    original = plugin._Session.pytest_sessionfinish

    def finish(self, session, exitstatus):  # type: ignore[no-untyped-def]
        before = session.exitstatus
        original(self, session, exitstatus)
        session.exitstatus = before

    m.setattr(plugin._Session, "pytest_sessionfinish", finish)


@falsetto.must_fail_when(json_failures_are_quiet)
def test_an_unwritable_json_report_is_an_internal_error_exit(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(PROVEN_ONLY)
    blocker = pytester.path / "blocker"
    blocker.write_text("not a directory")
    result = pytester.runpytest(*RUN, f"--falsetto-json={blocker / 'out.json'}")
    assert "could not write the JSON report" in result.stdout.str()
    assert result.ret == 3
