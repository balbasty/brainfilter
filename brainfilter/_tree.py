"""The dataset tree: children, JSON and TSV contents, sidecars and writes.

These mixins give `BidsPath` and its file classes a dict-like surface:

- a directory maps child names to paths: `dataset["sub-01"]["anat"]`;
- a JSON file maps its keys to values: `sidecar["RepetitionTime"]`, and
  `sidecar.as_dict()` loads it as a plain `dict`;
- a TSV file maps its column names to typed columns: `table["age"]`, and
  `table.as_dict()`, `table.as_list()` (rows), `table.rows()` (a stream of
  rows) and `table.as_dataframe()` (pandas) load it;
- a file's `sidecars` are the JSON sidecars that apply to it, nearest
  first, up to the dataset root (or, with no dataset root above it, those
  in its own directory), and its `sidecar` is their merged content.

On a writable path, `sidecar[key] = value`, `del sidecar[key]`,
`sidecar.update()`, `table[column] = values`, `del table[column]`, any
file's `write()` and a write to its merged `sidecar` each write the file at
once, in one atomic replace. Inside `with path:` (or
`with path.transaction():`) they are kept until the block ends, and every
read sees them; see `brainfilter.Transaction`. A value a read returns is a
copy: changing it in place is not saved.

The `Async*` mixins give `AsyncBidsPath` the same surface as coroutines.
Python has no awaitable indexing or `in`, so a directory's `ds[name]` is
`await ds.child(name)`, a file's `f[key]` is `await f.get(key)`,
`f[key] = value` is `await f.set(key, value)`, `del f[key]` is
`await f.delete(key)` and `key in f` is `await f.has(key)`; every other
method keeps its name and is awaited (`await ds.keys()`,
`await sidecar.as_dict()`, `await data.sidecars`), and iteration is
`async for`. Both surfaces share the parsing and the sidecar search below;
only the reads and writes differ.
"""
from __future__ import annotations

import asyncio
import copy
from collections import ChainMap
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    ValuesView,
)
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn, TypeVar

from brainfilter import _content
from brainfilter import transaction as _transaction
from brainfilter._content import Table, json_object
from brainfilter._mode import require_writable
from brainfilter._names import applies_to, parse_name
from brainfilter.transaction import (
    AsyncTransaction,
    Transaction,
    _Buffer,
    active_for,
    entered,
    pending_names,
)

if TYPE_CHECKING:
    from types import TracebackType

    from pandas import DataFrame
    from typing_extensions import Self

    from brainfilter.transaction import _Entry

__all__ = ["DATASET_DESCRIPTION", "AsyncJSONContentMixin",
           "AsyncSidecarChain", "AsyncTSVContentMixin", "AsyncTreeMixin",
           "JSONContentMixin", "SidecarChain", "TSVContentMixin", "Table",
           "TreeMixin"]

DATASET_DESCRIPTION = "dataset_description.json"

# Files are read as UTF-8, skipping a byte-order mark; written without one.
_ENCODING = "utf-8-sig"

# What a write is said to do in a read-only error.
_WRITE = "write to"

# A path of either family (sync or async).
_P = TypeVar("_P")


def _no_delete(obj: object) -> TypeError:
    return TypeError(
        f"{type(obj).__name__} cannot delete a child: the dataset tree edits "
        "the content of JSON and TSV files, it does not delete files; use "
        "the path's unlink() to remove one"
    )


def _not_content(name: str) -> TypeError:
    return TypeError(
        f"cannot write {name!r}: only JSON and TSV files can be written "
        "through the dataset tree"
    )


def _not_awaitable(obj: object, operation: str, instead: str) -> TypeError:
    return TypeError(
        f"{type(obj).__name__} is asynchronous: {operation} cannot be "
        f"awaited; use {instead}"
    )


# -- shared, I/O-free logic ------------------------------------------------------

def _is_child_name(name: object) -> bool:
    """Whether `name` can name one child (one level down, not `.` or `..`)."""
    return (
        isinstance(name, str) and name not in ("", ".", "..")
        and "/" not in name
    )


def _no_sidecar_error(path: Any) -> TypeError:  # noqa: ANN401
    if path.suffix is None:
        why = "it has no BIDS suffix, so no sidecar can apply to it"
        how = "give it a BIDS name (with a suffix) first"
    else:
        name = path.with_extension(".json").name
        if name == path.name:
            name = f"{path.suffix}.json"
        why = "no JSON sidecar applies to it"
        how = f"create one first, e.g. `(path.parent / {name!r}).write({{...}})`"
    return TypeError(
        f"cannot write the sidecar of {str(path)!r}: {why}, so there is no "
        f"file to write it to; {how}"
    )


class _Deferred:
    """An awaitable that starts its coroutine only when it is awaited.

    The async `sidecars` and `sidecar` properties return one, so reading
    the property without awaiting it (`hasattr`, `dir`, a debugger) leaves
    no coroutine behind that was never awaited.
    """

    __slots__ = ("_start",)

    def __init__(self, start: Callable[[], Awaitable]) -> None:
        self._start = start

    def __await__(self) -> Generator:
        return self._start().__await__()


