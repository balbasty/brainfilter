# brainfilter

Build, read and filter BIDS trees on any storage backend.

`brainfilter` walks a BIDS dataset (local or remote), exposes its files and
metadata, and selects files with glob, regex and BIDS-entity conditions.
Validation is out of scope for now.

## Reading a dataset

```python
from brainfilter import BidsPath

ds = BidsPath("memory://ds")            # or a local path, s3://, ...
anat = ds["sub-01"]["anat"]             # children by name; keys(), iteration
t1w = anat["sub-01_T1w.nii.gz"]

ds["dataset_description.json"]["Name"]  # a JSON file is a mapping of keys
ds["dataset_description.json"].as_dict()  # ... loaded as a plain dict

participants = ds["participants.tsv"]   # a TSV file is a mapping of columns
participants["age"]                     # one typed column: [30.0, None, ...]
participants.keys()                     # the column names
participants.as_dict()                  # every column: {name: [values]}
participants.as_list()                  # every row: [{column: value}, ...]
participants.as_dataframe()             # a pandas DataFrame (needs pandas)
for row in participants.rows(): ...     # the rows, one at a time

t1w.sidecars                            # the JSON sidecars, nearest first
t1w.sidecar["RepetitionTime"]           # their merged content (a ChainMap)
t1w.sidecar.as_dict()                   # ... flattened: the nearest wins
```

Every read goes to the files again; nothing is cached. A value a read
returns is a copy: changing it changes nothing on disk.

### Typed tables

A TSV file's columns are typed, and `n/a` reads as `None`:

```python
ds["participants.tsv"].as_list()
# [{"participant_id": "sub-01", "age": 30.0, "sex": "F"}, ...]
ds["participants.tsv"].as_list(raw=True)   # every value as its exact text
```

A column's type comes from the first of:

1. its description in the table's JSON sidecar (`participants.json`), if it
   has a `Format`: `number` is a `float` (even when integral), `integer`
   and `index` an `int`, `boolean` a `bool` (`true`/`false`), `date`,
   `datetime` and `time` a `datetime` object (strict ISO 8601 only, else
   text), anything else a `str`;
2. its standard BIDS definition (`age` and `onset` are numbers,
   `participant_id` and `trial_type` strings, `acq_time` a datetime);
3. its values: `int` if every value is an integer as Python writes it,
   else `float` if every value is, else `str`. So `02`, `1e3`, `1.50`, or a
   column mixing `3` and `1.5`, stay text. Booleans and dates are never
   guessed.

A declared type is used only if every value parses as it. A column with
`Levels` keeps its values as text (the keys of `Levels`); a column with a
`Delimiter` reads as lists. `as_dataframe()` gives the same types as pandas
dtypes. `as_dict()`, `as_list()`, `columns()` (the same as `as_dict()`) and
`rows()` take `raw=True`.

A BIDS table has no quoting: a cell is the exact text between two tabs, so
`"q"` reads as `"q"`, quotes included. A file may start with a UTF-8
byte-order mark; it is skipped.

When a table is written, an unchanged cell keeps its exact text (`1.50`
stays `1.50`). A changed or new cell is written from its value: `None` (or
a float NaN, as pandas holds a missing value) as `n/a`, a `bool` as
`true`/`false`, a `float` in its shortest form, a list joined with the
column's `Delimiter` (from the sidecar, for new columns and new tables
too). A value holding a tab or a line break, and an infinite float, cannot
be written: the write raises `ValueError` and writes nothing. Files are
written without a byte-order mark.

### Sidecars

Sidecars are inherited up to the dataset root: the nearest ancestor with a
`dataset_description.json`. A file with no dataset root above it (a loose
file, a scratch directory) gets the sidecars in its own directory only.

## Selecting files

A `Filter` picks a subset of a dataset from its file listing, before
anything is downloaded:

```python
from brainfilter import Filter, Glob

f = Filter(subjects="01", datatypes="anat", acq=Glob("mp*"), run=[1, 2])
f.select(listing)                      # relative path strings, or paths
f.walk("s3://openneuro.org/ds000224")  # list the dataset, then select
```

Data files are kept when they pass every filter, and the metadata that
applies to them (sidecars, `scans.tsv`, `events.tsv`, `channels.tsv`, ...)
comes with them under the BIDS inheritance principle. A few rules follow
BIDS rather than the file extension:

- a table that is a recording (`*_beh.tsv`, `*_motion.tsv`, `*_blood.tsv`)
  is data, and so is `*_physio.tsv.gz`, which also comes with the run it
  describes;
- a data file that is a directory (a CTF `*_meg.ds/`, an OME-Zarr
  `*.ome.zarr/`) is kept or skipped whole, hidden files inside included;
- a companion that names its own space or recording
  (`sub-01_space-CapTrak_electrodes.tsv`) still applies to recordings
  without one;
- metadata that applies to no data file at all (an `events.tsv` alone) is
  kept when the subject, session, datatype and entities it names pass.

So `Filter().select(listing)` keeps every file but hidden ones and the
optional folders (`derivatives/`, `sourcedata/`, ...; ask for them with
`folders=`). `select` expects files: pass `walk()`'s output, or filter
`rglob("*")` on `is_file()`. The files `walk()` lists have the mode of the
root it is given.

## Writing

Paths are read-only by default. A writable path is built with `mode="w"`,
or made with `with_mode("w")`, and every path derived from it is writable
too: `/`, `parent`, `with_subject()` and the other `with_*` methods, the
paths a listing yields (`iterdir()`, `glob()`, `walk()`, a directory's
children) and `sidecars`.

```python
ds = BidsPath("memory://ds", mode="w")  # or BidsPath(...).with_mode("w")
ds.mode                                 # "w"; "r" for a read-only path
```

