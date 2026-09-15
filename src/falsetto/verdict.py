from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    PROVEN = "proven"      # passed as written, failed under the declared change
    FAILED = "failed"      # failed as written: an ordinary red check
    FALSE = "false"        # passed as written, still passed under the change: the check is wrong
    UNPROVEN = "unproven"  # no declaration, or failed under the change for another reason


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
    verdict: Verdict
    reason: str
    declared: str | None = None
    hint: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "declared": self.declared,
            "hint": self.hint,
            "detail": self.detail,
        }
