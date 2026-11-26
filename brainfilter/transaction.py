"""Explicit write transactions on a BIDS tree.

The dataset tree is read-only, except inside one of two blocks:

```python
with dataset.transaction() as tx:          # many files
    dataset["T1w.json"]["RepetitionTime"] = 2.3
    del dataset["T1w.json"]["Obsolete"]
    rows = dataset["participants.tsv"].read()
    rows.append({"participant_id": "sub-03", "age": "41"})
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
each changed file once. A file that was read but not changed is not written.
Nothing is ever written outside these blocks: assigning into the tree outside
one raises `TypeError`.

A transaction covers the files below its root, in the thread or task that
opened it (and the tasks started inside it). Transactions on overlapping
trees cannot be nested; on disjoint trees they can. A file is read into the
transaction when it is first used there, and is not read again: a change
another writer makes meanwhile is overwritten. A file with no sidecar has an
empty `metadata`, which belongs to no file: a write to it is lost.

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

A single-file `edit()` raises the error of its one write directly. Inside a
transaction that covers the file, `edit()` joins it: the file is written
when the transaction commits.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from brainfilter import _content

if TYPE_CHECKING:
    from types import TracebackType

    from brainfilter._content import Table
    from brainfilter.bidspath import AsyncBidsPath, BidsPath

__all__ = ["AsyncEdit", "AsyncTransaction", "Edit", "Transaction",
           "TransactionError"]

# The transactions open in this context (thread or task).
_ACTIVE: ContextVar[tuple[_TransactionBase, ...]] = ContextVar(
    "brainfilter_transactions", default=()
)


def active_for(path: object) -> _TransactionBase | None:
    """Return the open transaction that covers `path`, or `None`."""
    for tx in _ACTIVE.get():
        if tx.covers(path):
            return tx
    return None


def pending_names(directory: object) -> set[str]:
    """Names of the children of `directory` that an open transaction holds.

    A new file, or a new directory above one, is listed this way before it
    is written.
    """
    names: set[str] = set()
    for tx in _ACTIVE.get():
        if isinstance(directory, tx._family):
            names |= tx._buffer.names_in(directory)
    return names


# -- the buffer (pure) ------------------------------------------------------------

class _Entry:
    """One file held by a transaction."""

    __slots__ = ("content", "kind", "original", "path")

    def __init__(
        self, path: object, kind: str, content: object, original: str | None
    ) -> None:
        self.path = path
        self.kind = kind
        self.content = content
        # The text the file would be written with if unchanged, or `None`
        # when it must be written (a new file, or one replaced unread).
        self.original = original

    def text(self) -> str | None:
        """Return the text to write, or `None` if the file is unchanged."""
        text = _content.dump(self.kind, self.content)
        return None if text == self.original else text


class _Buffer:
    """The files a transaction holds, in the order it first used them."""

    def __init__(self) -> None:
        self._entries: dict[object, _Entry] = {}

    def get(self, path: object) -> _Entry | None:
        return self._entries.get(path)

    def load(self, path: object, kind: str, text: str | None) -> _Entry:
        """Hold the file at `path`, read as `text` (`None`: no file yet).

        If it is already held (another task read it meanwhile), that entry
        is kept and returned.
        """
        entry = self._entries.get(path)
        if entry is None:
            content = _content.parse(kind, text)
            original = None if text is None else _content.dump(kind, content)
            entry = self._entries[path] = _Entry(path, kind, content, original)
        return entry

    def replace(self, path: object, kind: str, content: object) -> None:
        """Hold `content` as the whole new content of `path`."""
        entry = self._entries.get(path)
        if entry is None:
            self._entries[path] = _Entry(path, kind, content, None)
        else:
            entry.content = content

    def names_in(self, directory: object) -> set[str]:
        """Names, directly in `directory`, of held files or their parents."""
        names = set()
        for path in self._entries:
            child = path
            for parent in path.parents:
                if parent == directory:
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
        names = ", ".join(repr(str(p)) for p in self.written) or "none"
        rest = ", ".join(repr(str(p)) for p in self.not_written)
        super().__init__(
            f"the transaction on {str(root)!r} failed writing "
            f"{str(self.failed)!r} ({error}); written: {names}; "
            f"not written: {rest}"
        )
        self.errno = getattr(error, "errno", None)


# -- transactions ------------------------------------------------------------------

_NEW, _OPEN, _DONE = "new", "open", "done"


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
        """Whether `path` is the root or below it, in the same family."""
        if not isinstance(path, self._family):
            return False
        return path == self._root or self._root in path.parents

    def _open(self) -> None:
        if self._state != _NEW:
            raise RuntimeError(
                "a transaction can be entered once; start a new one"
            )
        active = _ACTIVE.get()
        for other in active:
            if other.covers(self._root) or self.covers(other._root):
                raise RuntimeError(
                    f"a transaction on {str(other._root)!r} is already open; "
                    "transactions on the same files cannot be nested"
                )
        _ACTIVE.set((*active, self))
        self._state = _OPEN

    def _close(self) -> None:
        _ACTIVE.set(tuple(t for t in _ACTIVE.get() if t is not self))
        self._state = _DONE

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

    def _commit(self) -> None:
        plan = self._buffer.plan()
        for index, (path, data) in enumerate(plan):
            try:
                _write_file(path, data)
            except Exception as error:
                raise self._failed(plan, index, error) from error
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

    async def _commit(self) -> None:
        plan = self._buffer.plan()
        for index, (path, data) in enumerate(plan):
            try:
                await _awrite_file(path, data)
            except Exception as error:
                raise self._failed(plan, index, error) from error
            self._written.append(path)


# -- single files -------------------------------------------------------------------

class Edit:
    """Edit one JSON or TSV file; returned by `path.edit()`.

    `with sidecar.edit() as content:` gives the content (a `dict`, or a
    `Table` for a TSV file; empty for a file that does not exist yet), to
    change in place. On a clean exit the file is replaced in one step; on
    an exception it is left as it was. Inside a transaction that covers the
    file, the edit joins it and the file is written when it commits.
    """

    def __init__(self, path: BidsPath) -> None:
        self._path = path
        self._tx: Transaction | None = None

    def __enter__(self) -> dict | Table:
        if active_for(self._path) is None:
            self._tx = Transaction(self._path, _single=True)
            self._tx.__enter__()
        try:
            return self._path._tx_writable()
        except BaseException as error:
            self._leave(type(error), error, error.__traceback__)
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._leave(exc_type, exc, tb)

    def _leave(self, *exc: object) -> None:
        tx, self._tx = self._tx, None
        if tx is not None:
            tx.__exit__(*exc)


class AsyncEdit:
    """The async counterpart of `Edit`, used with `async with`."""

    def __init__(self, path: AsyncBidsPath) -> None:
        self._path = path
        self._tx: AsyncTransaction | None = None

    async def __aenter__(self) -> dict | Table:
        if active_for(self._path) is None:
            self._tx = AsyncTransaction(self._path, _single=True)
            await self._tx.__aenter__()
        try:
            return await self._path._tx_writable()
        except BaseException as error:
            await self._leave(type(error), error, error.__traceback__)
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._leave(exc_type, exc, tb)

    async def _leave(self, *exc: object) -> None:
        tx, self._tx = self._tx, None
        if tx is not None:
            await tx.__aexit__(*exc)
