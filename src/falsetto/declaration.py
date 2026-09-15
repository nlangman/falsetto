"""The declaration: the change to the subject under which a check must fail."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Change = Callable[[Any], None]
Expect = type[BaseException] | tuple[type[BaseException], ...] | Callable[[BaseException], bool]

ATTR = "__falsetto_declaration__"


def _unwrap(func: Any) -> Any:
    func = getattr(func, "__func__", func)  # bound method -> function
    return inspect.unwrap(func)


def raised_in(exc: BaseException, func: Any) -> bool:
    """Return True when ``exc`` was raised directly in ``func``'s own frame."""
    code = getattr(_unwrap(func), "__code__", None)
    tb = exc.__traceback__
    last = None
    while tb is not None:
        last = tb
        tb = tb.tb_next
    return last is not None and last.tb_frame.f_code is code


def _describe_callable(fn: Callable[..., Any]) -> str:
    name = getattr(fn, "__name__", "")
    if name and name != "<lambda>":
        return str(getattr(fn, "__qualname__", name))
    try:
        src = " ".join(inspect.getsource(fn).split())
    except (OSError, TypeError):
        return repr(fn)
    start = src.find("lambda")
    if start < 0:
        return src[:160]
    src = src[start:]
    depth = 0
    for i, ch in enumerate(src):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                src = src[:i]
                break
    return src.rstrip(", ")[:160]


@dataclass(frozen=True)
class Declaration:
    """The change to the subject that must make a check fail, and the failure expected.

    ``change`` receives a scoped patching handle (pytest's ``MonkeyPatch``) and mutates
    the subject in-process; the handle reverts everything when the negative run ends.
    ``expect`` is an exception type, a tuple of types, or a predicate over the exception.
    With the default expectation, ``AssertionError``, the failure must also be raised in
    the check's own frame: "it crashed somewhere" is not proof.
    """

    change: Change
    expect: Expect = AssertionError
    describe: str | None = None

    @property
    def description(self) -> str:
        """A short human description of the declared change, for reports."""
        return self.describe or _describe_callable(self.change)

    def matches(self, exc: BaseException, func: Any) -> tuple[bool, str]:
        """Decide whether ``exc`` is the failure this declaration expects.

        Returns ``(ok, why)``; ``why`` explains a rejection in one clause.
        """
        expect = self.expect
        if isinstance(expect, type | tuple):
            if not isinstance(exc, expect):
                wanted = (
                    expect.__name__
                    if isinstance(expect, type)
                    else "/".join(t.__name__ for t in expect)
                )
                return False, f"expected {wanted}, got {type(exc).__name__}"
            if expect is AssertionError and not raised_in(exc, func):
                return False, "AssertionError was raised outside the check's own frame"
            return True, "ok"
        ok = bool(expect(exc))
        return ok, "ok" if ok else f"predicate rejected {type(exc).__name__}"


def must_fail_when(
    change: Change,
    *,
    expect: Expect = AssertionError,
    describe: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare the change to the subject under which the decorated check must fail.

    The decorator attaches the declaration and returns the function unchanged, so
    the runner's fixture resolution and signature handling are untouched.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, ATTR, Declaration(change=change, expect=expect, describe=describe))
        return func

    return decorate


def get_declaration(obj: Any) -> Declaration | None:
    """Return the declaration attached to ``obj``, or None."""
    decl = getattr(obj, ATTR, None)
    return decl if isinstance(decl, Declaration) else None
