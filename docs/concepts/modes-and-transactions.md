# Modes and transactions

Reading a dataset cannot damage it, but writing to one can. brainfilter
therefore separates the two cleanly. A path is either read-only or writable,
and a path is read-only unless you decide otherwise. Writes themselves come in
two forms: a single write that takes effect at once, and a group of writes that
takes effect together when a block ends. This page describes the model behind
both, so that the guarantees, and the limits of those guarantees, are clear
before you rely on them. For the same material as a worked example, see
[Editing a dataset safely](../tutorials/edit-dataset.md).

## Read-only by default

Every path has a mode, either `"r"` or `"w"`, and the default is `"r"`. A
program that only reads a dataset therefore needs no care to avoid changing it,
and a function that is handed a path from elsewhere cannot write through it
unless that path was opened for writing.

The default also catches mistakes early. Suppose a script that was meant to
analyse a dataset contains an assignment that was meant for a copy. On a
read-only path, the assignment fails at the line that wrote it, with an error
that names the file, instead of altering the original and being noticed weeks
later.

```pycon
>>> from brainfilter import BidsPath
>>> ds = BidsPath("memory://ds", mode="w")
>>> (ds / "dataset_description.json").write({"Name": "Demo", "BIDSVersion": "1.10.0"})
>>> (ds / "task-rest_bold.json").write({"RepetitionTime": 2.0, "TaskName": "rest"})
>>> BidsPath("memory://ds").mode
'r'
>>> ds.mode
'w'
```

You ask for a writable path when you build it, with `mode="w"`, or afterwards,
with `with_mode("w")`. The second form returns a new path and leaves the
original read-only, which is convenient when most of a program only reads and
one function needs to write.

### How the mode travels

The mode belongs to the path object, and every path derived from it inherits it.
That covers joining a name with `/`, `parent`, the `with_*` methods, a
directory's children, the paths that `iterdir()`, `glob()` and `walk()` yield,
and the paths in `sidecars`. The files that `Filter.walk` returns have the mode
of the root that was walked.

```pycon
>>> reader = BidsPath("memory://ds")
>>> writer = reader.with_mode("w")
>>> writer["task-rest_bold.json"].mode
'w'
>>> [p.mode for p in writer.glob("*.json")]
['w', 'w']
>>> [p.mode for p in reader.glob("*.json")]
['r', 'r']
```

Two paths at the same location are equal whatever their modes, so a read-only
path and a writable one can be mixed in sets and as dictionary keys without
surprises. Equality says that they name the same file, not that they are allowed
to do the same things with it.

A path built from a string does not inherit anything. `BidsPath("memory://ds")`
is read-only even when a writable path to the same dataset exists elsewhere in
the program. This is deliberate: the only way to obtain write access is to ask
for it at the point where the path is made.

### What a read-only path refuses

A read-only path raises `ReadOnlyError` for every brainfilter write, which are
assignment, `del`, `update` and `write` on JSON and TSV files, and also for
`with path:` and `transaction()`. It also refuses the members of the underlying
path that change a filesystem: `write_text`, `write_bytes`, `touch`, `mkdir`,
`unlink`, `rmdir`, `rmtree`, `symlink_to`, `hardlink_to`, `chmod`, `lchmod`,
`staged` and `upload_from`, as well as `open` with a mode that writes.

Operations that involve two paths are checked on each side that would change.
`rename` and `replace` refuse a read-only target, and `move` and `move_into`
refuse a read-only source (which would lose its file) as well as a read-only
destination. `copy`, `copy_into`, `link_to` and `download_to` refuse only the
read-only destination, since copying out of a read-only dataset is a perfectly
ordinary thing to do.

```pycon
>>> from brainfilter import ReadOnlyError
>>> source = reader / "task-rest_bold.json"
>>> source.copy(writer / "copy.json").name
'copy.json'
>>> try:
...     writer["copy.json"].copy(reader / "copy2.json")
... except ReadOnlyError as error:
...     print(error)
cannot copy onto 'memory://ds/copy2.json': the path is read-only; get a writable path with path.with_mode('w'), or build it with mode='w'
```

