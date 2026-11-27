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
image, an arterial spin labelling (ASL) series, an EEG recording, a MEG
recording with the files that describe its set-up, a PET scan with two blood
recordings, a spectroscopy scan, and four fieldmap images. It is built in memory with `memory://`, which
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
(func / "sub-01_task-rest_run-1_sbref.nii.gz").write_bytes(b"")

dwi = sub / "dwi"
(dwi / "sub-01_dwi.nii.gz").write_bytes(b"")
(dwi / "sub-01_dwi.bval").write_text("0 1000 1000\n")
(dwi / "sub-01_dwi.bvec").write_text("0 1 0\n0 0 1\n0 0 0\n")
(dwi / "sub-01_sbref.nii.gz").write_bytes(b"")

perf = sub / "perf"
(perf / "sub-01_asl.nii.gz").write_bytes(b"")
(perf / "sub-01_aslcontext.tsv").write_text("volume_type\ncontrol\nlabel\n")
(perf / "sub-01_m0scan.nii.gz").write_bytes(b"")

eeg = sub / "eeg"
(eeg / "sub-01_task-rest_eeg.edf").write_bytes(b"")
for space in ("CapTrak", "EEGLAB"):
    (eeg / f"sub-01_space-{space}_electrodes.tsv").write_text("name\tx\ty\tz\n")

meg = sub / "meg"
(meg / "sub-01_task-auditory_meg.fif").write_bytes(b"")
(meg / "sub-01_task-auditory_channels.tsv").write_text("name\ttype\tunits\n")
(meg / "sub-01_acq-calibration_meg.dat").write_bytes(b"")
(meg / "sub-01_acq-crosstalk_meg.fif").write_bytes(b"")
(meg / "sub-01_headshape.pos").write_bytes(b"")
(meg / "sub-01_photo.jpg").write_bytes(b"")

pet = sub / "pet"
(pet / "sub-01_trc-FDG_pet.nii.gz").write_bytes(b"")
for recording in ("autosampler", "manual"):
    (pet / f"sub-01_trc-FDG_recording-{recording}_blood.tsv").write_text("time\tplasma_radioactivity\n")
pet["sub-01_trc-FDG_recording-manual_blood.json"] = {"PlasmaAvail": True}

mrs = sub / "mrs"
(mrs / "sub-01_svs.nii.gz").write_bytes(b"")
(mrs / "sub-01_mrsref.nii.gz").write_bytes(b"")

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

Which companions a data file can have depends on how it was acquired. The
table lists them by kind of recording, and two kinds apply to almost every
recording besides: the physiological recordings made at the same time
(`physio`, `physioevents` and `stim`), and the `scans` and `sessions` tables
of its subject.

| Recording                         | Its companions                                                      |
| --------------------------------- | ------------------------------------------------------------------- |
| functional MRI (`func`)           | `events`                                                            |
| diffusion MRI (`dwi`)             | the gradient tables, `.bval` and `.bvec`                            |
| arterial spin labelling (`perf`)  | `aslcontext`, `asllabeling`                                         |
| EEG, iEEG and EMG                 | `events`, `channels`, `electrodes`, `coordsystem`, `photo`          |
| MEG                               | `events`, `channels`, `electrodes`, `coordsystem`, `photo`, `headshape`, `markers`, the calibration and crosstalk files |
| near-infrared spectroscopy        | `events`, `channels`, `optodes`, `coordsystem`, `photo`             |
| motion capture                    | `events`, `channels`                                                |
| PET                               | `events`, `blood`                                                   |
| microscopy                        | `photo`                                                             |
| behaviour and MR spectroscopy     | `events`                                                            |

