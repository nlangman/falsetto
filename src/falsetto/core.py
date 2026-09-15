"""The runner-agnostic core: the two-run protocol and the four verdicts.

Every front-end (the pytest plugin, a bespoke harness, a port) calls `prove` or
`check` here. Nothing else computes a verdict.
"""
from __future__ import annotations

from typing import Any, Callable

from pytest import MonkeyPatch

from .declaration import Declaration
from .verdict import HINTS, Result, Verdict

Run = Callable[[], Any]
PASSTHROUGH: tuple[type[BaseException], ...] = (KeyboardInterrupt, SystemExit)


def prove(
    run: Run,
    decl: Declaration | None,
    subject: Any = None,
    passthrough: tuple[type[BaseException], ...] = PASSTHROUGH,
) -> Result:
    """The negative run, for a check whose positive run already passed.

    `run` executes the check once and raises on failure. `subject` is the check's
    own function, used to confirm an AssertionError came from its frame.
    """
    if decl is None:
        return Result(Verdict.UNPROVEN, "undeclared", None, HINTS["undeclared"])
    declared = decl.description
    with MonkeyPatch.context() as m:
        try:
            decl.change(m)
        except Exception as e:  # noqa: BLE001 - a change that cannot apply is reported, never raised
            return Result(Verdict.UNPROVEN, "not-applied", declared, HINTS["not-applied"], f"{type(e).__name__}: {e}")
        try:
            run()
        except passthrough:
            raise
        except BaseException as e:  # noqa: BLE001 - every failure kind is classified, never raised
            ok, why = decl.matches(e, subject)
            if ok:
                return Result(Verdict.PROVEN, "negative run failed for the stated reason", declared)
            return Result(
                Verdict.UNPROVEN, "wrong-reason", declared, HINTS["wrong-reason"],
                f"{why} ({type(e).__name__}: {e})",
            )
    return Result(Verdict.FALSE, "negative run passed", declared, HINTS["false"])


def check(
    run: Run,
    decl: Declaration | None,
    subject: Any = None,
    passthrough: tuple[type[BaseException], ...] = PASSTHROUGH,
) -> Result:
    """The whole protocol: positive run, then the negative run. For front-ends that
    do not already run the check themselves."""
    declared = decl.description if decl else None
    try:
        run()
    except passthrough:
        raise
    except BaseException:  # noqa: BLE001 - the positive run's failure is the verdict, never raised
        return Result(Verdict.FAILED, "positive run failed", declared)
    return prove(run, decl, subject, passthrough)
