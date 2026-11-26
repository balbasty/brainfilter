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
