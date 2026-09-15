"""Falsetto: a test runner that refuses to count a check unless it can prove
the check is capable of failing."""

from .core import check, prove
from .declaration import Declaration, must_fail_when
from .verdict import Result, Verdict

__version__ = "0.0.1"
__all__ = ["Declaration", "Result", "Verdict", "__version__", "check", "must_fail_when", "prove"]
