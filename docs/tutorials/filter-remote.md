# Filtering a remote dataset (S3 / OpenNeuro)

Neuroimaging datasets are large, and the part of a dataset a study needs is
usually small. [OpenNeuro](https://openneuro.org) publishes its datasets in a
public S3 bucket, and this tutorial uses one of them, `ds000001`, to show the
workflow that brainfilter is designed for: open the dataset without
downloading it, list what it contains, decide which files you want, and only
then download those.

The tutorial needs network access and an S3 backend, which
[Installation](../getting-started/installation.md#remote-backends) explains:

```bash
pip install brainfilter universal-pathlib s3fs
```

## Open the dataset

A remote dataset is opened like a local one, with a URL in place of the path.
The bucket is public, so the connection must be anonymous. Connection options
go in `storage_options`, and they are handed unchanged to the backend, which
for S3 is [s3fs](https://s3fs.readthedocs.io). Its `anon` option turns off
authentication.

```pycon
>>> from brainfilter import BidsPath, BidsFilter
>>> ds = BidsPath("s3://openneuro.org/ds000001", storage_options={"anon": True})
>>> ds
BidsPath('s3://openneuro.org/ds000001')
```

Opening the path sent nothing over the network. The first request happens when
you ask the dataset a question, and the answer to a small question is a small
download.

```pycon
>>> ds.keys()
['.datalad', '.gitattributes', 'CHANGES', 'README', 'dataset_description.json', 'participants.tsv', 'sub-01', 'sub-02', ...]
>>> ds["dataset_description.json"]["Name"]
'Balloon Analog Risk-taking Task'
>>> ds["participants.tsv"].as_list()[:2]
[{'participant_id': 'sub-01', 'sex': 'F', 'age': 26.0}, {'participant_id': 'sub-02', 'sex': 'M', 'age': 24.0}]
```

Every call above transferred a directory listing or a file of a few hundred
bytes. The images, which are the bulk of the dataset, have not been touched.

!!! tip "Other S3 stores and private buckets"

    Anonymous access is specific to public buckets. For a private bucket, leave
    `storage_options` out to use the credentials the environment already
    provides (environment variables, `~/.aws/config`, an instance role), or
    pass `key` and `secret` explicitly. A store that speaks the S3 protocol
    but is not Amazon's, such as MinIO, takes an `endpoint_url` in the same
    dictionary. Anything that s3fs accepts can go there.

## Filter before downloading

Suppose a study needs the T1-weighted image of the first three participants.
The filter is the same one that would be used on a local disk:

```pycon
>>> f = BidsFilter(sub=[1, 2, 3], datatype="anat", suffix="T1w")
>>> kept = f.walk(ds)
>>> print(*[p.relative_to(ds).as_posix() for p in kept], sep="\n")
CHANGES
README
dataset_description.json
participants.tsv
sub-01/anat/sub-01_T1w.nii.gz
sub-02/anat/sub-02_T1w.nii.gz
sub-03/anat/sub-03_T1w.nii.gz
```

`walk()` listed the dataset folder by folder and applied the filter to the
names it found, and no file was opened to do so. It did not even list the
folders of the other subjects, since none of their files could pass. Three images were selected,
along with the files that every BIDS dataset carries. In `ds000001`, which
includes no sidecar for these images, the three images are all there is to
fetch. On a dataset with sidecars, `scans.tsv` files or events files, those
would appear here too, as they did in the
[local tutorial](filter-local.md#what-comes-along-with-the-images).

Because nothing has been downloaded yet, this is the moment to check the cost
of the selection. A path knows its size from the listing, so the total can be
computed without transferring any content:

```pycon
>>> sum(p.stat().st_size for p in kept) / 1e6
16.679189
```

A little under 17 MB, against about 2.4 GB for the whole dataset. If the number
is larger than expected, the filter can be refined and run again at no cost.

!!! note "Filters apply to every file they touch"

    Combining `task="balloonanalogrisktask"` with `datatype="anat"` selects
    nothing from `anat`, because an anatomical image has no `task` entity and
    a filter on an entity rejects the files that lack it. To select
    anatomical and functional data together, filter each kind separately and
    join the results.

## Download what was kept

The selected files are ordinary path objects, and `copy()` transfers one of
them to a destination. To download a selection, recreate each file's relative
path under a local folder and copy it there. Keeping the relative path
preserves the BIDS layout, so the local copy is itself a valid dataset that
brainfilter, or any other BIDS tool, can open.

```pycon
>>> from pathlib import Path
>>> out = Path("ds000001-subset")
>>> for path in kept:
...     target = out / path.relative_to(ds).as_posix()
...     target.parent.mkdir(parents=True, exist_ok=True)
...     _ = path.copy(target)
>>> print(*sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()), sep="\n")
CHANGES
README
dataset_description.json
participants.tsv
sub-01/anat/sub-01_T1w.nii.gz
sub-02/anat/sub-02_T1w.nii.gz
sub-03/anat/sub-03_T1w.nii.gz
```

Only now did the images cross the network. The result can be opened with a
local `BidsPath` and filtered again, with the same `BidsFilter`, whenever the
selection needs to be narrowed further.

If a library needs the file by name but you would rather not keep a copy, the
`local_copy()` method of a path, documented in bagof-paths, downloads it to a
temporary location for the length of a `with` block.

## Reuse one listing for several filters

Listing is the part of the workflow that costs time on a remote store, so it is
worth doing once. Instead of calling `walk()` for every filter, list the
dataset a single time with an empty `BidsFilter`, which keeps every file of the
raw dataset, and apply each filter to that listing with `select()`. The
`root` argument tells `select()` which part of each path to compare, so the
paths do not have to be converted to strings first.

```pycon
>>> files = BidsFilter().walk(ds)
>>> len(files)
133
>>> len(BidsFilter(datatype="anat").select(files, root=ds))
36
>>> len(BidsFilter(task="balloonanalogrisktask", run=1).select(files, root=ds))
37
```

The listing took a few seconds, and each `select()` call is a computation on a
list in memory. Trying out a dozen filters therefore costs the same network
time as trying one. The result of `select()` equals what `walk()` would have
returned for the same filter. The listing also gives the size of the whole
dataset, and so the proportion of it that a filter would download:

```pycon
>>> sum(p.stat().st_size for p in files) / 1e9
2.416199965
```

## Why listing once per directory matters

On a local disk, asking whether a file exists takes microseconds, and a
program can afford to ask about every file. On an object store, every question
is an HTTP request that takes tens or hundreds of milliseconds, and a dataset
with thousands of files turns a per-file question into minutes of waiting.

brainfilter avoids this by working from listings. A single request returns the
names of everything in a folder, together with the information needed to tell
files from folders, so the dataset is traversed with one request per folder and
none per file. The filter then decides on the names alone. This is also why
the same code is cheap on `ds000001`, which has 136 files, and still
practical on a dataset with hundreds of thousands.

Two habits keep it that way. Avoid loops that call `exists()`, `is_file()` or
`stat()` on one path after another when the paths came from a listing, and
prefer `walk()`, once, to ask about the whole tree. When a dataset is large and deeply nested, the asynchronous interface
lists the folders of each level concurrently:

```python
import asyncio
from brainfilter import AsyncBidsPath, BidsFilter


async def main():
    ds = AsyncBidsPath("s3://openneuro.org/ds000001", storage_options={"anon": True})
    return await BidsFilter(sub=[1, 2, 3], datatype="anat").awalk(ds)


kept = asyncio.run(main())
```

`awalk()` returns the same selection as `walk()`, as `AsyncBidsPath` objects.
On `ds000001` it is roughly three times faster than `walk()`, and the
difference grows with the number of folders. The
[async tutorial](async.md) covers the asynchronous interface in more detail.

## Where to go next

Filtering a dataset on a different store only changes the URL and the
`storage_options`: `gs://` for Google Cloud Storage, `https://` for a web
server (see the caveat on listing in
[Installation](../getting-started/installation.md#remote-backends)), and so
on. The [Paths and backends](../concepts/paths-and-backends.md) page explains
how a backend is chosen, and the [`BidsFilter`][brainfilter.BidsFilter] reference
lists every condition available.
