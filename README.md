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
ds["participants.tsv"].read()           # a TSV file is a list of rows
ds["participants.tsv"].read_dataframe() # ... or a DataFrame (needs pandas)

t1w.metadata["RepetitionTime"]          # ChainMap of applicable sidecars
t1w.sidecars()                          # the sidecars, nearest first
```

The tree is read-only for now; writing will come with transactions.

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
```
