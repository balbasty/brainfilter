# Filtering a local dataset

A [`Filter`][brainfilter.Filter] describes which part of a BIDS dataset you
want. This tutorial builds filters for the situations that come up most often:
picking subjects and sessions, picking a kind of recording, matching on the
entities in a file name, and cutting a selection down with patterns. The
examples use the small dataset from [First steps](../getting-started/first-steps.md)
(the collapsed script on that page creates it), opened as `ds`.

```pycon
>>> from brainfilter import BidsPath, Filter
>>> ds = BidsPath("ds")
```

A filter never changes the dataset, and it holds no reference to one. It is a
set of rules, and `walk()` applies them: it lists the dataset and returns the
files that pass. Since the examples below each try a new set of rules once,
`ds.filter(...)`, which builds the filter from the same keywords and walks the
dataset with it, would do as well; the tutorial spells out `Filter` because
the filter itself is the subject. To keep the output short, the examples below print only the
image files that were selected, through a small helper. Later in the tutorial
the helper is dropped, to look at everything that comes along with the images.

```pycon
>>> def images(files):
...     print(*[p.relative_to(ds).as_posix() for p in files
...             if p.name.endswith(".nii.gz")], sep="\n")
```

## Subjects and sessions

The `subjects` and `sessions` keywords take a label, or a list of labels. A
label can be written with or without its `sub-` or `ses-` prefix.

```pycon
>>> images(Filter(subjects="01", datatypes="anat", suffixes="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
>>> images(Filter(subjects=["sub-01", "sub-02"], datatypes="anat", suffixes="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
```

Labels in BIDS are text, and a subject called `01` is not the same text as
`1`. For the common case of zero-padded numbers, an integer matches by value:
`subjects=1` selects `sub-1`, `sub-01` and `sub-001`, but never `sub-10` or
`sub-1a`. A string, in contrast, matches exactly.

```pycon
>>> images(Filter(subjects=1, datatypes="anat", suffixes="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
>>> images(Filter(subjects="1", datatypes="anat", suffixes="T2w").walk(ds))
```

The second call prints nothing, because the dataset has no subject whose label
is exactly `1`. When you write the label as it appears in the dataset, either
form works, and the integer form is convenient when the labels are only
numbers.

Sessions work in the same way, and combine with subjects. The filter below asks
for the second session of subjects 1 and 10, and only subject 10 has one.

```pycon
>>> images(Filter(subjects=[1, 10], sessions=2, suffixes="T2w").walk(ds))
sub-10/ses-2/anat/sub-10_ses-2_acq-fse_T2w.nii.gz
```

To keep everyone except a few subjects, use `exclude_subjects`:

```pycon
>>> images(Filter(exclude_subjects=[1, 10], datatypes="anat", suffixes="T2w").walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
```

## Datatypes, suffixes and tasks

A *datatype* is the folder a recording lives in (`anat`, `func`, `dwi`, ...),
and a *suffix* is the last part of its name (`T1w`, `bold`, `events`). Both
take a value or a list, and `tasks` selects on the `task-` entity of
functional recordings.

```pycon
>>> images(Filter(subjects=2, datatypes="func").walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
>>> images(Filter(subjects=2, tasks="rest").walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
>>> images(Filter(subjects=2, suffixes=["T1w", "T2w"]).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
```

Filters combine with "and": a file is kept only if it passes every one of
them. This has a consequence worth knowing about. A filter on an entity
rejects the files that do not have that entity at all. Asking for
`tasks="rest"` therefore drops the anatomical images of the subject, since an
anatomical image has no task, and the third example above is the way to ask for
anatomy and function in one go.

## Other entities

Any other entity of the BIDS specification can be given as a keyword of its
own name, such as `acq`, `run`, `echo`, `dir` or `space`.

```pycon
>>> images(Filter(subjects=2, datatypes="anat", acq="mprage").walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
>>> images(Filter(subjects=2, datatypes="anat", run=[2]).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
```

Entities that count things (`run`, `echo`, `flip`, `inv`, `split` and `chunk`)
are always compared by number, so `run=1`, `run="1"` and `run="01"` all select
`run-01`. For the other entities, a string must match the text of the label,
and an integer matches by value, as it does for subjects.

Keywords are checked when the filter is built, so a misspelled entity fails
immediately instead of silently selecting nothing. For an entity that is not
part of the specification, pass a dictionary:
`Filter(entities={"myentity": "value"})`.

## Globs and regexes

A label can also be matched against a pattern. [`Glob`][brainfilter.Glob]
accepts the usual wildcards, and a regular expression is given as a compiled
`re.Pattern` or as a [`Regex`][brainfilter.Regex].

```pycon
>>> from brainfilter import Glob
>>> images(Filter(datatypes="anat", suffixes="T2w", subjects=Glob("0*")).walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
>>> images(Filter(subjects=2, datatypes="anat", acq=Glob("mp*"), run=1).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
```

A pattern is matched against the label without its entity key. For a subject,
that means `01` and not `sub-01`. A regular expression must match the *whole*
label, which differs from the behaviour of `re.search` and is the behaviour
people usually mean. The pattern `1` therefore matches the label `1` and
nothing else; it does not match `01`, and it certainly does not match `10`.

```pycon
>>> import re
>>> images(Filter(subjects=re.compile("0[12]"), datatypes="anat", suffixes="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
>>> images(Filter(subjects=re.compile("1"), datatypes="anat", suffixes="T2w").walk(ds))
```

When a partial match is what you want, say so with `Regex(..., full=False)`,
which finds the pattern anywhere in the label.

```pycon
>>> from brainfilter import Regex
>>> images(Filter(subjects=Regex("1", full=False), datatypes="anat", suffixes="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-10/ses-1/anat/sub-10_ses-1_acq-fse_T2w.nii.gz
sub-10/ses-2/anat/sub-10_ses-2_acq-fse_T2w.nii.gz
```

