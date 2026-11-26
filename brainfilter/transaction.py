"""Writes to a BIDS tree: written at once, or kept until a block ends.

A path is read-only unless it is writable (`BidsPath(url, mode="w")`, or
`path.with_mode("w")`). On a writable path, each write to a JSON or TSV
file writes it at once, in one atomic replace:

```python
ds = BidsPath("ds", mode="w")
ds["T1w.json"]["RepetitionTime"] = 2.3       # read, changed, replaced
ds["participants.tsv"]["handedness"] = ["R", "L"]
```

Inside `with path:`, the writes to the files below the path are kept in
memory instead, and written when the block ends:

```python
with ds:                                     # gives the path itself
    ds["T1w.json"]["RepetitionTime"] = 2.3
    del ds["T1w.json"]["Obsolete"]
    ds["participants.tsv"]["age"] = [30, 41]
    (ds / "sub-03")["sub-03_T1w.json"] = {"Level": "new"}  # new file

with ds.transaction() as tx:                 # the same, gives the Transaction
    ...
tx.written                                   # the files it wrote
```

The async family has the same blocks, with `async with`; see
[`AsyncTransaction`][brainfilter.AsyncTransaction].

Inside a block, every write to a covered file is kept, whichever path object
it goes through (one derived from the block's path, one built from a string,
sync or async), and every read of the tree sees them: a file's keys and
values, `as_dict()`, the directory listing (new files included), `sidecars`
and `sidecar`. A read returns a copy: changing it in place is not an edit.
A write that raises leaves the file's content as it was. Leaving the block
with an exception discards everything: nothing is written. Leaving it
cleanly writes each changed file once. A file that was read but not changed
is not written, and in a table that changed, the cells left unchanged keep
their exact text.

A transaction covers the files below its root, in the thread or task that
opened it (and the tasks started inside it), while it is open. A write
through the tree to one of those files from anywhere else raises
`RuntimeError` rather than being lost or written past the transaction:
from another thread (a `threading.Thread` or a `ThreadPoolExecutor` worker
does not share the block's context, so it does not join the transaction),
from a task started outside the block, and, once the block has closed, from
a task that outlived it or during its commit. Transactions on overlapping
trees cannot be nested, nor be open at once in two threads or tasks,
whether sync or async; on disjoint trees they can. A file is known by its
location: two names for one file (`sub-01/../T1w.json` and `T1w.json`, or a
symbolic link and its target on a local disk) share one entry. A file is
read into the transaction when it is first used there, and is not read
again: a change another writer makes meanwhile is overwritten. A file that
did not exist is created only once it is given content. A file with no
sidecar has an empty `sidecar` that cannot be written to: create a sidecar
first.

Writing
-------
Before the first file is written, every changed file is serialized, so a
value that cannot be written (a tab in a TSV cell, say) raises its error
with nothing written. Then the files are written one at a time, in the order
the transaction first used them (read or written), each through bagof-paths'
`staged()`: it is replaced in one step, so a reader sees the old file or the
new one, never a torn one (on POSIX and on object stores). A missing parent
directory is created first.

A set of files is not replaced atomically, on remote stores in particular.
If writing a file fails, the commit **stops there**: the files before it were
written, that file and the ones after it were not, and their edits are
dropped. [`TransactionError`][brainfilter.TransactionError] then says which
is which (`written`, `failed`, `not_written`), and its cause is the error
the write raised (a `bagof.paths.CommitError` when the store refused the
file). Stopping keeps the outcome a prefix of a known order: a file first
used after another is never written ahead of it, and a store that is down
is not tried once per remaining file. Files already written are not rolled
back. The async family writes the files one at a time too, so the report
means the same there.

If the commit is interrupted by an exception that is not an error
(`KeyboardInterrupt`, or the cancellation of an async task), that exception
propagates as itself, with a note (PEP 678, `__notes__`) saying which files
were written and which were not.

A write outside a block raises the error of its one write directly. Two
writes to one file outside a block are made one after the other, so that
neither is lost: through the sync family across the threads of the
process, and through the async family across the tasks of one event loop.
Writes from other processes are not coordinated: the last replace wins.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import os
import threading
from contextvars import ContextVar
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from brainfilter import _content
from brainfilter._family import in_family

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator, Mapping
    from types import TracebackType

    from brainfilter.bidspath import AsyncBidsPath, BidsPath

__all__ = ["AsyncTransaction", "Transaction", "TransactionError"]

# The transactions open in this context (thread or task).
_ACTIVE: ContextVar[tuple[_TransactionBase, ...]] = ContextVar(
    "brainfilter_transactions", default=()
)

# Every transaction open (or committing) in the process, whatever context
# opened it, guarded by `_REGISTRY_LOCK`: a write from another context to a
# file one of them covers is refused rather than written past it.
_REGISTRY_LOCK = threading.Lock()
_REGISTRY: list[_TransactionBase] = []


def active_for(
    path: object, *, write: bool = False
) -> _TransactionBase | None:
    """Return the open transaction that covers `path`, or `None`.

    A transaction that has closed (or is committing) is not active, but a
    task started inside it still sees it: with `write`, such a transaction
    raises `RuntimeError`, since a write through it would be lost. With
    `write`, a transaction that covers `path` but was opened in another
    context (a thread, or a task not started inside its block) raises
    `RuntimeError` too: the write would go past it.
    """
    own = _ACTIVE.get()
    closed = None
    for tx in own:
        if tx.covers(path):
            if tx._state == _OPEN:
                return tx
            closed = closed or tx
    if write:
        if closed is not None:
            raise closed._closed_error(path)
        elsewhere = _open_elsewhere(path, own)
        if elsewhere is not None:
            raise elsewhere._elsewhere_error(path)
    return None


def _open_elsewhere(
    path: object, own: tuple[_TransactionBase, ...]
) -> _TransactionBase | None:
    """Return a transaction covering `path` that this context is not in."""
    with _REGISTRY_LOCK:
        others = [tx for tx in _REGISTRY if not any(tx is t for t in own)]
    if not others:
        return None
    location = _location(path)
    for tx in others:
        if _within(location, tx._location):
            return tx
    return None


def pending_names(directory: object) -> set[str]:
    """Names of the children of `directory` that an open transaction holds.

    A new file, or a new directory above one, is listed this way before it
    is written.
    """
    names: set[str] = set()
    for tx in _ACTIVE.get():
        if tx._state == _OPEN:
            names |= tx._buffer.names_in(directory)
    return names


def entered(root: object) -> _TransactionBase:
    """Return the open transaction that `with root:` opened in this context."""
    for tx in reversed(_ACTIVE.get()):
        if tx._root is root and tx._state == _OPEN:
            return tx
    raise RuntimeError(
        f"no transaction was opened by `with` on {str(root)!r} here"
    )


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


# -- one write at a time per file ---------------------------------------------------

class _Slot:
    """A lock, and how many writes hold it or wait for it."""

    __slots__ = ("lock", "users")

    def __init__(self, lock: object) -> None:
        self.lock = lock
        self.users = 0


# `location -> slot` for the sync family, and `loop -> {location -> slot}`
# for the async one (an `asyncio.Lock` belongs to one event loop). A slot
# is dropped when its last user lets it go (a cancelled wait included), and
# a loop's table with its last slot, so neither holds a file or a loop that
# no write is using. Both are changed under `_LOCKS_LOCK`.
_LOCKS_LOCK = threading.Lock()
_LOCKS: dict[object, _Slot] = {}
_ALOCKS: dict[asyncio.AbstractEventLoop, dict[object, _Slot]] = {}


def _take(table: dict[object, _Slot], location: object,
          new: Callable[[], object]) -> _Slot:
    slot = table.get(location)
    if slot is None:
        slot = table[location] = _Slot(new())
    slot.users += 1
    return slot


def _let_go(table: dict[object, _Slot], location: object, slot: _Slot) -> None:
    slot.users -= 1
    if not slot.users:
        del table[location]


@contextlib.contextmanager
def file_lock(path: object) -> Iterator[None]:
    """Hold the lock on the file at `path` (by location) for a block.

    One write through at a time per file, across the threads of the
    process: a read, change and replace of the file is not interleaved with
    another of the same file.
    """
    location = _location(path)
    with _LOCKS_LOCK:
        slot = _take(_LOCKS, location, threading.Lock)
    try:
        with slot.lock:  # type: ignore[attr-defined]
            yield
    finally:
        with _LOCKS_LOCK:
            _let_go(_LOCKS, location, slot)


@contextlib.asynccontextmanager
async def afile_lock(path: object) -> AsyncIterator[None]:
    """Hold the lock on the file at `path` for a block, in this event loop.

    The async counterpart of `file_lock`: one write through at a time per
    file, across the tasks of the running event loop.
    """
    location = _location(path)
    loop = asyncio.get_running_loop()
    with _LOCKS_LOCK:
        table = _ALOCKS.get(loop)
        if table is None:
            table = _ALOCKS[loop] = {}
        slot = _take(table, location, asyncio.Lock)
    try:
        async with slot.lock:  # type: ignore[attr-defined]
            yield
    finally:
        with _LOCKS_LOCK:
            _let_go(table, location, slot)
            if not table:
                _ALOCKS.pop(loop, None)


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

    def replace(self, content: object) -> None:
        """Hold `content` as the whole new content of the file."""
        self.content = content
        if self.missing:
            # A new file that is written, even empty.
            self.original = None

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

        The content is put back in place, as the same object.
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

    def __init__(self, root: object) -> None:
        self._root = root
        # The family the files are written through, whatever path held them.
        self._family = getattr(type(root), "_root", type(root))
        self._buffer = _Buffer()
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
        """Whether `path` is the root or below it, sync or async alike.

        `..` is collapsed, and a local path resolved, before comparing.
        """
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
        with _REGISTRY_LOCK:
            for other in _REGISTRY:
                if self._overlaps(other):
                    raise RuntimeError(
                        f"a transaction on {str(other._root)!r} is already "
                        f"{_doing(other)} in another thread or task; "
                        "transactions on the same files cannot be open at "
                        "once: open this one after it ends"
                    )
            _REGISTRY.append(self)
        _ACTIVE.set((*active, self))
        self._state = _OPEN

    def _close(self) -> None:
        _ACTIVE.set(tuple(t for t in _ACTIVE.get() if t is not self))
        self._state = _COMMITTING

    def _finish(self) -> None:
        """Drop the held files, and let other contexts write the files."""
        self._buffer.clear()
        self._state = _DONE
        with _REGISTRY_LOCK:
            _REGISTRY[:] = [t for t in _REGISTRY if t is not self]

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

    def _elsewhere_error(self, path: object) -> RuntimeError:
        if self._state == _COMMITTING:
            return self._closed_error(path)
        return RuntimeError(
            f"cannot edit {str(path)!r}: a transaction on "
            f"{str(self._root)!r} is open in another thread or task, and "
            "this write would go past it (it would be written now, whatever "
            "the transaction does, and its commit could overwrite it); make "
            "the edit inside the transaction's block (a task started there "
            "shares it, a thread does not), or after it ends"
        )

    def _target(self, path: object) -> Any:  # noqa: ANN401
        """Return the path to write `path` through: of this family, writable.

        A file may have been held through a path of the other family, or a
        read-only one; the transaction was opened on a writable path.
        """
        return in_family(path, self._family).with_mode("w")

    def _failed(
        self, plan: list, index: int, error: Exception
    ) -> TransactionError:
        return TransactionError(
            self._root,
            [path for path, _ in plan[:index]],
            [path for path, _ in plan[index:]],
            error,
        )

    def _interrupted(self, plan: list, index: int, error: BaseException) -> None:
        """Note on `error` which files were written before it interrupted."""
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


def _doing(tx: _TransactionBase) -> str:
    return "being committed" if tx._state == _COMMITTING else "open"


def write_file(path: BidsPath, data: bytes) -> None:
    """Replace the file at `path` with `data`, in one step."""
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    with path.staged() as staged:
        staged.write_bytes(data)


async def awrite_file(path: AsyncBidsPath, data: bytes) -> None:
    """Replace the file at `path` with `data`, in one step (a coroutine)."""
    parent = path.parent
    if not await parent.exists():
        await parent.mkdir(parents=True, exist_ok=True)
    async with path.staged() as staged:
        await staged.write_bytes(data)


class Transaction(_TransactionBase):
    """The writes to the JSON and TSV files below a path, kept until it ends.

    Returned by `path.transaction()`, and opened by `with path:`; use it as
    a context manager. Every write to a file below its root is kept until
    the block ends, and every read of the tree sees it. On a clean exit,
    each changed file is written once, in one step; on an exception,
    nothing is written. If a write fails, the commit stops there and raises
    [`TransactionError`][brainfilter.TransactionError].

    ```python
    with ds.transaction() as tx:
        ds["T1w.json"]["RepetitionTime"] = 2.3
    tx.written       # the files the commit wrote, in order
    ```
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
            self._finish()

    def _commit(self) -> None:
        plan = self._buffer.plan()
        for index, (path, data) in enumerate(plan):
            try:
                write_file(self._target(path), data)
            except Exception as error:
                raise self._failed(plan, index, error) from error
            except BaseException as error:
                self._interrupted(plan, index, error)
                raise
            self._written.append(path)


class AsyncTransaction(_TransactionBase):
    """The async counterpart of `Transaction`, used with `async with`.

    Returned by `AsyncBidsPath.transaction()`, and opened by
    `async with path:`. Reads inside it are awaited as usual and see the
    kept writes; the files are written one at a time, as in `Transaction`.

    ```python
    async with dataset:
        sidecar = dataset / "T1w.json"
        await sidecar.set("RepetitionTime", 2.3)
        await sidecar.delete("Obsolete")
        await (dataset / "participants.tsv").set("age", [30, 41])
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
            self._finish()

    async def _commit(self) -> None:
        plan = self._buffer.plan()
        for index, (path, data) in enumerate(plan):
            try:
                await awrite_file(self._target(path), data)
            except Exception as error:
                raise self._failed(plan, index, error) from error
            except BaseException as error:
                # Cancelled, or interrupted: propagate as itself.
                self._interrupted(plan, index, error)
                raise
            self._written.append(path)