def _detached(content: object) -> object:
    """Return a copy of a file's content that shares nothing with it."""
    if isinstance(content, Table):
        return Table(
            [copy.deepcopy(row) for row in content], columns=content.columns
        )
    return copy.deepcopy(content)


def _columns(table: Table) -> dict[str, list]:
    return {
        column: [row.get(column) for row in table] for column in table.columns
    }


def _rows(table: Table) -> list[dict[str, object]]:
    columns = table.columns
    return [{column: row.get(column) for column in columns} for row in table]


def _column(table: Table, name: object) -> list:
    if name not in table.columns:
        raise KeyError(name)
    return [row.get(name) for row in table]


def _new_table(rows: Iterable[Mapping[str, object]], columns: object,
               origin: object) -> Table:
    """Return `rows` as the table a file holds in place of `origin`.

    `origin` is the table the file held so far: rows taken from it keep the
    text of their unchanged cells, and its `Delimiter`s join their lists.
    """
    origin = origin if isinstance(origin, Table) else None
    table = Table(rows, columns=columns, _origin=origin)
    for row in table:
        for column, value in row.items():
            if isinstance(value, list):
                # A list is the one cell value that can be changed in place.
                row[column] = copy.deepcopy(value)
    return table


def _with_pending(
    directory: object, listed: list[Any], pending: set[str]
) -> list[Any]:
    """Return the `listed` children and those a transaction holds, sorted."""
    names = {child.name for child in listed}
    listed.extend(directory / name for name in sorted(pending - names))
    return sorted(listed, key=lambda child: child.name)


def _search_sidecars(path: _P) -> Generator[_P, set[str], tuple[_P, ...]]:
    """Find the sidecars of `path`, nearest first (see `TreeMixin.sidecars`).

    The search lists one directory at a time and does no I/O itself: it
    yields each directory to list and is sent back the set of its child
    names, so one search serves the sync and the async surfaces.
    """
    if path.suffix is None:
        return ()
    # Each directory is listed once, in one walk up; `levels` runs from the
    # file's own directory up to the root.
    levels: list[tuple[_P, set[str]]] = []
    for directory in path.parents:
        names = yield directory
        levels.append((directory, names))
        if DATASET_DESCRIPTION in names:
            break
    else:
        # No dataset root: only the file's own directory counts. Its
        # listing is the first one, so this costs no more I/O.
        levels = levels[:1]

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
    return tuple(found)


# -- the merged sidecar ----------------------------------------------------------

class SidecarChain(ChainMap):
    """The merged content of the JSON sidecars that apply to a file.

    A `collections.ChainMap` of their contents, nearest first, so a key is
    looked up in the nearest sidecar that has it. It is loaded when
    `path.sidecar` is read, and `as_dict()` flattens it into a plain
    `dict`.

    A write goes to the nearest sidecar, `sidecars[0]`:
    `chain[key] = value`, `del chain[key]`, `update()`, `pop()`,
    `popitem()`, `setdefault()` and `clear()`. On a writable path each one
    writes that file at once, in one atomic replace; inside `with path:` it
    is kept until the block ends. The chain shows the change too. Changing
    a value in place (a nested `dict`) changes this chain only, and so does
    a write to one of its `maps`. With no sidecar, the chain is empty and a
    write raises `TypeError`: there is no file to write to.

    Attributes
    ----------
    sidecars : tuple
        The sidecar files, nearest first: the file each of `maps` was
        loaded from.
    """

    def __init__(
        self,
        *maps: Mapping,
        sidecars: Iterable[Any] = (),
        owner: object = None,
    ) -> None:
        super().__init__(*maps)
        self.sidecars = tuple(sidecars)
        self._owner = owner

    def as_dict(self) -> dict:
        """Return the merged content as a plain `dict`: the nearest wins."""
        return copy.deepcopy(dict(self))

    def _nearest(self) -> Any:  # noqa: ANN401
        if not self.sidecars:
            raise _no_sidecar_error(self._owner)
        return self.sidecars[0]

    def __setitem__(self, key: str, value: object) -> None:
        self._nearest()[key] = value
        self.maps[0][key] = copy.deepcopy(value)

    def __delitem__(self, key: str) -> None:
        del self._nearest()[key]
        self.maps[0].pop(key, None)

    def update(self, other: Mapping | Iterable = (), /, **kwargs) -> None:
        """Set several keys of the nearest sidecar, in one write."""
        new = dict(other, **kwargs)
        self._nearest().update(new)
        self.maps[0].update(copy.deepcopy(new))

    def __ior__(self, other: Mapping | Iterable) -> Self:
        self.update(other)
        return self

    def pop(self, key: str, *default: object) -> object:
        """Remove `key` from the nearest sidecar and return its value."""
        if key not in self.maps[0]:
            if default:
                return default[0]
            raise KeyError(f"Key not found in the first mapping: {key!r}")
        value = self.maps[0][key]
        del self[key]
        return value

    def popitem(self) -> tuple[str, object]:
        """Remove the last key of the nearest sidecar; return it, and its value."""
        if not self.maps[0]:
            raise KeyError("No keys found in the first mapping.")
        key = next(reversed(self.maps[0]))
        value = self.maps[0][key]
        del self[key]
        return key, value

    def clear(self) -> None:
        """Remove every key of the nearest sidecar."""
        self._nearest().write({})
        self.maps[0].clear()

    def copy(self) -> ChainMap:
        """Return a plain `ChainMap` of these maps: writes to it go nowhere."""
        return ChainMap(self.maps[0].copy(), *self.maps[1:])

    __copy__ = copy

    def new_child(self, m: Mapping | None = None, **kwargs) -> ChainMap:
        """Return a plain `ChainMap` of a new map and these ones."""
        if m is None:
            m = kwargs
        elif kwargs:
            m.update(kwargs)
        return ChainMap(m, *self.maps)

    @property
    def parents(self) -> Self:
        """The chain of every sidecar but the nearest; writes go to the next."""
        return type(self)(
            *self.maps[1:], sidecars=self.sidecars[1:], owner=self._owner
        )