A few of these are files of their own kind rather than tables or JSON
files: a `photo` of the set-up (a `.jpg`, `.png` or `.tif`), the `headshape`
digitised before a MEG recording and the `markers` of its head coils, and
the two files that a MEG system needs to process its recordings, its
fine-calibration file (`*_acq-calibration_meg.dat`) and its crosstalk file
(`*_acq-crosstalk_meg.fif`). Those two are named like a MEG recording, but
they have no task and they belong to every MEG recording of their subject
or session, whatever acquisition the recording names. A `blood` table, on
the other hand, is a recording in its own right, the radioactivity sampled
from the blood during a PET scan, and it is also a companion of that scan.

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

A MEG recording lists the files of its set-up next to the description of
its channels, and a PET scan its blood recordings, with the JSON file that
describes one of them.

```pycon
>>> for path in ds["sub-01"]["meg"]["sub-01_task-auditory_meg.fif"].companions:
...     print(path.relative_to(ds))
sub-01/meg/sub-01_acq-calibration_meg.dat
sub-01/meg/sub-01_acq-crosstalk_meg.fif
sub-01/meg/sub-01_headshape.pos
sub-01/meg/sub-01_photo.jpg
sub-01/meg/sub-01_task-auditory_channels.tsv
sub-01/sub-01_scans.tsv
>>> pet = ds["sub-01"]["pet"]["sub-01_trc-FDG_pet.nii.gz"]
>>> for path in pet.companions:
...     print(path.relative_to(ds))
sub-01/pet/sub-01_trc-FDG_recording-autosampler_blood.tsv
sub-01/pet/sub-01_trc-FDG_recording-manual_blood.json
sub-01/pet/sub-01_trc-FDG_recording-manual_blood.tsv
sub-01/sub-01_scans.tsv
```

A photo, a head shape or a set of markers may have an acquisition label
that names what it shows rather than how a recording was acquired: the
landmark a photo was taken of (`acq-NAS`, the nasion), the kind of
digitisation of a head shape (`acq-HEAD`), or markers measured before or
after the recording (`acq-pre`, `acq-post`, as MNE-BIDS writes them). So
such a file is matched by its label only when one of the recordings it
would describe has the same label. When none has it, the label describes the
file itself, and the file applies to every recording it matches on its
other entities. Here no recording has `acq-NAS`, so the photo of the nasion
comes along with both recordings, while the head shape labelled `acq-a`
belongs to the recording of that acquisition alone.

```pycon
>>> from brainfilter import BidsFilter
>>> listing = [
...     "dataset_description.json",
...     "sub-01/meg/sub-01_task-rest_acq-a_meg.fif",
...     "sub-01/meg/sub-01_task-rest_acq-b_meg.fif",
...     "sub-01/meg/sub-01_acq-NAS_photo.jpg",
...     "sub-01/meg/sub-01_acq-a_headshape.pos",
... ]
>>> for path in BidsFilter(acq="b").select(listing):
...     print(path)
dataset_description.json
sub-01/meg/sub-01_acq-NAS_photo.jpg
sub-01/meg/sub-01_task-rest_acq-b_meg.fif
```

A diffusion image has its gradient tables among its companions.

```pycon
>>> for path in ds["sub-01"]["dwi"]["sub-01_dwi.nii.gz"].companions:
...     print(path.relative_to(ds))
sub-01/dwi/sub-01_dwi.bval
sub-01/dwi/sub-01_dwi.bvec
sub-01/sub-01_scans.tsv
```

Only a recording has companions. A sidecar, a table, a photo or a directory
has none, and its `companions` is an empty tuple. A MEG crosstalk file has
none either, since it describes recordings rather than being one. A filter
selects such a file when it names it, as the next section shows, but it
brings only its own sidecars along, never the recordings it describes.

