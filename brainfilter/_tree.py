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
  in its own directory), and its `sidecar` is their merged content;
- a data file's `companions` are the other files that apply to it under
  the same rules (`events.tsv`, `physio.tsv.gz`, a `.bval`, ...),
  `companion(name)` one of them (or an image paired with it, `sbref`,
  `m0scan`), and its `fieldmaps` the fieldmaps of its subject meant for it.

On a writable path, `sidecar[key] = value`, `del sidecar[key]`,
`sidecar.update()`, `table[column] = values`, `del table[column]`, any
file's `write()` and a write to its merged `sidecar` each write the file at
once, in one atomic replace. Inside `with path:` (or
`with path.transaction():`) they are kept until the block ends, and every
read sees them; see `brainfilter.Transaction`.

Outside a block, a value a read returns is a copy: changing it in place is
not saved. Inside a block, on a writable path, `sidecar[key]` (and
`sidecar.get(key)`) returns the transaction's own value, and `table[column]`
(and `table.get(column)`) a `LiveColumn`, a `list` kept in step with the
transaction's own table, so a value changed in place is saved when the
block ends. Every other read
(`as_dict()`, `as_list()`, `rows()`, `values()`, `items()`,
`as_dataframe()`, the merged `sidecar`) returns a copy, inside a block too.

The `Async*` mixins give `AsyncBidsPath` the same surface as coroutines.
Python has no awaitable indexing or `in`, so a directory's `ds[name]` is
`await ds.child(name)`, a file's `f[key]` is `await f.get(key)`,
`f[key] = value` is `await f.set(key, value)`, `del f[key]` is
`await f.delete(key)` and `key in f` is `await f.has(key)`; every other
method keeps its name and is awaited (`await ds.keys()`,
`await sidecar.as_dict()`, `await data.sidecars`), and iteration is
`async for`. Both surfaces share the parsing below and the searches of
`brainfilter._associated`; only the reads and writes differ.
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
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn

from brainfilter import _content
from brainfilter import transaction as _transaction
from brainfilter._associated import (
    DATASET_DESCRIPTION,
    check_companion,
    search_companion,
    search_companions,
    search_fieldmaps,
    search_sidecars,
)
from brainfilter._content import Table, json_object
from brainfilter._mode import require_writable
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

    from brainfilter.filter import BidsFilter
    from brainfilter.transaction import _Entry

__all__ = ["DATASET_DESCRIPTION", "AsyncJSONContentMixin",
           "AsyncSidecarChain", "AsyncTSVContentMixin", "AsyncTreeMixin",
           "JSONContentMixin", "LiveColumn", "SidecarChain",
           "TSVContentMixin", "Table", "TreeMixin"]

# Files are read as UTF-8, skipping a byte-order mark; written without one.
_ENCODING = "utf-8-sig"

# What a write is said to do in a read-only error.
_WRITE = "write to"


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


def _live_column(path: object, tx: object, entry: _Entry,
                 name: object) -> LiveColumn:
    """Return the column `name` of the transaction's table; `KeyError` if none.

    One file gives one live column per name for the whole block.
    """
    live = entry.live
    if live is not None and isinstance(name, str):
        column = live.get(name)
        if type(column) is LiveColumn:
            return column
    table = entry.content
    if not isinstance(table, Table) or name not in table.columns:
        raise KeyError(name)
    if live is None:
        live = entry.live = {}
    column = live[name] = LiveColumn._over(path, tx, table, name)  # type: ignore[index]
    return column


def _sync_live(entry: _Entry) -> None:
    """Put the live columns of `entry` back in step with its table.

    After a change through the mapping API (a column set or dropped, the
    table replaced, or a change that raised and was put back): a column the
    table still has holds its values again, and one it has lost raises
    `KeyError` until the column is back. A column that has ended stays
    ended: a change that finishes once its block has closed (in a worker
    that outlived it) does not make it live again.
    """
    live = entry.live
    if not live:
        return
    table = entry.content
    columns = set(table.columns) if isinstance(table, Table) else set()
    with _transaction.LIVE_LOCK:
        for name, column in live.items():
            if name not in columns:
                column.__class__ = _EndedColumn
                continue
            is_open = column._tx._state == _transaction._OPEN
            if not is_open and type(column) is not LiveColumn:
                continue
            list.__setitem__(
                column, slice(None), [row.get(name) for row in table]
            )
            column._rows = table
            column.__class__ = LiveColumn
