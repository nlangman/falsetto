"""The four verdicts, the reasons behind them, and the record a check receives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    """What is known about a check after its runs."""

    PROVEN = "proven"
    """Passed as written, passed again without the change, and failed under it."""
    FAILED = "failed"
    """Failed as written: an ordinary red check."""
    FALSE = "false"
    """Passed as written and still passed under the change: the check is wrong."""
    UNPROVEN = "unproven"
    """Nothing is known: no declaration, or the runs could not attribute a failure to the change."""

    def __str__(self) -> str:
        return self.value


class Reason(str, Enum):
    """Why a check got its verdict. Stable slugs an agent can branch on."""

    STATED_REASON = "stated-reason"
    POSITIVE_FAILED = "positive-failed"
    NEGATIVE_PASSED = "negative-passed"
    UNDECLARED = "undeclared"
    NOT_APPLIED = "not-applied"
    NOT_REVERTED = "not-reverted"
    WRONG_REASON = "wrong-reason"
    NOT_REPEATABLE = "not-repeatable"
    OUT_OF_SCOPE = "out-of-scope"
    MISCONFIGURED = "misconfigured"
    INTERNAL_ERROR = "internal-error"

    def __str__(self) -> str:
        return self.value


MESSAGES: dict[Reason, str] = {
    Reason.STATED_REASON: (
        "passed again without the change and failed under it for the stated reason"
    ),
    Reason.POSITIVE_FAILED: "failed as written",
    Reason.NEGATIVE_PASSED: "still passed under the declared change",
    Reason.UNDECLARED: "no declared change",
    Reason.NOT_APPLIED: "the declared change could not be applied",
    Reason.NOT_REVERTED: "the declared change could not be undone, so it may still be applied to "
    "every later check",
    Reason.WRONG_REASON: "failed under the declared change, but not for the stated reason",
    Reason.NOT_REPEATABLE: "did not pass when run again without the change, so no failure can be "
    "attributed to the change",
    Reason.OUT_OF_SCOPE: "still passed under the declared change, but it uses fixtures of a wider "
    "scope than the declaration rebuilds, so the change may never have reached them and the "
    "check may be false",
    Reason.MISCONFIGURED: "the declaration or the no_proof marker is misconfigured",
    Reason.INTERNAL_ERROR: "Falsetto itself raised while grading this check",
}

HINTS: dict[Reason, str] = {
    Reason.UNDECLARED: "Declare the change to the subject that should make this check fail.",
    Reason.NEGATIVE_PASSED: (
        "Either the assertion does not observe the change, the fixture is the tautology, the "
        "change never reached the subject (a name imported directly into the test module is "
        "not affected by patching its source module), or state warmed by an earlier run, such "
        "as a cache, masked the change."
    ),
    Reason.NOT_APPLIED: (
        "Fix the declared change; nothing is known about this check until it applies."
    ),
    Reason.NOT_REVERTED: (
        "Nothing after this check in this session can be trusted. Make the change's undo path "
        "safe (whatever it patches must accept its original value back), then rerun."
    ),
    Reason.WRONG_REASON: (
        "Narrow the change so it trips the check's own assertion, or pass expect= on the "
        "declaration if the failure you see is the one you mean."
    ),
    Reason.NOT_REPEATABLE: (
        "Make the check repeatable: build its state in fixtures rather than at module level, "
        "and do not depend on the order or count of runs. If the control run timed out, give "
        "each run its own budget (pytest-timeout's timeout_func_only) rather than one budget "
        "for all runs."
    ),
    Reason.OUT_OF_SCOPE: (
        "Widen scope= on the declaration so those fixtures are rebuilt under the change, or "
        "make the check read the subject directly. Until then this check fails the build: it "
        "cannot be graded under its declaration."
    ),
    Reason.MISCONFIGURED: (
        "Give no_proof a reason, do not combine it with a declaration, and use a scope the "
        "check can have."
    ),
    Reason.INTERNAL_ERROR: "This is a bug in Falsetto or in a hook it called. Please report it.",
}


@dataclass(frozen=True)
class Result:
    """The verdict for one check: the reason, a sentence, a hint when non-green, and evidence."""

    verdict: Verdict
    reason: Reason
    declared: str | None = None
    detail: str | None = None
    evidence: str | None = None

    @property
    def message(self) -> str:
        return MESSAGES[self.reason]

    @property
    def hint(self) -> str | None:
        return HINTS.get(self.reason)

    def to_dict(self) -> dict[str, Any]:
        """A plain, serializable record of this result."""
        return {
            "verdict": self.verdict.value,
            "reason": self.reason.value,
            "message": self.message,
            "declared": self.declared,
            "detail": self.detail,
            "hint": self.hint,
            "evidence": self.evidence,
        }
