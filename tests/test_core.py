"""The runner-agnostic path and the patching handle, with no pytest item involved."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from typing import Any

import falsetto
import falsetto.core as core
from falsetto import Declaration, Outcome, Patch, Reason, Result, Verdict
from tests.helpers import changes_never_bite, no_control_run


def _grades_as(reason: Reason, verdict: Verdict) -> Callable[[Patch], None]:
    """A change that relabels one of prove's verdicts and leaves every other one alone."""

    def change(m: Patch) -> None:
        original = core.prove

        def prove(run, decl, positive, **kw):  # type: ignore[no-untyped-def]
            result = original(run, decl, positive, **kw)
            if result is not None and result.reason is reason:
                return Result(verdict, Reason.STATED_REASON, result.declared)
            return result

        m.setattr(core, "prove", prove)

    change.__name__ = f"{reason.value.replace('-', '_')}_is_graded_{verdict.value}"
    return change


@falsetto.must_fail_when(changes_never_bite)
def test_check_callable_proves_a_check_that_reads_the_changed_state() -> None:
    state = {"key": "k1"}

    def cell() -> None:
        assert state["key"] == "k1"

    drop = Declaration(lambda m: m.setitem(state, "key", None), describe="key dropped")
    assert core.check_callable(cell, drop).verdict is Verdict.PROVEN


@falsetto.must_fail_when(_grades_as(Reason.NEGATIVE_PASSED, Verdict.PROVEN))
def test_check_callable_calls_a_tautology_false() -> None:
    state = {"key": "k1"}

    def tautology() -> None:
        assert state["key"] == state["key"]

    drop = Declaration(lambda m: m.setitem(state, "key", None), describe="key dropped")
    assert core.check_callable(tautology, drop).verdict is Verdict.FALSE


@falsetto.must_fail_when(_grades_as(Reason.UNDECLARED, Verdict.PROVEN))
def test_check_callable_leaves_an_undeclared_check_unproven() -> None:
    state = {"key": "k1"}

    def cell() -> None:
        assert state["key"] == "k1"

    assert core.check_callable(cell, None).verdict is Verdict.UNPROVEN


@falsetto.must_fail_when(no_control_run)
def test_check_callable_leaves_a_check_that_fails_on_rerun_unproven() -> None:
    calls: list[int] = []

    def counts_itself() -> None:
        calls.append(1)
        assert len(calls) == 1

    nothing = Declaration(lambda m: None, describe="a change that changes nothing")
    assert core.check_callable(counts_itself, nothing).verdict is Verdict.UNPROVEN


@falsetto.must_fail_when(_grades_as(Reason.POSITIVE_FAILED, Verdict.PROVEN))
def test_check_callable_reports_a_check_that_failed_as_written() -> None:
    state = {"key": "other"}

    def cell() -> None:
        assert state["key"] == "k1"

    drop = Declaration(lambda m: m.setitem(state, "key", None), describe="key dropped")
    assert core.check_callable(cell, drop).verdict is Verdict.FAILED


def default_expect_is_ignored(m: Patch) -> None:
    """Falsifies "default_expect= widens what check_callable accepts": the argument is dropped."""
    original = core.check_callable

    def check_callable(fn, decl, **kw):  # type: ignore[no-untyped-def]
        kw.pop("default_expect", None)
        return original(fn, decl, **kw)

    m.setattr(core, "check_callable", check_callable)


@falsetto.must_fail_when(default_expect_is_ignored)
def test_check_callable_takes_a_wider_default_expectation() -> None:
    state: dict[str, Callable[[], int]] = {"f": lambda: 1}

    def cell() -> None:
        assert state["f"]() == 1

    def boom() -> int:
        raise ValueError("the call is broken in another way")

    raises = Declaration(lambda m: m.setitem(state, "f", boom), describe="the call raises")
    assert core.check_callable(cell, raises).verdict is Verdict.UNPROVEN
    widened = core.check_callable(cell, raises, default_expect=(AssertionError, ValueError))
    assert widened.verdict is Verdict.PROVEN


def failures_have_no_evidence(m: Patch) -> None:
    m.setattr(core, "EVIDENCE_LIMIT", 0)


@falsetto.must_fail_when(failures_have_no_evidence)
def test_run_callable_observes_a_failure_with_its_evidence() -> None:
    def boom() -> None:
        raise ValueError("what went wrong")

    observed = core.run_callable(boom)
    assert observed.outcome is Outcome.FAILED
    assert observed.summary == "ValueError: what went wrong"
    assert observed.location is not None
    assert "test_core.py:" in observed.location
    assert observed.longrepr is not None
    assert "what went wrong" in observed.longrepr


def a_positive_that_did_not_complete_is_graded_anyway(m: Patch) -> None:
    """Falsifies "a positive run that neither passed nor failed has no verdict".

    The branch that returns None is gone, so such a run is graded like a passing one;
    nothing after that branch reads the positive run again.
    """
    original = core.prove

    def prove(run, decl, positive, **kw):  # type: ignore[no-untyped-def]
        if positive.outcome not in (Outcome.PASSED, Outcome.FAILED):
            positive = falsetto.RunResult(Outcome.PASSED)
        return original(run, decl, positive, **kw)

    m.setattr(core, "prove", prove)


@falsetto.must_fail_when(a_positive_that_did_not_complete_is_graded_anyway)
def test_a_positive_run_that_did_not_complete_has_no_verdict() -> None:
    result = core.prove(
        lambda: falsetto.RunResult(Outcome.PASSED),
        Declaration(lambda m: None),
        falsetto.RunResult(Outcome.SKIPPED),
    )
    assert result is None


