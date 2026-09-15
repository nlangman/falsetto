"""The runner-agnostic core: the run protocol and the only place verdicts are computed.

A front-end (the pytest plugin, a bespoke harness, a port) supplies one thing: how to
run the check once, as a callable returning a :class:`RunResult`. The core drives the
control and negative runs, applies the declared change through a
:class:`~falsetto.patching.Patch`, and classifies. Nothing else computes a verdict.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from .declaration import Declaration, ExceptionTypes
from .patching import Patch
from .verdict import Reason, Result, Verdict


class Outcome(Enum):
    """What one run of a check did."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERRORED = "errored"
    """The run could not complete the check: its setup or teardown failed."""


@dataclass(frozen=True)
class RunResult:
    """One run of a check, as the front-end observed it."""

    outcome: Outcome
    exception: BaseException | None = None
    location: str | None = None
    summary: str | None = None
    longrepr: str | None = None


Run = Callable[[], RunResult]
Passthrough = tuple[type[BaseException], ...]
PASSTHROUGH: Passthrough = (KeyboardInterrupt, SystemExit)
DEFAULT_EXPECT: ExceptionTypes = (AssertionError,)
EVIDENCE_LIMIT = 4000


def describe_exception(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    first = text[0] if text else ""
    return f"{type(exc).__name__}: {first}"[:300]


def location_of(exc: BaseException) -> str | None:
    tb = traceback.extract_tb(exc.__traceback__)
    return f"{tb[-1].filename}:{tb[-1].lineno}" if tb else None


def _evidence(text: str) -> str:
    """The tail of a failure's text, bounded; an empty limit keeps nothing."""
    return text[-EVIDENCE_LIMIT:] if EVIDENCE_LIMIT else ""


def run_callable(fn: Callable[[], object], passthrough: Passthrough = PASSTHROUGH) -> RunResult:
    """Run a plain callable once and observe it. The building block for a harness."""
    try:
        fn()
    except passthrough:
        raise
    except BaseException as e:
        text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        return RunResult(Outcome.FAILED, e, location_of(e), describe_exception(e), _evidence(text))
    return RunResult(Outcome.PASSED)


def _detail(run: RunResult, why: str | None = None) -> str:
    parts = [p for p in (why, run.summary, run.location) if p]
    return "; ".join(parts) if parts else "no detail available"


def prove(
    run: Run,
    decl: Declaration | None,
    positive: RunResult,
    *,
    default_expect: ExceptionTypes = DEFAULT_EXPECT,
    passthrough: Passthrough = PASSTHROUGH,
    wider_fixtures: Sequence[str] = (),
) -> Result | None:
    """Grade a check whose positive run has already happened.

    Order: the control run first (the check again, unchanged, which must pass), then
    the negative run under the declared change. A control run second catches every
    check that does not pass on its second execution, before a failure could be
    credited to the change. ``wider_fixtures`` names fixtures the check uses that the
    declaration's scope does not rebuild; when the negative run passes and there are
    any, the verdict is unproven, never false.

    Returns None when the positive run neither passed nor failed, because then there
    is no check to grade.
    """
    declared = decl.description if decl else None
    if positive.outcome is Outcome.FAILED:
        return Result(Verdict.FAILED, Reason.POSITIVE_FAILED, declared, positive.summary)
    if positive.outcome is not Outcome.PASSED:
        return None
    if decl is None:
        return Result(Verdict.UNPROVEN, Reason.UNDECLARED)

    control = run()
    if control.outcome is not Outcome.PASSED:
        detail = _detail(control, f"control run {control.outcome.value}")
        return Result(Verdict.UNPROVEN, Reason.NOT_REPEATABLE, declared, detail, control.longrepr)

    with Patch() as patch:
        try:
            decl.change(patch)
        except passthrough:
            raise
        except BaseException as e:
            detail = "; ".join(p for p in (describe_exception(e), location_of(e)) if p)
            return Result(Verdict.UNPROVEN, Reason.NOT_APPLIED, declared, detail)
        negative = run()

    if negative.outcome is Outcome.PASSED:
        if wider_fixtures:
            detail = (
                "uses " + ", ".join(wider_fixtures) + f"; the declaration's scope is {decl.scope}"
            )
            return Result(Verdict.UNPROVEN, Reason.OUT_OF_SCOPE, declared, detail)
        return Result(Verdict.FALSE, Reason.NEGATIVE_PASSED, declared)
    if negative.outcome is Outcome.SKIPPED:
        detail = _detail(negative, "the check was skipped under the change")
        return Result(Verdict.UNPROVEN, Reason.WRONG_REASON, declared, detail, negative.longrepr)
    if negative.outcome is Outcome.ERRORED:
        detail = _detail(negative, "setup or teardown failed under the change")
        return Result(Verdict.UNPROVEN, Reason.WRONG_REASON, declared, detail, negative.longrepr)

    ok, why = decl.matches(negative.exception, default_expect)
    if not ok:
        detail = _detail(negative, why)
        return Result(Verdict.UNPROVEN, Reason.WRONG_REASON, declared, detail, negative.longrepr)
    return Result(Verdict.PROVEN, Reason.STATED_REASON, declared)


def check(
    run: Run,
    decl: Declaration | None,
    *,
    default_expect: ExceptionTypes = DEFAULT_EXPECT,
    passthrough: Passthrough = PASSTHROUGH,
) -> Result | None:
    """The whole protocol for a front-end that does not run checks itself."""
    return prove(run, decl, run(), default_expect=default_expect, passthrough=passthrough)


def check_callable(
    fn: Callable[[], object],
    decl: Declaration | None,
    *,
    default_expect: ExceptionTypes = DEFAULT_EXPECT,
    passthrough: Passthrough = PASSTHROUGH,
) -> Result:
    """Grade a plain callable: the one-line entry point for a bespoke harness.

    A plain callable either passes or raises, so there is always a verdict.
    """
    result = check(
        lambda: run_callable(fn, passthrough),
        decl,
        default_expect=default_expect,
        passthrough=passthrough,
    )
    assert result is not None  # a callable cannot be skipped or errored
    return result


def misconfigured(why: str, decl: Declaration | None) -> Result:
    """The verdict for a check whose declaration or marker cannot be honoured."""
    return Result(Verdict.UNPROVEN, Reason.MISCONFIGURED, decl.description if decl else None, why)


def internal_error(exc: BaseException, decl: Declaration | None) -> Result:
    """The verdict when Falsetto itself failed while grading: unproven, and loud."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    declared = decl.description if decl else None
    return Result(Verdict.UNPROVEN, Reason.INTERNAL_ERROR, declared, describe_exception(exc), tb)
