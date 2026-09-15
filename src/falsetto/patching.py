"""A scoped, in-process patching handle. Everything it changes is undone on exit."""

from __future__ import annotations

import os
from collections.abc import Callable, MutableMapping
from typing import Any

_MISSING = object()


class Patch:
    """The handle a declaration receives. Changes go through it so they revert.

    Use it as a context manager. Every change is recorded and undone in reverse
    order when the block ends, whether or not the block raised. Anything changed
    outside the handle is not reverted, and Falsetto cannot see it.
    """

    def __init__(self) -> None:
        self._undo: list[Callable[[], None]] = []

    def __enter__(self) -> Patch:
        return self

    def __exit__(self, *exc: object) -> None:
        self.undo()

    def undo(self) -> None:
        """Undo every recorded change, most recent first."""
        while self._undo:
            self._undo.pop()()

    def setattr(self, target: object, name: str, value: object, raising: bool = True) -> None:
        """Set ``target.name = value``; restore or delete it on undo."""
        old = getattr(target, name, _MISSING)
        if old is _MISSING and raising:
            raise AttributeError(f"{target!r} has no attribute {name!r}")
        setattr(target, name, value)
        if old is _MISSING:
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
        """Set ``mapping[key] = value``; restore or delete it on undo."""
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