`ReadOnlyError` is a subclass of `PermissionError`, so existing handlers for
permission failures catch it.

!!! warning "The mode is a rule of brainfilter, not a permission of the storage"

    The mode is checked by the path object and by nothing below it. The wrapped
    driver object (`path.wrapped`), and the backend's own handles (`path.fs` for
    a filesystem, `path.client` for a cloud client), reach the storage directly
    and do not look at the mode. This is the escape hatch that lets you use a
    backend feature brainfilter does not expose, and it is the reason the mode
    cannot be treated as a security boundary.

    ```pycon
    >>> reader["task-rest_bold.json"].wrapped.write_text('{"RepetitionTime": 9}')
    21
    >>> writer["task-rest_bold.json"].as_dict()
    {'RepetitionTime': 9}
    ```

    When the data must not change, enforce that where the storage can: with
    read-only credentials, a read-only mount or a bucket policy.

## Write-through and buffered writes

A write on a writable path is performed in one of two ways, depending on whether
a transaction is open.

Outside a transaction, a write goes through at once. brainfilter reads the file,
applies the change and replaces the file in one step, using `staged()` from
bagof-paths. The new content is prepared next to the target, then moved onto it,
so that a reader sees the old file or the new one and never a partial file. Each
such write is an independent unit: if you write five keys to five files, you have
made five separate replacements, and a failure after the third leaves three
files changed.

Inside a transaction, brainfilter does not touch storage when you write. The edit
is applied to an in-memory copy of the file, and every read sees it, so the code
in the block behaves as though the files had changed. The changed files are
written when the block ends cleanly, and are discarded if it ends with an
exception.

### Concurrent writes to one file

Two writes to the same file at the same time are made one after the other, under
a lock held per file, so neither is lost. A write is a read, a change and a
replace, and without the lock two of them could both read the old content and the
later replace would erase the earlier one. The lock covers the threads of one
process for `BidsPath`, and the tasks of one event loop for `AsyncBidsPath`.

The lock is not shared between processes. If two processes edit the same file,
each replacement is whole, but the later one wins, and an edit made by the other
process in between is overwritten. If you need to coordinate processes, do it
outside brainfilter, with a lock file or by giving each process its own files.

## Transactions

A transaction is opened with `with path:`, which yields the path itself, or with
`with path.transaction() as tx:`, which yields the transaction and lets you read
`tx.written` afterwards. The async family has the same blocks with `async with`.

A transaction covers the files below the path it was opened on. Writes to those
files are buffered, whichever path object they go through: a path derived from
the block's path, one built from a string, or an async path all reach the same
buffer, and a read of any of them sees the edits.

```pycon
>>> with writer as tx_root:
...     other = BidsPath("memory://ds", mode="w")
...     other["task-rest_bold.json"]["EchoTime"] = 0.03
...     print(writer["task-rest_bold.json"]["EchoTime"])
...     print("EchoTime" in (writer / "task-rest_bold.json").read_text())
0.03
False
```

### Files are known by location

The buffer is keyed on where a file is, not on the path object or the spelling
used to reach it. `ds["sub-01"] / ".." / "task-rest_bold.json"` and
`ds["task-rest_bold.json"]` are one file, and on a local disk a symbolic link and
its target are one file as well. Indexing never leaves the tree: a child name is
one level down, so `ds[".."]` is a `KeyError`, and a path that leads outside the
root of the transaction is not covered by it.

A file is read into the transaction the first time it is used there, and it is
not read again. A change that another writer makes to the file during the block
is not seen, and the commit will replace it. A file that did not exist is created
only once it has content, and a file that was read but not changed is not
written.

### Who is inside the block

A transaction holds for the thread or task that opened it, and for the tasks that
are started inside the block. Python carries that membership in the context of
the running code, which is why the boundary falls where it does.

