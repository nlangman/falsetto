"""A scoped, in-process patching handle. Everything it changes is undone on exit."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable, MutableMapping
from typing import Any

_MISSING = object()


def _attempt(step: Callable[[], None]) -> BaseException | None:
    """Run one undo step and report what it raised, so the loop can finish either way."""
    try:
        step()
    except BaseException as e:
        return e
    return None


class Patch:
    """The handle a declaration receives. Changes go through it so they revert.

    Use it as a context manager. Every change is recorded and undone in reverse
    order when the block ends, whether or not the block raised. An undo step that
    raises does not stop the others; the first error is raised after every step ran,
    and nothing another step raised is dropped without a trace.
    An attribute the target inherited is restored as inherited, not copied onto it.
    Anything changed outside the handle is not reverted, and Falsetto cannot see it.
    """

    def __init__(self) -> None:
        self._undo: list[Callable[[], None]] = []

    def __enter__(self) -> Patch:
        return self

    def __exit__(self, *exc: object) -> None:
        self.undo()

    def undo(self) -> None:
        """Undo every recorded change, most recent first, even if some steps raise.

        An interrupt (``KeyboardInterrupt``, ``SystemExit``) raised by one step does not
        leave the subject half-restored: the remaining steps still run, and the interrupt
        is raised afterwards, ahead of any ordinary error. That error is not lost with it:
        the first one becomes the interrupt's ``__context__``, so a traceback still shows
        what else went wrong while the subject was being put back.
        """
        errors: list[BaseException] = []
        interrupts: list[BaseException] = []
        while self._undo:
            raised = _attempt(self._undo.pop())
            if raised is None:
                continue
            (errors if isinstance(raised, Exception) else interrupts).append(raised)
        if interrupts:
            if not errors:
                raise interrupts[0]
            # Raising the error first makes it the exception being handled, so the
            # interrupt chains onto it. Assigning __context__ instead would be lost:
            # the raise overwrites it with whatever is being handled around undo().
            try:
                raise errors[0]
            except BaseException:
                raise interrupts[0]  # noqa: B904
        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise RuntimeError(
                f"{len(errors)} undo steps failed; the first: {errors[0]!r}"
            ) from errors[0]

    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        """Set ``target.name = value``; restore, or remove, it on undo.

        On a class the raw descriptor is restored, so a staticmethod or classmethod
        comes back as one, and an inherited attribute comes back inherited.
        """
        namespace = getattr(target, "__dict__", None)
        own = namespace is None or name in namespace
        if inspect.isclass(target) and own and namespace is not None:
            old: object = namespace[name]
        else:
            old = getattr(target, name, _MISSING)
        if old is _MISSING and raising:
            raise AttributeError(f"{target!r} has no attribute {name!r}")
        setattr(target, name, value)
        if old is _MISSING or not own:
            self._undo.append(lambda: delattr(target, name))
        else:
            self._undo.append(lambda: setattr(target, name, old))

    def delattr(self, target: object, name: str, raising: bool = True) -> None:
        """Delete ``target.name``; restore it on undo."""
        old = getattr(target, name, _MISSING)
        if old is _MISSING:
            if raising:
                raise AttributeError(f"{target!r} has no attribute {name!r}")
            return
        delattr(target, name)
        self._undo.append(lambda: setattr(target, name, old))

    def setitem(self, mapping: MutableMapping[Any, Any], key: Any, value: Any) -> None:
        """Set ``mapping[key] = value``; restore, or remove, it on undo."""
        old = mapping.get(key, _MISSING)
        mapping[key] = value
        if old is _MISSING:
            self._undo.append(lambda: mapping.pop(key, None))
        else:
            self._undo.append(lambda: mapping.__setitem__(key, old))

    def delitem(self, mapping: MutableMapping[Any, Any], key: Any, raising: bool = True) -> None:
        """Delete ``mapping[key]``; restore it on undo."""
        old = mapping.get(key, _MISSING)
        if old is _MISSING:
            if raising:
                raise KeyError(key)
            return
        del mapping[key]
        self._undo.append(lambda: mapping.__setitem__(key, old))

    def setenv(self, name: str, value: str, prepend: str | None = None) -> None:
        """Set an environment variable; ``prepend`` joins it in front of the old value."""
        if prepend is not None and name in os.environ:
            value = value + prepend + os.environ[name]
        self.setitem(os.environ, name, value)

    def delenv(self, name: str, raising: bool = True) -> None:
        """Delete an environment variable; restore it on undo."""
        self.delitem(os.environ, name, raising)
