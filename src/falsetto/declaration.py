"""The declaration: the change to the subject under which a check must fail."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .patching import Patch

Change = Callable[[Patch], None]
ExceptionTypes = type[BaseException] | tuple[type[BaseException], ...]
Expect = ExceptionTypes | Callable[[BaseException], bool]

ATTR = "__falsetto_declaration__"
UNDESCRIBED = "(undescribed change; pass describe= to name it)"


def _describe_callable(fn: Callable[..., Any]) -> str:
    name = getattr(fn, "__name__", "")
    if name and name != "<lambda>":
        return str(getattr(fn, "__qualname__", name))
    try:
        src = " ".join(inspect.getsource(fn).split())
    except (OSError, TypeError):
        return UNDESCRIBED
    start = src.find("lambda")
    if start < 0:
        return UNDESCRIBED
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


def _type_names(types: ExceptionTypes) -> str:
    if isinstance(types, type):
        return types.__name__
    return " or ".join(t.__name__ for t in types)


@dataclass(frozen=True)
class Declaration:
    """The change to the subject that must make a check fail, and the failure expected.

    ``change`` receives a :class:`~falsetto.patching.Patch` and mutates the subject
    in-process; the handle reverts everything when the negative run ends. ``expect``
    is an exception type, a tuple of types, or a predicate over the exception. When it
    is None the front-end's default applies: for the pytest plugin, an ``AssertionError``
    or a ``pytest.fail``. A failure of any other kind is "wrong reason", never proof.
    """

    change: Change
    expect: Expect | None = None
    describe: str | None = None

    @property
    def description(self) -> str:
        """A short human description of the declared change, for reports."""
        text = self.describe or _describe_callable(self.change)
        if self.expect is not None:
            text += f" [expect={self.expectation}]"
        return text

    @property
    def expectation(self) -> str:
        if self.expect is None:
            return "default"
        if isinstance(self.expect, type | tuple):
            return _type_names(self.expect)
        return f"predicate {getattr(self.expect, '__qualname__', repr(self.expect))}"

    def matches(self, exc: BaseException | None, default: ExceptionTypes) -> tuple[bool, str]:
        """Decide whether ``exc`` is the failure this declaration expects.

        Returns ``(ok, why)``; ``why`` explains a rejection in one clause.
        """
        if exc is None:
            return False, "the failure's exception could not be inspected"
        expect = self.expect if self.expect is not None else default
        if isinstance(expect, type | tuple):
            if isinstance(exc, expect):
                return True, "ok"
            return False, f"expected {_type_names(expect)}, got {type(exc).__name__}"
        try:
            ok = bool(expect(exc))
        except Exception as e:
            return False, f"the expectation predicate raised {type(e).__name__}: {e}"
        return ok, "ok" if ok else f"the expectation predicate rejected {type(exc).__name__}"


def must_fail_when(
    change: Change,
    *,
    expect: Expect | None = None,
    describe: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare the change to the subject under which the decorated check must fail.

    The decorator attaches the declaration and returns the function unchanged, so the
    runner's fixture resolution and signature handling are untouched. Applying it
    twice is an error: a check has one declaration.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        if _already_declared(func):
            raise TypeError(f"{func.__qualname__} already carries a declaration")
        setattr(func, ATTR, Declaration(change=change, expect=expect, describe=describe))
        return func

    return decorate


def _already_declared(func: Any) -> bool:
    return getattr(func, ATTR, None) is not None


def get_declaration(obj: Any) -> Declaration | None:
    """Return the declaration attached to ``obj``, or None."""
    decl = getattr(obj, ATTR, None)
    return decl if isinstance(decl, Declaration) else None