- Tasks created inside an `async with` block, for example with
  `asyncio.create_task` or `asyncio.gather`, join the transaction. So does
  `asyncio.to_thread`, which copies the caller's context into the worker thread.
- A plain `threading.Thread`, or a worker of a `ThreadPoolExecutor`, does not
  share the context of the block. Neither does a task that was started outside
  the block.
- A task started inside the block that is still running after the block has
  closed, or during its commit, is no longer part of anything.

A write to a covered file from any of the last three is refused with a
`RuntimeError`, because it could otherwise be lost or written ahead of the
transaction and then overwritten by its commit.

```pycon
>>> import threading
>>> def stray():
...     try:
...         BidsPath("memory://ds", mode="w")["task-rest_bold.json"]["Stray"] = 1
...     except RuntimeError as error:
...         print(str(error).partition(": ")[0])
>>> with writer:
...     thread = threading.Thread(target=stray)
...     thread.start()
...     thread.join()
cannot edit 'memory://ds/task-rest_bold.json'
```

The remedy is to make the writes inside the block, and to await the tasks that
make them before the block ends.

Transactions on the same files cannot be nested, and cannot be open at once in
two threads or tasks, sync or async. A second `with ds:` inside the first raises
`RuntimeError`. Transactions on disjoint trees do not conflict, so you can hold
one on `ds["sub-01"]` and another on `ds["sub-02"]` together. A write to a file
outside every open transaction is simply written through, as usual.

!!! warning "Only brainfilter's writes are buffered"

    The buffer holds the edits made through the JSON and TSV interface. A raw
    operation on the path, such as `write_text`, goes to storage immediately and
    is not part of the transaction. If it touches a file the transaction also
    covers, the commit later replaces the file with the buffered version, and the
    raw write is lost. Do not mix the two on one file.

## What is, and is not, atomic

The guarantees are easiest to state from the smallest unit upwards.

For a single file, every write replaces the file in one step, whether it comes from a
write-through assignment or from a commit. On POSIX filesystems and on object
stores, a reader sees the whole old file or the whole new file. A failed
replacement leaves the old file in place and removes the staged data, and the
error is a `CommitError` from bagof-paths.

Before the first file of a commit is replaced, every changed file is
serialized. Content that cannot be written, such as a tab inside a TSV cell or an
infinite float, raises its error at that point, with nothing written. This
catches the common failures, which are about the data, before the risky part
begins.

For several files, a set of files is not replaced atomically. The files are
written one at a time, in the order in which the transaction first used each of
them. On remote stores there is no operation that replaces several objects at
once, so brainfilter does not pretend to offer one. If a write fails, the commit
stops: the files before it stay written, the failed file and the files after it
are not written, and their edits are dropped. `TransactionError` reports which
is which in `written`, `failed` and `not_written`, with the store's own error as
its cause. Nothing is rolled back, because on a store that is failing, a rollback
would fail as well. Stopping at the first failure keeps the outcome a prefix of a
known order, and avoids trying a store that is down once for every remaining file.

An interruption that is not an error, such as `KeyboardInterrupt` or the
cancellation of an async task, propagates as itself with a note listing the files
written and the files not written.

Across processes, nothing coordinates writers in different processes, in a
transaction or outside one. Each replacement is whole, and the last one wins. A
transaction does not take a lock on the dataset, so two processes that each run a
transaction on the same files will each commit their own version of them.

In short, a transaction makes a group of edits convenient, consistent to read, and
free of partial results when the failure is in the data or in your code. It
makes each file safe to replace. It cannot make several files change together on
storage that offers no such operation, and it says plainly which files changed
when that matters.

## Where to go next

The tutorial [Editing a dataset safely](../tutorials/edit-dataset.md) uses these
rules on a concrete task, and [Async access](../tutorials/async.md) shows the
same blocks with coroutines. The classes are documented under
[Transactions and errors](../api/transactions.md) and [Paths](../api/paths.md).