```pycon
>>> func["sub-01_task-rest_run-1_events.tsv"].companions
()
>>> ds["sub-01"]["meg"]["sub-01_acq-crosstalk_meg.fif"].companions
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

The files of a MEG set-up come along with the recordings they describe in
the same way, so selecting the MEG recordings brings them along.

```pycon
>>> for path in ds.filter(datatypes="meg"):
...     print(path.relative_to(ds))
dataset_description.json
sub-01/meg/sub-01_acq-calibration_meg.dat
sub-01/meg/sub-01_acq-crosstalk_meg.fif
sub-01/meg/sub-01_headshape.pos
sub-01/meg/sub-01_photo.jpg
sub-01/meg/sub-01_task-auditory_channels.tsv
sub-01/meg/sub-01_task-auditory_meg.fif
sub-01/sub-01_scans.tsv
```

A companion is also a file in its own right, and a filter that names it
selects it, with its own sidecars and without the recordings it describes.
Asking for the crosstalk file by its acquisition label keeps that file
alone, and asking for the events keeps the events of both runs.

```pycon
>>> [path.name for path in ds.filter(acq="crosstalk")]
['dataset_description.json', 'sub-01_acq-crosstalk_meg.fif']
>>> for path in ds.filter(suffixes="events"):
...     print(path.relative_to(ds))
dataset_description.json
sub-01/func/sub-01_task-rest_run-1_events.tsv
sub-01/func/sub-01_task-rest_run-2_events.tsv
task-rest_events.json
```

The `events.json` at the root comes along because it is the sidecar of both
events files, while the runs they describe stay behind. The same holds for a
blood recording, which a filter keeps with its PET scan and also selects by
its own suffix, without the scan.

```pycon
>>> for path in ds.filter(suffixes="blood"):
...     print(path.relative_to(ds))
dataset_description.json
sub-01/pet/sub-01_trc-FDG_recording-autosampler_blood.tsv
sub-01/pet/sub-01_trc-FDG_recording-manual_blood.json
sub-01/pet/sub-01_trc-FDG_recording-manual_blood.tsv
sub-01/sub-01_scans.tsv
```

A single-band reference image (`_sbref`), an M0 scan of an ASL series
(`_m0scan`) or the reference scan of a spectroscopy scan (`_mrsref`) is an
image in its own right, so it is not a companion of the image it was
acquired with. A filter selects it by its suffix, and `companion`, below,
finds the one that belongs to an image.

## One companion at a time

Most of the time you want one particular companion rather than all of them:
the events of a run, or the gradient table of a diffusion image. The
`companion` method takes the suffix of the file you want and returns that
file, or `None` when there is none.

```pycon
>>> run1.companion("events").name
'sub-01_task-rest_run-1_events.tsv'
>>> print(run1.companion("channels"))
None
```

It follows the same inheritance as `companions`, and returns the nearest
match: a file in the run's own directory if there is one, else one in a
directory above it. A table or a recording is the file itself, not the JSON
that describes it, so the events above are the `.tsv` of the run, and neither
`physio.json` nor the `events.json` at the root of the dataset. That JSON
file is one of the recording's own sidecars.

```pycon
>>> physio = run1.companion("physio")
>>> physio.name
'sub-01_task-rest_run-1_physio.tsv.gz'
>>> physio.sidecars[0].name
'sub-01_task-rest_run-1_physio.json'
```

The gradient tables of a diffusion image are named by their extension,
`bval` and `bvec`, since they share the image's suffix, and the two system
files of a MEG recording by their acquisition label, `calibration` and
`crosstalk`. A photo, a head shape or a set of markers is named by its
suffix like any other companion.

```pycon
>>> meg = ds["sub-01"]["meg"]["sub-01_task-auditory_meg.fif"]
>>> meg.companion("crosstalk").name
'sub-01_acq-crosstalk_meg.fif'
>>> meg.companion("headshape").name
'sub-01_headshape.pos'
```

A single-band reference, an M0 scan and the reference scan of a
spectroscopy scan are named by their suffix, `sbref`, `m0scan` and `mrsref`.
They are not companions, so they are not inherited: each is the image in
the same directory whose name has the same entities, so the second run, which
was acquired without one, has none. A run number is compared by value, so
`run-1` and `run-01` name the same run.

```pycon
>>> dwi = ds["sub-01"]["dwi"]["sub-01_dwi.nii.gz"]
>>> dwi.companion("bval").read_text()
'0 1000 1000\n'
>>> run1.companion("sbref").name
'sub-01_task-rest_run-1_sbref.nii.gz'
>>> print(func["sub-01_task-rest_run-2_bold.nii.gz"].companion("sbref"))
None
>>> ds["sub-01"]["mrs"]["sub-01_svs.nii.gz"].companion("mrsref").name
'sub-01_mrsref.nii.gz'
```

### Shortcuts

A diffusion image, a functional run and an ASL series each have a property
for the companions they are rarely used without, which returns the same file
as `companion`:

| File           | Properties               |
| -------------- | ------------------------ |
| `*_dwi.nii.gz` | `bval`, `bvec`, `sbref`  |
| `*_bold.nii.gz`| `events`, `sbref`        |
| `*_asl.nii.gz` | `aslcontext`, `m0scan`   |

```pycon
>>> dwi.bval.name, dwi.bvec.name, dwi.sbref.name
('sub-01_dwi.bval', 'sub-01_dwi.bvec', 'sub-01_sbref.nii.gz')
>>> run1.events == run1.companion("events")
True
>>> asl = ds["sub-01"]["perf"]["sub-01_asl.nii.gz"]
>>> asl.aslcontext.name, asl.m0scan.name
('sub-01_aslcontext.tsv', 'sub-01_m0scan.nii.gz')
```

A property exists only where it makes sense, so a diffusion image has no
`events` and a run has no `bval`. Use `companion` for any other file.

```pycon
>>> hasattr(dwi, "events")
False
```

### When more than one file matches

Sometimes two files of the same kind apply to a data file from the same
directory. The positions of EEG electrodes, for instance, may be given in
several coordinate systems, each in a file of its own. `companion` cannot
choose between them, so it raises an error that lists them.

```pycon
>>> eeg = ds["sub-01"]["eeg"]["sub-01_task-rest_eeg.edf"]
>>> eeg.companion("electrodes")
Traceback (most recent call last):
  ...
