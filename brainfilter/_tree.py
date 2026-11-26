"""Read-only dataset tree: child access, file contents and sidecar metadata.

These mixins give `BidsPath` and its file classes a dict-like, read-only
surface:

- a directory maps child names to paths: `dataset["sub-01"]["anat"]`;
- a JSON file maps its keys to values: `sidecar["RepetitionTime"]`, and
  `sidecar.read()` returns the whole object as a `dict`;
- a TSV file reads as rows: `table.read()` is a list of `dict`, one per row,
  with typed values (`int`, `float`, ...; `read(raw=True)` for the text),
  and `table.read_dataframe()` a `pandas.DataFrame` (pandas is optional);
- any file's effective metadata, `data.metadata`, is a
  `collections.ChainMap` of the JSON sidecars that apply to it, nearest
  first, up to the dataset root (or, with no dataset root above it, those
  in its own directory).

The `Async*` mixins give `AsyncBidsPath` the same surface as coroutines.
Python has no awaitable indexing or `in`, so a directory's `ds[name]` is
`await ds.child(name)` and `name in ds` is `await ds.has(name)`; every
other method keeps its name and is awaited (`await ds.keys()`,
`await sidecar.read()`, `await data.read_metadata()`), and iteration is
`async for`. Both surfaces share the parsing and the sidecar search below;
only the reads differ.

The tree is read-only outside a transaction (`with dataset.transaction():`)
or a single-file edit (`with sidecar.edit() as content:`). Inside one, JSON
keys can be set and deleted, a JSON or TSV file replaced or created, and a
table's rows and columns edited; every read sees those edits. See
`brainfilter.transaction`.
"""
from __future__ import annotations

