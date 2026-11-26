"""Explicit write transactions on a BIDS tree.

The dataset tree is read-only, except inside one of two blocks:

```python
with dataset.transaction() as tx:          # many files
    dataset["T1w.json"]["RepetitionTime"] = 2.3
    del dataset["T1w.json"]["Obsolete"]
    rows = dataset["participants.tsv"].read()
    rows.append({"participant_id": "sub-03", "age": 41})
    rows.add_column("handedness")
    (dataset / "sub-03")["sub-03_T1w.json"] = {"Level": "new"}  # new file

with sidecar.edit() as content:            # one file
    content["RepetitionTime"] = 2.3
```

The async family has the same blocks, with `async with`; see
[`AsyncTransaction`][brainfilter.transaction.AsyncTransaction].

Inside a block, edits to JSON and TSV files are kept in memory, and every
read of the tree sees them: a file's `read()`, its keys, the directory
listing (new files included), `sidecars()` and `metadata`. The content a read
returns *is* the transaction's copy, so changing it in place is an edit, and
a write to `metadata` lands in the nearest sidecar. Leaving the block with an
exception discards everything: nothing is written. Leaving it cleanly writes
each changed file once. A file that was read but not changed is not written,
and in a table that changed, the cells left unchanged keep their exact text.
Nothing is ever written outside these blocks: assigning into the tree outside
one raises `TypeError`.

A transaction covers the files below its root, in the thread or task that
opened it (and the tasks started inside it), while it is open. A write
through the tree once it has closed (from a task that outlived the block,
say, or during its commit) raises `RuntimeError` rather than being lost.
Transactions on overlapping trees cannot be nested, whether sync or async;
on disjoint trees they can. A file is known by its location: two names for
one file (`sub-01/../T1w.json` and `T1w.json`, or a symbolic link and its
target on a local disk) share one entry. A file is read into the transaction
when it is first used there, and is not read again: a change another writer
makes meanwhile is overwritten. A file with no sidecar has an empty
`metadata` that cannot be written to: create a sidecar first.

Writing
-------
Before the first file is written, every changed file is serialized, so a
value that cannot be written (not JSON-serializable, say) raises its error
with nothing written. Then the files are written one at a time, in the order
the transaction first used them (read or written), each through bagof-paths'
`staged()`: it is replaced in one step, so a reader sees the old file or the
new one, never a torn one (on POSIX and on object stores). A missing parent
directory is created first.

A set of files is not replaced atomically, on remote stores in particular.
If writing a file fails, the commit **stops there**: the files before it were
written, that file and the ones after it were not, and their edits are
dropped. [`TransactionError`][brainfilter.transaction.TransactionError] then
says which is which (`written`, `failed`, `not_written`), and its cause is
the error the write raised (a `bagof.paths.CommitError` when the store
refused the file). Stopping keeps the outcome a prefix of a known order: a
file first used after another is never written ahead of it, and a store that
is down is not tried once per remaining file. Files already written are not
rolled back. The async family writes the files one at a time too, so the
report means the same there.

If the commit is interrupted by an exception that is not an error
(`KeyboardInterrupt`, or the cancellation of an async task), that exception
propagates as itself, with a note (PEP 678, `__notes__`) saying which files
were written and which were not.

A single-file `edit()` raises the error of its one write directly. Inside a
transaction that covers the file, `edit()` joins it: the file is written
when the transaction commits, and an exception leaving the `edit()` block
puts the file back as it was when the block was entered.
"""
from __future__ import annotations

import copy
import os
from contextvars import ContextVar
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from brainfilter import _content

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import TracebackType

    from brainfilter._content import Table
    from brainfilter.bidspath import AsyncBidsPath, BidsPath

__all__ = ["AsyncEdit", "AsyncTransaction", "Edit", "Transaction",
           "TransactionError"]

# The transactions open in this context (thread or task).
_ACTIVE: ContextVar[tuple[_TransactionBase, ...]] = ContextVar(
    "brainfilter_transactions", default=()
)