class _NoUndoPatch(Patch):
    def undo(self) -> None:
        return None


class _AppliesNothingPatch(Patch):
    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        return None

    def setitem(self, mapping: Any, key: Any, value: Any) -> None:
        return None


class _OldestFirstPatch(Patch):
    def undo(self) -> None:
        while self._undo:
            self._undo.pop(0)()


class _PermissivePatch(Patch):
    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        setattr(target, name, value)


class _StopsAtFirstErrorPatch(Patch):
    def undo(self) -> None:
        while self._undo:
            self._undo.pop()()


class _CopiesInheritedPatch(Patch):
    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        old = getattr(target, name)
        setattr(target, name, value)
        self._undo.append(lambda: setattr(target, name, old))


PatchUnderTest: type[Patch] = Patch


def _use(kind: type[Patch]) -> Callable[[Patch], None]:
    def change(m: Patch) -> None:
        import tests.test_core as here

        m.setattr(here, "PatchUnderTest", kind)

    change.__name__ = f"use_{kind.__name__}"
    return change


@falsetto.must_fail_when(_use(_AppliesNothingPatch), describe="handles apply nothing")
def test_patch_applies_attributes_items_and_env_while_the_block_is_open() -> None:
    class Holder:
        attr = "original"

    mapping = {"a": 1}
    os.environ["FALSETTO_TEST_ENV"] = "old"
    try:
        with PatchUnderTest() as p:
            p.setattr(Holder, "attr", "changed")
            p.setitem(mapping, "a", 2)
            p.setenv("FALSETTO_TEST_ENV", "new", prepend=":")
            assert Holder.attr == "changed"
            assert mapping == {"a": 2}
            assert os.environ["FALSETTO_TEST_ENV"] == "new:old"
    finally:
        os.environ.pop("FALSETTO_TEST_ENV", None)


@falsetto.must_fail_when(_use(_NoUndoPatch), describe="handles never undo")
def test_patch_reverts_attributes_items_and_env() -> None:
    class Holder:
        attr = "original"

    mapping = {"a": 1}
    os.environ["FALSETTO_TEST_ENV"] = "old"
    try:
        with PatchUnderTest() as p:
            p.setattr(Holder, "attr", "changed")
            p.setattr(Holder, "added", "new", raising=False)
            p.setitem(mapping, "b", 3)
            p.setenv("FALSETTO_TEST_ENV", "new", prepend=":")
        assert Holder.attr == "original"
        assert not hasattr(Holder, "added")
        assert mapping == {"a": 1}
        assert os.environ["FALSETTO_TEST_ENV"] == "old"
    finally:
        os.environ.pop("FALSETTO_TEST_ENV", None)


@falsetto.must_fail_when(_use(_OldestFirstPatch), describe="undo runs the oldest change first")
def test_patch_undoes_changes_in_reverse_order() -> None:
    mapping = {"a": 1}
    with PatchUnderTest() as p:
        p.setitem(mapping, "a", 2)
        p.delitem(mapping, "a")
    assert mapping == {"a": 1}


@falsetto.must_fail_when(_use(_NoUndoPatch), describe="handles never undo")
def test_patch_delattr_and_delenv_restore_what_they_removed() -> None:
    class Holder:
        attr = "original"

    os.environ["FALSETTO_TEST_ENV2"] = "kept"
    try:
        with PatchUnderTest() as p:
            p.delattr(Holder, "attr")
            p.delenv("FALSETTO_TEST_ENV2")
            p.delattr(Holder, "absent", raising=False)
            p.delenv("FALSETTO_ABSENT_ENV", raising=False)
            assert not hasattr(Holder, "attr")
            assert "FALSETTO_TEST_ENV2" not in os.environ
        assert getattr(Holder, "attr", None) == "original"
        assert os.environ.get("FALSETTO_TEST_ENV2") == "kept"
    finally:
        os.environ.pop("FALSETTO_TEST_ENV2", None)


@falsetto.must_fail_when(_use(_PermissivePatch), describe="setattr never checks presence")
def test_patch_refuses_a_missing_attribute_by_default() -> None:
    class Holder:
        attr = "original"

    with PatchUnderTest() as p:
        try:
            p.setattr(Holder, "missing", 1)
        except AttributeError:
            return
        raise AssertionError("setattr on a missing attribute did not raise")


@falsetto.must_fail_when(_use(_StopsAtFirstErrorPatch), describe="undo stops at the first error")
def test_patch_undoes_every_step_even_when_one_raises() -> None:
    class Holder:
        first = "a"
        second = "b"

    p = PatchUnderTest()
    p.setattr(Holder, "first", "changed-a")
    p.setattr(Holder, "second", "changed-b")
    delattr(Holder, "second")  # the subject removed what the handle would restore by setattr
    p._undo.insert(1, lambda: (_ for _ in ()).throw(RuntimeError("an undo step failed")))
    with contextlib.suppress(RuntimeError):
        p.undo()
    assert Holder.first == "a"
    assert Holder.second == "b"


@falsetto.must_fail_when(_use(_CopiesInheritedPatch), describe="undo copies inherited values")
def test_patch_restores_an_inherited_attribute_as_inherited() -> None:
    class Base:
        setting = "base"

    class Child(Base):
        pass

    with PatchUnderTest() as p:
        p.setattr(Child, "setting", "changed")
        assert Child.setting == "changed"
    assert Child.setting == "base"
    assert "setting" not in vars(Child)
    Base.setting = "updated"
    assert Child.setting == "updated"
