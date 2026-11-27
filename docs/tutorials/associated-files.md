# Companions and fieldmaps

An image rarely makes sense on its own. A functional run comes with the events
of its task and, often, a physiological recording made during the scan; a
diffusion image is useless without its gradient table; and most echo-planar
images have a fieldmap that was acquired to correct their distortions. BIDS
names all of these files so that a program can find them, and brainfilter
finds them for you. The JSON sidecars of a file are described in
[Reading sidecars and tables](read-metadata.md); this page covers the two other
kinds of file that belong with a data file, its *companions* and its
*fieldmaps*.

## A dataset to explore

The examples use one subject with two runs of a resting-state task, a diffusion
image, and four fieldmap images. It is built in memory with `memory://`, which
needs [universal-pathlib](../getting-started/installation.md), and building it
requires a writable path. You can skip this block and open a dataset of your
own instead.

```python
from brainfilter import BidsPath

w = BidsPath("memory://assoc", mode="w")
w["dataset_description.json"] = {"Name": "Associated files", "BIDSVersion": "1.10.0"}
w["task-rest_events.json"] = {"trial_type": {"Description": "The condition"}}

sub = w / "sub-01"
(sub / "sub-01_scans.tsv").write_text("filename\nfunc/sub-01_task-rest_run-1_bold.nii.gz\n")

func = sub / "func"
for run in ("1", "2"):
    (func / f"sub-01_task-rest_run-{run}_bold.nii.gz").write_bytes(b"")
    (func / f"sub-01_task-rest_run-{run}_events.tsv").write_text("onset\tduration\n0\t1\n")
func["sub-01_task-rest_bold.json"] = {"RepetitionTime": 2.0, "B0FieldSource": "pepolar"}
(func / "sub-01_task-rest_run-1_physio.tsv.gz").write_bytes(b"")
func["sub-01_task-rest_run-1_physio.json"] = {"SamplingFrequency": 100}

dwi = sub / "dwi"
(dwi / "sub-01_dwi.nii.gz").write_bytes(b"")
(dwi / "sub-01_dwi.bval").write_text("0 1000 1000\n")
(dwi / "sub-01_dwi.bvec").write_text("0 1 0\n0 0 1\n0 0 0\n")

fmap = sub / "fmap"
runs = [f"func/sub-01_task-rest_run-{run}_bold.nii.gz" for run in ("1", "2")]
for name in ("phasediff", "magnitude1"):
    (fmap / f"sub-01_{name}.nii.gz").write_bytes(b"")
    fmap[f"sub-01_{name}.json"] = {"IntendedFor": runs}
for direction in ("AP", "PA"):
    (fmap / f"sub-01_dir-{direction}_epi.nii.gz").write_bytes(b"")
    fmap[f"sub-01_dir-{direction}_epi.json"] = {
        "B0FieldIdentifier": "pepolar",
        "IntendedFor": "bids::sub-01/dwi/sub-01_dwi.nii.gz",
    }
```

From here on the dataset is opened for reading.

```pycon
>>> ds = BidsPath("memory://assoc")
>>> func = ds["sub-01"]["func"]
>>> run1 = func["sub-01_task-rest_run-1_bold.nii.gz"]
```

## Companion files

A companion is a file that describes a data file without being one of its JSON
sidecars. Most have a suffix of their own: the `events` of a task, the
`physio` and `stim` recordings made during a run, the `channels`,
`electrodes` and `coordsystem` files of an EEG or iEEG recording, the
`aslcontext` of an arterial spin labelling series, and the `scans` and
`sessions` tables. Others share the data file's suffix but are not JSON, such
as the `.bval` and `.bvec` gradient tables of a diffusion image. The
`companions` property of a data file lists every one that applies to it.

```pycon
>>> for path in run1.companions:
...     print(path.relative_to(ds))
sub-01/func/sub-01_task-rest_run-1_events.tsv
sub-01/func/sub-01_task-rest_run-1_physio.json
sub-01/func/sub-01_task-rest_run-1_physio.tsv.gz
sub-01/sub-01_scans.tsv
task-rest_events.json
```

A companion applies to a data file by the same inheritance as a sidecar,
which [Sidecar inheritance](../concepts/inheritance.md) describes: it must be
in the file's own directory or in one above it, up to the dataset root, and
every entity in its name must be in the file's name with the same label. So
the events of the second run are not listed, while the `events.json` at the
root, which names only the task, describes the events of every resting-state
run, including this one. The JSON file of a companion is a companion as well,
because it describes the companion rather than the image: here
`physio.json` describes the physiological recording. The image's own sidecar,
`sub-01_task-rest_bold.json`, is not listed, since `sidecars` already gives
it.

The order is the order of closeness. Files in the data file's own directory
come first, then those in its parent, and so on up to the root, and the files
of one directory are sorted by name.

A diffusion image has its gradient tables among its companions.

