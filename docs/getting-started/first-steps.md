# First steps

This page opens a small dataset, walks through its folders as if they were a
Python mapping, reads a few metadata files, and ends with a first filter. All
of the code runs against a dataset on local disk, and the same calls work
unchanged on a remote store once a backend is installed (see
[Installation](installation.md)).

To follow along, create the example dataset first. It has three subjects, two
sessions for the last one, anatomical and functional recordings, a few
sidecars, and a `derivatives` folder. The script writes empty placeholder
files where an image would be, which is all the examples need.

??? example "Create the example dataset"

    ```python
    import json
    from pathlib import Path

    root = Path("ds")


    def write(name, text=""):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


    write("dataset_description.json",
          json.dumps({"Name": "Demo", "BIDSVersion": "1.9.0"}))
    write("README", "An example dataset.")
    write("participants.tsv",
          "participant_id\tage\tsex\nsub-01\t30\tF\nsub-02\t41\tM\nsub-10\t25\tF\n")
    write("task-rest_bold.json", json.dumps({"RepetitionTime": 2.0}))
    write("T1w.json", json.dumps({"MagneticFieldStrength": 3}))

    for sub, sessions in [("01", ["1"]), ("02", ["1"]), ("10", ["1", "2"])]:
        write(f"sub-{sub}/sub-{sub}_sessions.tsv", "session_id\nses-1\n")
        for ses in sessions:
            d = f"sub-{sub}/ses-{ses}"
            stem = f"sub-{sub}_ses-{ses}"
            write(f"{d}/{stem}_scans.tsv", "filename\nanat/x.nii.gz\n")
            for run in (1, 2):
                name = f"{d}/anat/{stem}_acq-mprage_run-{run:02d}_T1w"
                write(f"{name}.nii.gz")
                write(f"{name}.json", json.dumps({"EchoTime": 0.003}))
            write(f"{d}/anat/{stem}_acq-fse_T2w.nii.gz")
            for task in ("rest", "nback"):
                write(f"{d}/func/{stem}_task-{task}_bold.nii.gz")
                write(f"{d}/func/{stem}_task-{task}_events.tsv",
                      "onset\tduration\n0\t1\n")
            write(f"{d}/func/{stem}_task-nback_bold.json",
                  json.dumps({"RepetitionTime": 1.5}))

    write("derivatives/fmriprep/dataset_description.json", "{}")
    write("derivatives/fmriprep/sub-01/anat/sub-01_desc-preproc_T1w.nii.gz")
    write("derivatives/fmriprep/sub-01/anat/"
          "sub-01_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz")
    write(".datalad/config")
    ```

## Open a dataset

A dataset is opened by giving [`BidsPath`][brainfilter.BidsPath] a path or a
URL. Nothing is read at this point, so opening a dataset on a slow remote
store costs nothing until the first question is asked of it.

```pycon
>>> from brainfilter import BidsPath
>>> ds = BidsPath("ds")
>>> ds
BidsPath('ds')
```