def active_for(
    path: object, *, write: bool = False
) -> _TransactionBase | None:
    """Return the open transaction that covers `path`, or `None`.

    A transaction that has closed (or is committing) is not active, but a
    task started inside it still sees it: with `write`, such a transaction
    raises `RuntimeError`, since a write through it would be lost.
    """
    closed = None
    for tx in _ACTIVE.get():
        if tx.covers(path):
            if tx._state == _OPEN:
                return tx
            closed = closed or tx
    if write and closed is not None:
        raise closed._closed_error(path)
    return None


def pending_names(directory: object) -> set[str]:
    """Names of the children of `directory` that an open transaction holds.

    A new file, or a new directory above one, is listed this way before it
    is written.
    """
    names: set[str] = set()
    for tx in _ACTIVE.get():
        if tx._state == _OPEN and isinstance(directory, tx._family):
            names |= tx._buffer.names_in(directory)
    return names


# -- locations (pure, apart from resolving local symbolic links) -------------------

def _lexical(path: Any) -> Any:  # noqa: ANN401
    """Return `path` with its `.` and `..` parts collapsed, lexically.

    A `..` above the anchor is dropped, as POSIX does at `/`. The path is
    returned as it is when it has neither.
    """
    names = []
    anchor = path
    while anchor.name and anchor.parent != anchor:
        names.append(anchor.name)
        anchor = anchor.parent
    if "." not in names and ".." not in names:
        return path
    kept: list[str] = []
    for name in reversed(names):
        if name == "..":
            if kept:
                kept.pop()
        elif name != ".":
            kept.append(name)
    for name in kept:
        anchor = anchor / name
    return anchor


def _location(path: Any) -> tuple[str, Any]:  # noqa: ANN401
    """Return where `path` is, the same for every name of one file.

    A local path is resolved (symbolic links and `..`, as the system does);
    a remote one is collapsed lexically. Paths of the sync and the async
    family at one place have the same location.
    """
    if path.is_local():
        return "local", PurePath(os.path.realpath(os.fspath(path)))
    return "remote", _lexical(path)


def _within(location: tuple[str, Any], top: tuple[str, Any]) -> bool:
    """Whether `location` is `top` or below it."""
    if location[0] != top[0]:
        return False
    return location[1] == top[1] or top[1] in location[1].parents


def _write_path(path: Any, location: tuple[str, Any]) -> Any:  # noqa: ANN401
    """Return the path to write the file at `location`, named as `path` is.

    Its `.` and `..` parts are collapsed, unless (locally) a symbolic link
    makes the collapsed path another file.
    """
    clean = _lexical(path)
    if clean is path or location[0] == "remote":
        return clean
    return clean if _location(clean) == location else path


# -- the buffer (pure) ------------------------------------------------------------

class _Entry:
    """One file held by a transaction."""

    __slots__ = ("content", "kind", "missing", "original", "path")

    def __init__(
        self,
        path: object,
        kind: str,
        content: object,
        original: str | None,
        missing: bool = False,
    ) -> None:
        self.path = path
        self.kind = kind
        self.content = content
        # The text the file would be written with if unchanged, or `None`
        # when it must be written (a file replaced, read or not).
        self.original = original
        # Whether the file did not exist when it was first used: it is
        # created only if its content is set or replaced.
        self.missing = missing

    def text(self) -> str | None:
        """Return the text to write, or `None` if the file is unchanged."""
        text = _content.dump(self.kind, self.content)
        return None if text == self.original else text

    def absent(self) -> bool:
        """Whether the file does not exist, and would not be created."""
        if not self.missing:
            return False
        try:
            return self.text() is None
        except Exception:
            # Content that cannot be written is not the empty content.
            return False

    def snapshot(self) -> Callable[[], None]:
        """Return a function that puts this entry back as it is now.

        The content is put back in place, so an object a caller holds (the
        `dict` or `Table` a read returned) is the entry's content again.
        """
        content, original, missing = self.content, self.original, self.missing
        restore_content = None
        if isinstance(content, _content.Table):
            restore_content = content._snapshot()
        elif isinstance(content, (dict, list)):
            saved = copy.deepcopy(content)

            def restore_content() -> None:
                if isinstance(content, dict):
                    content.clear()
                    content.update(saved)
                else:
                    content[:] = saved
        # Any other JSON value (a string, a number) cannot be changed in
        # place: holding it again is enough.

        def restore() -> None:
            if restore_content is not None:
                restore_content()
            self.content = content
            self.original = original
            self.missing = missing

        return restore


