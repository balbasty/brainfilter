# Async access

A dataset on a remote store is mostly waiting. Listing a bucket, reading a
sidecar and writing a table are each a network round trip, and a loop that does
them one after the other spends nearly all of its time idle. `AsyncBidsPath` is
the same path as [`BidsPath`](../api/paths.md#brainfilter.BidsPath), with the same classes, the same
modes and the same transactions, whose I/O is awaited, so that many such
operations can be in flight at once.

This page walks through the coroutine surface, then through transactions, and
ends with when it is worth using. Editing itself is introduced in
[Editing a dataset safely](edit-dataset.md), which is worth reading first, since
everything there applies here. The code on this page uses a local directory so
that it can run anywhere. It runs inside a coroutine, so to try it in a script
wrap it in a function and call `asyncio.run`, or use a console that allows
top-level `await` (`python -m asyncio`).

## A dataset to work with

The examples need a small dataset. The setup below builds one on disk with the
synchronous `BidsPath`; it is the only synchronous code on the page.

```python
import tempfile
from brainfilter import BidsPath

root = tempfile.mkdtemp()
sync = BidsPath(root, mode="w")
(sync / "dataset_description.json").write({"Name": "Demo", "BIDSVersion": "1.10.0"})
(sync / "participants.tsv").write([
    {"participant_id": "sub-01", "age": 30, "sex": "F"},
    {"participant_id": "sub-02", "age": None, "sex": "M"},
])
for sub in ("sub-01", "sub-02"):
    func = sync / sub / "func"
    (func / f"{sub}_task-rest_bold.json").write({"RepetitionTime": 20.0, "TaskName": "rest"})
    (func / f"{sub}_task-rest_bold.nii.gz").touch()
(sync / "task-rest_bold.json").write({"EchoTime": 0.03})
```

## Opening an async path

`AsyncBidsPath` is built exactly as `BidsPath` is, from a directory or a URL, and
it takes the same `mode`. Like its synchronous sibling it is read-only unless you
pass `mode="w"`, and the mode passes on to every path derived from it.

```python
from brainfilter import AsyncBidsPath

ds = AsyncBidsPath(root, mode="w")
ds.mode          # 'w'
```

Creating the path does no I/O. Nothing is read until you await something.

## Reading

Python cannot await inside an index expression, an `in` test or an assignment,
so those few operations have method spellings. On a directory, `child()` replaces
`ds[name]` and `has()` replaces `name in ds`. On a JSON or TSV file, `get()`
replaces `file[key]`, `has()` replaces `key in file`, `set()` replaces
`file[key] = value`, and `delete()` replaces `del file[key]`. Everything else
keeps its name and is awaited.

```python
sub = await ds.child("sub-01")
func = await sub.child("func")
await func.keys()
# ['sub-01_task-rest_bold.json', 'sub-01_task-rest_bold.nii.gz']

bold = func / "sub-01_task-rest_bold.json"
await bold.get("RepetitionTime")      # 20.0
await bold.as_dict()                  # {'RepetitionTime': 20.0, 'TaskName': 'rest'}
```

Joining names with `/` is a lexical operation, so it needs no `await`, and it
does not check that the file exists. That is why `func / name` is the cheapest
way to point at a file whose name you already know. A directory is also an
asynchronous iterator over its children.

```python
async for name in ds:
    print(name)
# dataset_description.json
# participants.tsv
# sub-01
# sub-02
# task-rest_bold.json
```

A TSV file works the same way, and its rows arrive one at a time.

```python
participants = ds / "participants.tsv"
await participants.keys()             # ['participant_id', 'age', 'sex']
await participants.get("age")         # [30.0, None]
async for row in participants.rows():
    print(row)
# {'participant_id': 'sub-01', 'age': 30.0, 'sex': 'F'}
# {'participant_id': 'sub-02', 'age': None, 'sex': 'M'}
```

## Sidecars

For a data file, `sidecars` and `sidecar` are the two things that need I/O, so
both are awaited. Awaiting `sidecars` gives the sidecars that apply, nearest
first. Awaiting `sidecar` loads them once and returns the merged mapping, which
you then read without further `await`.

```python
run = func / "sub-01_task-rest_bold.nii.gz"
await run.sidecars
# (AsyncBidsSidecarFile('.../sub-01/func/sub-01_task-rest_bold.json', mode='w'),
#  AsyncBidsSidecarFile('.../task-rest_bold.json', mode='w'))

merged = await run.sidecar
merged["RepetitionTime"]              # 20.0, from the nearest sidecar
merged["EchoTime"]                    # 0.03, inherited from the task-level file
merged.as_dict()
# {'EchoTime': 0.03, 'RepetitionTime': 20.0, 'TaskName': 'rest'}
```

The merged mapping holds what was loaded when you awaited it. Await `run.sidecar`
again to see later changes.

## Writing

Writes are awaited like reads. Outside a transaction, each one is a single atomic
replace of one file, just as in the synchronous case.

```python
await bold.set("RepetitionTime", 2.0)
await bold.delete("TaskName")
await participants.set("handedness", ["R", "L"])
await (ds / "sub-03" / "sub-03_T1w.json").write({"Level": "new"})
await merged.set("FlipAngle", 90)     # to the nearest sidecar
```

Two writes to one file that overlap in time, from two tasks on the same event
loop, are carried out one after the other, so neither is lost. This protection
holds within one event loop. Two processes writing to the same file are not
coordinated, and the last replace wins.

As in the synchronous API, a value that was read is a copy. Changing a nested
dictionary in place does not save anything; set it again.

## Transactions

`async with` groups edits in the same way `with` does. Writes inside the block are
kept in memory, reads see them, and the changed files are written when the block
ends cleanly. An exception inside the block discards everything.

```python
async with ds.transaction() as tx:
    async for path in ds.glob("sub-*/func/*_bold.json"):
        await path.set("RepetitionTime", 2.0)
[p.name for p in tx.written]
# ['sub-02_task-rest_bold.json']
```

Only one file was written. The `sub-01` sidecar had already been corrected by the
`set` call in the previous section, so setting the same value left it unchanged,
and a file that did not change is not written. Checking `tx.written` is a cheap
way to see what a block really did.

Writing `async with ds:` gives you the path instead of the transaction object, as
`with ds:` does. A failed commit raises `TransactionError` with `written`,
`failed` and `not_written`, exactly as described in
[Editing a dataset safely](edit-dataset.md#when-the-store-fails-partway). The
async family writes the files one at a time, in the order they were first used,
so the report means the same thing in both. If the task is cancelled while the
commit is running, `asyncio.CancelledError` propagates as itself, with a note
listing the files written and the files not written.

Tasks that you start inside the block share the transaction, so you can fan out
within it. Wait for them before the block ends: a task that outlives the block
raises `RuntimeError` when it tries to write.

```python
import asyncio

async with ds:
    paths = [p async for p in ds.glob("sub-*/func/*_bold.json")]
    await asyncio.gather(*(p.set("EchoTime", 0.03) for p in paths))
```

A write from somewhere the transaction does not reach, such as a plain thread or
a task started outside the block, raises `RuntimeError` instead of going past it.
`asyncio.to_thread` is not such a place: it copies the caller's context, so the
worker joins the transaction. The rules are laid out in
[Modes and transactions](../concepts/modes-and-transactions.md#transactions).

## Selecting files

A `Filter` has an asynchronous counterpart of `walk`. `Filter.awalk` lists the
dataset one level at a time, with all the directories of a level listed at once,
and returns the files to keep as `AsyncBidsPath` objects, with the mode of the
root you passed.

```python
from brainfilter import Filter

kept = await Filter(subjects="01", suffixes="bold").awalk(ds)
[p.name for p in kept]
# ['dataset_description.json', 'participants.tsv', 'sub-01_task-rest_bold.json',
#  'sub-01_task-rest_bold.nii.gz', 'task-rest_bold.json']
```

The list holds the data files of subject 01, and the metadata that comes with
them: the dataset description, the participants table, and the sidecars that
apply.

Listing every directory of a level at once is where a remote dataset gains most.
The selection is described in [Selecting files](filter-local.md).

## When async pays off

On a local disk, `AsyncBidsPath` gains little. A synchronous driver is run in a
worker thread, which keeps the event loop free, but the disk is fast and the
call count is small. The benefit appears when each operation spends its time
waiting on a network.

The clearest case is a remote store with a natively asynchronous backend, such
as `s3://` through s3fs. There `AsyncBidsPath` awaits the backend's own
coroutines, with no thread in between. Then reading the sidecars of a hundred
runs becomes a `gather` of a hundred reads that overlap, rather than a hundred
round trips in a row.

```python
runs = [p async for p in ds.glob("sub-*/func/*_bold.nii.gz")]
sidecars = await asyncio.gather(*(run.sidecar for run in runs))
```

Most of the time you will be reading metadata from many files, or listing a
large tree. For a single file, a short script or a notebook cell, the
synchronous `BidsPath` is simpler and just as fast. The two share one surface and
compare equal when they point at the same location, so you can move a piece of
code from one to the other when its needs change. The reference entries are
[`AsyncBidsPath`](../api/paths.md#brainfilter.AsyncBidsPath) and
[`AsyncTransaction`](../api/transactions.md#brainfilter.AsyncTransaction).