ValueError: sub-01_task-rest_eeg.edf has 2 'electrodes' companions in 'memory://assoc/sub-01/eeg': sub-01_space-CapTrak_electrodes.tsv, sub-01_space-EEGLAB_electrodes.tsv; name the one you want by an entity, e.g. companion('electrodes', space='CapTrak')
```

Name the one you want by an entity, as a keyword. Only a file with that
entity, and that label, is then considered, and a label of `None` asks for
a file without the entity.

```pycon
>>> eeg.companion("electrodes", space="EEGLAB").name
'sub-01_space-EEGLAB_electrodes.tsv'
```

Blood recordings are told apart in the same way, by the `recording` entity
that names how each was sampled.

```pycon
>>> pet.companion("blood", recording="manual").name
'sub-01_trc-FDG_recording-manual_blood.tsv'
```

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

On an [`AsyncBidsPath`](../api/paths.md#brainfilter.AsyncBidsPath) all of
these need I/O, so all of them are awaited, in the same way as `sidecars`:
the two properties, `companion`, and the shortcuts.

```python
from brainfilter import AsyncBidsPath

bold = AsyncBidsPath("memory://assoc/sub-01/func/sub-01_task-rest_run-1_bold.nii.gz")
companions = await bold.companions
fieldmaps = await bold.fieldmaps
physio = await bold.companion("physio")
events = await bold.events
```

## Where to go next

The rules that decide what applies to a file are written down in
[Sidecar inheritance](../concepts/inheritance.md), and the filter that keeps a
data file with its sidecars and companions in
[Filtering a local dataset](filter-local.md). The reference for these
properties and for `companion` is
[`BidsPath`](../api/paths.md#brainfilter.BidsPath).