class _Buffer:
    """The files a transaction holds, in the order it first used them."""

    def __init__(self) -> None:
        # `location -> entry`: two names for one file share an entry.
        self._entries: dict[object, _Entry] = {}

    def get(self, path: object) -> _Entry | None:
        return self._entries.get(_location(path))

    def source(self, path: object) -> Any:  # noqa: ANN401
        """Return the name the file at `path` is read and written by."""
        return _write_path(path, _location(path))

    def load(
        self,
        path: object,
        kind: str,
        text: str | None,
        descriptions: Mapping | None = None,
    ) -> _Entry:
        """Hold the file at `path`, read as `text` (`None`: no file yet).

        `descriptions` types the columns of a TSV file. If the file is
        already held (another task read it meanwhile), that entry is kept
        and returned.
        """
        location = _location(path)
        entry = self._entries.get(location)
        if entry is None:
            content = _content.parse(kind, text, descriptions)
            original = _content.dump(kind, content)
            entry = self._entries[location] = _Entry(
                _write_path(path, location), kind, content, original,
                missing=text is None,
            )
        return entry

    def replace(self, path: object, kind: str, content: object) -> None:
        """Hold `content` as the whole new content of `path`."""
        location = _location(path)
        entry = self._entries.get(location)
        if entry is None:
            self._entries[location] = _Entry(
                _write_path(path, location), kind, content, None
            )
        else:
            entry.content = content
            if entry.missing:
                # A new file that is written, even empty.
                entry.original = None

    def names_in(self, directory: object) -> set[str]:
        """Names, directly in `directory`, of held files or their parents."""
        kind, top = _location(directory)
        names = set()
        for (entry_kind, location), entry in self._entries.items():
            if entry_kind != kind or entry.absent():
                continue
            child = location
            for parent in location.parents:
                if parent == top:
                    names.add(child.name)
                    break
                child = parent
        return names

    def plan(self) -> list[tuple[Any, bytes]]:
        """`(path, data)` of each changed file, in order: nothing is written.

        Every file is serialized here, so a content error raises before the
        first write.
        """
        plan = []
        for entry in self._entries.values():
            text = entry.text()
            if text is not None:
                plan.append((entry.path, text.encode("utf-8")))
        return plan

    def clear(self) -> None:
        self._entries.clear()


# -- errors ---------------------------------------------------------------------

class TransactionError(OSError):
    """Writing the files of a transaction failed partway.

    The files are written one at a time, and the commit stops at the first
    failure. Files already written are not rolled back.

    Attributes
    ----------
    root
        The root of the transaction.
    written : list
        The files that were written, in order.
    failed
        The file whose write failed.
    not_written : list
        The files that were not written: `failed` and every file after it.
    error
        The error the write raised, also chained as `__cause__`: a
        `bagof.paths.CommitError` when the store refused the file.
    """

    def __init__(
        self,
        root: object,
        written: list,
        not_written: list,
        error: BaseException,
    ) -> None:
        self.root = root
        self.written = list(written)
        self.not_written = list(not_written)
        self.failed = self.not_written[0]
        self.error = error
        super().__init__(
            f"the transaction on {str(root)!r} failed writing "
            f"{str(self.failed)!r} ({error}); "
            + _report(self.written, self.not_written)
        )
        self.errno = getattr(error, "errno", None)


def _report(written: list, not_written: list) -> str:
    names = ", ".join(repr(str(p)) for p in written) or "none"
    rest = ", ".join(repr(str(p)) for p in not_written)
    return f"written: {names}; not written: {rest}"


def _add_note(error: BaseException, note: str) -> None:
    """Add a PEP 678 note to `error` (by hand before Python 3.11)."""
    if hasattr(error, "add_note"):
        error.add_note(note)
    else:  # pragma: no cover - Python 3.10
        error.__notes__ = [*getattr(error, "__notes__", ()), note]


