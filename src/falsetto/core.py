"""The runner-agnostic core: the run protocol and the only place verdicts are computed.

A front-end (the pytest plugin, a bespoke harness, a port) supplies one thing: how to
run the check once, as a callable returning a :class:`RunResult`. The core applies the
declared change through a :class:`~falsetto.patching.Patch`, drives the negative and
control runs, and classifies. Nothing else computes a verdict.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
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


Run = Callable[[], RunResult]
Passthrough = tuple[type[BaseException], ...]
PASSTHROUGH: Passthrough = (KeyboardInterrupt, SystemExit)
DEFAULT_EXPECT: ExceptionTypes = (AssertionError,)


def describe_exception(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    first = text[0] if text else ""
    return f"{type(exc).__name__}: {first}"[:300]


def run_callable(fn: Callable[[], object], passthrough: Passthrough = PASSTHROUGH) -> RunResult:
    """Run a plain callable once and observe it. The building block for a harness."""
    try:
        fn()
    except passthrough:
        raise
    except BaseException as e:
        tb = traceback.extract_tb(e.__traceback__)
        location = f"{tb[-1].filename}:{tb[-1].lineno}" if tb else None
        return RunResult(Outcome.FAILED, e, location, describe_exception(e))
    return RunResult(Outcome.PASSED)


def _failure_detail(run: RunResult, why: str | None = None) -> str:
    parts = [p for p in (why, run.summary, run.location) if p]
    return "; ".join(parts) if parts else "no detail available"


def prove(
    run: Run,
    decl: Declaration | None,
    positive: RunResult,
    *,
    default_expect: ExceptionTypes = DEFAULT_EXPECT,
    passthrough: Passthrough = PASSTHROUGH,
) -> Result | None:
    """Grade a check whose positive run has already happened.

    Returns None when the positive run neither passed nor failed (it was skipped, or
    could not complete), because then there is no check to grade.
    """
    declared = decl.description if decl else None
    if positive.outcome is Outcome.FAILED:
        return Result(Verdict.FAILED, Reason.POSITIVE_FAILED, declared, positive.summary)
    if positive.outcome is not Outcome.PASSED:
        return None
    if decl is None:
        return Result(Verdict.UNPROVEN, Reason.UNDECLARED)

    with Patch() as patch:
        try:
            decl.change(patch)
        except passthrough:
            raise
        except BaseException as e:
            return Result(Verdict.UNPROVEN, Reason.NOT_APPLIED, declared, describe_exception(e))
        negative = run()

    if negative.outcome is Outcome.PASSED:
        return Result(Verdict.FALSE, Reason.NEGATIVE_PASSED, declared)
    if negative.outcome is Outcome.SKIPPED:
        detail = _failure_detail(negative, "the check was skipped under the change")
        return Result(Verdict.UNPROVEN, Reason.WRONG_REASON, declared, detail)
    if negative.outcome is Outcome.ERRORED:
        detail = _failure_detail(negative, "setup or teardown failed under the change")
        return Result(Verdict.UNPROVEN, Reason.WRONG_REASON, declared, detail)

    ok, why = decl.matches(negative.exception, default_expect)
    if not ok:
        return Result(
            Verdict.UNPROVEN, Reason.WRONG_REASON, declared, _failure_detail(negative, why)
        )

    control = run()
    if control.outcome is Outcome.PASSED:
        return Result(Verdict.PROVEN, Reason.STATED_REASON, declared)
    detail = _failure_detail(control, f"control run {control.outcome.value}")
    return Result(Verdict.UNPROVEN, Reason.NOT_REPEATABLE, declared, detail)


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
) -> Result | None:
    """Grade a plain callable: the one-line entry point for a bespoke harness."""
    return check(
        lambda: run_callable(fn, passthrough),
        decl,
        default_expect=default_expect,
        passthrough=passthrough,
    )


def internal_error(exc: BaseException, decl: Declaration | None) -> Result:
    """The verdict when Falsetto itself failed while grading: unproven, and loud."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return Result(Verdict.UNPROVEN, Reason.INTERNAL_ERROR, decl.description if decl else None, tb)