def _column_values(column: str, values: object) -> list:
    """Return a copy of `values` as a list: one value per row of `column`."""
    if isinstance(values, (str, bytes, bytearray, Mapping)):
        raise TypeError(
            f"the values of column {column!r} cannot be a "
            f"{type(values).__name__}: give one value per row, as a list "
            "(a string is not split into its characters); to give every row "
            "the same value, repeat it: [value] * number_of_rows"
        )
    return copy.deepcopy(list(values))  # type: ignore[call-overload]


# The cell values that cannot be changed in place, so need no copy.
_IMMUTABLE = frozenset({str, int, float, bool, type(None), date, datetime, time})


def _cell(value: object) -> object:
    """Return a copy of `value`, to set in a cell."""
    return value if type(value) in _IMMUTABLE else copy.deepcopy(value)


class LiveColumn(list):
    """A column of a TSV file inside a `with` block: the block's own values.

    `table[column]` returns one inside a block, on a writable path. It is a
    `list` of the column's values, and a value set in it (`column[0] = 31`,
    a slice of as many values, `sort()`, `reverse()`), or a change to a list
    a cell holds, is set in the transaction's table and saved when the block
    ends; the cells left unchanged keep their exact text. Anything else a
    list does works as on a list, and gives plain lists (`column + [1]`,
    `column.copy()`, `sorted(column)`, slices).

    A column has one value per row, so adding or removing a value
    (`append`, `del`, `+=`, a slice of another length, ...) raises
    `TypeError`; rows are added and removed by writing the table. A value
    set is copied. A write from another thread, or from a task started
    outside the block, raises `RuntimeError`, as for the table itself.
    Once the column is dropped (`del table[column]`) it raises `KeyError`
    until the column is set again; once the block has ended, using it at
    all raises `RuntimeError`: read the column again. Either way its
    `repr()` says so, rather than raising. A column compares as a list
    does: `column == [30.0, None]`, not a tuple.
    """

    __slots__ = ("_name", "_path", "_rows", "_tx")

    if TYPE_CHECKING:
        _name: str
        _path: Any
        _rows: Table
        _tx: Any

    @classmethod
    def _over(cls, path: object, tx: object, table: Table,
              name: str) -> LiveColumn:
        column = cls(row.get(name) for row in table)
        column._path, column._tx, column._rows, column._name = (
            path, tx, table, name
        )
        return column

    def _writable(self) -> Table:
        """Return the table to write to, from inside the block alone."""
        tx = self._tx
        if not _transaction.in_block(tx):
            if tx._state == _transaction._OPEN:
                raise tx._elsewhere_error(self._path)
            raise tx._closed_error(self._path)
        return self._rows

    def __setitem__(self, index: Any, value: Any) -> None:  # noqa: ANN401
        rows = self._writable()
        name = self._name
        if isinstance(index, slice):
            positions = range(len(self))[index]
            values = [_cell(item) for item in value]
            if len(values) != len(positions):
                raise self._one_per_row(
                    f" ({len(values)} values for {len(positions)} rows)"
                )
            list.__setitem__(self, index, values)
            for position, item in zip(positions, values):
                rows[position][name] = item
        else:
            value = _cell(value)
            list.__setitem__(self, index, value)
            rows[index][name] = value

    def sort(self, *, key: Any = None, reverse: bool = False) -> None:  # noqa: ANN401
        """Sort the values in place (`list.sort`); the rows stay in place."""
        rows = self._writable()
        before = list(self)
        try:
            list.sort(self, key=key, reverse=reverse)
        except BaseException:
            list.__setitem__(self, slice(None), before)
            raise
        self._set_all(rows)

    def reverse(self) -> None:
        """Reverse the values in place; the rows stay in place."""
        rows = self._writable()
        list.reverse(self)
        self._set_all(rows)

    def _set_all(self, rows: Table) -> None:
        name = self._name
        for row, value in zip(rows, self):
            row[name] = value

    def _one_per_row(self, detail: str = "") -> TypeError:
        return TypeError(
            f"column {self._name!r} of {str(self._path)!r} holds one value "
            f"per row, so values cannot be added to it or removed from it"
            f"{detail}: add or remove rows by writing the table's rows "
            "(table.write(rows))"
        )

    def _not_rows(self, *args: object, **kwargs: object) -> NoReturn:
        raise self._one_per_row()

    __delitem__ = append = extend = insert = pop = remove = clear = _not_rows  # type: ignore[assignment]
    __iadd__ = __imul__ = _not_rows  # type: ignore[assignment]

    def __copy__(self) -> list:
        return list(self)

    def __deepcopy__(self, memo: dict) -> list:
        return copy.deepcopy(list(self), memo)

    def __reduce_ex__(self, protocol: object) -> tuple:
        return list, (list(self),)

    def _end(self) -> None:
        """End the column: the block it was read in has ended."""
        self.__class__ = _EndedColumn


