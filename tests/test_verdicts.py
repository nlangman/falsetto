"""The four verdicts, and the rules that make false and unproven real failures."""

from __future__ import annotations

import pytest

import falsetto
import falsetto.plugin as plugin
import falsetto.verdict as verdict
from falsetto import Reason
from tests.helpers import (
    RUN,
    changes_never_bite,
    everything_is_proven,
    false_never_fails_the_build,
    line,
)


def a_reason_without_a_message_is_accepted(m: falsetto.Patch) -> None:
    """Falsifies "a Reason with no message is refused": any mapping is accepted."""
    m.setattr(verdict, "_require_a_message_for_every_reason", lambda messages: None)


@falsetto.must_fail_when(a_reason_without_a_message_is_accepted)
def test_a_reason_without_a_message_is_refused() -> None:
    incomplete: dict[Reason, str] = {
        r: verdict.MESSAGES[r] for r in Reason if r is not Reason.POSITIVE_FAILED
    }
    with pytest.raises(AssertionError, match="positive-failed"):
        verdict._require_a_message_for_every_reason(incomplete)


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


@falsetto.must_fail_when(everything_is_proven)
def test_four_verdicts(pytester: pytest.Pytester) -> None:
    """A summary-shaped check: it uses the chokepoint, since every line below moves with it."""
    pytester.makepyfile(FOUR)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(1, 1, 1, 1) + " (4 graded of 4 run)" in out
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
    out = result.stdout.str()
    assert result.ret == 1
    assert "1 failed" in out
    assert "FALSE: still passed under the declared change" in out
    assert "at: " in out


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
    assert line(1, 0, 0, 0) in result.stdout.str()


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
    assert line(0, 0, 0, 1) in lenient.stdout.str()
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


DOCTEST_ONLY = '''
def double(n):
    """
    >>> double(2)
    4
    """
    return n * 2
'''


@falsetto.must_fail_when(strict_zero_never_fails)
def test_strict_fails_when_only_ungradable_items_ran(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(DOCTEST_ONLY)
    result = pytester.runpytest(*RUN, "--falsetto-strict", "--doctest-modules")
    assert result.ret == 1
    assert "no check was graded" in result.stdout.str()
    assert "1 not gradable" in result.stdout.str()


def ini_says_enabled(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_ini", lambda config, key: True)


@falsetto.must_fail_when(ini_says_enabled)
def test_plugin_is_inert_without_the_flag(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(UNDECLARED)
    result = pytester.runpytest("-p", "no:cacheprovider")
    out = result.stdout.str()
    assert "1 passed" in out
    assert "falsetto:" not in out
    assert "= falsetto =" not in out
    assert result.ret == 0


def ini_is_ignored(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_ini", lambda config, key: False)


@falsetto.must_fail_when(ini_is_ignored)
def test_ini_keys_enable_grading_and_strict(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nfalsetto = true\nfalsetto_strict = true\n")
    pytester.makepyfile(UNDECLARED)
    result = pytester.runpytest("-p", "no:cacheprovider")
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "UNPROVEN (strict)" in out
    assert result.ret == 1


CRASHING_CONFTEST = """
import falsetto.plugin as p

_original = p._observe

def _boom(item, reports, **kw):
    if item.name == "test_healthy":
        return _original(item, reports, **kw)
    raise RuntimeError("grading exploded")

def pytest_configure(config):
    p._observe = _boom

def pytest_unconfigure(config):
    p._observe = _original
"""


def internal_errors_look_proven(m: falsetto.Patch) -> None:
    import falsetto.core as core

    m.setattr(
        core,
        "internal_error",
        lambda exc, decl: falsetto.Result(falsetto.Verdict.PROVEN, falsetto.Reason.STATED_REASON),
    )


@falsetto.must_fail_when(internal_errors_look_proven)
def test_a_crash_inside_falsetto_is_loud_and_attributed(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(PROVEN_ONLY)
    pytester.makeconftest(CRASHING_CONFTEST)
    result = pytester.runpytest(*RUN, "--tb=no")
    out = result.stdout.str()
    assert "FALSETTO-ERROR" in out
    assert "grading exploded" in out
    assert line(0, 0, 0, 1) in out
    assert result.ret == 1


RED_AS_WRITTEN = """
VALUE = 1

def test_red():
    assert VALUE == 2, "the real defect this check caught"
"""


def internal_error_replaces_the_failure(m: falsetto.Patch) -> None:
    """Falsifies "a failing report keeps the text it already carried": the new text replaces it."""

    def fail_report(report: pytest.TestReport, text: str) -> None:
        report.outcome = "failed"
        report.longrepr = text

    m.setattr(plugin, "_fail_report", fail_report)


@falsetto.must_fail_when(internal_error_replaces_the_failure)
def test_an_internal_error_keeps_the_checks_own_failure(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(RED_AS_WRITTEN)
    pytester.makeconftest(CRASHING_CONFTEST)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "the real defect this check caught" in out
    assert "internal error while grading" in out


SKIPPING_FIXTURE = """
import pytest

@pytest.fixture
def gone():
    pytest.skip("no such thing here")

def test_uses_it(gone):
    assert True

def test_healthy():
    assert True
"""


def only_call_reports_carry_failures(m: falsetto.Patch) -> None:
    def call_only(reports):  # type: ignore[no-untyped-def]
        return next((r for r in reports if r.when == "call"), None)

    m.setattr(plugin, "_attach_target", call_only)


@falsetto.must_fail_when(only_call_reports_carry_failures)
def test_an_internal_error_without_a_call_report_is_still_loud(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(SKIPPING_FIXTURE)
    pytester.makeconftest(CRASHING_CONFTEST)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "FALSETTO-ERROR" in out
    assert result.ret == 1


def summarize_even_when_nothing_ran(m: falsetto.Patch) -> None:
    m.setattr(plugin.Tally, "run", property(lambda self: max(1, len(self.items))))


@falsetto.must_fail_when(summarize_even_when_nothing_ran)
def test_collect_only_prints_no_verdicts(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FOUR)
    result = pytester.runpytest(*RUN, "--collect-only")
    assert "falsetto:" not in result.stdout.str()
