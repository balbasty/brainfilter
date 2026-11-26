# brainfilter

brainfilter reads, filters and edits [BIDS](https://bids.neuroimaging.io)
neuroimaging datasets wherever they are stored: on local disk, in an S3 or
Google Cloud bucket, or behind an HTTP server. A dataset is opened with a path
or a URL, and from then on it behaves like a Python mapping of folders, JSON
files and tables.

The library is meant for researchers and developers who work with datasets too
large to copy before looking at them. It lets a script decide which subjects,
sessions, tasks or recordings it needs by reading file names alone, and
fetch only those. The files that describe a selected recording, such as its
sidecars, `events.tsv` or `scans.tsv`, are kept with it automatically.
Datasets can also be edited: sidecars and tables are written atomically and
can be grouped into transactions. Checking a dataset against the BIDS
specification is not something brainfilter does.

Storage access is provided by [bagof-paths](https://github.com/bagofseeds/bagof-paths),
which wraps [universal-pathlib](https://universal-pathlib.readthedocs.io) and
[cloudpathlib](https://cloudpathlib.drivendata.org) behind one interface, so
the code that works on a local dataset works on a remote one.

## A first taste

The example below opens a public dataset from OpenNeuro, reads from it, and
selects the anatomical images of two subjects without downloading anything.

```python
from brainfilter import BidsPath, Filter

ds = BidsPath("s3://openneuro.org/ds000001", storage_options={"anon": True})

ds["dataset_description.json"]["Name"]        # 'Balloon Analog Risk-taking Task'
ds["participants.tsv"]["age"][:3]             # [26.0, 24.0, 27.0]

kept = Filter(subjects=[1, 2], datatypes="anat").walk(ds)
[p.name for p in kept if p.name.endswith(".nii.gz")]
# ['sub-01_T1w.nii.gz', 'sub-01_inplaneT2.nii.gz',
#  'sub-02_T1w.nii.gz', 'sub-02_inplaneT2.nii.gz']
```

## Where to start

New readers should begin with [Installation](getting-started/installation.md),
which also explains what a remote dataset needs, and then
[First steps](getting-started/first-steps.md), which opens a dataset and runs a
first filter. The tutorials cover the common tasks in depth:
[filtering a local dataset](tutorials/filter-local.md),
[filtering a remote dataset](tutorials/filter-remote.md),
[reading sidecars and tables](tutorials/read-metadata.md),
[editing a dataset safely](tutorials/edit-dataset.md) and
[using the asynchronous interface](tutorials/async.md). The
[Concepts](concepts/inheritance.md) section explains the ideas behind them, and
the [API reference](api/paths.md) documents every public name.
