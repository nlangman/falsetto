"""Falsetto: a pytest plugin that refuses to count a test until it has proven
the test can fail."""

from .core import Outcome, RunResult, check, check_callable, prove, run_callable
from .declaration import SCOPES, Declaration, must_fail_when
from .patching import Patch
from .verdict import Reason, Result, Verdict

__version__ = "0.0.1"
__all__ = [
    "SCOPES",
    "Declaration",
    "Outcome",
    "Patch",
    "Reason",
    "Result",
    "RunResult",
    "Verdict",
    "__version__",
    "check",
    "check_callable",
    "must_fail_when",
    "prove",
    "run_callable",
]
