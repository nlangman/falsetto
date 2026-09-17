"""Every run of a check starts from the same boundary, and proven needs a control run."""

from __future__ import annotations

import pytest

import falsetto
import falsetto.plugin as plugin
from tests.helpers import (
    RUN,
    boundary_is_the_item,
    boundary_is_the_session,
    changes_never_bite,
    line,
    no_control_run,
)

ALTERNATING = """
import falsetto

STATE = {"n": 0}
SUBJECT = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(SUBJECT, "key", "BROKEN"),
                         describe="subject key broken (this check never reads it)")
def test_alternates():
    STATE["n"] += 1
    assert STATE["n"] % 2 == 1
"""


@falsetto.must_fail_when(no_control_run)
def test_a_check_that_alternates_is_never_proven(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(ALTERNATING)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "no failure can be attributed to the change" in out


MONOTONE = """
import falsetto

CALLS = []

@falsetto.must_fail_when(lambda m: None, describe="a change that changes nothing")
def test_counts_its_own_calls():
    CALLS.append(1)
    assert len(CALLS) == 1
"""


@falsetto.must_fail_when(no_control_run)
def test_a_check_that_fails_on_rerun_is_never_proven(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(MONOTONE)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "control run 1 failed" in out


FIXTURE_TARGET = """
import falsetto
import pytest

CONFIG = {"prefix": "id-"}

@pytest.fixture
def ident():
    return CONFIG["prefix"] + "42"

@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "prefix", "BROKEN-"))
def test_ident_has_the_prefix(ident):
    assert ident.startswith("id-")
"""


@falsetto.must_fail_when(changes_never_bite)
def test_a_change_applied_before_setup_reaches_function_fixtures(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FIXTURE_TARGET)
    result = pytester.runpytest(*RUN)
    assert line(1, 0, 0, 0) in result.stdout.str()
    assert result.ret == 0


FRESH_FIXTURE = """
import falsetto
import pytest

@pytest.fixture
def queue():
    return [1]

@falsetto.must_fail_when(lambda m: None, describe="a change that changes nothing")
def test_consumes_the_queue(queue):
    assert queue.pop() == 1
"""


@falsetto.must_fail_when(boundary_is_the_item)
def test_function_fixtures_are_fresh_for_every_run(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FRESH_FIXTURE)
    result = pytester.runpytest(*RUN)
    assert line(0, 0, 1, 0) in result.stdout.str()


MODULE_FIXTURE = """
import falsetto
import pytest

CONFIG = {"prefix": "id-"}

@pytest.fixture(scope="module")
def ident():
    return CONFIG["prefix"] + "42"

@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "prefix", "BROKEN-"), scope="module")
def test_first_with_a_sibling_after_it(ident):
    assert ident.startswith("id-")

@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "prefix", "BROKEN-"), scope="module")
def test_last_in_the_session(ident):
    assert ident.startswith("id-")
"""


@falsetto.must_fail_when(boundary_is_the_item)
def test_verdicts_do_not_depend_on_position(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(MODULE_FIXTURE)
    both = pytester.runpytest(*RUN)
    assert line(2, 0, 0, 0) + " (2 graded of 2 run)" in both.stdout.str()
    alone = pytester.runpytest(*RUN, "-k", "first_with_a_sibling")
    assert line(1, 0, 0, 0) in alone.stdout.str()


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


def every_fixture_is_in_scope(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_wider_fixtures", lambda item, scope: [])


@falsetto.must_fail_when(every_fixture_is_in_scope)
def test_a_wider_fixture_makes_a_passing_negative_run_out_of_scope_not_false(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(OUT_OF_SCOPE)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "ident (module-scoped)" in out
    assert "Widen scope=" in out
    assert result.ret == 1


SESSION_FIXTURE = """
import falsetto
import pytest

COUNT = {"setups": 0}

@pytest.fixture(scope="session")
def expensive():
    COUNT["setups"] += 1
    yield "ready"
    print("SESSION_SETUPS", COUNT["setups"])

@pytest.fixture
def value(expensive):
    return {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(FLAG, "on", False))
def test_uses_a_session_fixture(value):
    assert value["key"] == "k1" and FLAG["on"]

FLAG = {"on": True}
"""


@falsetto.must_fail_when(boundary_is_the_session)
def test_a_session_fixture_is_built_once_under_a_function_scoped_declaration(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(SESSION_FIXTURE)
    result = pytester.runpytest(*RUN, "-s")
    out = result.stdout.str()
    assert line(1, 0, 0, 0) in out
    assert "SESSION_SETUPS 1" in out
    assert "SESSION_SETUPS 2" not in out


UNITTEST = """
import unittest
import falsetto

VALUE = {"key": "k1"}

class Suite(unittest.TestCase):
    @falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
    def test_detects_the_change(self):
        self.assertEqual(VALUE["key"], "k1")

    def test_fails_as_written(self):
        self.assertEqual(VALUE["key"], "other")
"""


def unittest_failures_look_like_passes(m: falsetto.Patch) -> None:
    original = plugin._observe

    def observe(item, reports, *, graded_run):  # type: ignore[no-untyped-def]
        observed = original(item, reports, graded_run=graded_run)
        if observed is not None and observed.outcome is falsetto.Outcome.FAILED:
            return falsetto.RunResult(falsetto.Outcome.PASSED)
        return observed

    m.setattr(plugin, "_observe", observe)


@falsetto.must_fail_when(unittest_failures_look_like_passes)
def test_unittest_checks_are_graded_by_their_reports(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(UNITTEST)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(1, 1, 0, 0) in out
    assert "AssertionError" in out
    assert result.ret == 1


SETUPCLASS = """
import unittest
import falsetto

CONFIG = {"prefix": "id-"}

class Suite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ident = CONFIG["prefix"] + "42"

    @falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "prefix", "BROKEN-"), scope="class")
    def test_ident_has_the_prefix(self):
        self.assertTrue(self.ident.startswith("id-"))
"""


@falsetto.must_fail_when(changes_never_bite)
def test_setupclass_state_is_rebuilt_under_a_class_scoped_declaration(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(SETUPCLASS)
    result = pytester.runpytest(*RUN)
    assert line(1, 0, 0, 0) in result.stdout.str()


CLASS_AND_PARAMS = """
import falsetto
import pytest

VALUE = {"key": "k1"}

class TestGroup:
    @pytest.mark.parametrize("n", [1, 2])
    @falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
    def test_key(self, n):
        assert VALUE["key"] == "k1"
"""


@falsetto.must_fail_when(changes_never_bite)
def test_class_based_and_parametrized_checks(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(CLASS_AND_PARAMS)
    result = pytester.runpytest(*RUN)
    assert line(2, 0, 0, 0) + " (2 graded of 2 run)" in result.stdout.str()


REVERT = """
import falsetto

STATE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(STATE, "key", None))
def test_a_proven():
    assert STATE["key"] == "k1"

def test_b_sees_the_original_after_the_negative_run():
    assert STATE["key"] == "k1"
"""


class _NoUndoPatch(falsetto.Patch):
    def undo(self) -> None:
        return None


def leak_the_negative_run(m: falsetto.Patch) -> None:
    import falsetto.core as core

    m.setattr(core, "Patch", _NoUndoPatch)


@falsetto.must_fail_when(leak_the_negative_run)
def test_negative_run_is_reverted(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(REVERT)
    result = pytester.runpytest(*RUN)
    assert line(1, 0, 0, 1) in result.stdout.str()
    assert result.ret == 0


HOOK_CHAIN = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_x():
    assert VALUE["key"] == "k1"
"""

COUNTING_CONFTEST = """
import pytest

CALLS = {"call": 0}

@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    CALLS["call"] += 1
    return (yield)

def pytest_sessionfinish(session):
    print("RUNTEST_CALL_HOOK_SEEN", CALLS["call"])
"""


def rerun_only_the_body(m: falsetto.Patch) -> None:
    def bare_protocol(item, log=True, nextitem=None):  # type: ignore[no-untyped-def]
        item.runtest()
        setup = pytest.TestReport(
            item.nodeid, item.location, {}, "passed", None, "setup", [], 0.0, 0.0, 0.0
        )
        call = pytest.TestReport(
            item.nodeid, item.location, {}, "passed", None, "call", [], 0.0, 0.0, 0.0
        )
        return [setup, call]

    m.setattr(plugin, "runtestprotocol", bare_protocol)


@falsetto.must_fail_when(rerun_only_the_body)
def test_every_run_goes_through_the_full_hook_chain(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(COUNTING_CONFTEST)
    pytester.makepyfile(HOOK_CHAIN)
    result = pytester.runpytest(*RUN, "-s")
    assert "RUNTEST_CALL_HOOK_SEEN 3" in result.stdout.str()


TEARDOWN_BREAKS = """
import falsetto
import pytest

CONFIG = {"ok": True}

@pytest.fixture
def resource():
    yield "r"
    assert CONFIG["ok"], "teardown broke under the change"

@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "ok", False))
def test_reads_config(resource):
    assert CONFIG["ok"]
"""


def teardown_failures_are_ignored(m: falsetto.Patch) -> None:
    original = plugin._observe

    def observe(item, reports, *, graded_run):  # type: ignore[no-untyped-def]
        return original(item, [r for r in reports if r.when != "teardown"], graded_run=graded_run)

    m.setattr(plugin, "_observe", observe)


@falsetto.must_fail_when(teardown_failures_are_ignored)
def test_a_negative_run_whose_teardown_fails_is_unproven(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(TEARDOWN_BREAKS)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "setup or teardown failed under the change" in out


COVERAGE_MODULE = """
def used():
    return 1

def dead():
    return 2
"""

COVERAGE_TEST = """
import falsetto
import mod

@falsetto.must_fail_when(lambda m: m.setattr(mod, "used", lambda: mod.dead()))
def test_used():
    assert mod.used() == 1
"""


COVERAGE_CONFTEST = """
import contextlib
import os

import falsetto.plugin

if os.environ.get("FALSETTO_TEST_COVERAGE_RUNS_THROUGH"):
    falsetto.plugin._coverage_paused = contextlib.nullcontext
"""


def coverage_runs_through(m: falsetto.Patch) -> None:
    m.setenv("FALSETTO_TEST_COVERAGE_RUNS_THROUGH", "1")


@falsetto.must_fail_when(coverage_runs_through)
def test_graded_runs_do_not_inflate_coverage(pytester: pytest.Pytester) -> None:
    pytest.importorskip("pytest_cov")
    pytester.makeconftest(COVERAGE_CONFTEST)
    pytester.makepyfile(mod=COVERAGE_MODULE, test_cov=COVERAGE_TEST)
    result = pytester.runpytest_subprocess(*RUN, "--cov=mod", "--cov-report=term-missing")
    out = result.stdout.str()
    assert line(1, 0, 0, 0) in out
    mod_line = next(text for text in out.splitlines() if text.startswith("mod.py"))
    assert "100%" not in mod_line


FORGED = """
import json
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_forges_its_own_verdict(record_property):
    forged = {"verdict": "proven", "reason": "stated-reason"}
    record_property("falsetto.verdict", json.dumps(forged))
    expected = VALUE["key"]
    assert VALUE["key"] == expected
"""


def first_record_wins(m: falsetto.Patch) -> None:
    def first(report, name):  # type: ignore[no-untyped-def]
        for prop_name, value in report.user_properties:
            if prop_name == name:
                return value
        return None

    m.setattr(plugin, "_last_property", first)


@falsetto.must_fail_when(first_record_wins)
def test_a_check_cannot_forge_its_own_verdict(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FORGED)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 1, 0) in out
    assert result.ret == 1