class _EndedColumn(LiveColumn):
    """A live column that no longer holds a column of the file.

    Every use raises: `KeyError` while the block is open and the table has
    no such column, `RuntimeError` once the block has ended. Its `repr()`
    says which instead, so that printing a value that holds it works.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        tx = self._tx
        if tx._state == _transaction._OPEN:
            why = "the table no longer has this column"
        else:
            why = "read in a transaction that has ended"
        return (
            f"<column {self._name!r} of {str(self._path)!r}: {why}>"
        )

    def _gone(self, *args: object, **kwargs: object) -> NoReturn:
        tx = self._tx
        if tx._state != _transaction._OPEN:
            when = (
                "is being committed" if tx._state == _transaction._COMMITTING
                else "has already closed"
            )
            raise RuntimeError(
                f"cannot use the column {self._name!r} of "
                f"{str(self._path)!r}: it was read in the transaction on "
                f"{str(tx._root)!r}, which {when}, so it no longer holds "
                f"the file's values; read the column again "
                f"(table[{self._name!r}])"
            )
        raise KeyError(self._name)

    for _member in (
        "__getitem__", "__setitem__", "__delitem__", "__iter__",
        "__reversed__", "__len__", "__contains__", "__eq__",
        "__ne__", "__lt__", "__le__", "__gt__", "__ge__", "__add__",
        "__radd__", "__mul__", "__rmul__", "__iadd__", "__imul__",
        "__bool__", "__copy__", "__deepcopy__", "__reduce_ex__",
        "__reduce__", "copy", "count", "index", "append", "extend",
        "insert", "pop", "remove", "clear", "sort", "reverse",
    ):
        locals()[_member] = _gone
    del _member


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
        _farther: bool = False,
    ) -> None:
        super().__init__(*maps)
        self.sidecars = tuple(sidecars)
        self._owner = owner
        # Whether this is the `parents` of another chain: the sidecars
        # farther than the nearest one.
        self._farther = _farther

    def as_dict(self) -> dict:
        """Return the merged content as a plain `dict`: the nearest wins."""
        return copy.deepcopy(dict(self))

    def _nearest(self) -> Any:  # noqa: ANN401
        if not self.sidecars:
            if self._farther:
                raise TypeError(
                    f"cannot write the farther sidecars of "
                    f"{str(self._owner)!r}: there is no farther sidecar, so "
                    "there is no file to write to; write to the nearer "
                    "sidecars instead"
                )
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
            *self.maps[1:], sidecars=self.sidecars[1:], owner=self._owner,
            _farther=True,
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

    # -- listings ------------------------------------------------------------
    def filter(self, *args: BidsFilter, **kwargs: object) -> list[Self]:
        """Return the files of this dataset that a filter keeps, sorted.

        `ds.filter(subjects=1, suffixes="bold")` builds the
        `brainfilter.BidsFilter` from its keywords; `ds.filter(f)` uses a
        filter already made. It lists the dataset as `BidsFilter.walk` does.
        """
        return _make_filter(args, kwargs).walk(self)

    def subjects(self) -> list[str]:
        """Return the subject labels of this dataset, sorted.

        The labels are those of the `sub-<label>` directories directly
        below this path, without the `sub-` prefix. Numeric labels are
        sorted as numbers.
        """
        return _sorted_labels(_entity_labels(self, "sub"))

    def sessions(self) -> list[str]:
        """Return the session labels below this path, sorted.

        On a subject directory, the labels of its `ses-<label>`
        directories; on a dataset, every label any subject has, once.
        """
        if _entity_label(self.name, "sub") is not None:
            return _sorted_labels(_entity_labels(self, "ses"))
        labels: set[str] = set()
        for child in self.iterdir():
            if _entity_label(child.name, "sub") is not None and (
                child.pathinfo.is_dir()
            ):
                labels.update(_entity_labels(child, "ses"))
        return _sorted_labels(labels)

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
        return self._answer(search_sidecars(self))

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

    @property
    def companions(self) -> tuple[Self, ...]:
        """The other files that come along with this data file, nearest first.

        These are the files that apply to it under the same inheritance as
        its `sidecars` (in its directory or an ancestor up to the dataset
        root, with a subset of its entities, index entities such as `run`
        compared by number), other than its `sidecars` themselves: the
        files with a companion suffix (`events`, `physio`, `stim`,
        `physioevents`, `channels`, `electrodes`, `coordsystem`, `optodes`,
        `aslcontext`, `asllabeling`, `scans`, `sessions`) and their JSON
        files, and the metadata files with this file's own suffix that are
        not JSON (the `.bval` and `.bvec` of a `dwi` image). An
        `electrodes`, `coordsystem` or `physio` file may also have a
        `space` or `recording` entity that this file lacks. These are the
        files a `BidsFilter` keeps with this file, besides its sidecars. A
        single-band reference (`_sbref`) or an M0 scan (`_m0scan`) is a
        data file of its own, not a companion; `companion("sbref")` finds
        it.

        Files in a nearer directory come first, and within one directory
        they are sorted by name. A file that is not a data file (a sidecar,
        a table, a directory, a `README`) has none. Inside a transaction,
        new files count. The directories are listed each time this is read.
        """
        return self._answer(search_companions(self))

    def companion(self, name: str, /, **entities: object) -> Self | None:
        """Return one companion of this data file by name, or `None`.

        ```python
        dwi.companion("bval")                   # the .bval that applies
        bold.companion("events")                # its events.tsv
        eeg.companion("electrodes", space="CapTrak")
        bold.companion("sbref")                 # its single-band reference
        ```

        It is the file of `companions` with that suffix (or, for `bval`
        and `bvec`, that extension) in the nearest directory that holds
        one, so a file inherited from higher up is found too. A table or a
        recording is the file itself (`events.tsv`, `physio.tsv.gz`), not
        the JSON that describes it, which is among its own `sidecars`; a
        `coordsystem` is a JSON file.

        An `sbref` or an `m0scan` is an image of its own, not a companion:
        it is the `.nii.gz` (or `.nii`) image in this file's directory with
        the same entities (index entities such as `run` compared by
        number, so `run-1` is `run-01`) and that suffix.

        `None` when there is no such file, and for a file that is not a
        data file. Inside a transaction, new files count.

        Parameters
        ----------
        name
            A companion suffix (`events`, `physio`, `stim`, `physioevents`,
            `channels`, `electrodes`, `coordsystem`, `optodes`,
            `aslcontext`, `asllabeling`, `scans`, `sessions`), a gradient
            table (`bval`, `bvec`), or an image paired with this one
            (`sbref` with a `bold`, `cbv`, `phase` or `dwi` image, `m0scan`
            with an `asl` series).
        **entities
            Entities the file must have, `key=label` (index entities
            compared by number); a label of `None` asks for a file without
            that entity.

        Raises
        ------
        ValueError
            If `name` is not one of these, or if the nearest directory
            that holds such a file holds more than one (two `electrodes`
            files in different spaces): pass an entity that tells them
            apart.
        """
        entities = check_companion(name, entities)
        return self._answer(search_companion(self, name, entities))

    @property
    def fieldmaps(self) -> tuple[Self, ...]:
        """The fieldmaps meant to correct this data file, sorted by path.

        A fieldmap is a data file of a `fmap/` directory of this file's
        subject (`sub-<label>/fmap/`, or `sub-<label>/ses-<label>/fmap/` of
        any session), and it is meant for this file when its merged
        sidecar either

        - names this file in `IntendedFor` (a string or a list): a path
          relative to the subject directory (`func/sub-01_task-rest_bold.nii.gz`),
          or a BIDS URI relative to the dataset root
          (`bids::sub-01/func/sub-01_task-rest_bold.nii.gz`); a URI that
          names another dataset (`bids:<name>:...`) is not followed;
        - or has a `B0FieldIdentifier` (a string or a list) that is one of
          the `B0FieldSource` of this file's merged sidecar.

        Each fieldmap image is listed once, whichever way it is found
        (`_phasediff.nii.gz` and `_magnitude1.nii.gz`, an `_epi.nii.gz`, a
        `_fieldmap.nii.gz`, ...); their own sidecars are not. A file that is
        not a data file has none. Inside a transaction, new files and
        values count. The directories are listed, and the sidecars read,
        each time this is read.
        """
        return self._answer(search_fieldmaps(self))

    def _answer(self, search: Generator) -> Any:  # noqa: ANN401
        """Run a search of `_associated`, listing and reading for it."""
        try:
            kind, target = next(search)
            while True:
                if kind == "list":
                    answer = self._list_names(target)
                else:
                    answer = target.as_dict()
                kind, target = search.send(answer)
        except StopIteration as done:
            return done.value

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
            # Read under the file's lock, so that a write through that has
            # checked no transaction covers the file is read, not lost.
            with _transaction.file_lock(self):
                entry = tx._buffer.get(self)
                if entry is None:
                    tx._claim(self)
                    entry = self._load(tx._buffer, create)
        if not create and entry.absent():
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return entry

    def _live(self) -> tuple[Any, _Entry] | None:
        """Return the transaction and entry whose own values a read returns.

        Inside a block, on a writable path; `None` elsewhere (a read-only
        path is given copies, so it cannot change the file).
        """
        if getattr(self, "mode", "r") != "w":
            return None
        tx = active_for(self)
        if tx is None:
            return None
        return tx, self._tx_entry(create=False, tx=tx)  # type: ignore[return-value]

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
        atomic replace, holding the file's lock, so concurrent writes to one
        file are made one after the other; a change that raises writes
        nothing.
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
            finally:
                _sync_live(entry)
            return
        # One read-change-write at a time per file, so that two writes to
        # the same file (from two threads) do not lose one of them.
        with _transaction.file_lock(self):
            # A block opened meanwhile in another thread may cover the file
            # now: the write is refused, as one made after it opened is. A
            # block of this family reads the file under this lock, so one
            # that opens later reads this write; one that reads it under
            # another lock is kept apart by `marking_through`.
            active_for(self, write=True)
            with _transaction.marking_through(self):
                buffer = _Buffer()
                change(self._load(buffer, create=True))
                with _transaction.writing_through():
                    for path, data in buffer.plan():
                        _transaction.write_file(path, data)


class JSONContentMixin(_ContentMixin):
    """A JSON file as a mapping of its top-level keys.

    Every lookup reads the file again; `as_dict()` loads it once, as a
    plain `dict`. On a writable path, `sidecar[key] = value`,
    `del sidecar[key]`, `update()` and `write()` write the file at once, in
    one atomic replace (inside `with dataset:`, when the block ends). A
    value read is a copy, except `sidecar[key]` and `get()` inside a block,
    which return the transaction's own value: changing it in place is then
    saved.
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
        """Return the value of `key`; `KeyError` if it is missing.

        Outside a `with` block it is a copy. Inside one, on a writable path,
        it is the transaction's own value, so a nested value changed in
        place (`sidecar["Extra"]["Coil"] = "neck"`) is saved when the block
        ends.
        """
        live = self._live()
        if live is not None:
            return json_object(self, live[1].content)[key]
        return self.as_dict()[key]

    def __setitem__(self, key: str, value: object) -> None:
        """Set a key (the file is created if missing); `value` is copied."""
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
        """Return the value of `key`, or `default` (live as `sidecar[key]`)."""
        live = self._live()
        if live is not None:
            return json_object(self, live[1].content).get(key, default)
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
       (`true`/`false`), `date` as `datetime.date`, `datetime`
       as `datetime.datetime` and `time` as `datetime.time`, any other format as `str`;
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
    unchanged keep their exact text. Inside a block, `table[column]` is a
    `LiveColumn` over the transaction's own table, so a value set in it
    (`table["age"][0] = 31`) is saved too; every other read is a copy.
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
    def __getitem__(self, column: str) -> list | LiveColumn:
        """Return the column called `column`, typed; `KeyError` if none.

        Outside a `with` block it is a `list`, a copy. Inside one, on a
        writable path, it is a `LiveColumn` over the transaction's own
        table, so `table["age"][0] = 31` is saved when the block ends.
        """
        live = self._live()
        if live is not None:
            return _live_column(self, *live, column)
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

        In a table with no row yet (a new file, or a header alone), the
        first column set gives the number of rows, and the other columns
        are `n/a` in them. `values` is a list or another iterable of values;
        a `str`, `bytes` or mapping raises `TypeError`.
        """
        values = _column_values(column, values)
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

    # -- listings ------------------------------------------------------------
    async def filter(self, *args: BidsFilter, **kwargs: object) -> list[Self]:
        """Return the files of this dataset that a filter keeps, sorted.

        The coroutine counterpart of `BidsPath.filter`, listing the dataset
        as `BidsFilter.awalk` does.
        """
        return await _make_filter(args, kwargs).awalk(self)

    async def subjects(self) -> list[str]:
        """Return the subject labels of this dataset, sorted.

        The coroutine counterpart of `BidsPath.subjects`.
        """
        return _sorted_labels(await _aentity_labels(self, "sub"))

    async def sessions(self) -> list[str]:
        """Return the session labels below this path, sorted.

        The coroutine counterpart of `BidsPath.sessions`; the subjects of a
        dataset are listed at once.
        """
        if _entity_label(self.name, "sub") is not None:
            return _sorted_labels(await _aentity_labels(self, "ses"))
        subjects = await _aentity_dirs(self, "sub")
        listings = await asyncio.gather(
            *(_aentity_labels(s, "ses") for s in subjects)
        )
        return _sorted_labels(set().union(*listings))

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

    @property
    def companions(self) -> Awaitable[tuple[Self, ...]]:
        """The other files that come along with this data file, nearest first.

        Awaitable: `await data.companions`. The same rules as
        `BidsPath.companions`.
        """
        return _Deferred(lambda: self._answer(search_companions(self)))

    def companion(
        self, name: str, /, **entities: object
    ) -> Awaitable[Self | None]:
        """Return one companion of this data file by name, or `None`.

        Awaitable: `await bold.companion("events")`. The same rules as
        `BidsPath.companion`; an unknown `name` raises at once, before
        anything is awaited.
        """
        entities = check_companion(name, entities)
        return _Deferred(
            lambda: self._answer(search_companion(self, name, entities))
        )

    @property
    def fieldmaps(self) -> Awaitable[tuple[Self, ...]]:
        """The fieldmaps meant to correct this data file, sorted by path.

        Awaitable: `await data.fieldmaps`. The same rules as
        `BidsPath.fieldmaps`.
        """
        return _Deferred(lambda: self._answer(search_fieldmaps(self)))

    async def _find_sidecars(self) -> tuple[Self, ...]:
        return await self._answer(search_sidecars(self))

    async def _answer(self, search: Generator) -> Any:  # noqa: ANN401
        """Run a search of `_associated`, listing and reading for it."""
        try:
            kind, target = next(search)
            while True:
                if kind == "list":
                    answer = await self._list_names(target)
                else:
                    answer = await target.as_dict()
                kind, target = search.send(answer)
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
            # Read under the file's lock (see `_ContentMixin._tx_entry`).
            async with _transaction.afile_lock(self):
                entry = tx._buffer.get(self)
                if entry is None:
                    tx._claim(self)
                    entry = await self._load(tx._buffer, create)
        if not create and entry.absent():
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return entry

    async def _live(self) -> tuple[Any, _Entry] | None:
        """Return what `_ContentMixin._live` does, as a coroutine."""
        if getattr(self, "mode", "r") != "w":
            return None
        tx = active_for(self)
        if tx is None:
            return None
        return tx, await self._tx_entry(create=False, tx=tx)  # type: ignore[return-value]

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
            finally:
                _sync_live(entry)
            return
        # One read-change-write at a time per file, across the tasks of
        # this event loop (see `_ContentMixin._change`).
        async with _transaction.afile_lock(self):
            # Checked again under the lock (see `_ContentMixin._change`).
            active_for(self, write=True)
            with _transaction.marking_through(self):
                buffer = _Buffer()
                change(await self._load(buffer, create=True))
                with _transaction.writing_through():
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
        """Return the value of `key`, or `default`.

        Outside an `async with` block it is a copy. Inside one, on a
        writable path, it is the transaction's own value, so a nested value
        changed in place is saved when the block ends.
        """
        live = await self._live()
        if live is not None:
            return json_object(self, live[1].content).get(key, default)
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
        """Return the column called `column`, typed, or `default`.

        Outside an `async with` block it is a `list`, a copy. Inside one, on
        a writable path, it is a `LiveColumn` over the transaction's own
        table (see `BidsPath.__getitem__`).
        """
        try:
            live = await self._live()
            if live is not None:
                return _live_column(self, *live, column)
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
        """Set a column, adding it last if it is new: one value per row.

        As `BidsPath.__setitem__`: in a table with no row yet, the first
        column set gives the number of rows; a `str`, `bytes` or mapping
        raises `TypeError`.
        """
        values = _column_values(column, values)
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


# -- listings --------------------------------------------------------------------

def _make_filter(args: tuple, kwargs: dict) -> BidsFilter:
    """Return the `BidsFilter` given by position, or built from keywords."""
    from brainfilter.filter import BidsFilter

    if not args:
        return BidsFilter(**kwargs)
    if len(args) == 1 and not kwargs and isinstance(args[0], BidsFilter):
        return args[0]
    raise TypeError(
        "filter() takes either one BidsFilter or BidsFilter keywords, not both"
        if kwargs and args
        else "filter() takes one BidsFilter, or BidsFilter keywords"
    )


def _entity_label(name: str, key: str) -> str | None:
    """Return the label of a `<key>-<label>` name, or None."""
    prefix = f"{key}-"
    if name.startswith(prefix) and len(name) > len(prefix):
        return name[len(prefix):]
    return None


def _sorted_labels(labels: Iterable[str]) -> list[str]:
    """Sort labels as numbers when they all are, else as text."""
    labels = list(labels)
    if all(label.isdigit() for label in labels):
        return sorted(labels, key=lambda label: (int(label), label))
    return sorted(labels)


def _entity_labels(directory: TreeMixin, key: str) -> set[str]:
    """Return the labels of the `<key>-<label>` directories in `directory`."""
    return {
        label
        for child in directory.iterdir()
        if (label := _entity_label(child.name, key)) is not None
        and child.pathinfo.is_dir()
    }


async def _aentity_dirs(directory: AsyncTreeMixin, key: str) -> list:
    """Return the `<key>-<label>` directories in `directory`."""
    return [
        child
        async for child in directory.iterdir()
        if _entity_label(child.name, key) is not None
        and await child.pathinfo.is_dir()
    ]


async def _aentity_labels(directory: AsyncTreeMixin, key: str) -> set[str]:
    """Return the labels of the `<key>-<label>` directories in `directory`."""
    return {
        _entity_label(child.name, key)  # type: ignore[misc]
        for child in await _aentity_dirs(directory, key)
    }
