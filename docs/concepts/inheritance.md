# Sidecar inheritance

A BIDS dataset describes an image with JSON sidecars, but it does not ask you
to write one sidecar per image. The *inheritance principle* lets a file with
fewer entities in its name, placed higher in the tree, describe every file
below it that it matches. A repetition time written once at the root applies to
every `bold` image of the dataset, and a subject's sidecar can override it for
that subject alone. brainfilter implements this principle in one place, and the
same rules decide two things: what `sidecars` and `sidecar` return for a file,
and which metadata files a [`Filter`](../api/filtering.md#brainfilter.Filter)
keeps along with the data files it selects.

## Which sidecars apply to a file

A JSON file is a sidecar of a data file when all of the following hold.

1. **It is in the data file's directory or in one of its ancestors**, up to the
   dataset root (see [below](#the-dataset-root)).
2. **It is a `.json` file with the same suffix.** The sidecar of
   `sub-01_task-rest_bold.nii.gz` ends in `_bold.json`; a `T1w.json` or an
   `events.json` does not describe a `bold` image.
3. **Every entity in its name is in the data file's name, with the same
   label.** The sidecar may have fewer entities than the data file, never more
   and never different ones. `task-rest_bold.json` applies to a file with
   `sub-01`, `task-rest` and `run-1`, but not to one with `task-other`.
4. **Index entities are compared by number.** `run`, `echo`, `flip`, `inv`,
   `split` and `chunk` are numbers, so `run-1` and `run-01` are the same run.
   Every other entity, such as `sub`, `task` or `acq`, is compared as text.

The suffix is the last part of the name before the extension (`bold`, `T1w`),
and the entities are the `key-label` parts before it. If those words are new,
[Paths and storage backends](paths-and-backends.md) shows how a name is taken
apart. Two sets of entities can also be compared directly with the operators
`<` and `>`, which read as "inherits from": a name with more entities is
smaller than a more general one that it matches. Unlike the rule above, this
comparison reads labels as written, so it does not equate `run-1` and `run-01`.

```pycon
>>> from brainfilter import PureBidsPath
>>> general = PureBidsPath("task-rest_bold.json").entities
>>> specific = PureBidsPath("sub-01_task-rest_run-1_bold.json").entities
>>> specific < general, general > specific
(True, True)
```

The data file itself is never its own sidecar, and a file with no BIDS suffix
(a `README`, or a name that is not a BIDS name) has no sidecars at all.

## The order: nearest first

When several sidecars apply, the order matters, because the first one that has
a key decides its value. brainfilter lists them in the order of closeness:

1. **A closer directory comes first.** Sidecars in the data file's own
   directory come before those in its parent, and so on up to the root.
2. **Within one directory, more entities come first.** A sidecar that names
   more of the file's entities is more specific, so it comes before a more
   general one. Sidecars with the same number of entities are ordered by name.

Here is a dataset where six sidecars apply to the same image. The comments mark
what applies and what does not.

```text
ds/
├── dataset_description.json
├── bold.json                              applies (fifth)
├── task-rest_bold.json                    applies (fourth)
├── task-other_bold.json                   other task
├── T1w.json                               other suffix
└── sub-01/
    ├── sub-01_task-rest_bold.json         applies (third)
    ├── sub-02_task-rest_bold.json         other subject
    └── func/
        ├── task-rest_bold.json            applies (second)
        ├── sub-01_task-rest_run-1_bold.json   applies (first)
        ├── sub-01_task-rest_run-2_bold.json   other run
        ├── sub-01_task-rest_run-01_bold.nii.gz   the data file
        └── sub-01_task-rest_run-02_bold.nii.gz
```

Reading the sidecars of the first run confirms the order. The `run-1` sidecar
is in the file's own directory and has three entities, so it comes first; the
more general `task-rest_bold.json` in the same directory comes next, and then
the files in `sub-01/` and at the root. The directory outweighs the number of
entities: the subject-level file, with two entities, comes after the
one-entity file of the `func` directory because it is further away.

```python
from brainfilter import BidsPath

w = BidsPath("memory://inherit", mode="w")
w["dataset_description.json"] = {"Name": "Inheritance", "BIDSVersion": "1.9.0"}
w["bold.json"] = {"Manufacturer": "ACME", "RepetitionTime": 3.0}
w["task-rest_bold.json"] = {"TaskName": "rest", "RepetitionTime": 2.0}
w["task-other_bold.json"] = {"TaskName": "other"}
w["T1w.json"] = {"Unrelated": 1}
sub = w / "sub-01"
sub["sub-01_task-rest_bold.json"] = {"RepetitionTime": 2.5, "EchoTime": 0.03}
sub["sub-02_task-rest_bold.json"] = {"RepetitionTime": 9}
func = sub / "func"
func["task-rest_bold.json"] = {"SliceTiming": [0, 1]}
func["sub-01_task-rest_run-1_bold.json"] = {"RepetitionTime": 1.5}
func["sub-01_task-rest_run-2_bold.json"] = {"Run": 2}
(func / "sub-01_task-rest_run-01_bold.nii.gz").write_bytes(b"")
(func / "sub-01_task-rest_run-02_bold.nii.gz").write_bytes(b"")
```

```pycon
>>> ds = BidsPath("memory://inherit")
>>> image = ds["sub-01"]["func"]["sub-01_task-rest_run-01_bold.nii.gz"]
>>> for sidecar in image.sidecars:
...     print(sidecar.relative_to(ds))
sub-01/func/sub-01_task-rest_run-1_bold.json
sub-01/func/task-rest_bold.json
sub-01/sub-01_task-rest_bold.json
task-rest_bold.json
bold.json
```

Because `run-01` and `run-1` are compared as numbers, the `run-1` sidecar
applies to `run-01`, and `run-2` does not. The second image, `run-02`, picks up
the `run-2` sidecar instead of `run-1`.

```pycon
>>> other = ds["sub-01"]["func"]["sub-01_task-rest_run-02_bold.nii.gz"]
>>> other.sidecars[0].name
'sub-01_task-rest_run-2_bold.json'
```

## What the merged sidecar contains

The `sidecar` property is built from these files in the same order. A key is
looked up in the nearest file that has it, so a value written closer to the
image hides the same key written higher up. A key that only a farther file has
is still visible. For the first run, `RepetitionTime` comes from the
`run-1` sidecar, `EchoTime` from the subject level, and `Manufacturer` from the
root.

```pycon
>>> image.sidecar["RepetitionTime"]
1.5
>>> image.sidecar.as_dict()
{'Manufacturer': 'ACME', 'RepetitionTime': 1.5, 'TaskName': 'rest', 'EchoTime': 0.03, 'SliceTiming': [0, 1]}
```

Nothing is merged recursively. If a nearer file has a key whose value is a
dictionary, that dictionary replaces the farther one as a whole.

## The dataset root

The search upwards stops at the dataset root, which is the nearest ancestor
directory that holds a `dataset_description.json`. A sidecar that sits above
the root, in a directory that merely contains the dataset, is never considered.
This keeps a stray `bold.json` in your home directory from leaking into every
dataset below it.

A file with no dataset root above it, such as a loose image in a scratch
directory, has no boundary to stop at. brainfilter then uses only the sidecars
in the file's own directory, and nothing above. If a `dataset_description.json`
later appears, the search covers the ancestors up to it. The example below
shows both cases: the image has one sidecar while it is loose, and two once the
directory above becomes a dataset.

```pycon
>>> w = BidsPath("memory://loose", mode="w")
>>> w["bold.json"] = {"Level": "parent"}
>>> scratch = w / "scratch"
>>> scratch["bold.json"] = {"Level": "own"}
>>> (scratch / "sub-01_bold.nii.gz").write_bytes(b"")
0
>>> loose = BidsPath("memory://loose/scratch/sub-01_bold.nii.gz")
>>> [str(s.relative_to(w)) for s in loose.sidecars]
['scratch/bold.json']
>>> w["dataset_description.json"] = {"Name": "Now a dataset", "BIDSVersion": "1.9.0"}
>>> [str(s.relative_to(w)) for s in loose.sidecars]
['scratch/bold.json', 'bold.json']
```

## What a filter keeps

A [`Filter`](../api/filtering.md#brainfilter.Filter) works on a list of file
names, and it needs the same rules to know which metadata files belong with
the data files it keeps. A metadata file is kept when it applies to at least
one kept data file, so a filter that selects `run-1` of subject `01` also keeps
the sidecars above those images and drops the ones that describe only other
runs, other subjects or other tasks.

The rules of a filter are the ones above with a wider notion of "applies".
Besides the sidecar of the same suffix, a data file also receives its
*companion* files, which have a different suffix: `events.tsv`, `channels.tsv`,
`scans.tsv`, `sessions.tsv`, `physio` recordings and a few others. They are
matched in the same way, by directory, by a subset of the entities and by index
numbers. A companion may also have an entity that the data file cannot have
when that entity names the companion's own space or recording, so that
`sub-01_space-CapTrak_electrodes.tsv` still goes with an EEG recording that
has no `space` in its name. The `sidecar` property leaves companions out, since
an `events.json` describes the events table and not the image.

```pycon
>>> from brainfilter import Filter
>>> listing = [
...     "dataset_description.json", "participants.tsv",
...     "bold.json", "task-rest_bold.json", "task-other_bold.json", "T1w.json",
...     "sub-01/sub-01_task-rest_bold.json", "sub-01/sub-01_scans.tsv",
...     "sub-01/anat/sub-01_T1w.nii.gz",
...     "sub-01/func/sub-01_task-rest_run-1_bold.nii.gz",
...     "sub-01/func/sub-01_task-rest_run-1_bold.json",
...     "sub-01/func/sub-01_task-rest_run-1_events.tsv",
...     "sub-01/func/sub-01_task-rest_run-2_bold.nii.gz",
...     "sub-01/func/sub-01_task-rest_run-2_events.tsv",
...     "sub-02/func/sub-02_task-rest_run-1_bold.nii.gz",
...     "sub-02/sub-02_task-rest_bold.json",
... ]
>>> for name in Filter(subjects="01", tasks="rest", run="01").select(listing):
...     print(name)
bold.json
dataset_description.json
participants.tsv
sub-01/func/sub-01_task-rest_run-1_bold.json
sub-01/func/sub-01_task-rest_run-1_bold.nii.gz
sub-01/func/sub-01_task-rest_run-1_events.tsv
sub-01/sub-01_scans.tsv
sub-01/sub-01_task-rest_bold.json
task-rest_bold.json
```

The filter asked for `run="01"` and matched `run-1`, for the numeric reason
given earlier. Along with the one image and its events file, it kept the
sidecars at the subject and root levels and the subject's `scans.tsv`. It
dropped the anatomical image, the second run, the other subject, and the
sidecars of the other task. Dataset-level files such as `participants.tsv` are
always kept. The filtering rules in full, and the cases where a metadata file
applies to no data file at all, are in
[Filtering a local dataset](../tutorials/filter-local.md).

To see the merged values of a sidecar, rather than which files apply, read
[Reading sidecars and tables](../tutorials/read-metadata.md). A write to
`sidecar` goes to the nearest of the files listed here, and the page on
[editing a dataset](../tutorials/edit-dataset.md) describes it.
