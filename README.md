# brainfilter

Build, read and filter BIDS trees on any storage backend.

`brainfilter` walks a BIDS dataset (local or remote), exposes its files and
metadata, and selects files with glob, regex and BIDS-entity conditions.
Validation is out of scope for now.

## Reading a dataset

```python
from brainfilter.bidspath import BidsPath

ds = BidsPath("memory://ds")            # or a local path, s3://, ...
anat = ds["sub-01"]["anat"]             # children by name; keys(), iteration
t1w = anat["sub-01_T1w.nii.gz"]

ds["dataset_description.json"]["Name"]  # a JSON file is a mapping
ds["participants.tsv"].read()           # a TSV file is a Table: a list of rows
ds["participants.tsv"].read_dataframe() # ... or a DataFrame (needs pandas)

t1w.metadata["RepetitionTime"]          # ChainMap of applicable sidecars
t1w.sidecars()                          # the sidecars, nearest first
```

### Typed tables

`read()` types each column of a TSV file, and `n/a` reads as `None`:

```python
ds["participants.tsv"].read()
# [{"participant_id": "sub-01", "age": 30.0, "sex": "F"}, ...]
ds["participants.tsv"].read(raw=True)   # every value as its exact text
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
`Delimiter` reads as lists. `read_dataframe()` gives the same types as
pandas dtypes.

When a table is written, an unchanged cell keeps its exact text (`1.50`
stays `1.50`). A changed or new cell is written from its value: `None` as
`n/a`, a `bool` as `true`/`false`, a `float` in its shortest form, a list
joined with the column's `Delimiter`.

### Sidecars

Sidecars are inherited up to the dataset root: the nearest ancestor with a
`dataset_description.json`, or the `root=` you pass to `sidecars()` and
`read_metadata()`. A file with no dataset root above it (a loose file, a
scratch directory) gets the sidecars in its own directory only.

## Writing

The tree is read-only, except inside a transaction. Edits to JSON and TSV
files are kept in memory, and every read sees them, `metadata` included. On
a clean exit each changed file is written; on an exception, nothing is.

```python
with ds.transaction() as tx:
    ds["T1w.json"]["RepetitionTime"] = 2.3      # set a key
    del ds["T1w.json"]["Obsolete"]              # delete a key
    ds["task-rest_bold.json"].write({"TaskName": "rest"})   # replace a file
    (ds / "sub-03")["sub-03_T1w.json"] = {"Level": "new"}   # a new file
    rows = ds["participants.tsv"].read()        # this transaction's copy
    rows.append({"participant_id": "sub-03", "age": 41})
    rows.add_column("handedness")
    rows.drop_column("sex")
    t1w.metadata["EchoTime"] = 0.03             # lands in the nearest sidecar
tx.written                                      # the files written, in order
```

What a read returns inside the block is the transaction's own copy, so
changing it in place is an edit. A file that was read but not changed is
not written. Outside a block, assigning into the tree raises `TypeError`:
nothing is ever written behind your back.

One file can be edited on its own:

```python
with ds["participants.json"].edit() as content:   # {} for a new file
    content["age"] = {"Units": "year"}
```

### When a write fails

Each file is replaced in one step (bagof-paths' `staged()`), so a reader
never sees a torn file. A set of files is not replaced atomically, on remote
stores in particular. Every file is serialized before the first write, so
bad content fails with nothing written. Then the files are written one at a
time, in the order the transaction first used them; if one fails, the
commit **stops**, and `TransactionError` says what happened:

```python
from brainfilter.transaction import TransactionError

try:
    with ds.transaction():
        ...
except TransactionError as error:
    error.written       # written, in order; not rolled back
    error.failed        # the file whose write failed
    error.not_written   # that file and the ones after it, not attempted
    error.__cause__     # the store's error (a bagof.paths.CommitError)
```

A single-file `edit()` raises its write's error directly. An `edit()` inside
a transaction that covers the file joins it.

## Async

`AsyncBidsPath` has the same BIDS surface and classes, with coroutine I/O.
Indexing and `in` cannot be awaited, so they are `child()` and `has()`;
everything else keeps its name and is awaited.

```python
from brainfilter.bidspath import AsyncBidsPath
from brainfilter.filter import Filter

ds = AsyncBidsPath("s3://bucket/ds")          # native async on s3fs, gcsfs, ...
anat = await (await ds.child("sub-01")).child("anat")
names = await anat.keys()                     # also values(), items(), get()
async for name in ds: ...
await (ds / "participants.tsv").read()        # rows
await (ds / "T1w.json").get("RepetitionTime")
await (anat / "sub-01_T1w.nii.gz").read_metadata()   # ChainMap

kept = await Filter(subjects="01").awalk(ds)  # list AsyncBidsPath files

async with ds.transaction():                  # the same transactions
    sidecar = ds / "T1w.json"
    await sidecar.set("RepetitionTime", 2.3)  # for sidecar[key] = value
    await sidecar.delete("Obsolete")          # for del sidecar[key]
    (await (ds / "participants.tsv").read()).append({"participant_id": "sub-03"})
    await (ds / "sub-03" / "sub-03_T1w.json").write({"Level": "new"})

async with sidecar.edit() as content:
    content["EchoTime"] = 0.03
```
