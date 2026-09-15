"""The four verdicts, and the rules that make false and unproven real failures."""

from __future__ import annotations

import pytest

import falsetto
import falsetto.plugin as plugin
from tests.helpers import RUN, changes_never_bite, false_never_fails_the_build

FOUR = """
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
"""


@falsetto.must_fail_when(changes_never_bite)
def test_four_verdicts(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FOUR)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "falsetto: 1 proven, 1 failed, 1 false, 1 unproven (4 graded of 4 run)" in out
    assert "FALSE test_four_verdicts.py::test_false" in out
    assert "the fixture is the tautology" in out
    assert "UNPROVEN test_four_verdicts.py::test_unproven" in out
    assert result.ret == 1


FALSE_ONLY = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_false():
    expected = VALUE["key"]
    assert VALUE["key"] == expected
"""


@falsetto.must_fail_when(false_never_fails_the_build)
def test_a_false_check_alone_fails_the_build(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_ONLY)
    result = pytester.runpytest(*RUN)
    assert result.ret == 1
    assert "1 failed" in result.stdout.str()
    assert "FALSE: still passed under the declared change" in result.stdout.str()


PROVEN_ONLY = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_proven():
    assert VALUE["key"] == "k1"
"""


@falsetto.must_fail_when(changes_never_bite)
def test_a_proven_check_alone_passes_the_build(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(PROVEN_ONLY)
    result = pytester.runpytest(*RUN)
    assert result.ret == 0
    assert "1 proven" in result.stdout.str()


UNDECLARED = """
def test_passes():
    assert True
"""


def unproven_never_fails_strict(m: falsetto.Patch) -> None:
    m.setattr(
        plugin, "_fails_build", lambda result, strict: result.verdict is falsetto.Verdict.FALSE
    )


@falsetto.must_fail_when(unproven_never_fails_strict)
def test_strict_counts_unproven_as_failure(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(UNDECLARED)
    lenient = pytester.runpytest(*RUN)
    assert lenient.ret == 0
    assert "0 proven, 0 failed, 0 false, 1 unproven" in lenient.stdout.str()
    strict = pytester.runpytest(*RUN, "--falsetto-strict")
    assert strict.ret == 1
    assert "UNPROVEN (strict): no declared change" in strict.stdout.str()


def strict_zero_never_fails(m: falsetto.Patch) -> None:
    m.setattr(plugin._Session, "strict_zero_graded", lambda self: False)


ALL_SKIPPED = """
import pytest

@pytest.mark.skip(reason="not today")
def test_a():
    assert True
"""


@falsetto.must_fail_when(strict_zero_never_fails)
def test_strict_fails_when_nothing_was_graded(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(ALL_SKIPPED)
    result = pytester.runpytest(*RUN, "--falsetto-strict")
    assert result.ret == 1
    assert "falsetto: strict: no check was graded" in result.stdout.str()
    assert "0 graded of 1 run; 1 skipped" in result.stdout.str()


def always_enabled(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_settings", lambda config: plugin.Settings(True, False, None))


@falsetto.must_fail_when(always_enabled)
def test_plugin_is_inert_without_the_flag(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(UNDECLARED)
    result = pytester.runpytest("-p", "no:cacheprovider")
    out = result.stdout.str()
    assert "1 passed" in out
    assert "falsetto:" not in out
    assert "= falsetto =" not in out
    assert result.ret == 0


def internal_errors_look_proven(m: falsetto.Patch) -> None:
    import falsetto.core as core

    m.setattr(
        core,
        "internal_error",
        lambda exc, decl: falsetto.Result(falsetto.Verdict.PROVEN, falsetto.Reason.STATED_REASON),
    )


RAISING_EXPECT = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None), expect=lambda e: 1 / 0)
def test_x():
    assert VALUE["key"] == "k1"
"""


@falsetto.must_fail_when(internal_errors_look_proven)
def test_a_crash_inside_falsetto_is_loud_and_attributed(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(RAISING_EXPECT)
    pytester.makeconftest(
        "import falsetto.plugin as p\n"
        "_original = p._observe\n"
        "def _boom(*a, **k):\n    raise RuntimeError('grading exploded')\n"
        "def pytest_configure(config):\n    p._observe = _boom\n"
        "def pytest_unconfigure(config):\n    p._observe = _original\n"
    )
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "falsetto: internal error while grading this check" in out
    assert "grading exploded" in out
    assert "0 proven, 0 failed, 0 false, 1 unproven" in out
    assert result.ret == 1