import asyncio
from collections import ChainMap
from collections.abc import (
    AsyncIterator,
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
from brainfilter._content import Table, json_object
from brainfilter._names import applies_to, parse_name
from brainfilter.transaction import (
    AsyncEdit,
    AsyncTransaction,
    Edit,
    Transaction,
    active_for,
    pending_names,
)

if TYPE_CHECKING:
    from pandas import DataFrame
    from typing_extensions import Self

    from brainfilter.transaction import _Entry

__all__ = ["DATASET_DESCRIPTION", "AsyncJSONContentMixin",
           "AsyncTSVContentMixin", "AsyncTreeMixin", "JSONContentMixin",
           "TSVContentMixin", "Table", "TreeMixin"]

DATASET_DESCRIPTION = "dataset_description.json"

# Files are read as UTF-8, skipping a byte-order mark; written without one.
_ENCODING = "utf-8-sig"

# A path of either family (sync or async).
_P = TypeVar("_P")


def _read_only(obj: object, prefix: str = "") -> TypeError:
    return TypeError(
        f"{type(obj).__name__} is read-only outside a transaction: edit it "
        f"inside `{prefix}with dataset.transaction():` or "
        f"`{prefix}with path.edit() as content:`"
    )


def _no_delete(obj: object) -> TypeError:
    return TypeError(
        f"{type(obj).__name__} cannot delete a child: a transaction edits "
        "the content of JSON and TSV files, it does not delete files"
    )


def _not_content(name: str) -> TypeError:
    return TypeError(
        f"cannot write {name!r}: only JSON and TSV files can be written "
        "through the dataset tree"
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
        how = (
            f"create one inside a transaction first, e.g. "
            f"`(path.parent / {name!r}).write({{...}})`"
        )
    return TypeError(
        f"cannot write the metadata of {str(path)!r}: {why}, so there is no "
        f"file to write it to; {how}"
    )


class _NoSidecar(dict):
    """The metadata of a file that no sidecar applies to: empty, read-only.

    It is the only map of the file's `ChainMap`, so a write to the
    `ChainMap` raises rather than being lost.
    """

    __slots__ = ("_path",)

    def __init__(self, path: object = None) -> None:
        super().__init__()
        self._path = path

    def _refuse(self, *args: object, **kwargs: object) -> NoReturn:
        raise _no_sidecar_error(self._path)

    __setitem__ = __delitem__ = _refuse
    setdefault = update = pop = popitem = clear = __ior__ = _refuse


def _metadata(path: object, contents: list) -> ChainMap:
    """Return the `ChainMap` of a file's sidecar contents, nearest first."""
    return ChainMap(*contents) if contents else ChainMap(_NoSidecar(path))


def _by_name(children: Iterable[Any]) -> list[Any]:
    return sorted(children, key=lambda child: child.name)


def _with_pending(
    directory: object, listed: list[Any], pending: set[str]
) -> list[Any]:
    """Return the `listed` children and those a transaction holds, sorted."""
    names = {child.name for child in listed}
    listed.extend(directory / name for name in sorted(pending - names))
    return _by_name(listed)


def _new_content(
    kind: str,
    content: object,
    columns: object,
    origin: object = None,
    delimiters: dict[str, str] | None = None,
) -> object:
    """Return a copy of `content`, as a transaction holds it.

    For a table, `origin` is the table the transaction held so far: rows
    taken from it keep their original text. `delimiters` join the lists
    of the columns the rows do not already know a `Delimiter` for.
    """
    if kind == _content.JSON:
        if columns is not None:
            raise TypeError("columns= is for a TSV file")
        return _content.copy_json(content)
    origin = origin if isinstance(origin, Table) else None
    table = Table(content, columns=columns, _origin=origin)
    table._delimiters = {**(delimiters or {}), **table._delimiters}
    return table


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
    # Each directory is listed once, in one walk up; `levels` runs from the
    # file's own directory up to the root.
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
    return found


def _as_root(path: _P, root: object) -> _P | None:
    """`root` as a path of `path`'s family, or `None`."""
    return None if root is None else path._root(root)


# -- sync surface ----------------------------------------------------------------

class TreeMixin:
    """A directory as a mapping `child name -> path`, read-only by default.

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
        """Buffer edits to the JSON and TSV files below this path.

        ```python
        with dataset.transaction():
            dataset["T1w.json"]["RepetitionTime"] = 2.3
        ```

        On a clean exit each changed file is written, in one step; on an
        exception nothing is written. See `brainfilter.transaction`.

        Raises
        ------
        RuntimeError
            If a transaction on this path, an ancestor or a descendant is
            already open.
        """
        return Transaction(self)

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
        """Create or replace the JSON or TSV file `name`, in a transaction."""
        if not _is_child_name(name):
            raise KeyError(name)
        child = self / name
        if not isinstance(child, _ContentMixin):
            raise _not_content(name)
        child.write(content)

    def __delitem__(self, name: str) -> None:
        raise _no_delete(self)

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
        entities comes first. Inside a transaction, new sidecars count.

        Parameters
        ----------
        root
            The dataset root. By default, the nearest ancestor that holds a
            `dataset_description.json`. If no ancestor holds one, only the
            sidecars in this file's own directory count.

        Raises
        ------
        ValueError
            If `root` is given and is not an ancestor.
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
        Inside a transaction they are the transaction's own copies, so a
        write to the `ChainMap` edits the nearest sidecar. With no sidecar,
        the `ChainMap` is empty and a write to it raises `TypeError`: there
        is no file to write it to.
        """
        return _metadata(
            self, [sidecar.read() for sidecar in self.sidecars(root)]
        )

    @staticmethod
    def _list_names(directory: TreeMixin) -> set[str]:
        pending = pending_names(directory)
        try:
            return {child.name for child in directory.iterdir()} | pending
        except OSError:
            return pending


class _ContentMixin:
    """What a JSON and a TSV file share: reads and edits in a transaction."""

    __slots__ = ()

    _kind: ClassVar[str]

    if TYPE_CHECKING:
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    def _descriptions(self, root: object = None) -> Mapping | None:
        """Return what types the content when parsed (a table's columns)."""
        return None

    def _tx_entry(
        self, create: bool, root: object = None, tx: Any = None  # noqa: ANN401
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
            # Read through the name the file is written with (no `..`).
            source = tx._buffer.source(self)
            try:
                text = source.read_text(encoding=_ENCODING)
            except FileNotFoundError:
                if not create:
                    raise
                text = None
            descriptions = source._descriptions(root)
            entry = tx._buffer.load(source, self._kind, text, descriptions)
        if not create and entry.absent():
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return entry

    def _read_content(self, root: object = None) -> object:
        entry = self._tx_entry(create=False, root=root)
        if entry is not None:
            return entry.content
        text = self.read_text(encoding=_ENCODING)
        return _content.parse(self._kind, text, self._descriptions(root))

    def _tx_writable(self) -> object:
        tx = active_for(self, write=True)
        if tx is None:
            raise _read_only(self)
        return self._tx_entry(create=True, tx=tx).content

    def _tx_replace(
        self,
        content: object,
        columns: object = None,
        delimiters: dict[str, str] | None = None,
    ) -> None:
        tx = active_for(self, write=True)
        if tx is None:
            raise _read_only(self)
        held = tx._buffer.get(self)
        origin = None if held is None else held.content
        tx._buffer.replace(self, self._kind, _new_content(
            self._kind, content, columns, origin, delimiters
        ))

    def edit(self) -> Edit:
        """Edit this file on its own: `with path.edit() as content:`.

        `content` is the file's content (a `dict`, or a `Table` for a TSV
        file; empty if the file does not exist yet), to change in place. On
        a clean exit the file is replaced in one step, and an error writing
        it is raised as is; on an exception it is left as it was. Inside a
        transaction that covers the file, the edit joins it.
        """
        return Edit(self)


class JSONContentMixin(_ContentMixin):
    """A JSON file as a mapping of its top-level keys.

    Outside a transaction it is read-only, and every lookup reads the file
    again; call `read()` once to work on the content as a plain `dict`.
    Inside one, `sidecar[key] = value`, `del sidecar[key]`, `update()` and
    `write()` edit the transaction's copy.
    """

    __slots__ = ()
    _kind = _content.JSON

    def read(self) -> object:
        """Read and parse the file (a `dict` for a BIDS JSON file).

        Inside a transaction this is the transaction's copy: changing it
        edits the file.
        """
        return self._read_content()

    def write(self, content: object) -> None:
        """Replace the whole content of the file, in a transaction.

        `content` is copied, and must be JSON-serializable. The file is
        created if it does not exist.
        """
        self._tx_replace(content)

    def _mapping(self) -> dict:
        return json_object(self, self.read())

    def _writable_mapping(self) -> dict:
        return json_object(self, self._tx_writable())

    def __getitem__(self, key: str) -> object:
        return self._mapping()[key]

    def __setitem__(self, key: str, value: object) -> None:
        """Set a key, in a transaction (the file is created if missing)."""
        self._writable_mapping()[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete a key, in a transaction."""
        del self._writable_mapping()[key]

    def update(self, *args: Mapping | Iterable, **kwargs: object) -> None:
        """Set several keys, as `dict.update`, in a transaction."""
        self._writable_mapping().update(*args, **kwargs)

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


class TSVContentMixin(_ContentMixin):
    """A TSV table, read as rows.

    Inside a transaction, the `Table` that `read()` returns is the
    transaction's copy: edit its rows and columns in place, or replace the
    whole table with `write()`.
    """

    __slots__ = ()
    _kind = _content.TSV

    def read(self, raw: bool = False, root: object = None) -> Table:
        """Read the table as a `Table`: a list of rows, `column -> value`.

        Values are typed, one type per column, and the BIDS missing value
        `n/a` reads as `None`. A column's type comes from the first of:

        1. its description in the table's JSON sidecar (`participants.json`
           for `participants.tsv`, found as `metadata` is), if it has a
           `Format`: `number` reads as `float`, `integer` and `index` as
           `int`, `boolean` as `bool` (`true`/`false`), `date`, `datetime`
           and `time` as `datetime` objects, any other format as `str`;
        2. its standard BIDS definition (`age` is a number, `onset` too,
           `participant_id` a string, ...);
        3. its values: `int` if every value is an integer written as
           Python writes it, else `float` if every value is, else `str`.
           So `02`, `1e3`, `1.50` and a column mixing `3` and `1.5` stay
           text; booleans and dates are never guessed.

        A declared type (1 or 2) is used only if every value of the column
        parses as it (a date must be ISO 8601: `2024-01-31`,
        `2024-01-31T10:00:00[.ffffff][Z|+hh:mm]`, `10:00:00[.ffffff]`);
        otherwise the next one is tried. A column whose description has
        `Levels` keeps its values as text, the keys of `Levels`. A column
        whose description has a `Delimiter` reads as lists. A `number`
        always reads as `float`, even when integral.

        Inside a transaction this is the transaction's copy: changing it
        edits the file. When the file is written, the cells left unchanged
        keep their exact text.

        Parameters
        ----------
        raw
            Return every value as its exact text, `n/a` included, without
            reading any sidecar. Inside a transaction this is a copy of
            the transaction's table, as it would be written: changing it
            does not edit the file.
        root
            The dataset root up to which sidecars describe the columns, as
            in `read_metadata`. Inside a transaction, a table is typed when
            it is first used there.
        """
        if raw:
            return self._read_raw()
        return self._read_content(root)

    def _descriptions(self, root: object = None) -> Mapping | None:
        return self.read_metadata(root)

    def _read_raw(self) -> Table:
        tx = active_for(self)
        entry = None if tx is None else tx._buffer.get(self)
        if entry is not None and not entry.absent():
            text = _content.dump_tsv(entry.content)
        else:
            text = self.read_text(encoding=_ENCODING)
        return _content.parse_tsv(text, raw=True)

    def write(
        self,
        rows: Iterable[Mapping[str, object]],
        columns: Iterable[str] | None = None,
    ) -> None:
        """Replace the whole table, in a transaction.

        `rows` are copied. `columns` sets the order of the columns (by
        default, a `Table`'s own, else the order the keys first appear in).
        The file is created if it does not exist. Rows taken from this
        file's `read()` keep the text of their unchanged cells. A list value
        is joined with its column's `Delimiter`, from the table's JSON
        sidecar.
        """
        tx = active_for(self, write=True)
        if tx is None:
            raise _read_only(self)
        rows = rows if isinstance(rows, Table) else list(rows)
        delimiters = None
        if _content.has_lists(rows) or tx._buffer.get(self) is None:
            # Rows appended later may hold lists too.
            delimiters = _content.delimiters(self._descriptions())
        self._tx_replace(rows, columns, delimiters)

    def read_dataframe(self, root: object = None, **kwargs: object) -> DataFrame:
        """Read the table as a `pandas.DataFrame` (needs pandas).

        `n/a` reads as a missing value, and the columns have the types
        `read()` gives them, as pandas dtypes: `int64` (`Int64` with a
        missing value), `float64`, `bool` (`boolean`), `datetime64` for a
        `datetime` column with one time zone, and `object` for the rest
        (text, dates, times and the lists of a `Delimiter`). Keywords go to
        `pandas.read_csv`; with `dtype=` or `converters=`, pandas types the
        columns as asked instead. `root` is the dataset root, as in
        `read()`. Inside a transaction, the frame is a copy of the buffered
        table.
        """
        entry = self._tx_entry(create=False, root=root)
        if entry is not None:
            text = _content.dump_tsv(entry.content)
        else:
            text = self.read_text(encoding=_ENCODING)
        return _content.tsv_dataframe(text, kwargs, self._descriptions(root))

    def __getitem__(self, key: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: use read() for its rows"
        )

    def __setitem__(self, key: object, value: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: edit the rows of read() "
            "inside a transaction, or replace them with write()"
        )

    def __delitem__(self, key: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: edit the rows of read() "
            "inside a transaction"
        )

    def __iter__(self) -> Iterator[dict[str, object]]:
        return iter(self.read())


# -- async surface ---------------------------------------------------------------

def _not_awaitable(obj: object, operation: str, instead: str) -> TypeError:
    return TypeError(
        f"{type(obj).__name__} is asynchronous: {operation} cannot be "
        f"awaited; use {instead}"
    )


class AsyncTreeMixin:
    """A directory as an asynchronous mapping `child name -> path`.

    The coroutine counterpart of `TreeMixin`: `await ds.child(name)` for
    `ds[name]`, `await ds.has(name)` for `name in ds`, `await ds.keys()`,
    `values()`, `items()`, `get()`, and `async for name in ds`. Each call
    lists the directory again; nothing is cached. Inside a transaction
    (`async with ds.transaction():`) the files it holds are listed too.
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
        """Buffer edits to the JSON and TSV files below this path.

        The async counterpart of `BidsPath.transaction`, used with
        `async with`; see `brainfilter.transaction`.
        """
        return AsyncTransaction(self)

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
    async def sidecars(self, root: object = None) -> list[Self]:
        """Return the JSON sidecars that apply to this file, nearest first.

        The coroutine counterpart of `BidsPath.sidecars`, with the same
        rules and errors: with no dataset root above the file, only the
        sidecars in its own directory count.
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
        the sidecars are read concurrently. Inside a transaction they are
        the transaction's own copies, as in `BidsPath.read_metadata`. If
        several sidecars cannot be read, the error of the nearest is
        raised, as in `BidsPath.read_metadata`.
        """
        sidecars = await self.sidecars(root)
        contents = await asyncio.gather(
            *(s.read() for s in sidecars), return_exceptions=True
        )
        for content in contents:
            if isinstance(content, BaseException):
                raise content
        return _metadata(self, contents)

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

    async def _descriptions(self, root: object = None) -> Mapping | None:
        return None

    async def _tx_entry(
        self, create: bool, root: object = None, tx: Any = None  # noqa: ANN401
    ) -> _Entry | None:
        tx = tx or active_for(self)
        if tx is None:
            return None
        entry = tx._buffer.get(self)
        if entry is None:
            source = tx._buffer.source(self)
            try:
                text = await source.read_text(encoding=_ENCODING)
            except FileNotFoundError:
                if not create:
                    raise
                text = None
            descriptions = await source._descriptions(root)
            # Another task may have read it meanwhile: `load` keeps the
            # first entry, edits included.
            entry = tx._buffer.load(source, self._kind, text, descriptions)
        if not create and entry.absent():
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return entry

    async def _read_content(self, root: object = None) -> object:
        entry = await self._tx_entry(create=False, root=root)
        if entry is not None:
            return entry.content
        text = await self.read_text(encoding=_ENCODING)
        return _content.parse(self._kind, text, await self._descriptions(root))

    async def _tx_writable(self) -> object:
        tx = active_for(self, write=True)
        if tx is None:
            raise _read_only(self, "async ")
        return (await self._tx_entry(create=True, tx=tx)).content

    def _tx_replace(
        self,
        content: object,
        columns: object = None,
        delimiters: dict[str, str] | None = None,
    ) -> None:
        tx = active_for(self, write=True)
        if tx is None:
            raise _read_only(self, "async ")
        held = tx._buffer.get(self)
        origin = None if held is None else held.content
        tx._buffer.replace(self, self._kind, _new_content(
            self._kind, content, columns, origin, delimiters
        ))

    def edit(self) -> AsyncEdit:
        """Edit this file on its own: `async with path.edit() as content:`.

        The async counterpart of `BidsPath.edit`.
        """
        return AsyncEdit(self)


class AsyncJSONContentMixin(_AsyncContentMixin):
    """A JSON file as an asynchronous mapping of its top-level keys.

    The coroutine counterpart of `JSONContentMixin`: `await sidecar.read()`,
    `get()`, `has()`, `keys()`, `values()`, `items()`, and
    `async for key in sidecar`. Every call reads the file again, outside a
    transaction. Inside one, `await sidecar.set(key, value)`,
    `delete(key)`, `update()` and `write()` edit the transaction's copy.
    """

    __slots__ = ()
    _kind = _content.JSON

    async def read(self) -> object:
        """Read and parse the file (a `dict` for a BIDS JSON file).

        Inside a transaction this is the transaction's copy: changing it
        edits the file.
        """
        return await self._read_content()

    async def write(self, content: object) -> None:
        """Replace the whole content of the file, in a transaction."""
        self._tx_replace(content)

    async def _mapping(self) -> dict:
        return json_object(self, await self.read())

    async def _writable_mapping(self) -> dict:
        return json_object(self, await self._tx_writable())

    async def set(self, key: str, value: object) -> None:
        """Set a key, in a transaction (the file is created if missing)."""
        (await self._writable_mapping())[key] = value

    async def delete(self, key: str) -> None:
        """Delete a key, in a transaction; `KeyError` if it is missing."""
        del (await self._writable_mapping())[key]

    async def update(self, *args: Mapping | Iterable, **kwargs: object) -> None:
        """Set several keys, as `dict.update`, in a transaction."""
        (await self._writable_mapping()).update(*args, **kwargs)

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

    def __setitem__(self, key: str, value: object) -> NoReturn:
        raise _not_awaitable(self, "assignment", "await path.set(key, value)")

    def __delitem__(self, key: str) -> NoReturn:
        raise _not_awaitable(self, "'del'", "await path.delete(key)")

    def __contains__(self, key: object) -> NoReturn:
        raise _not_awaitable(self, "'in'", "await path.has(key)")


class AsyncTSVContentMixin(_AsyncContentMixin):
    """A TSV table, read as rows by coroutines.

    Inside a transaction, the `Table` that `await read()` returns is the
    transaction's copy, as in `TSVContentMixin`.
    """

    __slots__ = ()
    _kind = _content.TSV

    async def read(self, raw: bool = False, root: object = None) -> Table:
        """Read the table as a `Table`: a list of rows, `column -> value`.

        The coroutine counterpart of `BidsPath.read`: values are typed the
        same way, `raw=True` returns their exact text, and `root` is the
        dataset root up to which sidecars describe the columns. Inside a
        transaction this is the transaction's copy.
        """
        if raw:
            return await self._read_raw()
        return await self._read_content(root)

    async def _descriptions(self, root: object = None) -> Mapping | None:
        return await self.read_metadata(root)

    async def _read_raw(self) -> Table:
        tx = active_for(self)
        entry = None if tx is None else tx._buffer.get(self)
        if entry is not None and not entry.absent():
            text = _content.dump_tsv(entry.content)
        else:
            text = await self.read_text(encoding=_ENCODING)
        return _content.parse_tsv(text, raw=True)

    async def write(
        self,
        rows: Iterable[Mapping[str, object]],
        columns: Iterable[str] | None = None,
    ) -> None:
        """Replace the whole table, in a transaction (see `BidsPath.write`)."""
        tx = active_for(self, write=True)
        if tx is None:
            raise _read_only(self, "async ")
        rows = rows if isinstance(rows, Table) else list(rows)
        delimiters = None
        if _content.has_lists(rows) or tx._buffer.get(self) is None:
            delimiters = _content.delimiters(await self._descriptions())
        self._tx_replace(rows, columns, delimiters)

    async def read_dataframe(
        self, root: object = None, **kwargs: object
    ) -> DataFrame:
        """Read the table as a `pandas.DataFrame` (needs pandas).

        The coroutine counterpart of `BidsPath.read_dataframe`, with the
        same column types and `root`.
        """
        entry = await self._tx_entry(create=False, root=root)
        if entry is not None:
            text = _content.dump_tsv(entry.content)
        else:
            text = await self.read_text(encoding=_ENCODING)
        return _content.tsv_dataframe(
            text, kwargs, await self._descriptions(root)
        )

    def __getitem__(self, key: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: use await read() for its rows"
        )

    def __setitem__(self, key: object, value: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: edit the rows of await "
            "read() inside a transaction, or replace them with await write()"
        )

    def __delitem__(self, key: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: edit the rows of await "
            "read() inside a transaction"
        )

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        for row in await self.read():
            yield row