A `BidsPath` behaves like a [`pathlib.Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) that also knows
about BIDS. It has the usual members (`exists()`, `iterdir()`, `read_text()`,
the `/` operator), and it adds the mapping interface and the BIDS vocabulary
shown below. By default it is read-only: any operation that would change the
storage raises [`ReadOnlyError`][brainfilter.ReadOnlyError]. Writing requires
building the path with `mode="w"`, which is the subject of
[Editing a dataset safely](../tutorials/edit-dataset.md).

## Navigate it like a mapping

A directory is a mapping from the names of its children to the children
themselves. Indexing goes one level down, and `keys()` lists what a directory
holds.

```pycon
>>> ds.keys()
['.datalad', 'README', 'T1w.json', 'dataset_description.json', 'derivatives', 'participants.tsv', 'sub-01', 'sub-02', 'sub-10', 'task-rest_bold.json']
>>> ds["sub-01"].keys()
['ses-1', 'sub-01_sessions.tsv']
>>> anat = ds["sub-01"]["ses-1"]["anat"]
>>> anat.keys()
['sub-01_ses-1_acq-fse_T2w.nii.gz', 'sub-01_ses-1_acq-mprage_run-01_T1w.json', 'sub-01_ses-1_acq-mprage_run-01_T1w.nii.gz', 'sub-01_ses-1_acq-mprage_run-02_T1w.json', 'sub-01_ses-1_acq-mprage_run-02_T1w.nii.gz']
>>> "sub-02" in ds
True
```

The children are themselves `BidsPath` objects, so they can be indexed,
iterated over, or passed to any function that expects a path. Each child also
understands its own file name. BIDS file names are made of *entities*
(`sub-01`, `ses-1`, `run-01`, each a key and a label joined by a dash)
followed by a *suffix* that says what kind of measurement the file holds
(`T1w`, `bold`, `events`). The directory that contains a recording, such as
`anat` or `func`, is its *datatype*.

```pycon
>>> t1w = anat["sub-01_ses-1_acq-mprage_run-01_T1w.nii.gz"]
>>> t1w.entities
{'sub': '01', 'ses': '1', 'acq': 'mprage', 'run': '01'}
>>> t1w.suffix, t1w.datatype
('T1w', 'anat')
>>> t1w.subject, t1w.session
('01', '1')
```

Every read goes back to the storage, so a `BidsPath` never holds a stale
copy of a file. The listing above is therefore as current as the dataset
itself.

## Read the metadata

JSON files behave as mappings of their keys, and TSV files as mappings of
their columns.

```pycon
>>> ds["dataset_description.json"]["Name"]
'Demo'
>>> participants = ds["participants.tsv"]
>>> participants.keys()
['participant_id', 'age', 'sex']
>>> participants["age"]
[30.0, 41.0, 25.0]
>>> participants.as_list()[0]
{'participant_id': 'sub-01', 'age': 30.0, 'sex': 'F'}
```

Columns are typed: `age` was read as numbers, and a cell written as `n/a`
would come back as `None`. The [`Table`][brainfilter.Table] reference lists
the other ways to read a table, including `as_dataframe()` when pandas is
installed.

A recording does not usually carry its own parameters. BIDS stores them in
JSON *sidecars*, and a sidecar higher up the tree applies to every file
below it that does not override it. The `sidecars` property of a file lists
the sidecars that apply to it, nearest first, and `sidecar` merges them into
one mapping in which the nearest value wins.

```pycon
>>> t1w.sidecars
(BidsSidecarFile('ds/sub-01/ses-1/anat/sub-01_ses-1_acq-mprage_run-01_T1w.json'), BidsSidecarFile('ds/T1w.json'))
>>> t1w.sidecar["EchoTime"]
0.003
>>> t1w.sidecar.as_dict()
{'MagneticFieldStrength': 3, 'EchoTime': 0.003}
```

The first sidecar sits next to the image, and the second one is a
dataset-level `T1w.json` that supplies the field strength. The
[inheritance principle](../concepts/inheritance.md) page explains exactly
which sidecars apply to which files.

## Run a first filter

Before selecting anything, it helps to know who is in the dataset.
`subjects()` returns the subject labels, and `sessions()` the session labels,
either across the whole dataset or for one subject. Labels made only of
digits are sorted by value.

```pycon
>>> ds.subjects()
['01', '02', '10']
>>> ds.sessions()
['1', '2']
>>> ds["sub-01"].sessions()
['1']
```

Suppose you want only the T1-weighted images of one subject. The dataset's
`filter()` method takes a description of that selection, lists the dataset,
and returns the files to keep.

```pycon
>>> kept = ds.filter(sub=1, datatype="anat", suffix="T1w")
>>> print(*[p.relative_to(ds).as_posix() for p in kept], sep="\n")
README
T1w.json
dataset_description.json
participants.tsv
sub-01/ses-1/anat/sub-01_ses-1_acq-mprage_run-01_T1w.json
sub-01/ses-1/anat/sub-01_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-01/ses-1/anat/sub-01_ses-1_acq-mprage_run-02_T1w.json
sub-01/ses-1/anat/sub-01_ses-1_acq-mprage_run-02_T1w.nii.gz
sub-01/ses-1/sub-01_ses-1_scans.tsv
sub-01/sub-01_sessions.tsv
```

Two images were requested, yet ten files came back. The extra files are the
ones that describe those two images: the sidecars next to them, the
dataset-level `T1w.json`, the `scans.tsv` and `sessions.tsv` of the subject,
and the files every BIDS dataset needs (`README`, `dataset_description.json`,
`participants.tsv`). A selection that kept the images alone would leave the
recordings impossible to interpret, so brainfilter keeps what applies to them
automatically.

The result is a list of ordinary `BidsPath` objects, still read-only, that can
be read, copied or opened like any other path. Nothing was downloaded to
build it; the only work was listing the directories. That distinction matters
on a remote store, where it is the difference between fetching a few
kilobytes of names and gigabytes of images.

The keywords of `filter()` are those of a
[`BidsFilter`][brainfilter.BidsFilter], which holds the same selection as an object of
its own. Build one when a selection is reused, and pass it to `filter()` or
call its `walk()` method with the dataset; the two give the same files.

```pycon
>>> from brainfilter import BidsFilter
>>> t1w_of_01 = BidsFilter(sub=1, datatype="anat", suffix="T1w")
>>> ds.filter(t1w_of_01) == t1w_of_01.walk(ds) == kept
True
```

The next pages go further with each half of this example.
[Filtering a local dataset](../tutorials/filter-local.md) covers the
conditions a `BidsFilter` accepts, and
[Filtering a remote dataset](../tutorials/filter-remote.md) does the same on a
public dataset in the cloud.
