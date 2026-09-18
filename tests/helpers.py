"""Declarations Falsetto's own checks use, each aimed at the property the check names.

A few checks assert what the whole summary reports rather than one mechanism; those use
the chokepoint at the end and say so. Everything else targets the mechanism it claims to
prove.
"""

from __future__ import annotations

from typing import Any

import falsetto.core as core
import falsetto.plugin as plugin
from falsetto import Outcome, Patch, Result, Verdict
from falsetto.verdict import Reason

RUN = ("-p", "no:cacheprovider", "--falsetto")
LINE = "falsetto: {proven} proven, {failed} failed as written, {false} false, {unproven} unproven"


def line(proven: int = 0, failed: int = 0, false: int = 0, unproven: int = 0) -> str:
    return LINE.format(proven=proven, failed=failed, false=false, unproven=unproven)


class _InertPatch(Patch):
    """A handle whose setattr and setitem do nothing: a change through either never lands.

    setenv goes through setitem and is neutered with it. delattr, delitem and delenv are
    not overridden and still bite.
    """

    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        return None

    def setitem(self, mapping: Any, key: Any, value: Any) -> None:
        return None


class _NoUndoPatch(Patch):
    """A handle that reverts nothing: whatever a change applied is still applied afterwards."""

    def undo(self) -> None:
        return None


class _ResolvingPatch(Patch):
    """A handle whose setattr reads the old value through ``getattr`` instead of the class slot.

    It restores what the attribute resolved to rather than what the class itself held, so an
    inherited value is copied onto the child and a descriptor comes back already bound.
    """

    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        old = getattr(target, name)
        setattr(target, name, value)
        self._undo.append(lambda: setattr(target, name, old))


def changes_never_bite(m: Patch) -> None:
    """Falsifies "the negative run applies the declared change"."""
    m.setattr(core, "Patch", _InertPatch)


def markers_are_ignored(m: Patch) -> None:
    """Falsifies "the no_proof marker is read": no check carries one."""
    m.setattr(plugin, "_marker_reason", lambda item: None)


def every_fixture_is_in_scope(m: Patch) -> None:
    """Falsifies "a fixture wider than the declaration's scope is found": none ever is."""
    m.setattr(plugin, "_wider_fixtures", lambda item, scope: [])


def false_never_fails_the_build(m: Patch) -> None:
    """Falsifies "a false check is a failure"."""
    m.setattr(plugin, "_fails_build", lambda result, strict: False)


def no_control_run(m: Patch) -> None:
    """Falsifies "proven requires a passing control run": positive, then negative only."""

    def prove_without_control(run, decl, positive, **kw):  # type: ignore[no-untyped-def]
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


def boundary_is_the_item(m: Patch) -> None:
    """Falsifies "every run starts from a fresh boundary": nothing is torn down between runs."""
    m.setattr(plugin, "_boundary", lambda item, scope: item)


def boundary_is_the_session(m: Patch) -> None:
    """Falsifies "the default boundary keeps wider fixtures alive": everything is rebuilt."""
    m.setattr(plugin, "_boundary", lambda item, scope: None)


def everything_is_proven(m: Patch) -> None:
    """The chokepoint: every graded check reports proven.

    Used only by checks whose subject is the summary itself, where every line of the
    summary moves together and no narrower change reaches all of them.
    """
    m.setattr(
        core,
        "prove",
        lambda run, decl, positive, **kw: Result(Verdict.PROVEN, Reason.STATED_REASON),
    )
