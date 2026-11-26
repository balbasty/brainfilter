"""Read-only dataset tree: child access, file contents and sidecar metadata.

These mixins give `BidsPath` and its file classes a dict-like, read-only
surface:

- a directory maps child names to paths: `dataset["sub-01"]["anat"]`;
- a JSON file maps its keys to values: `sidecar["RepetitionTime"]`, and
  `sidecar.read()` returns the whole object as a `dict`;
- a TSV file reads as rows: `table.read()` is a list of `dict`, one per row,
  and `table.read_dataframe()` a `pandas.DataFrame` (pandas is optional);
- any file's effective metadata, `data.metadata`, is a
  `collections.ChainMap` of the JSON sidecars that apply to it, nearest
  first, up to the dataset root.

The `Async*` mixins give `AsyncBidsPath` the same surface as coroutines.
Python has no awaitable indexing or `in`, so a directory's `ds[name]` is
`await ds.child(name)` and `name in ds` is `await ds.has(name)`; every
other method keeps its name and is awaited (`await ds.keys()`,
`await sidecar.read()`, `await data.read_metadata()`), and iteration is
`async for`. Both surfaces share the parsing and the sidecar search below;
only the reads differ.

Writing is not supported here: it will come with transactions.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
from collections import ChainMap
from collections.abc import (
    AsyncIterator,
    Generator,
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    ValuesView,
)
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar

from brainfilter._names import applies_to, parse_name

if TYPE_CHECKING:
    from pandas import DataFrame
    from typing_extensions import Self

__all__ = ["DATASET_DESCRIPTION", "AsyncJSONContentMixin",
           "AsyncTSVContentMixin", "AsyncTreeMixin", "JSONContentMixin",
           "TSVContentMixin", "TreeMixin"]

DATASET_DESCRIPTION = "dataset_description.json"

# Missing-value marker of BIDS tables.
_NA = "n/a"

# A path of either family (sync or async).
_P = TypeVar("_P")


def _read_only(obj: object) -> TypeError:
    return TypeError(
        f"{type(obj).__name__} is read-only: writing through the dataset "
        "tree is not supported yet (it will come with transactions)"
    )


# -- shared, I/O-free logic ------------------------------------------------------

def _is_child_name(name: object) -> bool:
    """Whether `name` can name one child (one level, non-empty)."""
    return isinstance(name, str) and bool(name) and "/" not in name


def _by_name(children: Iterable[Any]) -> list[Any]:
    return sorted(children, key=lambda child: child.name)


def _parse_json(text: str) -> object:
    return json.loads(text)


def _json_object(path: object, content: object) -> dict:
    if not isinstance(content, dict):
        raise TypeError(f"{path!s} does not hold a JSON object")
    return content


def _parse_tsv(text: str) -> list[dict[str, str | None]]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return [
        {k: (None if v == _NA else v) for k, v in row.items()}
        for row in reader
    ]


def _tsv_dataframe(text: str, kwargs: dict) -> DataFrame:
    try:
        import pandas
    except ImportError:
        raise ImportError(
            "read_dataframe needs pandas; install it, or use read() "
            "for a list of rows"
        ) from None
    options = {"sep": "\t", "na_values": [_NA], "keep_default_na": False}
    options.update(kwargs)
    return pandas.read_csv(io.StringIO(text), **options)


def _search_sidecars(
    path: _P, root: object, root_path: _P | None
) -> Generator[_P, set[str], list[_P]]:
    """Find the sidecars of `path`, nearest first (see `TreeMixin.sidecars`).

    The search lists one directory at a time and does no I/O itself: it
    yields each directory to list and is sent back the set of its child
    names, so one search serves the sync and the async surfaces.
    """
    if path.suffix is None:
        return []
    # Each directory is listed once; `levels` runs from the file's own
    # directory up to the root.
    levels: list[tuple[_P, set[str]]] = []
    for directory in path.parents:
        names = yield directory
        levels.append((directory, names))
        at_root = (
            directory == root_path if root_path is not None
            else DATASET_DESCRIPTION in names
        )
        if at_root:
            break
    else:
        if root_path is not None:
            raise ValueError(f"{root!s} is not an ancestor of {path!s}")
        raise ValueError(
            f"no dataset root above {path!s}: no ancestor holds a "
            f"{DATASET_DESCRIPTION}; pass root= explicitly"
        )

    # Paths relative to the root, as `applies_to` expects.
    dirs = [d.name for d, _ in levels[:-1]]
    rel_dirs = ["/".join(reversed(dirs[i:])) for i in range(len(dirs))]
    rel_dirs.append("")
    data_rel = f"{rel_dirs[0]}/{path.name}".lstrip("/")

    found = []
    for (directory, names), rel_dir in zip(levels, rel_dirs):
        level = []
        for name in names:
            parsed = parse_name(name)
            if parsed.extension != ".json" or parsed.suffix is None:
                continue
            if directory == path.parent and name == path.name:
                continue
            meta_rel = f"{rel_dir}/{name}".lstrip("/")
            if applies_to(meta_rel, data_rel, companions=False):
                level.append((-len(parsed.entities), name))
        found.extend(directory / name for _, name in sorted(level))
    return found


def _as_root(path: _P, root: object) -> _P | None:
    """`root` as a path of `path`'s family, or `None`."""
    return None if root is None else path._root(root)


