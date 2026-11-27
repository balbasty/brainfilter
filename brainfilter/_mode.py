"""The read/write mode of a BIDS path, and the guard on its mutating members.

A path is read-only (`"r"`) unless it was built with `mode="w"` or
returned by `with_mode("w")`. The mode is held on the path object and
carried onto every path derived from it. It is a brainfilter rule, not a
filesystem permission: the wrapped driver object (`path.wrapped`) and the
backend's own handles (`path.fs`, `path.client`) reach the storage directly
and are not guarded.

The same members, on a writable path, refuse a raw write that an open
transaction would lose: to a JSON or TSV file below its root, to a
directory holding a file it holds, or a directory made where it holds a
file (see `transaction.refuse_raw_write`).
"""
from __future__ import annotations

import functools
import inspect
import os
from collections.abc import Callable
from typing import Any

from brainfilter._family import in_family
from brainfilter.transaction import refuse_raw_write

__all__ = ["MODES", "ReadOnlyError", "check_mode", "guard_members",
           "is_read_only", "require_writable"]

MODES = ("r", "w")

# The members of `bagof.paths.Path` and `AsyncPath` that change the
# filesystem, with what each is said to do in an error. `own`: the path
# itself is written or removed. `target`: the parameter that names a
# destination, refused when it is a read-only BIDS path.
_MEMBERS: dict[str, tuple[str, bool, str | None]] = {
    "write_text": ("write to", True, None),
    "write_bytes": ("write to", True, None),
    "open": ("open for writing", True, None),
    "touch": ("touch", True, None),
    "mkdir": ("create the directory", True, None),
    "unlink": ("remove", True, None),
    "rmdir": ("remove the directory", True, None),
    "rename": ("rename", True, "target"),
    "replace": ("rename", True, "target"),
    "symlink_to": ("make a symbolic link at", True, None),
    "hardlink_to": ("make a hard link at", True, None),
    "link_to": ("make a hard link at", False, "target"),
    "chmod": ("change the mode of", True, None),
    "lchmod": ("change the mode of", True, None),
    "staged": ("stage a new version of", True, None),
    "copy": ("copy onto", False, "target"),
    "copy_into": ("copy into", False, "target_dir"),
    "move": ("move", True, "target"),
    "move_into": ("move into", True, "target_dir"),
    "upload_from": ("upload to", True, None),
    "download_to": ("download to", False, "destination"),
}

# The characters of an `open()` mode that write.
_WRITING = frozenset("wax+")

# What a member does to its destination, said in the error of a raw write
# that a transaction refuses.
_ONTO = {
    "rename": "rename onto",
    "replace": "rename onto",
    "move": "move onto",
    "move_into": "move onto",
    "copy": "copy onto",
    "copy_into": "copy onto",
    "link_to": "make a hard link at",
    "download_to": "download to",
}

# The members whose destination is a directory, the path's name in it: a
# `download_to` destination may be either.
_INTO = frozenset({"copy_into", "move_into"})


class ReadOnlyError(PermissionError):
    """A write was asked of a read-only path.

    Paths are read-only by default. Build a writable one with
    `BidsPath(url, mode="w")`, or get one with `path.with_mode("w")`.
    """


def check_mode(mode: object) -> str:
    """Return `mode`, checked to be `"r"` or `"w"`."""
    if mode not in MODES:
        raise ValueError(
            f"invalid mode {mode!r}: a path is read-only (mode='r') or "
            "writable (mode='w')"
        )
    return mode  # type: ignore[return-value]


def is_read_only(path: object) -> bool:
    """Whether `path` is a BIDS path in read-only mode.

    Any other object (a string, a plain `bagof.paths.Path`) has no mode.
    """
    return getattr(path, "mode", None) == "r"


def require_writable(path: object, verb: str) -> None:
    """Raise `ReadOnlyError` if `path` is read-only; `verb` says what failed."""
    if is_read_only(path):
        raise ReadOnlyError(
            f"cannot {verb} {str(path)!r}: the path is read-only; get a "
            "writable path with path.with_mode('w'), or build it with "
            "mode='w'"
        )


def _inherited(owner: type, name: str) -> Callable | None:
    """Return the member `name` that `owner` inherits, or `None`."""
    for base in owner.__mro__[1:]:
        if name in base.__dict__:
            return base.__dict__[name]
    return None


def _guard(owner: type, name: str, real: Callable) -> Callable:
    """Return the guarded override of member `name` on class `owner`."""
    verb, own, target = _MEMBERS[name]
    signature = inspect.signature(real)

    def argument(args: tuple, kwargs: dict, parameter: str) -> object:
        try:
            bound = signature.bind(None, *args, **kwargs)
        except TypeError:
            # A bad call: the member raises its own error.
            return None
        bound.apply_defaults()
        return bound.arguments.get(parameter)

    def check(path: object, args: tuple, kwargs: dict) -> None:
        if name == "open":
            mode = argument(args, kwargs, "mode")
            if not (isinstance(mode, str) and _WRITING & set(mode)):
                return
        destination = None
        if own:
            require_writable(path, verb)
        if target is not None:
            destination = argument(args, kwargs, target)
            require_writable(destination, verb)
        if own:
            refuse_raw_write(path, name, verb)
        if destination is not None:
            for written in _destinations(name, path, destination):
                refuse_raw_write(written, name, _ONTO[name])

    if inspect.iscoroutinefunction(real):
        async def member(self: Any, *args, **kwargs) -> Any:  # noqa: ANN401
            check(self, args, kwargs)
            return await getattr(super(owner, self), name)(*args, **kwargs)
    else:
        def member(self: Any, *args, **kwargs) -> Any:  # noqa: ANN401
            check(self, args, kwargs)
            return getattr(super(owner, self), name)(*args, **kwargs)

    return functools.wraps(real)(member)


def _destinations(name: str, path: Any, destination: object) -> list:  # noqa: ANN401
    """Return the paths that member `name` of `path` writes at `destination`.

    Each is a path of the family of `path`, so that its location can be
    told whatever `destination` is (a string, another path). One that
    cannot be built is left out: the member raises its own error for it.
    """
    try:
        family = getattr(type(path), "_root", type(path))
        written = in_family(destination, family)
        if name in _INTO:
            return [written / path.name]
        if name == "download_to" and written.is_local() and os.path.isdir(
            os.fspath(written)
        ):
            # Into a directory (which is not changed), under the path's name.
            return [written / path.name]
        return [written]
    except Exception:  # noqa: BLE001
        return []


def guard_members(cls: type) -> type:
    """Guard the members of `cls` that change the filesystem (a decorator).

    Each refuses, with `ReadOnlyError`, to write to or remove a read-only
    path, and to write onto a read-only destination; and, with
    `RuntimeError`, a write that an open transaction would lose (see
    `transaction.refuse_raw_write`). A member the base class does not have
    is left out.
    """
    for name in _MEMBERS:
        real = _inherited(cls, name)
        if real is not None and name not in cls.__dict__:
            setattr(cls, name, _guard(cls, name, real))
    return cls