class AsyncSidecarChain(SidecarChain):
    """The merged content of the sidecars of an `AsyncBidsPath`.

    The same `ChainMap` as `SidecarChain`, already loaded, so it is read
    without `await`: `chain["RepetitionTime"]`, `chain.as_dict()`. A write
    is a coroutine: `await chain.set(key, value)`,
    `await chain.delete(key)` and `await chain.update(...)`.
    """

    async def set(self, key: str, value: object) -> None:
        """Set a key of the nearest sidecar."""
        await self._nearest().set(key, value)
        self.maps[0][key] = copy.deepcopy(value)

    async def delete(self, key: str) -> None:
        """Delete a key of the nearest sidecar; `KeyError` if it is missing."""
        await self._nearest().delete(key)
        self.maps[0].pop(key, None)

    async def update(  # type: ignore[override]
        self, other: Mapping | Iterable = (), /, **kwargs
    ) -> None:
        """Set several keys of the nearest sidecar, in one write."""
        new = dict(other, **kwargs)
        await self._nearest().update(new)
        self.maps[0].update(copy.deepcopy(new))

    def __setitem__(self, key: str, value: object) -> NoReturn:
        raise _not_awaitable(self, "assignment", "await chain.set(key, value)")

    def __delitem__(self, key: str) -> NoReturn:
        raise _not_awaitable(self, "'del'", "await chain.delete(key)")

    def _refuse(self, *args: object, **kwargs: object) -> NoReturn:
        raise _not_awaitable(
            self, "this write", "await chain.set(), delete() or update()"
        )

    pop = popitem = clear = setdefault = __ior__ = _refuse  # type: ignore


# -- sync surface ----------------------------------------------------------------

