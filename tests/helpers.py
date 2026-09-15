"""Declarations Falsetto's own checks use, each aimed at the property the check names.

A few checks assert only that the verdict line reads a certain way; those use the
chokepoint below and say so. Everything else targets the mechanism it claims to prove.
"""

from __future__ import annotations

import falsetto.core as core
import falsetto.plugin as plugin
from falsetto import Outcome, Patch, Result, Verdict
from falsetto.verdict import Reason

RUN = ("-p", "no:cacheprovider", "--falsetto")


class _InertPatch(Patch):
    """A handle that records nothing and changes nothing: declared changes never bite."""

    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        return None

    def setitem(self, mapping, key, value) -> None:  # type: ignore[no-untyped-def]
        return None


def changes_never_bite(m: Patch) -> None:
    """Falsifies "the negative run applies the declared change"."""
    m.setattr(core, "Patch", _InertPatch)


def false_never_fails_the_build(m: Patch) -> None:
    """Falsifies "a false check is a failure"."""
    m.setattr(plugin, "_fails_build", lambda result, strict: False)


def no_control_run(m: Patch) -> None:
    """Falsifies "proven requires a passing control run"."""

    def prove_without_control(run, decl, positive, *, default_expect, passthrough):  # type: ignore[no-untyped-def]
        declared = decl.description if decl else None
        if positive.outcome is Outcome.FAILED:
            return Result(Verdict.FAILED, Reason.POSITIVE_FAILED, declared)
        if decl is None:
            return Result(Verdict.UNPROVEN, Reason.UNDECLARED)
        with Patch() as patch:
            decl.change(patch)
            negative = run()
        if negative.outcome is Outcome.FAILED:
            return Result(Verdict.PROVEN, Reason.STATED_REASON, declared)
        return Result(Verdict.FALSE, Reason.NEGATIVE_PASSED, declared)

    m.setattr(core, "prove", prove_without_control)


def everything_is_proven(m: Patch) -> None:
    """The chokepoint: every graded check reports proven. Used only by line-shape checks."""
    m.setattr(
        core,
        "prove",
        lambda run, decl, positive, **kw: Result(Verdict.PROVEN, Reason.STATED_REASON),
    )
