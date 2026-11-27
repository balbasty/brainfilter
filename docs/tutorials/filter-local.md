# Filtering a local dataset

A [`BidsFilter`][brainfilter.BidsFilter] describes which part of a BIDS dataset you
want. This tutorial builds filters for the situations that come up most often:
picking subjects and sessions, picking a kind of recording, matching on the
entities in a file name, on the values in the sidecars and on the
participants table, and cutting a selection down with patterns. The
examples use the small dataset from [First steps](../getting-started/first-steps.md)
(the collapsed script on that page creates it), opened as `ds`.

```pycon
>>> from brainfilter import BidsPath, BidsFilter
>>> ds = BidsPath("ds")
```

A filter never changes the dataset, and it holds no reference to one. It is a
set of rules, and `walk()` applies them: it lists the dataset and returns the
files that pass. Since the examples below each try a new set of rules once,
`ds.filter(...)`, which builds the filter from the same keywords and walks the
dataset with it, would do as well; the tutorial spells out `BidsFilter` because
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
>>> images(BidsFilter(sub="01", datatype="anat", suffix="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
>>> images(BidsFilter(sub=["sub-01", "sub-02"], datatype="anat", suffix="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
```

Labels in BIDS are text, and a subject called `01` is not the same text as
`1`. For the common case of zero-padded numbers, an integer matches by value:
`sub=1` selects `sub-1`, `sub-01` and `sub-001`, but never `sub-10` or
`sub-1a`. A string, in contrast, matches exactly.

```pycon
>>> images(BidsFilter(sub=1, datatype="anat", suffix="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
>>> images(BidsFilter(sub="1", datatype="anat", suffix="T2w").walk(ds))
```

The second call prints nothing, because the dataset has no subject whose label
is exactly `1`. When you write the label as it appears in the dataset, either
form works, and the integer form is convenient when the labels are only
numbers.

Sessions work in the same way, and combine with subjects. The filter below asks
for the second session of subjects 1 and 10, and only subject 10 has one.

```pycon
>>> images(BidsFilter(sub=[1, 10], ses=2, suffix="T2w").walk(ds))
sub-10/ses-2/anat/sub-10_ses-2_acq-fse_T2w.nii.gz
```

To keep everyone except a few subjects, wrap them in `Not`, which keeps
whatever the value it is given does not:

```pycon
>>> from brainfilter import Not
>>> images(BidsFilter(sub=Not([1, 10]), datatype="anat", suffix="T2w").walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
```

## Datatypes, suffixes and tasks

A *datatype* is the folder a recording lives in (`anat`, `func`, `dwi`, ...),
and a *suffix* is the last part of its name (`T1w`, `bold`, `events`). Both
take a value or a list, and `task` selects on the `task-` entity of
functional recordings.

```pycon
>>> images(BidsFilter(sub=2, datatype="func").walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
>>> images(BidsFilter(sub=2, task="rest").walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
>>> images(BidsFilter(sub=2, suffix=["T1w", "T2w"]).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
```

Filters combine with "and": a file is kept only if it passes every one of
them. This has a consequence worth knowing about. A filter on an entity
rejects the files that do not have that entity at all. Asking for
`task="rest"` therefore drops the anatomical images of the subject, since an
anatomical image has no task, and the third example above is the way to ask for
anatomy and function in one go.

## Other entities

Any other entity of the BIDS specification can be given as a keyword of its
own name, such as `acq`, `run`, `echo`, `dir` or `space`.

```pycon
>>> images(BidsFilter(sub=2, datatype="anat", acq="mprage").walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
>>> images(BidsFilter(sub=2, datatype="anat", run=[2]).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
```

Entities that count things (`run`, `echo`, `flip`, `inv`, `split` and `chunk`)
are always compared by number, so `run=1`, `run="1"` and `run="01"` all select
`run-01`. For the other entities, a string must match the text of the label,
and an integer matches by value, as it does for subjects.

Keywords are checked when the filter is built, so a misspelled entity fails
immediately instead of silently selecting nothing. For an entity that is not
part of the specification, pass a dictionary:
`BidsFilter(entities={"myentity": "value"})`.

## Globs and regexes

A label can also be matched against a pattern. [`Glob`][brainfilter.Glob]
accepts the usual wildcards, and a regular expression is given as a compiled
`re.Pattern` or as a [`Regex`][brainfilter.Regex].

```pycon
>>> from brainfilter import Glob
>>> images(BidsFilter(datatype="anat", suffix="T2w", sub=Glob("0*")).walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
>>> images(BidsFilter(sub=2, datatype="anat", acq=Glob("mp*"), run=1).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
```

A pattern is matched against the label without its entity key. For a subject,
that means `01` and not `sub-01`. A regular expression must match the *whole*
label, which differs from the behaviour of `re.search` and is the behaviour
people usually mean. The pattern `1` therefore matches the label `1` and
nothing else; it does not match `01`, and it certainly does not match `10`.

```pycon
>>> import re
>>> images(BidsFilter(sub=re.compile("0[12]"), datatype="anat", suffix="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
>>> images(BidsFilter(sub=re.compile("1"), datatype="anat", suffix="T2w").walk(ds))
```

When a partial match is what you want, say so with `Regex(..., full=False)`,
which finds the pattern anywhere in the label.

```pycon
>>> from brainfilter import Regex
>>> images(BidsFilter(sub=Regex("1", full=False), datatype="anat", suffix="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-10/ses-1/anat/sub-10_ses-1_acq-fse_T2w.nii.gz
sub-10/ses-2/anat/sub-10_ses-2_acq-fse_T2w.nii.gz
```

A list may mix plain values, globs and regexes, and selects a label that
matches any of them. A set does the same, and so does a function that takes
the label and says whether it matches, such as
`run=lambda run: int(run) > 1`.

## With or without an entity

A filter on an entity keeps only the files that have it, as the section on
tasks pointed out. Sometimes the files you want are precisely those without
it, or those with it whatever its label. The markers of the standard `typing`
module say so: `Never` selects the files that do not have the entity, and
`Any` the files that have it with any label. Here are the images of subject 2
with no run number, and then those with one.

```pycon
>>> from typing import Any, Never
>>> images(BidsFilter(sub=2, run=Never).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
>>> images(BidsFilter(sub=2, run=Any).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
```

`typing.Required` means the same as `Any`. On an entity keyword such as
`run` or `acq`, `None` means the same as `Never`, since a label is never
empty, and the same holds for `datatype`, `suffix` and `extension`:
`datatype=None` keeps the files that are not in a datatype folder. A
keyword you leave out applies no filter, so pass nothing, not `None`, when
you do not want to filter on it. On Python 3.10, which
lacks `Never` and `Required`, import them from `typing_extensions`. A marker
can sit in a set beside ordinary values. The filter below keeps the images that have no
acquisition label, together with those acquired with the `fse` sequence.

```pycon
>>> images(BidsFilter(sub=2, acq={Never, "fse"}).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
```

`Not` turns any of these values around. A file that lacks the entity
passes `Not(x)` unless `x` itself keeps such a file, so `acq=Not("fse")`
keeps the images with no acquisition label as well as the others, while
`Not(Never)` keeps exactly the files that have the entity, as `Any` does.
`Not` goes around the whole value, `Not({"fse", "mprage"})`, and works on
the sidecar and participants filters as well.

```pycon
>>> images(BidsFilter(sub=2, acq=Not("fse")).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
```

## Values in the sidecars

The parameters of a recording live in its JSON sidecars, and a filter can
select on them too. A keyword that starts with a capital letter names a
sidecar field, and the value it is compared with is the one the
recording's merged sidecar holds, the nearest sidecar winning as it does for
[`sidecar`](read-metadata.md). In the example dataset, the resting-state
recordings take their repetition time of 2 seconds from the top-level
`task-rest_bold.json`, while the *n*-back recordings have sidecars of their
own that say 1.5.

```pycon
>>> images(BidsFilter(sub=2, RepetitionTime=1.5).walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
>>> images(BidsFilter(sub=2, RepetitionTime=2).walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
```

A plain value is compared with `==`, so the integer `2` matches the `2.0` of
the sidecar, while a string has to match exactly. A function of the value
expresses a condition, and the markers of the previous section ask whether a
field is there at all.

```pycon
>>> images(BidsFilter(sub=2, EchoTime=lambda echo: echo < 0.01).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
>>> images(BidsFilter(sub=2, RepetitionTime=Never).walk(ds))
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-01_T1w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-mprage_run-02_T1w.nii.gz
```

The function is only asked about recordings that have the field, and one that
fails on a value of the wrong type (a comparison between a number and a
string, say) does not match it rather than stopping the walk. Two forms
differ from the label filters, because a sidecar value need not be text. A
list is a value in its own right, compared as a whole, so
`SliceTiming=[0.0, 0.5]` selects the recordings with exactly those slice
times; to accept one of several values, put them in a set, as in
`PhaseEncodingDirection={"j", "j-"}`. And `None` matches a field whose value
is the JSON `null`, while `Never` matches one that is absent. A field whose
name is not a valid keyword goes in a dictionary instead:
`BidsFilter(sidecar={"Field-Name": 1})`.

A sidecar filter decides which recordings are kept, and the metadata that
goes with them follows as usual. The sidecars are read only for the
recordings that pass every other filter, and each file is read once.

## Participants

The `participants` keyword filters on the columns of `participants.tsv`, and
keeps the recordings of the subjects whose row passes every condition. The
values take the same forms as for sidecars, and they are compared with the
typed values of the table, so the ages below are numbers.

```pycon
>>> images(BidsFilter(participants={"age": lambda age: age > 28}, suffix="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-02/ses-1/anat/sub-02_ses-1_acq-fse_T2w.nii.gz
>>> images(BidsFilter(participants={"sex": "F"}, suffix="T2w").walk(ds))
sub-01/ses-1/anat/sub-01_ses-1_acq-fse_T2w.nii.gz
sub-10/ses-1/anat/sub-10_ses-1_acq-fse_T2w.nii.gz
sub-10/ses-2/anat/sub-10_ses-2_acq-fse_T2w.nii.gz
```

A cell written `n/a` reads as `None`, so `None` selects the subjects whose
value is missing, and a condition on the value does not match them. `Any`
asks for the column to exist, and `Never` for it not to. A subject that has
no row in the table is left out, and the filter combines with `subjects` and
the other keywords: a recording is kept only if it passes them all. A dataset
without a `participants.tsv` cannot answer the question, and filtering it on
participants raises `FileNotFoundError`.

## Include and exclude

The keywords so far look at the parts of a file name. When a rule is easier to
state about the whole path, `include` and `exclude` match against the path
relative to the dataset root. A string is a glob, which must match the entire
path, and a compiled regex is searched for anywhere in it.

```pycon
>>> images(BidsFilter(sub=2, include="*/func/*").walk(ds))
sub-02/ses-1/func/sub-02_ses-1_task-nback_bold.nii.gz
sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz
>>> images(BidsFilter(sub=2, exclude=re.compile("run-02|task-nback")).walk(ds))
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
>>> files = BidsFilter(sub=1, datatype="anat", suffix="T2w", folders="derivatives").walk(ds)
>>> print(*[p.relative_to(ds).as_posix() for p in files if "derivatives" in p.parts], sep="\n")
derivatives/fmriprep/dataset_description.json
derivatives/fmriprep/sub-01/anat/sub-01_desc-preproc_T1w.nii.gz
derivatives/fmriprep/sub-01/anat/sub-01_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz
```

A requested folder is kept whole, and the other filters do not apply inside
it. Ask for several folders with a list, such as
`folders=["derivatives", "code"]`; a name outside those four is an error that
lists the valid choices.

## Files the dataset ignores

A dataset can name files that the BIDS validator should not check in a
`.bidsignore` file at its root, written with the same patterns as a
`.gitignore`. Lines starting with `#` are comments, a pattern ending in `/`
names folders, a pattern containing a `/` is matched from the dataset root,
`**` stands for any number of folders, and a pattern starting with `!` brings
back a file that an earlier pattern left out. A dataset with the `.bidsignore`
below keeps its notes and its scanner logs out of every selection.

```text
# not part of the BIDS dataset
*_notes.txt
sub-*/logs/
```

A filter reads `.bidsignore` to decide which files are recordings to select,
and never to decide which metadata applies. A recording that it names is
never selected, and a folder that it names is only looked into when the
filter needs to know what the folder holds. A metadata file that it names
still describes the recordings it applies to: an ignored sidecar, events table
or `.bval` file counts for a filter on sidecar values, and comes along with
the recordings it describes, exactly as `path.sidecars` finds it. Ignored
metadata, or an ignored companion such as an events table, is never kept on
its own account, though, so it is left out when it describes no kept
recording. Dataset-level files, such as `participants.tsv`,
`README` and `phenotype/`, are kept whether `.bidsignore` names them or not,
and an ignored `participants.tsv` is still read by a filter on participants.

To
see the files that the dataset ignores, build the filter with
`bidsignore=False`.

## Filtering a derivatives dataset

A pipeline such as fMRIPrep writes its outputs as a BIDS dataset of their own,
inside `derivatives`. To filter those outputs rather than the raw data, open
the derivatives dataset and filter it in the same way. Its folder names and
entities follow BIDS, so every keyword applies, including the entities that
only derivatives use, such as `space` and `desc`.

```pycon
>>> fmriprep = ds["derivatives"]["fmriprep"]
>>> files = fmriprep.filter(sub=1, space="MNI152NLin2009cAsym", desc="preproc")
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
>>> files = BidsFilter(sub=1, task="nback").walk(ds)
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
`task="rest"`. The dataset-level `T1w.json` is left out for the same reason.

A few rules follow BIDS rather than the file extension. Tables that are
recordings in their own right (`*_beh.tsv`, `*_physio.tsv.gz`) are treated as
data, and a recording stored as a folder, such as a CTF `*_meg.ds` or an
OME-Zarr store, is kept or skipped as one unit. A file with a suffix of its
own that describes other recordings, such as an events table, a
`*_photo.jpg` of the electrodes, the `*_headshape.pos` of a MEG session and
its crosstalk and fine-calibration files, is kept with the recordings it
describes, as metadata is, and is also a file a filter can select on its
own: `suffix="events"` keeps the events tables (with their JSON files)
without the images, and `acq="crosstalk"` the crosstalk files. The
[`BidsFilter`][brainfilter.BidsFilter] reference gives the complete rules.

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
>>> BidsFilter(sub="01", datatype="anat", acq=Glob("mp*"), run=[1, 2]).select(listing)
['sub-01/anat/sub-01_acq-mprage_run-1_T1w.nii.gz']
```

The same call accepts path objects together with the `root` they are under,
and returns the items it was given. That is the tool of choice when one
listing serves several filters, as the
[remote tutorial](filter-remote.md#reuse-one-listing-for-several-filters) shows.
Two details apply to `select()`: it expects files, so a list that includes
directories must be reduced with `is_file()` first, and it returns the result
sorted by relative path.

Most filters only look at names, so they work on plain strings. The others
need something to read. A filter on participants reads `participants.tsv`
under `root`, a filter on sidecar values reads the sidecars of the listing,
which must then hold path objects, and a `.bidsignore` in the listing is read
when it is a path object or when `root` is given.

## Where to go next

The [`BidsFilter`][brainfilter.BidsFilter] reference lists every keyword and the
complete selection rules. Reading the selected files, and the sidecars that go
with them, is covered by [Reading sidecars and tables](read-metadata.md), and
running the same filter against a dataset in the cloud only changes the path
you pass, as [Filtering a remote dataset](filter-remote.md) shows.
