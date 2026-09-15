"""The runner-agnostic path and the patching handle, with no pytest item involved."""

from __future__ import annotations

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
        result = core.check_callable(fn, decl)
        assert result is not None
        return result.verdict

    assert verdict(cell, drop) is Verdict.PROVEN
    assert verdict(tautology, drop) is Verdict.FALSE
    assert verdict(cell, None) is Verdict.UNPROVEN
    assert verdict(counts_itself, nothing) is Verdict.UNPROVEN
    state["key"] = "other"
    assert verdict(cell, drop) is Verdict.FAILED


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


PatchUnderTest: type[Patch] = Patch


def never_undo(m: Patch) -> None:
    import tests.test_core as here

    m.setattr(here, "PatchUnderTest", _NoUndoPatch)


def permissive_setattr(m: Patch) -> None:
    import tests.test_core as here

    m.setattr(here, "PatchUnderTest", _PermissivePatch)


@falsetto.must_fail_when(never_undo)
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


@falsetto.must_fail_when(permissive_setattr)
def test_patch_refuses_a_missing_attribute_by_default() -> None:
    class Holder:
        attr = "original"

    with PatchUnderTest() as p:
        try:
            p.setattr(Holder, "missing", 1)
        except AttributeError:
            return
        raise AssertionError("setattr on a missing attribute did not raise")