# -- transactions ------------------------------------------------------------------

_NEW, _OPEN, _COMMITTING, _DONE = "new", "open", "committing", "done"


class _TransactionBase:
    """What the sync and async transactions share: everything but I/O."""

    def __init__(self, root: object, *, _single: bool = False) -> None:
        self._root = root
        # Paths of this family only: a sync transaction is not seen by an
        # async path at the same place, nor the reverse.
        self._family = getattr(type(root), "_root", type(root))
        self._buffer = _Buffer()
        self._single = _single
        self._state = _NEW
        self._written: list = []
        self._location = _location(root)

    @property
    def root(self) -> object:
        """The path whose files this transaction covers (itself included)."""
        return self._root

    @property
    def written(self) -> list:
        """The files written when the transaction committed, in order."""
        return list(self._written)

    @property
    def changed(self) -> list:
        """The files that committing now would write, in order."""
        return [path for path, _ in self._buffer.plan()]

    def covers(self, path: object) -> bool:
        """Whether `path` is the root or below it, in the same family.

        `..` is collapsed, and a local path resolved, before comparing.
        """
        if not isinstance(path, self._family):
            return False
        return _within(_location(path), self._location)

    def _overlaps(self, other: _TransactionBase) -> bool:
        """Whether the two transactions cover a file in common (any family)."""
        return _within(self._location, other._location) or _within(
            other._location, self._location
        )

    def _open(self) -> None:
        if self._state != _NEW:
            raise RuntimeError(
                "a transaction can be entered once; start a new one"
            )
        # A transaction that has closed is still listed in the tasks that
        # were started inside it; it no longer counts.
        active = tuple(t for t in _ACTIVE.get() if t._state == _OPEN)
        for other in active:
            if self._overlaps(other):
                raise RuntimeError(
                    f"a transaction on {str(other._root)!r} is already open; "
                    "transactions on the same files cannot be nested, "
                    "whether sync or async"
                )
        _ACTIVE.set((*active, self))
        self._state = _OPEN

    def _close(self) -> None:
        _ACTIVE.set(tuple(t for t in _ACTIVE.get() if t is not self))
        self._state = _COMMITTING

    def _closed_error(self, path: object) -> RuntimeError:
        when = (
            "is being committed" if self._state == _COMMITTING
            else "has already closed"
        )
        return RuntimeError(
            f"cannot edit {str(path)!r}: the transaction on "
            f"{str(self._root)!r} {when}, so the edit would be lost; make "
            "every edit inside the transaction's block (await the tasks "
            "that make them before it ends)"
        )

    def _failed(
        self, plan: list, index: int, error: Exception
    ) -> Exception:
        if self._single:
            return error
        return TransactionError(
            self._root,
            [path for path, _ in plan[:index]],
            [path for path, _ in plan[index:]],
            error,
        )

    def _interrupted(self, plan: list, index: int, error: BaseException) -> None:
        """Note on `error` which files were written before it interrupted."""
        if self._single:
            return
        current = str(plan[index][0])
        _add_note(error, (
            f"the transaction on {str(self._root)!r} was interrupted "
            f"writing {current!r}; "
            + _report(
                [path for path, _ in plan[:index]],
                [path for path, _ in plan[index:]],
            )
            + f" ({current!r} is either the old file or the new one)"
        ))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self._root)!r})"


def _write_file(path: BidsPath, data: bytes) -> None:
    """Replace the file at `path` with `data`, in one step."""
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    with path.staged() as staged:
        staged.write_bytes(data)


async def _awrite_file(path: AsyncBidsPath, data: bytes) -> None:
    parent = path.parent
    if not await parent.exists():
        await parent.mkdir(parents=True, exist_ok=True)
    async with path.staged() as staged:
        await staged.write_bytes(data)