A list may mix plain values, globs and regexes, and selects a label that
matches any of them.

## Include and exclude

The keywords so far look at the parts of a file name. When a rule is easier to
state about the whole path, `include` and `exclude` match against the path
relative to the dataset root. A string is a glob, which must match the entire
path, and a compiled regex is searched for anywhere in it.

```pycon
>>> images(Filter(subjects=2, include="*/func/*").walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
>>> images(Filter(subjects=2, exclude=re.compile("run-02|task-nback")).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
```

`include` narrows the data files that are selected, and `exclude` is applied
last, to everything that survived, sidecars included. The only file that
`exclude` never removes is `dataset_description.json`, because a dataset
without it is no longer a BIDS dataset.

## Optional folders

BIDS datasets often hold more than raw recordings. `derivatives`, `sourcedata`,
`code` and `stimuli` are left out unless they are requested, which keeps a
default selection to the raw data. Other top-level folders and hidden files,
such as `.datalad`, are never listed.

```pycon
>>> files = Filter(subjects=1, datatypes="anat", suffixes="T2w", folders="derivatives").walk(ds)
>>> print(*[p.relative_to(ds).as_posix() for p in files if "derivatives" in p.parts], sep="\n")
derivatives/fmriprep/dataset_description.json
derivatives/fmriprep/sub-01/anat/sub-01_desc-preproc_T1w.nii.gz
derivatives/fmriprep/sub-01/anat/sub-01_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz
```

A requested folder is kept whole, and the other filters do not apply inside
it. Ask for several folders with a list, such as
`folders=["derivatives", "code"]`; a name outside those four is an error that
lists the valid choices.

## Filtering a derivatives dataset

A pipeline such as fMRIPrep writes its outputs as a BIDS dataset of their own,
inside `derivatives`. To filter those outputs rather than the raw data, open
the derivatives dataset and filter it in the same way. Its folder names and
entities follow BIDS, so every keyword applies, including the entities that
only derivatives use, such as `space` and `desc`.

```pycon
>>> fmriprep = ds["derivatives"]["fmriprep"]
>>> files = fmriprep.filter(subjects=1, space="MNI152NLin2009cAsym", desc="preproc")
>>> print(*[p.relative_to(fmriprep).as_posix() for p in files], sep="\n")
dataset_description.json
sub-01/anat/sub-01_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz
```

The direction matters. A filter run on the raw dataset never descends into
`derivatives`, as the previous section showed, unless the folder is requested
with `folders=["derivatives"]`, and then it is kept whole. Filtering inside
the derivatives dataset is the way to select among its files.

## What comes along with the images

So far the helper has hidden everything but the images. A filter selects
recordings, but a recording is only useful with the files that describe it,
and brainfilter adds those without being asked. Here is the complete result for
the *n*-back recording of one subject.

```pycon
>>> files = Filter(subjects=1, tasks="nback").walk(ds)
>>> print(*[p.relative_to(ds).as_posix() for p in files], sep="\n")
README
dataset_description.json
participants.tsv
sub-01/ses-1/func/sub-01_ses-1_task-nback_bold.json
sub-01/ses-1/func/sub-01_ses-1_task-nback_bold.nii.gz
sub-01/ses-1/func/sub-01_ses-1_task-nback_events.tsv
sub-01/ses-1/sub-01_ses-1_scans.tsv
sub-01/sub-01_sessions.tsv
```

The image is accompanied by its sidecar and its events file, by the `scans.tsv`
and `sessions.tsv` of its subject, and by the three files found at the top of
every dataset. Metadata is kept when it applies to at least one selected
recording, following the [inheritance principle](../concepts/inheritance.md),
and that rule reaches files at any level of the tree. A top-level
`task-rest_bold.json` is left out here, because it describes resting-state
recordings and none was selected, while the same file appears in the result for
`tasks="rest"`. The dataset-level `T1w.json` is left out for the same reason.

A few rules follow BIDS rather than the file extension. Tables that are
recordings in their own right (`*_beh.tsv`, `*_physio.tsv.gz`) are treated as
data, and a recording stored as a folder, such as a CTF `*_meg.ds` or an
OME-Zarr store, is kept or skipped as one unit. The
[`Filter`][brainfilter.Filter] reference gives the complete rules.

## Filtering a listing you already have

`walk()` lists the dataset itself, but a filter can also be applied to a list
of paths obtained some other way, with `select()`. It accepts path strings
relative to the dataset root, which is convenient when the listing comes from a
file, a database or a previous call.

```pycon
>>> listing = [
...     "sub-01/anat/sub-01_acq-mprage_run-1_T1w.nii.gz",
...     "sub-02/anat/sub-02_acq-mprage_run-1_T1w.nii.gz",
... ]
>>> Filter(subjects="01", datatypes="anat", acq=Glob("mp*"), run=[1, 2]).select(listing)
['sub-01/anat/sub-01_acq-mprage_run-1_T1w.nii.gz']
```

The same call accepts path objects together with the `root` they are under,
and returns the items it was given. That is the tool of choice when one
listing serves several filters, as the
[remote tutorial](filter-remote.md#reuse-one-listing-for-several-filters) shows.
Two details apply to `select()`: it expects files, so a list that includes
directories must be reduced with `is_file()` first, and it returns the result
sorted by relative path.

## Where to go next

The [`Filter`][brainfilter.Filter] reference lists every keyword and the
complete selection rules. Reading the selected files, and the sidecars that go
with them, is covered by [Reading sidecars and tables](read-metadata.md), and
running the same filter against a dataset in the cloud only changes the path
you pass, as [Filtering a remote dataset](filter-remote.md) shows.
