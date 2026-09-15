"""Falsetto's own checks, each declaring the change to Falsetto that must make it red."""

import contextlib

import pytest

import falsetto
import falsetto.plugin as plugin
from falsetto.verdict import Result, Verdict

RUN = ("-p", "no:cacheprovider")


def stub_prove_all_proven(m):
    m.setattr(plugin, "prove", lambda item, decl: Result(Verdict.PROVEN, "stubbed", None))


def stub_prove_all_unproven(m):
    m.setattr(plugin, "prove", lambda item, decl: Result(Verdict.UNPROVEN, "stubbed", None, "stub"))


@contextlib.contextmanager
def _leaky_context():
    yield pytest.MonkeyPatch()  # never undone


def leak_the_negative_run(m):
    m.setattr(pytest.MonkeyPatch, "context", staticmethod(_leaky_context))


FOUR = '''
import falsetto

VALUE = {"key": "k1"}

def read_key():
    return VALUE["key"]

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None), describe="key dropped")
def test_proven():
    assert read_key() == "k1"

def test_failed():
    assert read_key() == "other"

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_false():
    expected = read_key()
    assert read_key() == expected

def test_unproven():
    assert read_key() == "k1"
'''


@falsetto.must_fail_when(stub_prove_all_proven)
def test_four_verdicts(pytester):
    pytester.makepyfile(FOUR)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "falsetto: 1 proven, 1 failed, 1 false, 1 unproven" in out
    assert "FALSE test_four_verdicts.py::test_false" in out
    assert "the fixture is the tautology" in out
    assert "UNPROVEN test_four_verdicts.py::test_unproven" in out
    assert result.ret == 1


UNDECLARED = '''
def test_passes():
    assert True
'''


@falsetto.must_fail_when(stub_prove_all_proven)
def test_strict_counts_unproven_as_failure(pytester):
    pytester.makepyfile(UNDECLARED)
    lenient = pytester.runpytest(*RUN)
    assert "falsetto: 0 proven, 0 failed, 0 false, 1 unproven" in lenient.stdout.str()
    assert lenient.ret == 0
    strict = pytester.runpytest(*RUN, "--falsetto-strict")
    assert strict.ret == 1


WRONG_REASON = '''
import falsetto

def boom():
    raise ValueError("boom")

STATE = {"f": lambda: 1}

@falsetto.must_fail_when(lambda m: m.setitem(STATE, "f", boom))
def test_wrong_reason():
    assert STATE["f"]() == 1
'''


@falsetto.must_fail_when(stub_prove_all_proven)
def test_failure_for_another_reason_is_unproven(pytester):
    pytester.makepyfile(WRONG_REASON)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "falsetto: 0 proven, 0 failed, 0 false, 1 unproven" in out
    assert "expected AssertionError, got ValueError" in out


EXPECTED_TYPE = '''
import falsetto

def boom():
    raise ValueError("boom")

STATE = {"f": lambda: 1}

@falsetto.must_fail_when(lambda m: m.setitem(STATE, "f", boom), expect=ValueError)
def test_expect_value_error():
    assert STATE["f"]() == 1
'''


@falsetto.must_fail_when(stub_prove_all_unproven)
def test_expectation_can_name_an_exception_type(pytester):
    pytester.makepyfile(EXPECTED_TYPE)
    result = pytester.runpytest(*RUN)
    assert "falsetto: 1 proven, 0 failed, 0 false, 0 unproven" in result.stdout.str()
    assert result.ret == 0


REVERT = '''
import falsetto

STATE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(STATE, "key", None))
def test_a_proven():
    assert STATE["key"] == "k1"

def test_b_sees_the_original_after_the_negative_run():
    assert STATE["key"] == "k1"
'''


@falsetto.must_fail_when(leak_the_negative_run)
def test_negative_run_is_reverted(pytester):
    pytester.makepyfile(REVERT)
    result = pytester.runpytest(*RUN)
    assert "falsetto: 1 proven, 0 failed, 0 false, 1 unproven" in result.stdout.str()
    assert result.ret == 0


NOT_APPLIED = '''
import falsetto

def cannot(m):
    raise RuntimeError("cannot apply")

@falsetto.must_fail_when(cannot)
def test_x():
    assert True
'''


@falsetto.must_fail_when(stub_prove_all_proven)
def test_declaration_that_cannot_apply_is_unproven(pytester):
    pytester.makepyfile(NOT_APPLIED)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "falsetto: 0 proven, 0 failed, 0 false, 1 unproven" in out
    assert "RuntimeError: cannot apply" in out


# The runner-agnostic path: a bespoke harness hands `check` a plain callable and a
# declaration, and gets the same verdicts the pytest adapter gets.
def stub_core_prove_all_proven(m):
    import falsetto.core as core
    m.setattr(core, "prove", lambda run, decl, subject=None, passthrough=(): Result(Verdict.PROVEN, "stubbed", None))


@falsetto.must_fail_when(stub_core_prove_all_proven)
def test_core_check_without_a_runner():
    import falsetto.core as core

    state = {"key": "k1"}

    def cell():
        assert state["key"] == "k1"

    def tautology():
        assert state["key"] == state["key"]

    drop = falsetto.Declaration(lambda m: m.setitem(state, "key", None), describe="key dropped")

    assert core.check(cell, drop, subject=cell).verdict is Verdict.PROVEN
    assert core.check(tautology, drop, subject=tautology).verdict is Verdict.FALSE
    assert core.check(cell, None).verdict is Verdict.UNPROVEN
    state["key"] = "other"
    assert core.check(cell, drop, subject=cell).verdict is Verdict.FAILED