class Transaction(_TransactionBase):
    """Edits to the JSON and TSV files below a path, written on success.

    Returned by `BidsPath.transaction()`; use it as a context manager. See
    the module documentation for what is buffered and how it is written.
    """

    def __enter__(self) -> Transaction:
        self._open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._close()
        try:
            if exc_type is None:
                self._commit()
        finally:
            self._buffer.clear()
            self._state = _DONE

    def _commit(self) -> None:
        plan = self._buffer.plan()
        for index, (path, data) in enumerate(plan):
            try:
                _write_file(path, data)
            except Exception as error:
                raise self._failed(plan, index, error) from error
            except BaseException as error:
                self._interrupted(plan, index, error)
                raise
            self._written.append(path)


class AsyncTransaction(_TransactionBase):
    """The async counterpart of `Transaction`, used with `async with`.

    Returned by `AsyncBidsPath.transaction()`. Reads inside it are awaited
    as usual and see the buffered edits; the files are written one at a
    time, as in `Transaction`.

    ```python
    async with dataset.transaction():
        sidecar = dataset / "T1w.json"
        await sidecar.set("RepetitionTime", 2.3)
        await sidecar.delete("Obsolete")
        rows = await (dataset / "participants.tsv").read()
        rows.append({"participant_id": "sub-03"})
    ```
    """

    async def __aenter__(self) -> AsyncTransaction:
        self._open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._close()
        try:
            if exc_type is None:
                await self._commit()
        finally:
            self._buffer.clear()
            self._state = _DONE

    async def _commit(self) -> None:
        plan = self._buffer.plan()
        for index, (path, data) in enumerate(plan):
            try:
                await _awrite_file(path, data)
            except Exception as error:
                raise self._failed(plan, index, error) from error
            except BaseException as error:
                # Cancelled, or interrupted: propagate as itself.
                self._interrupted(plan, index, error)
                raise
            self._written.append(path)


# -- single files -------------------------------------------------------------------

class Edit:
    """Edit one JSON or TSV file; returned by `path.edit()`.

    `with sidecar.edit() as content:` gives the content (a `dict`, or a
    `Table` for a TSV file; empty for a file that does not exist yet), to
    change in place. On a clean exit the file is replaced in one step; on
    an exception it is left as it was. Inside a transaction that covers the
    file, the edit joins it and the file is written when it commits; an
    exception leaving the edit puts the transaction's copy of the file back
    as it was when the edit began.
    """

    def __init__(self, path: BidsPath) -> None:
        self._path = path
        self._tx: Transaction | None = None
        # Puts the joined transaction's entry back, on an exception.
        self._restore: Callable[[], None] | None = None

    def __enter__(self) -> dict | Table:
        joined = active_for(self._path, write=True)
        if joined is None:
            self._tx = Transaction(self._path, _single=True)
            self._tx.__enter__()
        try:
            content = self._path._tx_writable()
        except BaseException as error:
            self._leave(type(error), error, error.__traceback__)
            raise
        if joined is not None:
            self._restore = joined._buffer.get(self._path).snapshot()
        return content

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._leave(exc_type, exc, tb)

    def _leave(self, *exc: object) -> None:
        tx, self._tx = self._tx, None
        restore, self._restore = self._restore, None
        if restore is not None and exc[0] is not None:
            restore()
        if tx is not None:
            tx.__exit__(*exc)


class AsyncEdit:
    """The async counterpart of `Edit`, used with `async with`."""

    def __init__(self, path: AsyncBidsPath) -> None:
        self._path = path
        self._tx: AsyncTransaction | None = None
        self._restore: Callable[[], None] | None = None

    async def __aenter__(self) -> dict | Table:
        joined = active_for(self._path, write=True)
        if joined is None:
            self._tx = AsyncTransaction(self._path, _single=True)
            await self._tx.__aenter__()
        try:
            content = await self._path._tx_writable()
        except BaseException as error:
            await self._leave(type(error), error, error.__traceback__)
            raise
        if joined is not None:
            self._restore = joined._buffer.get(self._path).snapshot()
        return content

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._leave(exc_type, exc, tb)

    async def _leave(self, *exc: object) -> None:
        tx, self._tx = self._tx, None
        restore, self._restore = self._restore, None
        if restore is not None and exc[0] is not None:
            restore()
        if tx is not None:
            await tx.__aexit__(*exc)