# -- sync surface ----------------------------------------------------------------

class TreeMixin:
    """A directory as a read-only mapping `child name -> path`.

    Indexing, `in`, `keys()`, `values()`, `items()` and iteration list the
    directory each time they are called; nothing is cached.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        name: str
        parent: Self
        parents: tuple[Self, ...]
        suffix: str | None

        def iterdir(self) -> Iterator[Self]: ...  # noqa: D102
        def exists(self) -> bool: ...  # noqa: D102
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102
        def __truediv__(self, other: object) -> Self: ...  # noqa: D105

    # -- mapping of children -------------------------------------------------
    def __getitem__(self, name: str) -> Self:
        """Return the child called `name`; `KeyError` if there is none."""
        if not _is_child_name(name):
            raise KeyError(name)
        child = self / name
        if not child.exists():
            raise KeyError(name)
        return child

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.keys()

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def keys(self) -> list[str]:
        """Return the names of the children, sorted."""
        return [child.name for child in self.values()]

    def values(self) -> list[Self]:
        """Return the children, sorted by name."""
        return _by_name(self.iterdir())

    def items(self) -> list[tuple[str, Self]]:
        """Return `(name, child)` pairs, sorted by name."""
        return [(child.name, child) for child in self.values()]

    def get(self, name: str, default: object = None) -> object:
        """Return the child called `name`, or `default`."""
        try:
            return self[name]
        except KeyError:
            return default

    def __setitem__(self, name: str, value: object) -> None:
        raise _read_only(self)

    def __delitem__(self, name: str) -> None:
        raise _read_only(self)

    # -- sidecar inheritance -------------------------------------------------
    @property
    def metadata(self) -> ChainMap:
        """The effective metadata of this file; see `read_metadata`."""
        return self.read_metadata()

    def sidecars(self, root: object = None) -> list[Self]:
        """Return the JSON sidecars that apply to this file, nearest first.

        A sidecar applies when it is a `.json` file with the same BIDS
        suffix, its entities are a subset of this file's (same labels), and
        it is in this file's directory or an ancestor up to the dataset
        root (BIDS inheritance). Within one directory, a sidecar with more
        entities comes first.

        Parameters
        ----------
        root
            The dataset root. By default, the nearest ancestor that holds a
            `dataset_description.json`.

        Raises
        ------
        ValueError
            If no dataset root is found, or `root` is not an ancestor.
        """
        search = _search_sidecars(self, root, _as_root(self, root))
        try:
            directory = next(search)
            while True:
                directory = search.send(self._list_names(directory))
        except StopIteration as done:
            return done.value

    def read_metadata(self, root: object = None) -> ChainMap:
        """Read the effective metadata of this file, as a `ChainMap`.

        Its maps are the contents of `sidecars(root)`, nearest first, so a
        key is looked up in the nearest sidecar that has it. The maps are
        read when this is called; they are not kept in sync with the files.
        """
        return ChainMap(*(sidecar.read() for sidecar in self.sidecars(root)))

    @staticmethod
    def _list_names(directory: TreeMixin) -> set[str]:
        try:
            return {child.name for child in directory.iterdir()}
        except OSError:
            return set()


class JSONContentMixin:
    """A JSON file as a read-only mapping of its top-level keys.

    Every lookup reads the file again; call `read()` once to work on the
    content as a plain `dict`.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    def read(self) -> object:
        """Read and parse the file (a `dict` for a BIDS JSON file)."""
        return _parse_json(self.read_text(encoding="utf-8"))

    def _mapping(self) -> dict:
        return _json_object(self, self.read())

    def __getitem__(self, key: str) -> object:
        return self._mapping()[key]

    def __contains__(self, key: object) -> bool:
        return key in self._mapping()

    def __iter__(self) -> Iterator[str]:
        return iter(self._mapping())

    def keys(self) -> KeysView[str]:
        """Return the keys of the JSON object."""
        return self._mapping().keys()

    def values(self) -> ValuesView[object]:
        """Return the values of the JSON object."""
        return self._mapping().values()

    def items(self) -> ItemsView[str, object]:
        """Return the `(key, value)` pairs of the JSON object."""
        return self._mapping().items()

    def get(self, key: str, default: object = None) -> object:
        """Return the value of `key`, or `default`."""
        return self._mapping().get(key, default)