On a writable path, each write to a JSON or TSV file is written at once, in
one atomic replace: the file is read, changed and replaced in one step, so a
reader sees the old file or the new one.

```python
ds["T1w.json"]["RepetitionTime"] = 2.3          # set a key
del ds["T1w.json"]["Obsolete"]                  # delete a key
ds["T1w.json"].update(EchoTime=0.03)            # several keys, one write
ds["task-rest_bold.json"].write({"TaskName": "rest"})   # replace a file
(ds / "sub-03")["sub-03_T1w.json"] = {"Level": "new"}   # a new file
ds["participants.tsv"]["handedness"] = ["R", "L"]       # one value per row
del ds["participants.tsv"]["sex"]               # drop a column
rows = ds["participants.tsv"].as_list()
ds["participants.tsv"].write([*rows, {"participant_id": "sub-03"}])
t1w.sidecar["EchoTime"] = 0.03                  # to the nearest sidecar
```

Changing a value in place (a nested `dict`, a row of `as_list()`) is not
saved: write it back. On a read-only path, each of these raises
`ReadOnlyError`, and so do `with path:`, `transaction()` and the `Path`
members that change the filesystem: `write_text`, `write_bytes`, `open`
for writing, `touch`, `mkdir`, `unlink`, `rmdir`, `rename`, `replace`,
`symlink_to`, `hardlink_to`, `chmod`, `staged`, and `copy`/`move` onto a
read-only path (or, for `move`, from one). The mode is a brainfilter rule,
not a filesystem permission: the wrapped driver object (`path.wrapped`)
does not check it.

### Transactions

Inside `with path:`, every write to a JSON or TSV file below the path is
kept in memory, through any path object, and every read sees it, `sidecar`
included. On a clean exit each changed file is written; on an exception,
nothing is.

```python
with ds:                                        # gives ds itself
    ds["T1w.json"]["RepetitionTime"] = 2.3
    ds["participants.tsv"]["age"] = [30, 41]
    t1w.sidecar["EchoTime"] = 0.03

with ds.transaction() as tx:                    # the same block
    ...
tx.written                                      # the files written, in order
```

A file that was read but not changed is not written, and a new file is
created only once it is given content. A write that raises inside the block
leaves the file's content as it was.

- A transaction holds while its block is open. A write from a task that
  outlives the block (or runs during its commit) raises `RuntimeError`
  instead of being lost: await such tasks inside the block.
- A file is known by its location, so `ds["sub-01"] / ".." / "T1w.json"`
  and `ds["T1w.json"]` (or, on a local disk, a symbolic link and its
  target) are one file. A child name is one level down: `ds[".."]` is a
  `KeyError`, and a path that leads out of the transaction's root is not
  covered by it.
- Transactions on the same files cannot be nested, sync and async alike.
- A file that no sidecar applies to has an empty `sidecar` that cannot be
  written to (`TypeError`): create its sidecar first.

### When a write fails

Each file is replaced in one step (bagof-paths' `staged()`), so a reader
never sees a torn file. Outside a transaction, a write raises its error
directly (a `bagof.paths.CommitError` when the store refused the file).

A set of files is not replaced atomically, on remote stores in particular.
At the end of a transaction, every file is serialized before the first
write, so bad content fails with nothing written. Then the files are
written one at a time, in the order the transaction first used them; if one
fails, the commit **stops**, and `TransactionError` says what happened:

```python
from brainfilter import TransactionError

try:
    with ds:
        ...
except TransactionError as error:
    error.written       # written, in order; not rolled back
    error.failed        # the file whose write failed
    error.not_written   # that file and the ones after it, not attempted
    error.__cause__     # the store's error (a bagof.paths.CommitError)
```

If the commit is interrupted instead (`KeyboardInterrupt`, or the async task
is cancelled), that exception propagates as itself, with a note listing the
files written and those not written (`error.__notes__`).

## Async

`AsyncBidsPath` has the same BIDS surface, classes and mode, with coroutine
I/O. Indexing, `in` and assignment cannot be awaited, so they are methods:
`child()` and `has()` on a directory, `get()`, `has()`, `set()` and
`delete()` on a JSON or TSV file. Everything else keeps its name and is
awaited.

```python
from brainfilter import AsyncBidsPath, Filter

ds = AsyncBidsPath("s3://bucket/ds", mode="w")  # native async on s3fs, ...
anat = await (await ds.child("sub-01")).child("anat")
names = await anat.keys()                     # also values(), items(), get()
async for name in ds: ...

sidecar = ds / "T1w.json"
await sidecar.get("RepetitionTime")           # for sidecar["RepetitionTime"]
await sidecar.as_dict()

participants = ds / "participants.tsv"
await participants.get("age")                 # for participants["age"]
await participants.as_dict()                  # also as_list(), as_dataframe()
async for row in participants.rows(): ...

t1w = anat / "sub-01_T1w.nii.gz"
await t1w.sidecars                            # the sidecars, nearest first
merged = await t1w.sidecar                    # loaded: read without await
merged["RepetitionTime"], merged.as_dict()
await merged.set("EchoTime", 0.03)            # to the nearest sidecar

await sidecar.set("RepetitionTime", 2.3)      # for sidecar[key] = value
await sidecar.delete("Obsolete")              # for del sidecar[key]
await participants.set("handedness", ["R", "L"])
await (ds / "sub-03" / "sub-03_T1w.json").write({"Level": "new"})

async with ds:                                # the same transactions
    await sidecar.set("RepetitionTime", 2.3)

kept = await Filter(subjects="01").awalk(ds)  # list AsyncBidsPath files
```
