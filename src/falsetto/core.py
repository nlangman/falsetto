"""The runner-agnostic core: the two-run protocol and the four verdicts.

Every front-end (the pytest plugin, a bespoke harness, a port) calls :func:`prove`
or :func:`check` here. Nothing else computes a verdict.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from .declaration import Declaration
from .verdict import HINTS, Result, Verdict

Run = Callable[[], Any]
Passthrough = tuple[type[BaseException], ...]
PASSTHROUGH: Passthrough = (KeyboardInterrupt, SystemExit)


def prove(
    run: Run,
    decl: Declaration | None,
    subject: Any = None,
    passthrough: Passthrough = PASSTHROUGH,
) -> Result:
    """The negative run, for a check whose positive run already passed.

    ``run`` executes the check once and raises on failure. ``subject`` is the check's
    own function, used to confirm an ``AssertionError`` came from its frame.
    Exceptions listed in ``passthrough`` are re-raised, never classified.
    """
    if decl is None:
        return Result(Verdict.UNPROVEN, "undeclared", None, HINTS["undeclared"])
    declared = decl.description
    with pytest.MonkeyPatch.context() as m:
        try:
            decl.change(m)
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            return Result(Verdict.UNPROVEN, "not-applied", declared, HINTS["not-applied"], detail)
        try:
            run()
        except passthrough:
            raise
        except BaseException as e:
            ok, why = decl.matches(e, subject)
            if ok:
                return Result(Verdict.PROVEN, "negative run failed for the stated reason", declared)
            detail = f"{why} ({type(e).__name__}: {e})"
            return Result(Verdict.UNPROVEN, "wrong-reason", declared, HINTS["wrong-reason"], detail)
    return Result(Verdict.FALSE, "negative run passed", declared, HINTS["false"])


def check(
    run: Run,
    decl: Declaration | None,
    subject: Any = None,
    passthrough: Passthrough = PASSTHROUGH,
) -> Result:
    """The whole protocol: the positive run, then the negative run.

    For front-ends that do not run checks themselves. The pytest plugin does not use
    it, because pytest performs the positive run.
    """
    declared = decl.description if decl else None
    try:
        run()
    except passthrough:
        raise
    except BaseException:
        return Result(Verdict.FAILED, "positive run failed", declared)
    return prove(run, decl, subject, passthrough)