```pycon
>>> for path in ds["sub-01"]["dwi"]["sub-01_dwi.nii.gz"].companions:
...     print(path.relative_to(ds))
sub-01/dwi/sub-01_dwi.bval
sub-01/dwi/sub-01_dwi.bvec
sub-01/sub-01_scans.tsv
```

Only a data file has companions. A sidecar, a table or a directory has none,
and its `companions` is an empty tuple.

```pycon
>>> func["sub-01_task-rest_run-1_events.tsv"].companions
()
```

### The same files a filter keeps

A [`BidsFilter`](../api/filtering.md#brainfilter.BidsFilter) keeps the
metadata of the data files it selects by the same rules, so a data file's
`sidecars` and `companions` together are exactly the files that come along
with it. Selecting the first run shows them, next to the dataset-level files
that a filter always keeps.

```pycon
>>> for path in ds.filter(run=1, suffixes="bold"):
...     print(path.relative_to(ds))
dataset_description.json
sub-01/func/sub-01_task-rest_bold.json
sub-01/func/sub-01_task-rest_run-1_bold.nii.gz
sub-01/func/sub-01_task-rest_run-1_events.tsv
sub-01/func/sub-01_task-rest_run-1_physio.json
sub-01/func/sub-01_task-rest_run-1_physio.tsv.gz
sub-01/sub-01_scans.tsv
task-rest_events.json
```

A single-band reference image (`_sbref`) or an M0 scan of an ASL series
(`_m0scan`) is an image in its own right, so it is not a companion of the run
or the series it was acquired with. Select it by its suffix instead.

## Fieldmaps

A fieldmap is an image of a `fmap/` directory that measures the
inhomogeneity of the magnetic field, so that the distortions it causes in
other images can be corrected. BIDS gives two ways to say which images a
fieldmap is meant for, and the `fieldmaps` property of a data file follows
both.

```pycon
>>> for path in run1.fieldmaps:
...     print(path.relative_to(ds))
sub-01/fmap/sub-01_dir-AP_epi.nii.gz
sub-01/fmap/sub-01_dir-PA_epi.nii.gz
sub-01/fmap/sub-01_magnitude1.nii.gz
sub-01/fmap/sub-01_phasediff.nii.gz
```

The phase-difference map and its magnitude image name the run in their
`IntendedFor` field. That field holds one path or a list of them, each either
relative to the subject's directory, as in this dataset
(`func/sub-01_task-rest_run-1_bold.nii.gz`), or a BIDS URI relative to the
dataset root (`bids::sub-01/func/sub-01_task-rest_run-1_bold.nii.gz`), which
recent versions of BIDS recommend. The two phase-encoding images are found the
other way: their `B0FieldIdentifier` is `pepolar`, and the run's sidecar
declares `pepolar` as its `B0FieldSource`. Either field may hold one string or
a list of strings, and a fieldmap is listed once even when both ways find it.

Both fields are read from the merged sidecars, of the fieldmap and of the data
file, so a value inherited from higher up counts as well. The diffusion image
has no `B0FieldSource`, and the phase-encoding images name it with a BIDS
URI, so it gets those two alone.

```pycon
>>> for path in ds["sub-01"]["dwi"]["sub-01_dwi.nii.gz"].fieldmaps:
...     print(path.relative_to(ds))
sub-01/fmap/sub-01_dir-AP_epi.nii.gz
sub-01/fmap/sub-01_dir-PA_epi.nii.gz
```

The fieldmaps of a file are searched for in the `fmap/` directories of its
subject, in every session, and they are sorted by path. An `IntendedFor`
names a file exactly as it is written, so `run-01` there does not name a file
called `run-1`, and an entry that names a file that is not there simply names
nothing. A BIDS URI of another dataset (`bids:<name>:...`) is not followed,
and a BIDS URI cannot be resolved at all without a `dataset_description.json`
above the file.

The result holds the fieldmap images only, not their sidecars. Each one is an
ordinary path, so its own metadata is a `sidecar` away.

```pycon
>>> run1.fieldmaps[0].sidecar["B0FieldIdentifier"]
'pepolar'
```

## In async code

On an [`AsyncBidsPath`](../api/paths.md#brainfilter.AsyncBidsPath) both
properties need I/O, so both are awaited, in the same way as `sidecars`:

```python
from brainfilter import AsyncBidsPath

bold = AsyncBidsPath("memory://assoc/sub-01/func/sub-01_task-rest_run-1_bold.nii.gz")
companions = await bold.companions
fieldmaps = await bold.fieldmaps
```

## Where to go next

The rules that decide what applies to a file are written down in
[Sidecar inheritance](../concepts/inheritance.md), and the filter that keeps a
data file with its sidecars and companions in
[Filtering a local dataset](filter-local.md). The reference for these
properties is [`BidsPath`](../api/paths.md#brainfilter.BidsPath).