class TSVContentMixin:
    """A TSV table, read as rows."""

    __slots__ = ()

    if TYPE_CHECKING:
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    def read(self) -> list[dict[str, str | None]]:
        """Read the table as a list of rows, `column -> value`.

        Values are strings, and the BIDS missing value `n/a` reads as
        `None`.
        """
        return _parse_tsv(self.read_text(encoding="utf-8"))

    def read_dataframe(self, **kwargs: object) -> DataFrame:
        """Read the table as a `pandas.DataFrame` (needs pandas).

        `n/a` reads as a missing value. Keywords go to `pandas.read_csv`.
        """
        return _tsv_dataframe(self.read_text(encoding="utf-8"), kwargs)

    def __getitem__(self, key: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: use read() for its rows"
        )

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        return iter(self.read())


# -- async surface ---------------------------------------------------------------

def _not_awaitable(obj: object, operation: str, instead: str) -> TypeError:
    return TypeError(
        f"{type(obj).__name__} is asynchronous: {operation} cannot be "
        f"awaited; use {instead}"
    )


class AsyncTreeMixin:
    """A directory as a read-only, asynchronous mapping `child name -> path`.

    The coroutine counterpart of `TreeMixin`: `await ds.child(name)` for
    `ds[name]`, `await ds.has(name)` for `name in ds`, `await ds.keys()`,
    `values()`, `items()`, `get()`, and `async for name in ds`. Each call
    lists the directory again; nothing is cached.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        name: str
        parent: Self
        parents: tuple[Self, ...]
        suffix: str | None

        def iterdir(self) -> AsyncIterator[Self]: ...  # noqa: D102
        async def exists(self) -> bool: ...  # noqa: D102
        async def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102
        def __truediv__(self, other: object) -> Self: ...  # noqa: D105

    # -- mapping of children -------------------------------------------------
    async def child(self, name: str) -> Self:
        """Return the child called `name`; `KeyError` if there is none."""
        if not _is_child_name(name):
            raise KeyError(name)
        child = self / name
        if not await child.exists():
            raise KeyError(name)
        return child

    async def has(self, name: object) -> bool:
        """Whether this directory has a child called `name`."""
        return isinstance(name, str) and name in await self.keys()

    async def __aiter__(self) -> AsyncIterator[str]:
        for name in await self.keys():
            yield name

    async def keys(self) -> list[str]:
        """Return the names of the children, sorted."""
        return [child.name for child in await self.values()]

    async def values(self) -> list[Self]:
        """Return the children, sorted by name."""
        return _by_name([child async for child in self.iterdir()])

    async def items(self) -> list[tuple[str, Self]]:
        """Return `(name, child)` pairs, sorted by name."""
        return [(child.name, child) for child in await self.values()]

    async def get(self, name: str, default: object = None) -> object:
        """Return the child called `name`, or `default`."""
        try:
            return await self.child(name)
        except KeyError:
            return default

    def __getitem__(self, name: str) -> NoReturn:
        raise _not_awaitable(self, "indexing", "await path.child(name)")

    def __contains__(self, name: object) -> NoReturn:
        raise _not_awaitable(self, "'in'", "await path.has(name)")

    def __setitem__(self, name: str, value: object) -> None:
        raise _read_only(self)

    def __delitem__(self, name: str) -> None:
        raise _read_only(self)

    # -- sidecar inheritance -------------------------------------------------
    async def sidecars(self, root: object = None) -> list[Self]:
        """Return the JSON sidecars that apply to this file, nearest first.

        The coroutine counterpart of `BidsPath.sidecars`, with the same
        rules and errors.
        """
        search = _search_sidecars(self, root, _as_root(self, root))
        try:
            directory = next(search)
            while True:
                directory = search.send(await self._list_names(directory))
        except StopIteration as done:
            return done.value

    async def read_metadata(self, root: object = None) -> ChainMap:
        """Read the effective metadata of this file, as a `ChainMap`.

        Its maps are the contents of `await sidecars(root)`, nearest first;
        the sidecars are read concurrently.
        """
        sidecars = await self.sidecars(root)
        return ChainMap(*await asyncio.gather(*(s.read() for s in sidecars)))

    @staticmethod
    async def _list_names(directory: AsyncTreeMixin) -> set[str]:
        try:
            return {child.name async for child in directory.iterdir()}
        except OSError:
            return set()


class AsyncJSONContentMixin:
    """A JSON file as a read-only, asynchronous mapping of its top-level keys.

    The coroutine counterpart of `JSONContentMixin`: `await sidecar.read()`,
    `get()`, `has()`, `keys()`, `values()`, `items()`, and
    `async for key in sidecar`. Every call reads the file again.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        async def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    async def read(self) -> object:
        """Read and parse the file (a `dict` for a BIDS JSON file)."""
        return _parse_json(await self.read_text(encoding="utf-8"))

    async def _mapping(self) -> dict:
        return _json_object(self, await self.read())

    async def has(self, key: object) -> bool:
        """Whether the JSON object has `key`."""
        return key in await self._mapping()

    async def __aiter__(self) -> AsyncIterator[str]:
        for key in await self._mapping():
            yield key

    async def keys(self) -> KeysView[str]:
        """Return the keys of the JSON object."""
        return (await self._mapping()).keys()

    async def values(self) -> ValuesView[object]:
        """Return the values of the JSON object."""
        return (await self._mapping()).values()

    async def items(self) -> ItemsView[str, object]:
        """Return the `(key, value)` pairs of the JSON object."""
        return (await self._mapping()).items()

    async def get(self, key: str, default: object = None) -> object:
        """Return the value of `key`, or `default`."""
        return (await self._mapping()).get(key, default)

    def __getitem__(self, key: str) -> NoReturn:
        raise _not_awaitable(
            self, "indexing", "await path.get(key) or await path.read()"
        )

    def __contains__(self, key: object) -> NoReturn:
        raise _not_awaitable(self, "'in'", "await path.has(key)")


class AsyncTSVContentMixin:
    """A TSV table, read as rows by coroutines."""

    __slots__ = ()

    if TYPE_CHECKING:
        async def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    async def read(self) -> list[dict[str, str | None]]:
        """Read the table as a list of rows, `column -> value`.

        Values are strings, and the BIDS missing value `n/a` reads as
        `None`.
        """
        return _parse_tsv(await self.read_text(encoding="utf-8"))

    async def read_dataframe(self, **kwargs: object) -> DataFrame:
        """Read the table as a `pandas.DataFrame` (needs pandas).

        `n/a` reads as a missing value. Keywords go to `pandas.read_csv`.
        """
        return _tsv_dataframe(await self.read_text(encoding="utf-8"), kwargs)

    def __getitem__(self, key: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: use await read() for its rows"
        )

    async def __aiter__(self) -> AsyncIterator[dict[str, str | None]]:
        for row in await self.read():
            yield row
