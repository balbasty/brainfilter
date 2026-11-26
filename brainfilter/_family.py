"""Rebuilding a path in another family (sync `BidsPath`, async `AsyncBidsPath`)."""
from __future__ import annotations

from typing import Any

from bagof.paths import AsyncPath, Path, PurePath, UnsupportedPathOperation

__all__ = ["in_family"]


def in_family(path: object, cls: type) -> Any:  # noqa: ANN401
    """`path` as a path of `cls` (`BidsPath` or `AsyncBidsPath`), same mode.

    A path of the same front-end (`bagof.paths.Path` for `BidsPath`,
    `bagof.paths.AsyncPath` for `AsyncBidsPath`) and any driver object or
    string are wrapped as they are. A path of another front-end is rebuilt
    from its string and its storage options, so the store is reached by the
    driver `cls` picks for it: an async driver cannot be wrapped by a
    synchronous path, and a synchronous one would be run in a thread. A
    BIDS path's mode is kept.
    """
    if isinstance(path, cls):
        return path
    mode = getattr(path, "mode", None)
    kwargs = {} if mode is None else {"mode": mode}
    same = Path if issubclass(cls, Path) else AsyncPath
    if isinstance(path, same) or not isinstance(path, (Path, AsyncPath, PurePath)):
        return cls(path, **kwargs)
    options: dict = {}
    if not path.is_local():
        try:
            options = dict(path.storage_options or {})
        except UnsupportedPathOperation:
            options = {}  # a driver with no storage options (cloudpathlib)
    if options:
        kwargs["storage_options"] = options
    return cls(str(path), **kwargs)
