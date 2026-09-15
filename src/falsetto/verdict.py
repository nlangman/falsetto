"""The four verdicts and the record a check receives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    """What is known about a check after the two runs."""

    PROVEN = "proven"
    """Passed as written, and failed under the declared change."""
    FAILED = "failed"
    """Failed as written: an ordinary red check."""
    FALSE = "false"
    """Passed as written, and still passed under the change: the check is wrong."""
    UNPROVEN = "unproven"
    """No declaration, or failed under the change for a reason other than the one declared."""


HINTS = {
    "undeclared": "Declare the change to the subject that should make this check fail.",
    "false": (
        "Under the declared change this check still passed. Either the assertion "
        "does not observe the change, or the fixture is the tautology."
    ),
    "wrong-reason": (
        "The negative run failed, but not for the stated reason. Narrow the change, "
        "or widen the expectation if the other failure is the one you mean."
    ),
    "not-applied": "The declared change could not be applied. Nothing is known about this check.",
}


@dataclass(frozen=True)
class Result:
    """The verdict for one check, with the reason and, for non-green verdicts, a hint."""

    verdict: Verdict
    reason: str
    declared: str | None = None
    hint: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """A plain, serializable record of this result."""
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "declared": self.declared,
            "hint": self.hint,
            "detail": self.detail,
        }
