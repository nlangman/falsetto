"""What counts as failing for the stated reason, and how a declaration is described."""

from __future__ import annotations

import pytest

import falsetto
import falsetto.declaration as declaration
import falsetto.plugin as plugin
from falsetto.declaration import Declaration
from tests.helpers import RUN, line

WRONG_REASON = """
import falsetto

def boom():
    raise ValueError("connection refused to nowhere")

STATE = {"f": lambda: 1}

@falsetto.must_fail_when(lambda m: m.setitem(STATE, "f", boom))
def test_wrong_reason():
    assert STATE["f"]() == 1
"""


def accept_any_failure(m: falsetto.Patch) -> None:
    m.setattr(plugin, "DEFAULT_EXPECT", (BaseException,))


@falsetto.must_fail_when(accept_any_failure)
def test_failure_for_another_reason_is_unproven(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(WRONG_REASON)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "expected AssertionError or Failed, got ValueError" in out
    assert "pass expect=" in out


def summaries_are_empty(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_summary", lambda report: "")


@falsetto.must_fail_when(summaries_are_empty)
def test_a_wrong_reason_carries_the_failures_message_and_evidence(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(WRONG_REASON)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "got ValueError; ValueError: connection refused to nowhere" in out
    assert "    | " in out


EXPECTED_TYPE = """
import falsetto

def boom():
    raise ValueError("boom")

STATE = {"f": lambda: 1}

@falsetto.must_fail_when(lambda m: m.setitem(STATE, "f", boom), expect=ValueError)
def test_expect_value_error():
    assert STATE["f"]() == 1
"""


def reject_every_expectation(m: falsetto.Patch) -> None:
    m.setattr(Declaration, "matches", lambda self, exc, default: (False, "rejected"))


@falsetto.must_fail_when(reject_every_expectation)
def test_expectation_can_name_an_exception_type(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(EXPECTED_TYPE)
    result = pytester.runpytest(*RUN)
    assert line(1, 0, 0, 0) in result.stdout.str()
    assert result.ret == 0


PREDICATE = """
import falsetto

def boom():
    raise ValueError("boom happened")

STATE = {"f": lambda: 1}

@falsetto.must_fail_when(lambda m: m.setitem(STATE, "f", boom), expect=lambda e: "boom" in str(e))
def test_expect_predicate():
    assert STATE["f"]() == 1
"""


@falsetto.must_fail_when(reject_every_expectation)
def test_expectation_can_be_a_predicate_and_is_shown(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(PREDICATE)
    result = pytester.runpytest(*RUN, "--falsetto-json=out.json")
    assert line(1, 0, 0, 0) in result.stdout.str()
    assert "[expect=predicate" in (pytester.path / "out.json").read_text()


PYTEST_FAIL = """
import falsetto
import pytest

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_uses_pytest_fail():
    if VALUE["key"] != "k1":
        pytest.fail("key is wrong")
"""


def only_bare_assertions(m: falsetto.Patch) -> None:
    m.setattr(plugin, "DEFAULT_EXPECT", (AssertionError,))


@falsetto.must_fail_when(only_bare_assertions)
def test_pytest_fail_counts_as_the_stated_reason(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(PYTEST_FAIL)
    result = pytester.runpytest(*RUN)
    assert line(1, 0, 0, 0) in result.stdout.str()


HELPER = """
import falsetto

VALUE = {"key": "k1"}

def assert_key_is(expected):
    assert VALUE["key"] == expected

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_asserts_through_a_helper():
    assert_key_is("k1")
"""


@falsetto.must_fail_when(reject_every_expectation)
def test_assertions_in_helpers_count(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(HELPER)
    result = pytester.runpytest(*RUN)
    assert line(1, 0, 0, 0) in result.stdout.str()


NOT_APPLIED = """
import falsetto

def cannot(m):
    raise RuntimeError("cannot apply")

@falsetto.must_fail_when(cannot)
def test_x():
    assert True
"""


def locations_are_unknown(m: falsetto.Patch) -> None:
    import falsetto.core as core

    m.setattr(core, "location_of", lambda exc: None)


@falsetto.must_fail_when(locations_are_unknown)
def test_a_change_that_cannot_apply_is_unproven_with_a_location(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(NOT_APPLIED)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "RuntimeError: cannot apply; " in out
    assert "test_a_change_that_cannot_apply_is_unproven_with_a_location.py:4" in out


IMPORTORSKIP = """
import falsetto
import pytest

@falsetto.must_fail_when(lambda m: pytest.importorskip("no_such_module_anywhere"))
def test_x():
    assert True
"""


def describe_nothing(m: falsetto.Patch) -> None:
    import falsetto.core as core

    m.setattr(core, "describe_exception", lambda exc: "")


@falsetto.must_fail_when(describe_nothing)
def test_a_change_that_skips_is_not_applied_rather_than_a_skip(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(IMPORTORSKIP)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "1 unproven (1 graded of 1 run)" in out
    assert "could not be applied" in out
    assert "Skipped" in out


def never_already_declared(m: falsetto.Patch) -> None:
    m.setattr(declaration, "_already_declared", lambda func: False)


@falsetto.must_fail_when(never_already_declared)
def test_double_declaration_is_an_error() -> None:
    with pytest.raises(TypeError):

        @falsetto.must_fail_when(lambda m: None)
        @falsetto.must_fail_when(lambda m: None)
        def check() -> None:
            pass


def any_scope_goes(m: falsetto.Patch) -> None:
    m.setattr(declaration, "SCOPES", (*declaration.SCOPES, "bogus"))


@falsetto.must_fail_when(any_scope_goes)
def test_an_unknown_scope_is_an_error() -> None:
    with pytest.raises(ValueError, match="scope must be one of"):
        Declaration(lambda m: None, scope="bogus")  # type: ignore[arg-type]


def lambdas_are_undescribed(m: falsetto.Patch) -> None:
    m.setattr(declaration, "_describe_callable", lambda fn: declaration.UNDESCRIBED)


@falsetto.must_fail_when(lambdas_are_undescribed)
def test_a_lambda_declaration_is_described_by_its_source() -> None:
    data: dict[str, int] = {}
    decl = Declaration(lambda m: m.setitem(data, "k", 1), scope="module")
    assert decl.description.startswith("lambda m: m.setitem(data")
    assert decl.description.endswith("[scope=module]")
