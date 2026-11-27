# Paths and storage backends

Everything in brainfilter starts from a path. A dataset, a subject's directory,
an image and a sidecar are all the same kind of object, and the same few
spellings work whether the data is on your disk, in a bucket on S3, or behind
an HTTP server. This page explains what that object is, what it knows about a
BIDS name without ever touching storage, and how the same code reaches
different backends.

## Three families of path

brainfilter provides three path classes, which differ in what they are allowed
to do with storage.

| Class | Touches storage | Use it for |
|---|---|---|
| [`PureBidsPath`](../api/paths.md#brainfilter.PureBidsPath) | never | working with names: building, parsing and editing paths |
| [`BidsPath`](../api/paths.md#brainfilter.BidsPath) | yes, synchronously | reading a dataset, listing it, and (opt in) writing |
| [`AsyncBidsPath`](../api/paths.md#brainfilter.AsyncBidsPath) | yes, with `await` | the same, when you want to overlap many remote requests |

All three are built on the path classes of
[bagof-paths](https://github.com/bagofseeds/bagof-paths), which give every
backend the same `pathlib`-style interface, and add what is specific to BIDS on
top. You construct them from a string, a URL, or another path.

```python
from brainfilter import BidsPath

ds = BidsPath("/data/ds000224")          # a local directory
ds = BidsPath("s3://openneuro.org/ds000224")   # a bucket
ds = BidsPath("https://example.org/ds000224")  # a web server
```

## The class is chosen from the name

A path is not only a location. `BidsPath("ds/participants.tsv")` is a
participants table, and `BidsPath("ds/sub-01/func/sub-01_task-rest_bold.json")`
is a sidecar, and each of them has the methods that suit it: you can ask a
table for its columns and a JSON file for its keys. brainfilter picks the class
from the name of the path and the name of its parent directory, and only from
those. It does not look at the filesystem, so a file on a remote bucket, a
file that does not exist yet, and a file on your disk all get the same class.

```pycon
>>> from brainfilter import BidsPath, PureBidsPath, AsyncBidsPath
>>> type(BidsPath("ds/participants.tsv")).__name__
'BidsParticipantsFile'
>>> type(BidsPath("ds/dataset_description.json")).__name__
'BidsDatasetDescriptionFile'
>>> type(BidsPath("ds/sub-01/func/sub-01_task-rest_bold.json")).__name__
'BidsSidecarFile'
>>> type(PureBidsPath("ds/participants.tsv")).__name__
'PureBidsParticipantsFile'
>>> type(AsyncBidsPath("ds/participants.tsv")).__name__
'AsyncBidsParticipantsFile'
```

The class follows the path through every operation. A path built with `/`,
`parent` or any of the editors below is classified again from its new name, so
`ds / "participants.tsv"` is a table, and its `parent` is a plain directory
path. You never choose these specialised classes yourself. You construct one of the
three classes above, and the specialised class is what you receive.

## What a name says

BIDS packs a lot into a file name. In `sub-01_ses-1_T1w.nii.gz`, the
*entities* are the `key-label` pairs (`sub-01`, `ses-1`), the *suffix* is the
word before the extension (`T1w`), and the *extension* is everything from the
first dot (`.nii.gz`). The *datatype* is the directory the file is in
(`anat`, `func`, `dwi`, and so on). A path exposes each of them as an
attribute, computed from the name whenever you ask.

```pycon
>>> p = BidsPath("ds/sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz")
>>> p.entities
{'sub': '01', 'ses': '1'}
>>> p.suffix, p.extension, p.datatype
('T1w', '.nii.gz', 'anat')
>>> p.basename
'sub-01_ses-1_T1w'
>>> p.subject, p.session
('01', '1')
```

The `subject` and `session` labels come from the name when it has them, and
otherwise from the nearest `sub-<label>` or `ses-<label>` directory above the
path. This is how a sidecar in `sub-01/` can know its subject although its name
says nothing about it.

!!! warning "`suffix` is the BIDS suffix, not the extension"
    On a standard `pathlib` path, `suffix` is `.gz`. On these paths it is the
    BIDS suffix (`T1w`), and the file extension is `extension`. The same goes
    for `with_suffix`, which replaces the BIDS suffix, and `with_extension`,
    which replaces the extension.

## Changing a name

Because the components are read from the name, they are edited by building a
new name, and each editor returns a new path of the same kind. The path you
started from does not change, and nothing on disk is renamed; these methods
compute a location.

`with_subject()` and `with_session()` rename every place where the subject or
session appears: the entity in the file name and the directories above it.

```pycon
>>> print(p.with_subject("02"))
ds/sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz
>>> print(p.with_session("2"))
ds/sub-01/ses-2/anat/sub-01_ses-2_T1w.nii.gz
```

`with_suffix()` and `with_extension()` replace the two other components. The
usual pairing is a data file and its sidecar.

```pycon
>>> print(p.with_suffix("T2w"))
ds/sub-01/ses-1/anat/sub-01_ses-1_T2w.nii.gz
>>> print(p.with_extension(".json"))
ds/sub-01/ses-1/anat/sub-01_ses-1_T1w.json
```

`with_entities()` sets any entity. Keywords or a dictionary give the values,
and a value of `None` removes an entity. By default the entities you pass
replace all the existing ones; with `keep_existing=True`, they are added to the
name, and the result is put in the canonical BIDS order.

```pycon
>>> print(p.with_entities(acq="mprage", keep_existing=True))
ds/sub-01/ses-1/anat/sub-01_ses-1_acq-mprage_T1w.nii.gz
>>> print(p.with_entities(ses=None, keep_existing=True))
ds/sub-01/ses-1/anat/sub-01_T1w.nii.gz
>>> print(p.with_entities({"sub": "01", "run": 2}))
ds/sub-01/ses-1/anat/sub-01_run-2_T1w.nii.gz
```

Removing an entity from the name does not move the file between directories,
as the second result shows: only the name changes. `with_basename()` replaces
the part of the name before the extension, and `with_name()` replaces the whole
name.

An edit that cannot produce a valid BIDS name raises an error instead of
guessing. Adding an entity to a directory such as `anat` is refused with a
`BidsNameError`, and a suffix or label that contains a character BIDS reserves
(`_`, `.`, `/`, and `-` in a key) raises a `ValueError` that names the problem.

```pycon
>>> BidsPath("ds/anat").with_entities(sub="01")
Traceback (most recent call last):
    ...
brainfilter.bidspath.BidsNameError: cannot add the entity sub-01 to 'anat': it is not a BIDS name of a file, which has a suffix and entities or an extension (<key>-<label>_..._<suffix><extension>)
```

## One interface, many backends

Reading a dataset looks the same wherever the dataset is. The following
examples use `memory://`, an in-memory store provided by universal-pathlib, so
that they run anywhere. Only the string you pass to `BidsPath` would change for
a bucket.

```python
w = BidsPath("memory://ds", mode="w")
w["dataset_description.json"] = {"Name": "Toy dataset", "BIDSVersion": "1.9.0"}
(w / "participants.tsv").write_text("participant_id\tage\nsub-01\t30\nsub-02\tn/a\n")
```

```pycon
>>> ds = BidsPath("memory://ds")
>>> ds.keys()
['dataset_description.json', 'participants.tsv']
>>> ds["participants.tsv"]["age"]
[30.0, None]
>>> ds.protocol, ds.is_local()
('memory', False)
```

A local path needs nothing beyond brainfilter. For any other scheme, the work
of talking to the storage is done by a path library, and brainfilter chooses
one for you: [universal-pathlib](https://github.com/fsspec/universal_pathlib)
(imported as `upath`), which builds on fsspec and so reaches S3, Google Cloud
Storage, HTTP, Azure, and many more, or
[cloudpathlib](https://cloudpathlib.drivendata.org/) if that is what you have
installed. The library that talks to the particular service has to be installed
too. For example, `s3://` needs `s3fs`, and `gs://` needs `gcsfs`; HTTP needs
`aiohttp`. [Installation](../getting-started/installation.md) covers
installing them. A scheme whose backend is missing still parses, and every lexical
operation works; the first read is what raises, with a message that says which
package to install.

```python
ds = BidsPath("s3://openneuro.org/ds000224")
ds["participants.tsv"].as_dict()           # needs universal-pathlib and s3fs

ds = BidsPath("gs://my-bucket/ds000224")   # needs gcsfs
ds = BidsPath("https://example.org/ds000224")
```

Wherever the dataset is, `BidsPath` gives you the same methods: indexing to
reach children, `sidecars`, `as_dict()` and `as_dataframe()`, and everything
the other pages describe. What the backend changes is cost. Each read of a
remote file is a request, and `keys()` on a directory is a listing. A
[`BidsFilter`](../tutorials/filter-local.md) lists a dataset once and decides before
any file is downloaded, which is the reason it exists.

### Credentials and options

Connection details go in `storage_options`, a dictionary that is passed
straight to the backend. Without it, the backend uses what it normally uses:
environment variables, a configuration file, or an instance role. This is how
you read a public bucket anonymously, or point at an S3-compatible server.

```python
ds = BidsPath(
    "s3://openneuro.org/ds000224",
    storage_options={"anon": True},
)

ds = BidsPath(
    "s3://my-bucket/ds",
    storage_options={"key": "...", "secret": "...", "endpoint_url": "https://minio.local"},
)
```

Every path derived from `ds` keeps these options, so you pass them once.
bagof-paths can also set defaults for a whole scheme, which a per-call
`storage_options` then overrides key by key; its documentation describes
`set_storage_options`. The `storage_options` attribute of a path returns the
dictionary as it is, secrets included, so it is better not printed or logged.
The path's own `repr` does not show them.

### Reaching what brainfilter does not wrap

A path is a thin layer over the object that does the work. The `wrapped`
attribute is that underlying object (a `pathlib.Path`, a `UPath` or a cloudpathlib
`CloudPath`), and `fs` or `client` are the filesystem or client behind it, for
the backends that have one. They are the way to reach a feature of a particular
library. They also bypass brainfilter's read-only default, which is a rule of
brainfilter and not a permission of the filesystem.

## Pure paths, concrete paths

A `PureBidsPath` has the entire naming interface of this page and nothing that
could read or write: there is no `exists()`, no `read_text()` and no
`iterdir()`. That is not a limitation to work around but the reason to use it.
It works with no backend installed, even for a URL, so it is the right type
for code that only computes names: deciding which files to expect, building
the paths of a download plan, or checking that a name is well formed.

```pycon
>>> url = PureBidsPath("s3://bucket/ds/sub-01/anat/sub-01_T1w.nii.gz")
>>> url
PureBidsPath('s3://bucket/ds/sub-01/anat/sub-01_T1w.nii.gz')
>>> print(url.with_subject("02"))
s3://bucket/ds/sub-02/anat/sub-02_T1w.nii.gz
>>> url.datatype, url.suffix
('anat', 'T1w')
>>> hasattr(url, "read_text")
False
```

Moving between the families is a construction. A concrete path can be made
from a pure one when you are ready to read it, and it keeps the pure path's
mode, which is `"r"` (read-only) unless you ask for `"w"`. The mode is what
[Editing a dataset](../tutorials/edit-dataset.md) is about.

```pycon
>>> BidsPath(PureBidsPath("ds", mode="w")).mode
'w'
>>> BidsPath(url).mode
'r'
```

## When to use the async family

`AsyncBidsPath` has the same classes, the same names and the same editors, and
its operations that touch storage are coroutines. The reason to choose it is a
remote dataset and many things to read: while one request waits for the
network, the others proceed. For a native async backend, such as S3 through
`s3fs`, requests really are concurrent on one event loop. For a backend that is
only synchronous, brainfilter runs each call in a worker thread, so the same
code works but the gain is smaller. On local disk there is little to gain.

Python cannot await an index, a membership test or an assignment, so the
mappings have methods in their place: `child()` and `has()` on a directory, and
`get()`, `has()`, `set()` and `delete()` on a JSON or TSV file. Everything
else keeps its name and is awaited. Here, two datasets are read at the same
time.

```python
import asyncio

for name, ids in {"a": ["sub-01", "sub-02"], "b": ["sub-01"]}.items():
    root = BidsPath(f"memory://{name}", mode="w")
    (root / "participants.tsv").write_text(
        "participant_id\n" + "".join(f"{i}\n" for i in ids)
    )
```

```pycon
>>> async def count(root):
...     table = AsyncBidsPath(root) / "participants.tsv"
...     return len(await table.get("participant_id"))
>>> async def main():
...     return await asyncio.gather(count("memory://a"), count("memory://b"))
>>> asyncio.run(main())
[2, 1]
```

The pure parts of the path (`name`, `parent`, `entities`, the `with_*`
editors, `/`) remain ordinary synchronous calls on an `AsyncBidsPath`, since
they never wait for anything.

## Where to go next

[Reading sidecars and tables](../tutorials/read-metadata.md) uses these paths
to read the content of a dataset, and
[Sidecar inheritance](inheritance.md) explains the rules that connect a file to
its sidecars. The full list of members is in the reference for
[`BidsPath`](../api/paths.md#brainfilter.BidsPath),
[`PureBidsPath`](../api/paths.md#brainfilter.PureBidsPath) and
[`AsyncBidsPath`](../api/paths.md#brainfilter.AsyncBidsPath).
