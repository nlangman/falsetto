"""The negative run is a whole fresh protocol, and proven needs a passing control run."""

from __future__ import annotations

import pytest

import falsetto
from tests.helpers import RUN, changes_never_bite, everything_is_proven, no_control_run

NON_REPEATABLE = """
import falsetto

CALLS = []

@falsetto.must_fail_when(lambda m: None, describe="a change that changes nothing")
def test_counts_its_own_calls():
    CALLS.append(1)
    assert len(CALLS) == 1
"""


@falsetto.must_fail_when(no_control_run)
def test_a_check_that_fails_on_rerun_is_never_proven(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(NON_REPEATABLE)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "0 proven" in out
    assert "1 unproven" in out
    assert "cannot be attributed to the change" in out


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
def test_a_change_applied_before_setup_reaches_fixtures(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FIXTURE_TARGET)
    result = pytester.runpytest(*RUN)
    assert "1 proven, 0 failed, 0 false, 0 unproven" in result.stdout.str()
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


@falsetto.must_fail_when(everything_is_proven)
def test_fixtures_are_fresh_so_residue_cannot_fake_a_failure(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FRESH_FIXTURE)
    result = pytester.runpytest(*RUN)
    assert "0 proven, 0 failed, 1 false, 0 unproven" in result.stdout.str()


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
    import falsetto.plugin as plugin

    original = plugin._observe

    def observe(item, reports):  # type: ignore[no-untyped-def]
        observed = original(item, reports)
        if observed is not None and observed.outcome is falsetto.Outcome.FAILED:
            return falsetto.RunResult(falsetto.Outcome.PASSED)
        return observed

    m.setattr(plugin, "_observe", observe)


@falsetto.must_fail_when(unittest_failures_look_like_passes)
def test_unittest_checks_are_graded_by_their_reports(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(UNITTEST)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "1 proven, 1 failed, 0 false, 0 unproven" in out
    assert "AssertionError" in out
    assert result.ret == 1


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
    assert "2 proven, 0 failed, 0 false, 0 unproven (2 graded of 2 run)" in result.stdout.str()


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
    """Falsifies "the negative run is reverted": new handles never undo."""
    import falsetto.core as core

    m.setattr(core, "Patch", _NoUndoPatch)


@falsetto.must_fail_when(leak_the_negative_run)
def test_negative_run_is_reverted(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(REVERT)
    result = pytester.runpytest(*RUN)
    assert "1 proven, 0 failed, 0 false, 1 unproven" in result.stdout.str()
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
    import falsetto.plugin as plugin

    def bare_protocol(item, log=True, nextitem=None):  # type: ignore[no-untyped-def]
        item.runtest()
        report = pytest.TestReport(
            item.nodeid, item.location, {}, "passed", None, "call", [], 0.0, 0.0, 0.0
        )
        setup = pytest.TestReport(
            item.nodeid, item.location, {}, "passed", None, "setup", [], 0.0, 0.0, 0.0
        )
        return [setup, report]

    m.setattr(plugin, "runtestprotocol", bare_protocol)


@falsetto.must_fail_when(rerun_only_the_body)
def test_every_run_goes_through_the_full_hook_chain(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(COUNTING_CONFTEST)
    pytester.makepyfile(HOOK_CHAIN)
    result = pytester.runpytest(*RUN, "-s")
    assert "RUNTEST_CALL_HOOK_SEEN 3" in result.stdout.str()