class TreeMixin:
    """A directory as a mapping `child name -> path`; a file's sidecars.

    Indexing, `in`, `keys()`, `values()`, `items()` and iteration list the
    directory each time they are called; nothing is cached. Inside a
    transaction, the files it holds are listed too, before they are written,
    and `dataset[name] = content` creates or replaces a JSON or TSV file.
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

    # -- transactions --------------------------------------------------------
    def transaction(self) -> Transaction:
        """Keep the writes to the JSON and TSV files below this path.

        ```python
        with dataset.transaction() as tx:
            dataset["T1w.json"]["RepetitionTime"] = 2.3
        tx.written                   # what the commit wrote
        ```

        The same block as `with dataset:`, which gives the path rather
        than the `Transaction`. On a clean exit each changed file is
        written, in one step; on an exception nothing is written. See
        `brainfilter.Transaction`.

        Raises
        ------
        brainfilter.ReadOnlyError
            If this path is read-only.
        RuntimeError
            When the block is entered, if a transaction on this path, an
            ancestor or a descendant is already open.
        """
        require_writable(self, "open a transaction on")
        return Transaction(self)

    def __enter__(self) -> Self:
        """Open a transaction on this path: `with dataset:`.

        Every write to the JSON and TSV files below it, through any path,
        is kept until the block ends; see `transaction`.
        """
        self.transaction().__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        entered(self).__exit__(exc_type, exc, tb)

    # -- mapping of children -------------------------------------------------
    def __getitem__(self, name: str) -> Self:
        """Return the child called `name`; `KeyError` if there is none.

        A child is one level down: `.`, `..` and a name with `/` are not.
        """
        if not _is_child_name(name):
            raise KeyError(name)
        child = self / name
        if name not in pending_names(self) and not child.exists():
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
        pending = pending_names(self)
        try:
            listed = list(self.iterdir())
        except OSError:
            # A directory that only the transaction holds so far.
            if not pending:
                raise
            listed = []
        return _with_pending(self, listed, pending)

    def items(self) -> list[tuple[str, Self]]:
        """Return `(name, child)` pairs, sorted by name."""
        return [(child.name, child) for child in self.values()]

    def get(self, name: str, default: object = None) -> object:
        """Return the child called `name`, or `default`."""
        try:
            return self[name]
        except KeyError:
            return default

    def __setitem__(self, name: str, content: object) -> None:
        """Create or replace the JSON or TSV file `name` (see its `write`)."""
        if not _is_child_name(name):
            raise KeyError(name)
        child = self / name
        if not isinstance(child, _ContentMixin):
            raise _not_content(name)
        child.write(content)

    def __delitem__(self, name: str) -> NoReturn:
        raise _no_delete(self)

    # -- sidecar inheritance -------------------------------------------------
    @property
    def sidecars(self) -> tuple[Self, ...]:
        """The JSON sidecars that apply to this file, nearest first.

        A sidecar applies when it is a `.json` file with the same BIDS
        suffix, its entities are a subset of this file's (same labels), and
        it is in this file's directory or an ancestor up to the dataset
        root (BIDS inheritance): the nearest ancestor that holds a
        `dataset_description.json`. If no ancestor holds one, only the
        sidecars in this file's own directory count. Within one directory,
        a sidecar with more entities comes first. Inside a transaction, new
        sidecars count. The directories are listed each time this is read.
        """
        search = _search_sidecars(self)
        try:
            directory = next(search)
            while True:
                directory = search.send(self._list_names(directory))
        except StopIteration as done:
            return done.value

    @property
    def sidecar(self) -> SidecarChain:
        """The merged content of this file's `sidecars`, nearest first.

        A `collections.ChainMap` of their contents, read when this is read:
        `t1w.sidecar["RepetitionTime"]` is the value of the nearest sidecar
        that has the key, and `t1w.sidecar.as_dict()` a plain `dict` of
        every key. `t1w.sidecar[key] = value` writes the nearest sidecar;
        see `SidecarChain`.
        """
        sidecars = self.sidecars
        contents = [sidecar.as_dict() for sidecar in sidecars]
        return SidecarChain(*contents, sidecars=sidecars, owner=self)

    @staticmethod
    def _list_names(directory: TreeMixin) -> set[str]:
        pending = pending_names(directory)
        try:
            return {child.name for child in directory.iterdir()} | pending
        except OSError:
            return pending


class _ContentMixin:
    """What a JSON and a TSV file share: loading, and writes."""

    __slots__ = ()

    _kind: ClassVar[str]

    if TYPE_CHECKING:
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    def _descriptions(self) -> Mapping | None:
        """Return what types the content when parsed (a table's columns)."""
        return None

    def _load(self, buffer: _Buffer, create: bool) -> _Entry:
        """Read this file into `buffer`; held empty if missing and `create`."""
        # Read through the name the file is written with (no `..`).
        source = buffer.source(self)
        try:
            text = source.read_text(encoding=_ENCODING)
        except FileNotFoundError:
            if not create:
                raise
            text = None
        return buffer.load(source, self._kind, text, source._descriptions())

    def _tx_entry(
        self, create: bool, tx: Any = None  # noqa: ANN401
    ) -> _Entry | None:
        """Return the transaction's entry for this file (`None` outside one).

        The file is read into the transaction the first time it is used
        there; a file that does not exist is held empty if `create`, and is
        created only if its content is then set.
        """
        tx = tx or active_for(self)
        if tx is None:
            return None
        entry = tx._buffer.get(self)
        if entry is None:
            entry = self._load(tx._buffer, create)
        if not create and entry.absent():
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return entry

    def _loaded(self) -> object:
        """Return a copy of the content: what a read of the file sees."""
        entry = self._tx_entry(create=False)
        if entry is not None:
            return _detached(entry.content)
        text = self.read_text(encoding=_ENCODING)
        return _content.parse(self._kind, text, self._descriptions())

    def _change(self, change: Callable[[_Entry], None]) -> None:
        """Apply `change` to the content: written now, or kept by a transaction.

        Inside a transaction, a change that raises leaves the content as it
        was. Outside one, the file is read, changed and written in one
        atomic replace; a change that raises writes nothing.
        """
        require_writable(self, _WRITE)
        tx = active_for(self, write=True)
        if tx is not None:
            entry = self._tx_entry(create=True, tx=tx)
            restore = entry.snapshot()
            try:
                change(entry)
            except BaseException:
                restore()
                raise
            return
        buffer = _Buffer()
        change(self._load(buffer, create=True))
        for path, data in buffer.plan():
            _transaction.write_file(path, data)


class JSONContentMixin(_ContentMixin):
    """A JSON file as a mapping of its top-level keys.

    Every lookup reads the file again; `as_dict()` loads it once, as a
    plain `dict`. On a writable path, `sidecar[key] = value`,
    `del sidecar[key]`, `update()` and `write()` write the file at once, in
    one atomic replace (inside `with dataset:`, when the block ends).
    """

    __slots__ = ()
    _kind = _content.JSON

    def as_dict(self) -> dict:
        """Load the file as a plain `dict`.

        Inside a transaction it is a copy of the transaction's content.
        Changing it never changes the file: write it back with `write()`.
        """
        return json_object(self, self._loaded())

    def write(self, content: object) -> None:
        """Replace the whole content of the file.

        `content` is copied, and must be JSON-serializable. The file is
        created if it does not exist (and its directory with it).
        """
        new = _content.copy_json(content)
        self._change(lambda entry: entry.replace(new))

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def __setitem__(self, key: str, value: object) -> None:
        """Set a key (the file is created if missing)."""
        value = _content.copy_json(value)

        def change(entry: _Entry) -> None:
            json_object(self, entry.content)[key] = value

        self._change(change)

    def __delitem__(self, key: str) -> None:
        """Delete a key; `KeyError` if it is missing."""
        self._change(lambda entry: json_object(self, entry.content).pop(key))

    def update(self, *args: Mapping | Iterable, **kwargs: object) -> None:
        """Set several keys, as `dict.update`, in one write."""
        new = _content.copy_json(dict(*args, **kwargs))
        self._change(lambda entry: json_object(self, entry.content).update(new))

    def __contains__(self, key: object) -> bool:
        return key in self.as_dict()

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def keys(self) -> KeysView[str]:
        """Return the keys of the JSON object."""
        return self.as_dict().keys()

    def values(self) -> ValuesView[object]:
        """Return the values of the JSON object."""
        return self.as_dict().values()

    def items(self) -> ItemsView[str, object]:
        """Return the `(key, value)` pairs of the JSON object."""
        return self.as_dict().items()

    def get(self, key: str, default: object = None) -> object:
        """Return the value of `key`, or `default`."""
        return self.as_dict().get(key, default)


class TSVContentMixin(_ContentMixin):
    """A TSV table as a mapping of its column names to typed columns.

    `table["age"]` is the column as a `list` of typed values, and `keys()`
    and iteration give the column names. `as_dict()` loads every column,
    `as_list()` every row (a `dict` per row), `rows()` streams the rows and
    `as_dataframe()` loads a `pandas.DataFrame`.

    Values are typed, one type per column, and the BIDS missing value
    `n/a` is `None`. A column's type comes from the first of:

    1. its description in the table's JSON sidecar (`participants.json`
       for `participants.tsv`), if it has a `Format`: `number` reads as
       `float`, `integer` and `index` as `int`, `boolean` as `bool`
       (`true`/`false`), `date`, `datetime` and `time` as `datetime`
       objects, any other format as `str`;
    2. its standard BIDS definition (`age` is a number, `onset` too,
       `participant_id` a string, ...);
    3. its values: `int` if every value is an integer written as Python
       writes it, else `float` if every value is, else `str`. So `02`,
       `1e3`, `1.50` and a column mixing `3` and `1.5` stay text; booleans
       and dates are never guessed.

    A declared type (1 or 2) is used only if every value of the column
    parses as it (a date must be ISO 8601: `2024-01-31`,
    `2024-01-31T10:00:00[.ffffff][Z|+hh:mm]`, `10:00:00[.ffffff]`);
    otherwise the next one is tried. A column whose description has
    `Levels` keeps its values as text, the keys of `Levels`. A column whose
    description has a `Delimiter` reads as lists. With `raw=True`, every
    value is its exact text instead, `n/a` included.

    On a writable path, `table[column] = values` (one value per row) and
    `del table[column]` and `write()` write the file at once, in one atomic
    replace (inside `with dataset:`, when the block ends). The cells left
    unchanged keep their exact text.
    """

    __slots__ = ()
    _kind = _content.TSV

    if TYPE_CHECKING:
        sidecar: SidecarChain

    def _descriptions(self) -> Mapping | None:
        return self.sidecar

    def _table(self, raw: bool = False) -> Table:
        if not raw:
            return self._loaded()  # type: ignore[return-value]
        tx = active_for(self)
        entry = None if tx is None else tx._buffer.get(self)
        if entry is not None and not entry.absent():
            text = _content.dump_tsv(entry.content)
        else:
            text = self.read_text(encoding=_ENCODING)
        return _content.parse_tsv(text, raw=True)

    # -- loading -------------------------------------------------------------
    def as_dict(self, raw: bool = False) -> dict[str, list]:
        """Load the table as a `dict` of columns: `name -> list of values`.

        Inside a transaction it is a copy of the transaction's content:
        changing it never changes the file.
        """
        return _columns(self._table(raw))

    def columns(self, raw: bool = False) -> dict[str, list]:
        """Load the table as a `dict` of columns; the same as `as_dict()`."""
        return self.as_dict(raw)

    def as_list(self, raw: bool = False) -> list[dict[str, object]]:
        """Load the table as a `list` of rows, each a `dict` `column -> value`.

        Inside a transaction it is a copy of the transaction's content:
        changing it never changes the file. To change the rows, write them
        back with `write()`.
        """
        return _rows(self._table(raw))

    def rows(self, raw: bool = False) -> Iterator[dict[str, object]]:
        """Iterate over the rows, each a `dict` `column -> value`.

        The file is read when this is called.
        """
        return iter(self.as_list(raw))

    def as_dataframe(self, **kwargs: object) -> DataFrame:
        """Load the table as a `pandas.DataFrame` (needs pandas).

        `n/a` reads as a missing value, and the columns have the types
        `as_dict()` gives them, as pandas dtypes: `int64` (`Int64` with a
        missing value), `float64`, `bool` (`boolean`), `datetime64` for a
        `datetime` column with one time zone, and `object` for the rest
        (text, dates, times and the lists of a `Delimiter`). Keywords go to
        `pandas.read_csv`; with `dtype=` or `converters=`, pandas types the
        columns as asked instead. Inside a transaction, the frame is a copy
        of the transaction's table.
        """
        entry = self._tx_entry(create=False)
        if entry is not None:
            text = _content.dump_tsv(entry.content)
        else:
            text = self.read_text(encoding=_ENCODING)
        return _content.tsv_dataframe(text, kwargs, self._descriptions())

    # -- mapping of columns --------------------------------------------------
    def __getitem__(self, column: str) -> list:
        """Return the column called `column`, typed; `KeyError` if none."""
        return _column(self._table(), column)

    def get(self, column: str, default: object = None) -> object:
        """Return the column called `column`, typed, or `default`."""
        try:
            return self[column]
        except KeyError:
            return default

    def keys(self) -> list[str]:
        """Return the column names, in order (the header of the file)."""
        return self._table(raw=True).columns

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __contains__(self, column: object) -> bool:
        return column in self.keys()

    def values(self) -> list[list]:
        """Return the columns, typed, in order."""
        return list(self.as_dict().values())

    def items(self) -> list[tuple[str, list]]:
        """Return `(name, column)` pairs, in order."""
        return list(self.as_dict().items())

    # -- writes --------------------------------------------------------------
    def __setitem__(self, column: str, values: Iterable[object]) -> None:
        """Set a column, adding it last if it is new: one value per row.

        In a table with no column yet (a new file), the first column sets
        the number of rows.
        """
        values = copy.deepcopy(list(values))
        self._change(lambda entry: entry.content._set_column(column, values))

    def __delitem__(self, column: str) -> None:
        """Remove a column; `KeyError` if there is none."""
        self._change(lambda entry: entry.content.drop_column(column))

    def write(
        self,
        rows: Iterable[Mapping[str, object]],
        columns: Iterable[str] | None = None,
    ) -> None:
        """Replace the whole table with `rows`.

        `rows` are copied. `columns` sets the order of the columns (by
        default, a `Table`'s own, else the order the keys first appear in).
        The file is created if it does not exist. A cell that holds the
        value it was read with keeps its exact text. A list value is joined
        with its column's `Delimiter`, from the table's JSON sidecar.
        """
        rows = rows if isinstance(rows, Table) else list(rows)
        self._change(lambda entry: entry.replace(
            _new_table(rows, columns, entry.content)
        ))


# -- async surface ---------------------------------------------------------------

class AsyncTreeMixin:
    """A directory as an asynchronous mapping `child name -> path`.

    The coroutine counterpart of `TreeMixin`: `await ds.child(name)` for
    `ds[name]`, `await ds.has(name)` for `name in ds`, `await ds.keys()`,
    `values()`, `items()`, `get()`, and `async for name in ds`. Each call
    lists the directory again; nothing is cached. Inside a transaction
    (`async with ds:`) the files it holds are listed too.
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

    # -- transactions --------------------------------------------------------
    def transaction(self) -> AsyncTransaction:
        """Keep the writes to the JSON and TSV files below this path.

        The async counterpart of `BidsPath.transaction`, used with
        `async with`; `async with dataset:` is the same block, and gives
        the path.
        """
        require_writable(self, "open a transaction on")
        return AsyncTransaction(self)

    async def __aenter__(self) -> Self:
        await self.transaction().__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await entered(self).__aexit__(exc_type, exc, tb)

    # -- mapping of children -------------------------------------------------
    async def child(self, name: str) -> Self:
        """Return the child called `name`; `KeyError` if there is none.

        A child is one level down: `.`, `..` and a name with `/` are not.
        """
        if not _is_child_name(name):
            raise KeyError(name)
        child = self / name
        if name not in pending_names(self) and not await child.exists():
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
        pending = pending_names(self)
        try:
            listed = [child async for child in self.iterdir()]
        except OSError:
            # A directory that only the transaction holds so far.
            if not pending:
                raise
            listed = []
        return _with_pending(self, listed, pending)

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

    def __setitem__(self, name: str, value: object) -> NoReturn:
        raise _not_awaitable(
            self, "assignment", "await (path / name).write(content)"
        )

    def __delitem__(self, name: str) -> NoReturn:
        raise _no_delete(self)

    # -- sidecar inheritance -------------------------------------------------
    @property
    def sidecars(self) -> Awaitable[tuple[Self, ...]]:
        """The JSON sidecars that apply to this file, nearest first.

        Awaitable: `await data.sidecars`. The same rules as
        `BidsPath.sidecars`.
        """
        return _Deferred(self._find_sidecars)

    @property
    def sidecar(self) -> Awaitable[AsyncSidecarChain]:
        """The merged content of this file's `sidecars`, nearest first.

        Awaitable: `chain = await data.sidecar`. The chain is loaded, so it
        is read without `await` (`chain["RepetitionTime"]`,
        `chain.as_dict()`); a write to the nearest sidecar is awaited
        (`await chain.set(key, value)`). See `AsyncSidecarChain`.
        """
        return _Deferred(self._merged)

    async def _find_sidecars(self) -> tuple[Self, ...]:
        search = _search_sidecars(self)
        try:
            directory = next(search)
            while True:
                directory = search.send(await self._list_names(directory))
        except StopIteration as done:
            return done.value

    async def _merged(self) -> AsyncSidecarChain:
        sidecars = await self.sidecars
        contents = await asyncio.gather(
            *(s.as_dict() for s in sidecars), return_exceptions=True
        )
        # If several sidecars cannot be read, the nearest one's error.
        for content in contents:
            if isinstance(content, BaseException):
                raise content
        return AsyncSidecarChain(*contents, sidecars=sidecars, owner=self)

    @staticmethod
    async def _list_names(directory: AsyncTreeMixin) -> set[str]:
        pending = pending_names(directory)
        try:
            return {child.name async for child in directory.iterdir()} | pending
        except OSError:
            return pending


class _AsyncContentMixin:
    """The coroutine counterpart of `_ContentMixin`."""

    __slots__ = ()

    _kind: ClassVar[str]

    if TYPE_CHECKING:
        async def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    async def _descriptions(self) -> Mapping | None:
        return None

    async def _load(self, buffer: _Buffer, create: bool) -> _Entry:
        source = buffer.source(self)
        try:
            text = await source.read_text(encoding=_ENCODING)
        except FileNotFoundError:
            if not create:
                raise
            text = None
        descriptions = await source._descriptions()
        # Another task may have read it meanwhile: `load` keeps the first
        # entry, edits included.
        return buffer.load(source, self._kind, text, descriptions)

    async def _tx_entry(
        self, create: bool, tx: Any = None  # noqa: ANN401
    ) -> _Entry | None:
        tx = tx or active_for(self)
        if tx is None:
            return None
        entry = tx._buffer.get(self)
        if entry is None:
            entry = await self._load(tx._buffer, create)
        if not create and entry.absent():
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return entry

    async def _loaded(self) -> object:
        entry = await self._tx_entry(create=False)
        if entry is not None:
            return _detached(entry.content)
        text = await self.read_text(encoding=_ENCODING)
        return _content.parse(self._kind, text, await self._descriptions())

    async def _change(self, change: Callable[[_Entry], None]) -> None:
        require_writable(self, _WRITE)
        tx = active_for(self, write=True)
        if tx is not None:
            entry = await self._tx_entry(create=True, tx=tx)
            restore = entry.snapshot()
            try:
                change(entry)
            except BaseException:
                restore()
                raise
            return
        buffer = _Buffer()
        change(await self._load(buffer, create=True))
        for path, data in buffer.plan():
            await _transaction.awrite_file(path, data)


class AsyncJSONContentMixin(_AsyncContentMixin):
    """A JSON file as an asynchronous mapping of its top-level keys.

    The coroutine counterpart of `JSONContentMixin`:
    `await sidecar.as_dict()`, `get()`, `has()`, `keys()`, `values()`,
    `items()`, and `async for key in sidecar`; on a writable path,
    `await sidecar.set(key, value)`, `delete(key)`, `update()` and
    `write()`. Every call reads the file again.
    """

    __slots__ = ()
    _kind = _content.JSON

    async def as_dict(self) -> dict:
        """Load the file as a plain `dict` (see `BidsPath.as_dict`)."""
        return json_object(self, await self._loaded())

    async def write(self, content: object) -> None:
        """Replace the whole content of the file (see `BidsPath.write`)."""
        new = _content.copy_json(content)
        await self._change(lambda entry: entry.replace(new))

    async def set(self, key: str, value: object) -> None:
        """Set a key (the file is created if missing)."""
        value = _content.copy_json(value)

        def change(entry: _Entry) -> None:
            json_object(self, entry.content)[key] = value

        await self._change(change)

    async def delete(self, key: str) -> None:
        """Delete a key; `KeyError` if it is missing."""
        await self._change(
            lambda entry: json_object(self, entry.content).pop(key)
        )

    async def update(self, *args: Mapping | Iterable, **kwargs: object) -> None:
        """Set several keys, as `dict.update`, in one write."""
        new = _content.copy_json(dict(*args, **kwargs))
        await self._change(
            lambda entry: json_object(self, entry.content).update(new)
        )

    async def has(self, key: object) -> bool:
        """Whether the JSON object has `key`."""
        return key in await self.as_dict()

    async def __aiter__(self) -> AsyncIterator[str]:
        for key in await self.as_dict():
            yield key

    async def keys(self) -> KeysView[str]:
        """Return the keys of the JSON object."""
        return (await self.as_dict()).keys()

    async def values(self) -> ValuesView[object]:
        """Return the values of the JSON object."""
        return (await self.as_dict()).values()

    async def items(self) -> ItemsView[str, object]:
        """Return the `(key, value)` pairs of the JSON object."""
        return (await self.as_dict()).items()

    async def get(self, key: str, default: object = None) -> object:
        """Return the value of `key`, or `default`."""
        return (await self.as_dict()).get(key, default)

    def __getitem__(self, key: str) -> NoReturn:
        raise _not_awaitable(
            self, "indexing", "await path.get(key) or await path.as_dict()"
        )

    def __setitem__(self, key: str, value: object) -> NoReturn:
        raise _not_awaitable(self, "assignment", "await path.set(key, value)")

    def __delitem__(self, key: str) -> NoReturn:
        raise _not_awaitable(self, "'del'", "await path.delete(key)")

    def __contains__(self, key: object) -> NoReturn:
        raise _not_awaitable(self, "'in'", "await path.has(key)")


class AsyncTSVContentMixin(_AsyncContentMixin):
    """A TSV table as an asynchronous mapping of column names to columns.

    The coroutine counterpart of `TSVContentMixin`, with the same types:
    `await table.get("age")`, `has()`, `keys()`, `values()`, `items()`,
    `async for name in table`, `await table.as_dict()`, `as_list()`,
    `as_dataframe()`, and `async for row in table.rows()`; on a writable
    path, `await table.set(column, values)`, `delete(column)` and
    `write()`.
    """

    __slots__ = ()
    _kind = _content.TSV

    if TYPE_CHECKING:
        sidecar: Awaitable[AsyncSidecarChain]

    async def _descriptions(self) -> Mapping | None:
        return await self.sidecar

    async def _table(self, raw: bool = False) -> Table:
        if not raw:
            return await self._loaded()  # type: ignore[return-value]
        tx = active_for(self)
        entry = None if tx is None else tx._buffer.get(self)
        if entry is not None and not entry.absent():
            text = _content.dump_tsv(entry.content)
        else:
            text = await self.read_text(encoding=_ENCODING)
        return _content.parse_tsv(text, raw=True)

    # -- loading -------------------------------------------------------------
    async def as_dict(self, raw: bool = False) -> dict[str, list]:
        """Load the table as a `dict` of columns (see `BidsPath.as_dict`)."""
        return _columns(await self._table(raw))

    async def columns(self, raw: bool = False) -> dict[str, list]:
        """Load the table as a `dict` of columns; the same as `as_dict()`."""
        return await self.as_dict(raw)

    async def as_list(self, raw: bool = False) -> list[dict[str, object]]:
        """Load the table as a `list` of rows (see `BidsPath.as_list`)."""
        return _rows(await self._table(raw))

    async def rows(self, raw: bool = False) -> AsyncIterator[dict[str, object]]:
        """Iterate over the rows: `async for row in table.rows()`."""
        for row in await self.as_list(raw):
            yield row

    async def as_dataframe(self, **kwargs: object) -> DataFrame:
        """Load the table as a `pandas.DataFrame` (needs pandas).

        The coroutine counterpart of `BidsPath.as_dataframe`, with the same
        column types.
        """
        entry = await self._tx_entry(create=False)
        if entry is not None:
            text = _content.dump_tsv(entry.content)
        else:
            text = await self.read_text(encoding=_ENCODING)
        return _content.tsv_dataframe(
            text, kwargs, await self._descriptions()
        )

    # -- mapping of columns --------------------------------------------------
    async def get(self, column: str, default: object = None) -> object:
        """Return the column called `column`, typed, or `default`."""
        try:
            return _column(await self._table(), column)
        except KeyError:
            return default

    async def keys(self) -> list[str]:
        """Return the column names, in order (the header of the file)."""
        return (await self._table(raw=True)).columns

    async def has(self, column: object) -> bool:
        """Whether the table has a column called `column`."""
        return column in await self.keys()

    async def __aiter__(self) -> AsyncIterator[str]:
        for name in await self.keys():
            yield name

    async def values(self) -> list[list]:
        """Return the columns, typed, in order."""
        return list((await self.as_dict()).values())

    async def items(self) -> list[tuple[str, list]]:
        """Return `(name, column)` pairs, in order."""
        return list((await self.as_dict()).items())

    # -- writes --------------------------------------------------------------
    async def set(self, column: str, values: Iterable[object]) -> None:
        """Set a column, adding it last if it is new: one value per row."""
        values = copy.deepcopy(list(values))
        await self._change(
            lambda entry: entry.content._set_column(column, values)
        )

    async def delete(self, column: str) -> None:
        """Remove a column; `KeyError` if there is none."""
        await self._change(lambda entry: entry.content.drop_column(column))

    async def write(
        self,
        rows: Iterable[Mapping[str, object]],
        columns: Iterable[str] | None = None,
    ) -> None:
        """Replace the whole table with `rows` (see `BidsPath.write`)."""
        rows = rows if isinstance(rows, Table) else list(rows)
        await self._change(lambda entry: entry.replace(
            _new_table(rows, columns, entry.content)
        ))

    def __getitem__(self, column: str) -> NoReturn:
        raise _not_awaitable(self, "indexing", "await table.get(column)")

    def __setitem__(self, column: str, values: object) -> NoReturn:
        raise _not_awaitable(
            self, "assignment", "await table.set(column, values)"
        )

    def __delitem__(self, column: str) -> NoReturn:
        raise _not_awaitable(self, "'del'", "await table.delete(column)")

    def __contains__(self, column: object) -> NoReturn:
        raise _not_awaitable(self, "'in'", "await table.has(column)")
