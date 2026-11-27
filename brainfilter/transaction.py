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
and `sidecar`. A write that raises leaves the file's content as it was.
Leaving the block with an exception discards everything: nothing is
written. Leaving it cleanly writes each changed file once. A file that was
read but not changed is not written, and in a table that changed, the cells
left unchanged keep their exact text.

Inside a block, on a writable path, `sidecar[key]` (`await sidecar.get(key)`
in the async family) returns the transaction's own value, and
`table[column]` (`await table.get(column)`) a live column of its own table
(a `list` whose values are the table's), so a nested value changed in place
is an edit too:

```python
with ds:
    ds["T1w.json"]["Extra"]["Coil"] = "neck"     # saved on exit
    ds["T1w.json"]["Notes"].append("checked")
    ds["participants.tsv"]["age"][0] = 31        # the other cells keep their text
```

Every other read returns a copy, inside a block too: `as_dict()`,
`as_list()`, `rows()`, `values()`, `items()`, `as_dataframe()`, and the
merged `sidecar`. A value written through a file (`path[key] = value`,
`update()`, `write()`, a column set) is copied, so the caller's object is
never the file's. A value stored into a live value is not copied
(`ds["b.json"]["Y"]["s"] = ds["a.json"]["X"]` makes the two files share
one object, and a later change to it is written to both): copy it first
to keep them apart. Outside a block, every read is a copy. A read-only path
is given copies inside a block as well. Once the block has ended, a live
column raises `RuntimeError` when it is used, and a live JSON value is a
plain object that no longer belongs to the file.

Inside a block, a raw write through a path to a file the block covers would
be overwritten by the commit, or would mix with its edits, so it is refused
with `RuntimeError`: `write_text`, `write_bytes`, `open` for writing,
`touch`, `unlink`, `rename` and `replace` (either side), and every other
member that a read-only path refuses, to a JSON or TSV file below the root,
whether the transaction has read it yet or not, and to a directory that
holds a file the transaction holds (one it has read or edited), apart from
`touch`, `chmod` and `lchmod` of a directory that exists, which change it
alone. Raw writes to other files (a `.nii.gz`, say) are allowed, and so are
reads. `mkdir` is allowed, except where the transaction holds a file with
content, at the path or above it, since the commit would find a directory
in its place. The refusal holds whichever path the write goes through, and
from every thread and task while the transaction is open. The wrapped
driver object and the backend's own handles are not checked.

A transaction covers the files below its root, in the thread or task that
opened it (and the tasks started inside it), while it is open. A write
through the tree to one of those files from anywhere else raises
`RuntimeError` rather than being lost or written past the transaction:
from another thread (a `threading.Thread` or a `ThreadPoolExecutor` worker
does not share the block's context, so it does not join the transaction),
from a task started outside the block, and, once the block has closed, from
a task that outlived it or during its commit. A write that started before
the block opened raises the same way if the block covers the file by the
time the write holds it; if the write got there first, the block reads the
file it wrote. Transactions on overlapping trees cannot be nested, nor be
open at once in two threads or tasks, whether sync or async; on disjoint
trees they can. A file is known by its
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
value that cannot be written (a tab in a TSV cell, a value JSON cannot hold
set inside a live value) raises its error with nothing written; the message
names the file, and in a JSON file the key that holds the value
(`T1w.json: Extra.Coils[0]: ...`). On a local disk, a directory found where
a file goes, or a file where its directory goes, raises too (an
`IsADirectoryError` or `NotADirectoryError`), with nothing written. Then
the files are written one at a time, in the order the transaction first
used them (read or written), each through bagof-paths' `staged()`: it is
replaced in one step, so a reader sees the old file or the
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
import errno
import os
import threading
from contextvars import ContextVar
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from brainfilter import _content
from brainfilter._family import in_family
from brainfilter._names import parse_name

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


# The transaction whose commit is writing in this context: the commit's own
# writes go through the guarded members of the paths, and are not refused as
# raw writes to the files it covers.
_COMMITTING_HERE: ContextVar[_TransactionBase | None] = ContextVar(
    "brainfilter_committing", default=None
)

# Whether this context is writing a file through (outside every block),
# having checked under the file's lock that no transaction covers it: that
# write is brainfilter's own, and is not refused as a raw write.
_WRITING_THROUGH: ContextVar[bool] = ContextVar(
    "brainfilter_writing_through", default=False
)

# The extensions of the files a transaction holds (JSON and TSV).
_CONTENT_EXTENSIONS = (".json", ".tsv")

# The members that change a directory without replacing or removing what it
# holds: a held file in it is not lost.
_KEEPS_FILES = frozenset({"touch", "chmod", "lchmod"})


@contextlib.contextmanager
def writing_through() -> Iterator[None]:
    """Mark the writes of a block as a write through, not raw writes.

    Used around the write of one file, outside every transaction, once
    `active_for(path, write=True)` has been checked under the file's lock.
    """
    token = _WRITING_THROUGH.set(True)
    try:
        yield
    finally:
        _WRITING_THROUGH.reset(token)


def in_block(tx: _TransactionBase) -> bool:
    """Whether this context is inside `tx`'s block, and `tx` is open."""
    return tx._state == _OPEN and tx in _ACTIVE.get()


def refuse_raw_write(path: object, member: str, verb: str) -> None:
    """Refuse a raw write to `path` that a transaction would lose.

    `member` is the path member called (`write_text`, `rename`, ...) and
    `verb` what it does to `path`, both for the error. A raw write is
    refused, with `RuntimeError`, while a transaction is open (in any
    context) or committing when `path` is a JSON or TSV file below its root,
    held yet or not, or a directory that holds a file it holds (unless the
    member only touches the directory or changes its mode): the commit would
    overwrite the write, or write the file back. `mkdir` is refused only at
    a file the transaction holds, or below one. The commit's own writes,
    and a write through outside every block, are not refused.
    """
    with _REGISTRY_LOCK:
        if not _REGISTRY:
            return
        others = list(_REGISTRY)
    if _WRITING_THROUGH.get():
        return
    writing = _COMMITTING_HERE.get()
    location = _location(path)
    for tx in others:
        if tx is writing:
            continue
        held = tx._holds_at(location, path, member)
        if held is not None:
            raise tx._raw_write_error(path, member, verb, held)


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

    __slots__ = ("content", "kind", "live", "missing", "original", "path")

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
        # `column -> LiveColumn`: the live columns read from this table in
        # the block, kept in step with it by every change (see `_tree`).
        self.live: dict | None = None

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

        The content is put back in place, as the same object, and so is
        each value in it: a change only sets, removes or replaces the
        top-level values (the keys of a JSON object, the cells of a table's
        rows), so their own objects are kept as they are, and a value a
        caller holds from the content stays the content's own.
        """
        content, original, missing = self.content, self.original, self.missing
        restore_content = None
        if isinstance(content, _content.Table):
            restore_content = content._snapshot()
        elif isinstance(content, (dict, list)):
            saved = copy.copy(content)

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
        # An index of the held files, so that a raw write is checked in
        # time proportional to its path's depth: `location -> how many
        # files that existed when held are at it or below it`, and the
        # files that did not exist (which count once they have content).
        self._below: dict[object, int] = {}
        self._missing: dict[object, _Entry] = {}
        # Tasks run in a thread with `asyncio.to_thread` join the block, so
        # two threads may hold a file at once.
        self._lock = threading.Lock()

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
        if entry is not None:
            return entry
        content = _content.parse(kind, text, descriptions)
        original = _content.dump(kind, content)
        with self._lock:
            entry = self._entries.get(location)
            if entry is None:
                entry = self._entries[location] = _Entry(
                    _write_path(path, location), kind, content, original,
                    missing=text is None,
                )
                self._index(location, entry)
        return entry

    def _index(self, location: tuple[str, Any], entry: _Entry) -> None:
        if entry.missing:
            self._missing[location] = entry
            return
        kind, place = location
        for at in (place, *place.parents):
            key = (kind, at)
            self._below[key] = self._below.get(key, 0) + 1

    def exists_below(self, location: tuple[str, Any]) -> bool:
        """Whether a held file that existed when held is at or below it."""
        return bool(self._below.get(location))

    def holds_below(self, location: tuple[str, Any]) -> bool:
        """Whether a file held at `location`, or below it, has content."""
        if self._below.get(location):
            return True
        return any(
            _within(held, location) and not entry.absent()
            for held, entry in list(self._missing.items())
        )

    def file_at_or_above(
        self, location: tuple[str, Any], top: tuple[str, Any]
    ) -> bool:
        """Whether a held file with content is at `location`, or above it.

        Only the places from `location` up to `top` are looked at.
        """
        kind, place = location
        for at in (place, *place.parents):
            entry = self._entries.get((kind, at))
            if entry is not None and not entry.absent():
                return True
            if at == top[1]:
                break
        return False

    def names_in(self, directory: object) -> set[str]:
        """Names, directly in `directory`, of held files or their parents."""
        kind, top = _location(directory)
        names = set()
        for (entry_kind, location), entry in list(self._entries.items()):
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
        first write; its message names the file, and the key that holds the
        value in a JSON file.
        """
        plan = []
        for entry in list(self._entries.values()):
            try:
                text = entry.text()
            except Exception as error:
                named = _content_error(entry, error)
                if named is None:
                    raise
                raise named from error
            if text is not None:
                plan.append((entry.path, text.encode("utf-8")))
        return plan

    def end_live(self) -> None:
        """End every live column read from a held table (the block ended)."""
        for entry in list(self._entries.values()):
            for column in list((entry.live or {}).values()):
                column._end()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._below.clear()
            self._missing.clear()


def _serializable(value: object) -> bool:
    try:
        _content.dump_json(value)
    except (TypeError, ValueError):
        return False
    return True


def _key_path(content: object) -> str:
    """Return where, in JSON `content`, the first value JSON cannot hold is.

    As `Extra.Coils[0]`: a key after a dot, an index (or a key that is not
    text) in brackets. Empty when it is `content` itself.
    """
    parts: list[str] = []
    seen: set[int] = set()
    value = content
    while isinstance(value, (dict, list, tuple)) and id(value) not in seen:
        seen.add(id(value))
        items = (
            value.items() if isinstance(value, dict) else enumerate(value)
        )
        for key, item in items:
            if isinstance(value, dict) and isinstance(key, str):
                part = f".{key}" if parts else key
            else:
                part = f"[{key!r}]"
            if isinstance(value, dict) and not (
                key is None or isinstance(key, (str, int, float, bool))
            ):
                parts.append(part)
                return "".join(parts)
            if not _serializable(item):
                parts.append(part)
                value = item
                break
        else:
            break
    return "".join(parts)


def _content_error(entry: _Entry, error: Exception) -> Exception | None:
    """Return `error` again, its message naming the file (and the key).

    `None` when an error of its type cannot be built from a message alone.
    """
    where = str(entry.path)
    if entry.kind == _content.JSON:
        keys = _key_path(entry.content)
        if keys:
            where = f"{where}: {keys}"
    try:
        return type(error)(f"{where}: {error}")
    except Exception:  # noqa: BLE001
        return None


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
        # A live column holds the block's values; once the block has ended
        # they are no longer the file's, so it is not read or written.
        self._buffer.end_live()

    def _check_plan(self, plan: list) -> None:
        """Refuse, before the first write, a local file that cannot be written.

        A directory at the file's place, or a file at its parent's, would
        stop the commit partway; the error raises with nothing written.
        """
        for path, _ in plan:
            if not path.is_local():
                continue
            name = os.fspath(path)
            if os.path.isdir(name):
                raise IsADirectoryError(
                    errno.EISDIR,
                    f"cannot commit the transaction on {str(self._root)!r}, "
                    "nothing was written: a directory is now where this "
                    "file goes",
                    name,
                )
            parent = os.path.dirname(name)
            while parent and not os.path.isdir(parent):
                if os.path.lexists(parent):
                    raise NotADirectoryError(
                        errno.ENOTDIR,
                        f"cannot commit the transaction on "
                        f"{str(self._root)!r}, nothing was written: a file "
                        f"is now where the directory {parent!r} goes",
                        name,
                    )
                above = os.path.dirname(parent)
                if above == parent:
                    break
                parent = above

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

    def _holds_at(
        self, location: tuple[str, Any], path: Any, member: str  # noqa: ANN401
    ) -> str | None:
        """Say what this transaction covers at `location`, or `None`.

        `"file"`: a JSON or TSV file below the root (held yet or not);
        `"directory"`: a directory that holds a file the transaction holds
        (not said to `touch`, `chmod` or `lchmod` when one of those files
        existed, so that the path is a directory, which they change alone);
        `"pending"`, said to `mkdir` alone: a file the transaction holds is
        there, or above it, so the commit would find a directory there.
        Each check takes time in proportion to the depth of `path`.
        """
        if member == "mkdir":
            if _within(location, self._location) and (
                self._buffer.file_at_or_above(location, self._location)
            ):
                return "pending"
            return None
        if parse_name(path.name).extension in _CONTENT_EXTENSIONS and (
            _within(location, self._location)
        ):
            return "file"
        if member in _KEEPS_FILES and self._buffer.exists_below(location):
            # A directory, since a file below it existed: changed alone.
            return None
        if self._buffer.holds_below(location):
            return "directory"
        return None

    def _raw_write_error(
        self, path: object, member: str, verb: str, held: str
    ) -> RuntimeError:
        where = (
            "open" if self._state == _OPEN and any(
                tx is self for tx in _ACTIVE.get()
            ) else f"{_doing(self)} in another thread or task"
        )
        if held == "file":
            why = (
                f"a transaction on {str(self._root)!r} is {where}, and it "
                "covers this file, so its commit could overwrite this write"
            )
            how = (
                "inside the block, change a JSON or TSV file through "
                "brainfilter (`path[key] = value`, `path.write(...)`), or "
                "make this write after the block ends"
            )
        elif held == "pending":
            why = (
                f"a transaction on {str(self._root)!r} is {where}, and it "
                "holds a file at this path (or above it), which its commit "
                "will write"
            )
            how = (
                "make this directory after the block ends, or do not give "
                "that file content in the block"
            )
        else:
            why = (
                f"a transaction on {str(self._root)!r} is {where}, and it "
                "holds files in this directory (read or edited), so its "
                "commit could write them back"
            )
            how = "make this change after the block ends"
        return RuntimeError(
            f"cannot {verb} {str(path)!r} with {member}(): {why}; {how}"
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
        ds["T1w.json"]["Extra"]["Coil"] = "neck"   # a nested edit, kept too
    tx.written       # the files the commit wrote, in order
    ```

    Inside the block, a raw write (`write_text`, `unlink`, ...) to a JSON or
    TSV file it covers raises `RuntimeError`, since the commit would
    overwrite it; see the module documentation.
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
        self._check_plan(plan)
        token = _COMMITTING_HERE.set(self)
        try:
            for index, (path, data) in enumerate(plan):
                try:
                    write_file(self._target(path), data)
                except Exception as error:
                    raise self._failed(plan, index, error) from error
                except BaseException as error:
                    self._interrupted(plan, index, error)
                    raise
                self._written.append(path)
        finally:
            _COMMITTING_HERE.reset(token)


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
        self._check_plan(plan)
        token = _COMMITTING_HERE.set(self)
        try:
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
        finally:
            _COMMITTING_HERE.reset(token)
