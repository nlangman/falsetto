"""The runner-agnostic path and the patching handle, with no pytest item involved."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable

import falsetto
import falsetto.core as core
from falsetto import Declaration, Outcome, Patch, Verdict
from tests.helpers import no_control_run


@falsetto.must_fail_when(no_control_run)
def test_check_callable_grades_without_a_runner() -> None:
    state = {"key": "k1"}
    calls: list[int] = []

    def cell() -> None:
        assert state["key"] == "k1"

    def tautology() -> None:
        assert state["key"] == state["key"]

    def counts_itself() -> None:
        calls.append(1)
        assert len(calls) == 1

    drop = Declaration(lambda m: m.setitem(state, "key", None), describe="key dropped")
    nothing = Declaration(lambda m: None, describe="nothing")

    def verdict(fn: Callable[[], None], decl: Declaration | None) -> Verdict:
        return core.check_callable(fn, decl).verdict

    assert verdict(cell, drop) is Verdict.PROVEN
    assert verdict(tautology, drop) is Verdict.FALSE
    assert verdict(cell, None) is Verdict.UNPROVEN
    assert verdict(counts_itself, nothing) is Verdict.UNPROVEN
    state["key"] = "other"
    assert verdict(cell, drop) is Verdict.FAILED


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


def skipped_counts_as_failed(m: Patch) -> None:
    m.setattr(
        core,
        "prove",
        lambda run, decl, positive, **kw: falsetto.Result(
            Verdict.FAILED, falsetto.Reason.POSITIVE_FAILED
        ),
    )


@falsetto.must_fail_when(skipped_counts_as_failed)
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


@falsetto.must_fail_when(_use(_NoUndoPatch), describe="handles never undo")
def test_patch_reverts_attributes_items_and_env_in_reverse_order() -> None:
    class Holder:
        attr = "original"

    mapping = {"a": 1}
    os.environ["FALSETTO_TEST_ENV"] = "old"
    try:
        with PatchUnderTest() as p:
            p.setattr(Holder, "attr", "changed")
            p.setattr(Holder, "added", "new", raising=False)
            p.setitem(mapping, "a", 2)
            p.setitem(mapping, "b", 3)
            p.delitem(mapping, "a")
            p.setenv("FALSETTO_TEST_ENV", "new", prepend=":")
            assert Holder.attr == "changed"
            assert mapping == {"b": 3}
            assert os.environ["FALSETTO_TEST_ENV"] == "new:old"
        assert Holder.attr == "original"
        assert not hasattr(Holder, "added")
        assert mapping == {"a": 1}
        assert os.environ["FALSETTO_TEST_ENV"] == "old"
    finally:
        os.environ.pop("FALSETTO_TEST_ENV", None)


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
