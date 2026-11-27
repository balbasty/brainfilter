"""A data file's associated files: `companions` and `fieldmaps`."""
import json
import random
import re
import warnings

import pytest

from brainfilter import AsyncBidsPath, BidsFilter, BidsPath, PureBidsPath

BOLD = "sub-01/ses-1/func/sub-01_ses-1_task-rest_run-01_bold.nii.gz"
DWI = "sub-01/ses-1/dwi/sub-01_ses-1_dwi.nii.gz"
ASL = "sub-01/ses-1/perf/sub-01_ses-1_asl.nii.gz"
EEG = "sub-01/ses-1/eeg/sub-01_ses-1_task-rest_eeg.edf"
T1W = "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz"
BOLD2 = "sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz"
BOLD_NOSES = "sub-02/func/sub-02_task-rest_bold.nii.gz"
MEG = "sub-01/ses-1/meg/sub-01_ses-1_task-rest_meg.fif"
MEG_ACQ = "sub-01/ses-1/meg/sub-01_ses-1_task-rest_acq-b_meg.fif"
PET = "sub-01/ses-1/pet/sub-01_ses-1_trc-FDG_pet.nii.gz"
MICR = "sub-01/ses-1/micr/sub-01_ses-1_sample-A_BF.png"

FUNC = "sub-01/ses-1/func/sub-01_ses-1_"
FMAP = "sub-01/ses-1/fmap/sub-01_ses-1_"
MEG_DIR = "sub-01/ses-1/meg/sub-01_ses-1_"
PET_DIR = "sub-01/ses-1/pet/sub-01_ses-1_"
MICR_DIR = "sub-01/ses-1/micr/sub-01_ses-1_"

FILES = {
    "dataset_description.json": {"Name": "associated", "BIDSVersion": "1.10.0"},
    "participants.tsv": "participant_id\nsub-01\nsub-02\n",
    "README": "",
    # dataset level
    "task-rest_events.json": {"trial_type": {}},      # applies to every rest run
    "task-other_events.json": {},                     # another task
    "task-rest_bold.json": {"TaskName": "rest"},      # a sidecar
    "dwi.bval": "0 1000",                             # inherited by every dwi
    # subject level
    "sub-01/sub-01_sessions.tsv": "session_id\nses-1\nses-2\n",
    "sub-01/sub-02_sessions.tsv": "session_id\n",     # another subject
    # session level
    "sub-01/ses-1/sub-01_ses-1_scans.tsv": "filename\n",
    "sub-01/ses-1/sub-01_ses-1_task-rest_events.tsv": "onset\n",
    # func
    BOLD: b"",
    f"{FUNC}task-rest_run-01_bold.json": {"B0FieldSource": ["pd0", "epi0"]},
    f"{FUNC}task-rest_run-1_events.tsv": "onset\n",   # run-1 is run-01
    f"{FUNC}task-rest_run-2_events.tsv": "onset\n",   # another run
    f"{FUNC}task-other_events.tsv": "onset\n",        # another task
    f"{FUNC}task-rest_run-1_recording-cardiac_physio.tsv.gz": b"",
    f"{FUNC}task-rest_run-1_recording-cardiac_physio.json": {},
    f"{FUNC}task-rest_run-1_stim.tsv.gz": b"",
    f"{FUNC}task-rest_run-1_sbref.nii.gz": b"",       # a data file of its own
    f"{FUNC}task-rest_run-1_sbref.json": {},
    # dwi
    DWI: b"",
    "sub-01/ses-1/dwi/sub-01_ses-1_dwi.json": {},
    "sub-01/ses-1/dwi/sub-01_ses-1_dwi.bval": "0 1000",
    "sub-01/ses-1/dwi/sub-01_ses-1_dwi.bvec": "0 1\n0 0\n0 0\n",
    "sub-01/ses-1/dwi/sub-01_ses-1_acq-b_dwi.bval": "0",   # another acq
    # perf
    ASL: b"",
    "sub-01/ses-1/perf/sub-01_ses-1_asl.json": {},
    "sub-01/ses-1/perf/sub-01_ses-1_aslcontext.tsv": "volume_type\n",
    "sub-01/ses-1/perf/sub-01_ses-1_m0scan.nii.gz": b"",
    # eeg
    EEG: b"",
    "sub-01/ses-1/eeg/sub-01_ses-1_task-rest_eeg.json": {},
    "sub-01/ses-1/eeg/sub-01_ses-1_task-rest_channels.tsv": "name\n",
    "sub-01/ses-1/eeg/sub-01_ses-1_space-CapTrak_electrodes.tsv": "name\n",
    "sub-01/ses-1/eeg/sub-01_ses-1_space-CapTrak_coordsystem.json": {},
    # meg: two recordings, the files of the session's set-up
    MEG: b"",
    MEG_ACQ: b"",
    f"{MEG_DIR}task-rest_meg.json": {},
    f"{MEG_DIR}task-rest_channels.tsv": "name\n",
    f"{MEG_DIR}acq-calibration_meg.dat": b"",
    f"{MEG_DIR}acq-crosstalk_meg.fif": b"",
    f"{MEG_DIR}headshape.pos": b"",
    f"{MEG_DIR}photo.jpg": b"",
    f"{MEG_DIR}acq-NAS_photo.jpg": b"",          # no recording has acq-NAS
    f"{MEG_DIR}acq-b_headshape.pos": b"",         # MEG_ACQ has acq-b
    f"{MEG_DIR}task-rest_markers.mrk": b"",
    f"{MEG_DIR}task-other_markers.mrk": b"",      # another task
    # pet: two blood recordings of the tracer
    PET: b"",
    f"{PET_DIR}trc-FDG_pet.json": {},
    f"{PET_DIR}trc-FDG_recording-manual_blood.tsv": "time\n",
    f"{PET_DIR}trc-FDG_recording-manual_blood.json": {},
    f"{PET_DIR}trc-FDG_recording-auto_blood.tsv": "time\n",
    f"{PET_DIR}trc-other_recording-manual_blood.tsv": "time\n",  # another
    # micr: a photo of the sample, with its JSON
    MICR: b"",
    f"{MICR_DIR}sample-A_photo.jpg": b"",
    f"{MICR_DIR}sample-A_photo.json": {},
    f"{MICR_DIR}sample-B_photo.jpg": b"",         # another sample
    # anat
    T1W: b"",
    # fieldmaps of session 1
    f"{FMAP}phasediff.nii.gz": b"",
    f"{FMAP}phasediff.json": {       # found both ways, listed once
        "B0FieldIdentifier": "pd0",
        "IntendedFor": "ses-1/func/sub-01_ses-1_task-rest_run-01_bold.nii.gz",
    },
    f"{FMAP}magnitude1.nii.gz": b"",
    f"{FMAP}magnitude1.json": {"B0FieldIdentifier": "pd0"},
    f"{FMAP}dir-AP_epi.nii.gz": b"",
    f"{FMAP}dir-AP_epi.json": {"IntendedFor": [
        f"bids::{BOLD}",
        f"bids::{DWI}",
    ]},
    f"{FMAP}dir-PA_epi.nii.gz": b"",
    f"{FMAP}dir-PA_epi.json": {"B0FieldIdentifier": ["epi0", "other"]},
    f"{FMAP}fieldmap.nii.gz": b"",
    f"{FMAP}fieldmap.json": {         # names nothing that applies
        "IntendedFor": ["ses-1/func/sub-01_ses-1_task-rest_run-02_bold.nii.gz",
                        "bids::sub-01/ses-1/func/missing_bold.nii.gz", 3],
        "B0FieldIdentifier": "unused",
    },
    f"{FMAP}acq-ext_epi.nii.gz": b"",
    f"{FMAP}acq-ext_epi.json": {       # another dataset's file of that name
        "IntendedFor": f"bids:other:{BOLD}",
    },
    # session 2: a fieldmap shared across sessions by its identifier
    BOLD2: b"",
    "sub-01/ses-2/fmap/sub-01_ses-2_dir-AP_epi.nii.gz": b"",
    "sub-01/ses-2/fmap/sub-01_ses-2_dir-AP_epi.json": {
        "B0FieldIdentifier": "epi0",
    },
    # a subject without sessions: IntendedFor relative to the subject
    BOLD_NOSES: b"",
    "sub-02/fmap/sub-02_phasediff.nii.gz": b"",
    "sub-02/fmap/sub-02_phasediff.json": {
        "IntendedFor": "func/sub-02_task-rest_bold.nii.gz",
    },
    "sub-02/fmap/sub-02_magnitude1.nii.gz": b"",
    "sub-02/fmap/sub-02_magnitude1.json": {
        "IntendedFor": ["func/sub-02_task-rest_bold.nii.gz"],
    },
}


def _write(top, files):
    top = top.with_mode("w")
    for rel, content in files.items():
        path = top / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, str):
            path.write_text(content)
        else:
            path.write_text(json.dumps(content))


def _clear_memory():
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture
def local_ds(tmp_path):
    _write(BidsPath(str(tmp_path / "ds")), FILES)
    return BidsPath(str(tmp_path / "ds"))


@pytest.fixture
def memory_store():
    pytest.importorskip("upath")
    _clear_memory()
    yield
    _clear_memory()


@pytest.fixture
def memory_ds(memory_store):
    _write(BidsPath("memory://ds"), FILES)
    return BidsPath("memory://ds")


@pytest.fixture(params=["local", "memory"])
def ds(request):
    return request.getfixturevalue(f"{request.param}_ds")


def _rel(paths, root):
    return [p.relative_to(root).as_posix() for p in paths]


# -- companions -------------------------------------------------------------------

def test_companions_of_a_run(ds):
    bold = ds / BOLD
    assert _rel(bold.companions, ds) == [
        # its own directory, by name
        f"{FUNC}task-rest_run-1_events.tsv",
        f"{FUNC}task-rest_run-1_recording-cardiac_physio.json",
        f"{FUNC}task-rest_run-1_recording-cardiac_physio.tsv.gz",
        f"{FUNC}task-rest_run-1_stim.tsv.gz",
        # the session, the subject, then the dataset root
        "sub-01/ses-1/sub-01_ses-1_scans.tsv",
        "sub-01/ses-1/sub-01_ses-1_task-rest_events.tsv",
        "sub-01/sub-01_sessions.tsv",
        "task-rest_events.json",
    ]


def test_companions_leave_out_the_sidecars(ds):
    bold = ds / BOLD
    assert _rel(bold.sidecars, ds) == [
        f"{FUNC}task-rest_run-01_bold.json", "task-rest_bold.json",
    ]
    assert not set(bold.companions) & set(bold.sidecars)


def test_companions_are_paths_of_the_family_and_mode(ds):
    companions = (ds / BOLD).companions
    assert isinstance(companions, tuple)
    assert all(isinstance(p, BidsPath) and p.mode == "r" for p in companions)
    events = companions[0]
    assert events.as_list() == []          # a table, read as one
    writable = ds.with_mode("w") / BOLD
    assert all(p.mode == "w" for p in writable.companions)


def test_sbref_and_m0scan_are_data_files_of_their_own(ds):
    names = [p.name for p in (ds / BOLD).companions]
    assert not [n for n in names if "sbref" in n]
    assert "sub-01_ses-1_m0scan.nii.gz" not in [
        p.name for p in (ds / ASL).companions
    ]


def test_dwi_gradients(ds):
    assert _rel((ds / DWI).companions, ds) == [
        "sub-01/ses-1/dwi/sub-01_ses-1_dwi.bval",
        "sub-01/ses-1/dwi/sub-01_ses-1_dwi.bvec",
        "sub-01/ses-1/sub-01_ses-1_scans.tsv",
        "sub-01/sub-01_sessions.tsv",
        "dwi.bval",
    ]


def test_asl_context(ds):
    assert _rel((ds / ASL).companions, ds)[:1] == [
        "sub-01/ses-1/perf/sub-01_ses-1_aslcontext.tsv",
    ]


def test_eeg_channels_electrodes_coordsystem(ds):
    # `space` names the electrodes' own space, which the recording lacks
    assert _rel((ds / EEG).companions, ds)[:3] == [
        "sub-01/ses-1/eeg/sub-01_ses-1_space-CapTrak_coordsystem.json",
        "sub-01/ses-1/eeg/sub-01_ses-1_space-CapTrak_electrodes.tsv",
        "sub-01/ses-1/eeg/sub-01_ses-1_task-rest_channels.tsv",
    ]


def test_meg_set_up_files(ds):
    # the system files apply to every recording of the session, whatever
    # its `acq`; a photo or a headshape to every recording too; markers to
    # the recordings of their task. A photo or a headshape whose `acq` no
    # recording has (`acq-NAS`) applies to every recording; one whose `acq`
    # a recording has (`acq-b`) to that recording alone.
    session = [
        "sub-01/ses-1/sub-01_ses-1_scans.tsv",
        "sub-01/ses-1/sub-01_ses-1_task-rest_events.tsv",
        "sub-01/sub-01_sessions.tsv",
        "task-rest_events.json",
    ]
    own = [
        f"{MEG_DIR}acq-NAS_photo.jpg",
        f"{MEG_DIR}acq-calibration_meg.dat",
        f"{MEG_DIR}acq-crosstalk_meg.fif",
        f"{MEG_DIR}headshape.pos",
        f"{MEG_DIR}photo.jpg",
        f"{MEG_DIR}task-rest_channels.tsv",
        f"{MEG_DIR}task-rest_markers.mrk",
    ]
    assert _rel((ds / MEG).companions, ds) == own + session
    assert _rel((ds / MEG_ACQ).companions, ds) == sorted(
        [*own, f"{MEG_DIR}acq-b_headshape.pos"]
    ) + session


def _set_up(tmp_path, files):
    _write(BidsPath(str(tmp_path)), dict.fromkeys(
        ["dataset_description.json", *files], b""
    ))
    return BidsPath(str(tmp_path))


@pytest.mark.parametrize("other_acq, applies", [("X", False), ("Y", True)])
def test_an_acq_tag_above_the_recordings(tmp_path, other_acq, applies):
    # a headshape of the session, above the datatype directories: whether a
    # recording it applies to has its `acq` is asked of all of them
    shape = "sub-01/ses-1/sub-01_ses-1_acq-X_headshape.pos"
    a = "sub-01/ses-1/meg/sub-01_ses-1_task-a_meg.fif"
    b = f"sub-01/ses-1/meg/sub-01_ses-1_task-b_acq-{other_acq}_meg.fif"
    elsewhere = "sub-01/ses-2/meg/sub-01_ses-2_task-a_acq-X_meg.fif"
    root = _set_up(tmp_path, [shape, a, b, elsewhere])
    assert (shape in _rel((root / a).companions, root)) is applies
    assert (shape in _rel((root / b).companions, root)) is (
        applies or other_acq == "X"
    )
    kept = BidsFilter(subjects="01", tasks="a", sessions="1").select(
        sorted(["dataset_description.json", shape, a, b, elsewhere])
    )
    assert (shape in kept) is applies


def test_an_acq_tag_in_a_nested_dataset_is_not_asked_of_it(tmp_path):
    # the recordings of a nested dataset inherit nothing from above it
    shape = "sub-01/sub-01_acq-X_headshape.pos"
    a = "sub-01/ses-1/meg/sub-01_ses-1_task-a_meg.fif"
    nested = "sub-01/ses-2/meg/sub-01_ses-2_task-a_acq-X_meg.fif"
    root = _set_up(tmp_path, [shape, a, nested,
                              "sub-01/ses-2/dataset_description.json"])
    assert shape in _rel((root / a).companions, root)


def test_blood_recordings_of_a_pet_image(ds):
    assert _rel((ds / PET).companions, ds)[:3] == [
        f"{PET_DIR}trc-FDG_recording-auto_blood.tsv",
        f"{PET_DIR}trc-FDG_recording-manual_blood.json",
        f"{PET_DIR}trc-FDG_recording-manual_blood.tsv",
    ]
    assert f"{PET_DIR}trc-FDG_pet.json" not in _rel((ds / PET).companions, ds)


def test_a_photo_of_a_sample_and_its_json(ds):
    assert _rel((ds / MICR).companions, ds)[:2] == [
        f"{MICR_DIR}sample-A_photo.jpg",
        f"{MICR_DIR}sample-A_photo.json",
    ]


def test_companions_of_an_image_without_any(ds):
    assert _rel((ds / T1W).companions, ds) == [
        "sub-01/ses-1/sub-01_ses-1_scans.tsv", "sub-01/sub-01_sessions.tsv",
    ]


@pytest.mark.parametrize("rel", [
    "", "sub-01", "sub-01/ses-1/func", "README", "participants.tsv",
    "task-rest_bold.json", f"{FUNC}task-rest_run-1_events.tsv",
    "sub-01/ses-1/dwi/sub-01_ses-1_dwi.bval", "dataset_description.json",
    # companion files are no data files
    f"{MEG_DIR}acq-crosstalk_meg.fif", f"{MEG_DIR}acq-calibration_meg.dat",
    f"{MEG_DIR}photo.jpg", f"{MEG_DIR}headshape.pos",
    f"{MEG_DIR}task-rest_markers.mrk", f"{MICR_DIR}sample-A_photo.jpg",
])
def test_not_a_data_file_has_none(ds, rel):
    path = ds / rel if rel else ds
    assert path.companions == ()
    assert path.fieldmaps == ()


def test_a_recording_has_companions_too(ds):
    physio = ds / f"{FUNC}task-rest_run-1_stim.tsv.gz"
    assert f"{FUNC}task-rest_run-1_events.tsv" in _rel(physio.companions, ds)
    # a blood recording's JSON is its sidecar
    blood = ds / f"{PET_DIR}trc-FDG_recording-manual_blood.tsv"
    assert _rel(blood.sidecars, ds) == [
        f"{PET_DIR}trc-FDG_recording-manual_blood.json",
    ]


def test_without_a_dataset_root_only_the_own_directory(tmp_path):
    top = BidsPath(str(tmp_path / "loose"))
    _write(top, {
        "task-rest_events.json": {},
        "sub-01/func/sub-01_task-rest_bold.nii.gz": b"",
        "sub-01/func/sub-01_task-rest_events.tsv": "onset\n",
        "sub-01/sub-01_scans.tsv": "filename\n",
    })
    bold = top / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert [p.name for p in bold.companions] == ["sub-01_task-rest_events.tsv"]


def test_a_nested_dataset_root_ends_the_search(tmp_path):
    top = BidsPath(str(tmp_path / "outer"))
    _write(top, {
        "dataset_description.json": {},
        "task-rest_events.json": {},
        "sub-01/dataset_description.json": {},
        "sub-01/task-rest_events.tsv": "onset\n",
        "sub-01/func/sub-01_task-rest_bold.nii.gz": b"",
    })
    bold = top / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert [p.name for p in bold.companions] == ["task-rest_events.tsv"]


def test_companions_see_a_transaction(tmp_path):
    _write(BidsPath(str(tmp_path / "ds")), FILES)
    ds = BidsPath(str(tmp_path / "ds"), mode="w")
    new = "sub-01/ses-1/func/sub-01_ses-1_task-rest_run-01_events.json"
    with ds:
        ds["sub-01"]["ses-1"]["func"][new.rsplit("/", 1)[1]] = {"onset": {}}
        assert new in _rel((ds / BOLD).companions, ds)
    assert new in _rel((ds / BOLD).companions, ds)


def test_pure_paths_have_no_associated_files():
    pure = PureBidsPath(BOLD)
    assert not hasattr(pure, "companions")
    assert not hasattr(pure, "fieldmaps")


# -- fieldmaps --------------------------------------------------------------------

def test_fieldmaps_by_both_mechanisms(ds):
    assert _rel((ds / BOLD).fieldmaps, ds) == [
        f"{FMAP}dir-AP_epi.nii.gz",      # IntendedFor, a bids:: URI in a list
        f"{FMAP}dir-PA_epi.nii.gz",      # B0FieldIdentifier in a list
        f"{FMAP}magnitude1.nii.gz",      # B0FieldIdentifier
        f"{FMAP}phasediff.nii.gz",       # both, listed once
        "sub-01/ses-2/fmap/sub-01_ses-2_dir-AP_epi.nii.gz",   # another session
    ]


def test_fieldmaps_are_data_files_only(ds):
    fieldmaps = (ds / BOLD).fieldmaps
    assert all(not p.is_metadata for p in fieldmaps)
    assert all(isinstance(p, BidsPath) and p.mode == "r" for p in fieldmaps)


def test_fieldmaps_by_intended_for_alone(ds):
    assert _rel((ds / DWI).fieldmaps, ds) == [f"{FMAP}dir-AP_epi.nii.gz"]


def test_fieldmaps_relative_to_the_subject(ds):
    assert _rel((ds / BOLD_NOSES).fieldmaps, ds) == [
        "sub-02/fmap/sub-02_magnitude1.nii.gz",
        "sub-02/fmap/sub-02_phasediff.nii.gz",
    ]


def test_no_fieldmaps(ds):
    assert (ds / T1W).fieldmaps == ()
    assert (ds / BOLD2).fieldmaps == ()     # no B0FieldSource, not named


def test_a_fieldmap_named_for_another_file_is_not_this_ones(ds):
    run2 = ds / "sub-01/ses-1/func/sub-01_ses-1_task-rest_run-02_bold.nii.gz"
    # it need not exist: the names are matched, exactly
    assert _rel(run2.fieldmaps, ds) == [f"{FMAP}fieldmap.nii.gz"]
    run2_short = ds / "sub-01/ses-1/func/sub-01_ses-1_task-rest_run-2_bold.nii.gz"
    assert run2_short.fieldmaps == ()


def test_fieldmaps_read_merged_sidecars(tmp_path):
    top = BidsPath(str(tmp_path / "ds"))
    _write(top, {
        "dataset_description.json": {},
        "bold.json": {"B0FieldSource": "inherited"},
        "phasediff.json": {"B0FieldIdentifier": "inherited"},
        "sub-01/func/sub-01_task-rest_bold.nii.gz": b"",
        "sub-01/fmap/sub-01_phasediff.nii.gz": b"",
        "sub-01/fmap/sub-01_magnitude1.nii.gz": b"",
        "sub-01/fmap/sub-01_magnitude1.json": {"B0FieldIdentifier": "own"},
    })
    bold = top / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert [p.name for p in bold.fieldmaps] == ["sub-01_phasediff.nii.gz"]


def test_bids_uris_need_a_dataset_root(tmp_path):
    top = BidsPath(str(tmp_path / "loose"))
    _write(top, {
        "sub-01/func/sub-01_task-rest_bold.nii.gz": b"",
        "sub-01/fmap/sub-01_dir-AP_epi.nii.gz": b"",
        "sub-01/fmap/sub-01_dir-AP_epi.json": {
            "IntendedFor": "bids::sub-01/func/sub-01_task-rest_bold.nii.gz",
        },
        "sub-01/fmap/sub-01_dir-PA_epi.nii.gz": b"",
        "sub-01/fmap/sub-01_dir-PA_epi.json": {
            "IntendedFor": "./func/sub-01_task-rest_bold.nii.gz",
        },
    })
    bold = top / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert [p.name for p in bold.fieldmaps] == ["sub-01_dir-PA_epi.nii.gz"]


def test_fieldmaps_outside_a_subject(tmp_path):
    top = BidsPath(str(tmp_path / "ds"))
    _write(top, {"dataset_description.json": {}, "func/x_bold.nii.gz": b""})
    assert (top / "func/x_bold.nii.gz").fieldmaps == ()


def test_fieldmaps_see_a_transaction(tmp_path):
    _write(BidsPath(str(tmp_path / "ds")), FILES)
    ds = BidsPath(str(tmp_path / "ds"), mode="w")
    with ds:
        (ds / BOLD).sidecar["B0FieldSource"] = "unused"
        assert _rel((ds / BOLD).fieldmaps, ds) == [
            f"{FMAP}dir-AP_epi.nii.gz", f"{FMAP}fieldmap.nii.gz",
            f"{FMAP}phasediff.nii.gz",
        ]


def test_fieldmaps_list_and_read_once(memory_ds, monkeypatch):
    from fsspec.implementations.memory import MemoryFileSystem

    from brainfilter.bidspath import BidsJSONFile

    listed, read = [], []
    ls, as_dict = MemoryFileSystem.ls, BidsJSONFile.as_dict

    def counting_ls(self, path, *args, **kwargs):
        listed.append(path)
        return ls(self, path, *args, **kwargs)

    def counting_as_dict(self):
        read.append(str(self))
        return as_dict(self)

    monkeypatch.setattr(MemoryFileSystem, "ls", counting_ls)
    monkeypatch.setattr(BidsJSONFile, "as_dict", counting_as_dict)
    assert len((memory_ds / BOLD).fieldmaps) == 5
    assert listed and len(listed) == len(set(listed))
    assert read and len(read) == len(set(read))


# -- async ------------------------------------------------------------------------

@pytest.fixture
def async_local_ds(local_ds):
    return AsyncBidsPath(str(local_ds))


@pytest.fixture
def async_memory_ds(memory_ds, async_memory):
    ds = AsyncBidsPath("memory://ds")
    assert type(ds.wrapped).__name__ == "AsyncFSPath"   # the native driver
    return ds


@pytest.fixture(params=["local", "memory"])
def ads(request):
    return request.getfixturevalue(f"async_{request.param}_ds")


@pytest.mark.anyio
@pytest.mark.parametrize("rel", [BOLD, DWI, ASL, EEG, T1W, BOLD2, BOLD_NOSES,
                                 MEG, MEG_ACQ, PET, MICR, f"{MEG_DIR}photo.jpg",
                                 "sub-01", "task-rest_bold.json"])
async def test_async_matches_sync(ads, tmp_path, rel):
    sync = BidsPath(str(tmp_path / "sync"))
    _write(sync, FILES)
    path = ads / rel
    companions = await path.companions
    fieldmaps = await path.fieldmaps
    assert isinstance(companions, tuple) and isinstance(fieldmaps, tuple)
    assert all(isinstance(p, AsyncBidsPath) for p in companions + fieldmaps)
    assert _rel(companions, ads) == _rel((sync / rel).companions, sync)
    assert _rel(fieldmaps, ads) == _rel((sync / rel).fieldmaps, sync)


@pytest.mark.anyio
async def test_async_properties_start_when_awaited(ads):
    import gc

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        (ads / BOLD).companions          # read, never awaited
        (ads / BOLD).fieldmaps
        gc.collect()


@pytest.mark.anyio
async def test_async_sees_a_transaction(tmp_path):
    _write(BidsPath(str(tmp_path / "ds")), FILES)
    ds = AsyncBidsPath(str(tmp_path / "ds"), mode="w")
    new = "sub-01_ses-1_task-rest_run-01_events.json"
    async with ds:
        func = await (await (await ds.child("sub-01")).child("ses-1")).child("func")
        await (func / new).write({"onset": {}})
        assert new in [p.name for p in await (ds / BOLD).companions]
        await (await (ds / BOLD).sidecar).set("B0FieldSource", "unused")
        assert [p.name for p in await (ds / BOLD).fieldmaps] == [
            "sub-01_ses-1_dir-AP_epi.nii.gz", "sub-01_ses-1_fieldmap.nii.gz",
            "sub-01_ses-1_phasediff.nii.gz",
        ]


# -- the same files as the filter keeps --------------------------------------------

def _random_dataset(rng):
    """The relative paths of a random dataset, for the filter comparison."""
    files = []
    pick = rng.random
    if pick() < .8:
        files.append("dataset_description.json")
    files.append("participants.tsv")
    for name in ("task-rest_events.json", "task-x_events.tsv", "dwi.bval",
                 "task-rest_bold.json", "events.json", "task-rest_physio.tsv.gz",
                 "task-rest_physio.json", "space-CapTrak_electrodes.tsv"):
        if pick() < .3:
            files.append(name)
    for sub in ("01", "02", "1"):
        if pick() < .2:
            continue
        sessions = [s for s in ("1", "2") if pick() < .5] or [None]
        if pick() < .1:
            files.append(f"sub-{sub}/dataset_description.json")
        if pick() < .3:
            files.append(f"sub-{sub}/sub-{sub}_task-rest_events.tsv")
        if pick() < .3 and sessions != [None]:
            files.append(f"sub-{sub}/sub-{sub}_sessions.tsv")
        if pick() < .2:
            files.append(f"sub-{sub}/sub-{sub}_task-rest_physio.tsv.gz")
        if pick() < .2:     # the sidecar of the coordsystem.json below
            files.append(f"sub-{sub}/sub-{sub}_space-CapTrak_coordsystem.json")
        for ses in sessions:
            base = f"sub-{sub}" + (f"/ses-{ses}" if ses else "")
            pre = f"sub-{sub}" + (f"_ses-{ses}" if ses else "")
            if pick() < .1 and ses:
                files.append(f"{base}/dataset_description.json")
            if pick() < .3:
                files.append(f"{base}/{pre}_scans.tsv")
            if pick() < .15:    # above the datatype directories
                files.append(f"{base}/{pre}_acq-{rng.choice('ab')}_headshape.pos")
            if pick() < .2:
                files.append(f"{base}/{pre}_scans.json")
            for run in rng.sample(["", "_run-1", "_run-01", "_run-2"], 2):
                task = rng.choice(["rest", "x"])
                stem = f"{base}/func/{pre}_task-{task}{run}"
                files.append(f"{stem}_bold.nii.gz")
                for suffix, p in (("_events.tsv", .5), ("_events.json", .2),
                                  ("_bold.json", .3), ("_physio.tsv.gz", .3),
                                  ("_recording-r_physio.json", .2),
                                  ("_stim.tsv.gz", .2), ("_sbref.nii.gz", .2)):
                    if pick() < p:
                        files.append(f"{stem}{suffix}")
                if pick() < .3:
                    other = rng.choice(["_run-1", "_run-02", "_acq-a", ""])
                    files.append(f"{base}/func/{pre}_task-{task}{other}_events.tsv")
            if pick() < .4:
                files.append(f"{base}/dwi/{pre}_dwi.nii.gz")
                for ext in (".bval", ".bvec", ".json"):
                    if pick() < .6:
                        files.append(f"{base}/dwi/{pre}_dwi{ext}")
                if pick() < .3:
                    files.append(f"{base}/dwi/{pre}_acq-a_dwi.bval")
            if pick() < .3:
                files.append(f"{base}/perf/{pre}_asl.nii.gz")
                files.append(f"{base}/perf/{pre}_aslcontext.tsv")
                if pick() < .5:
                    files.append(f"{base}/perf/{pre}_m0scan.nii.gz")
            if pick() < .3:
                files.append(f"{base}/eeg/{pre}_task-rest_eeg.edf")
                for name in ("task-rest_channels.tsv", "space-CapTrak_electrodes.tsv",
                             "space-CapTrak_coordsystem.json", "task-x_channels.tsv"):
                    if pick() < .6:
                        files.append(f"{base}/eeg/{pre}_{name}")
            if pick() < .3:
                files.append(f"{base}/beh/{pre}_task-x_events.tsv")
                files.append(f"{base}/beh/{pre}_task-x_beh.tsv")
            if pick() < .3:
                files.append(f"{base}/anat/{pre}_T1w.nii.gz")
            if pick() < .4:
                meg = f"{base}/meg/{pre}"
                for task in rng.sample(["rest", "x"], rng.randint(0, 2)):
                    acq = rng.choice(["", "_acq-a"])
                    files.append(f"{meg}_task-{task}{acq}_meg.fif")
                    if pick() < .3:
                        files.append(f"{meg}_task-{task}{acq}_meg.json")
                    if pick() < .3:
                        files.append(f"{meg}_task-{task}_markers.mrk")
                for name, p in (("acq-calibration_meg.dat", .5),
                                ("acq-crosstalk_meg.fif", .5),
                                ("acq-calibration_meg.fif", .1),  # data
                                ("headshape.pos", .4), ("photo.jpg", .3),
                                ("acq-NAS_photo.jpg", .3),
                                ("acq-a_photo.jpg", .3),
                                ("acq-a_photo.json", .2),
                                ("acq-b_headshape.pos", .2),
                                ("space-CapTrak_markers.sqd", .2)):
                    if pick() < p:
                        files.append(f"{meg}_{name}")
            if pick() < .3:
                pet = f"{base}/pet/{pre}"
                trc = rng.choice(["", "_trc-FDG"])
                if pick() < .8:
                    files.append(f"{pet}{trc}_pet.nii.gz")
                for name in ("recording-manual_blood.tsv",
                             "recording-manual_blood.json",
                             "recording-auto_blood.tsv"):
                    if pick() < .5:
                        files.append(f"{pet}{rng.choice([trc, '_trc-x'])}_{name}")
            if pick() < .2:
                mrs = f"{base}/mrs/{pre}"
                files.append(f"{mrs}_{rng.choice(['svs', 'mrsi'])}.nii.gz")
                if pick() < .5:
                    files.append(f"{mrs}_mrsref.nii.gz")
            if pick() < .2:
                micr = f"{base}/micr/{pre}"
                files.append(f"{micr}_sample-A_BF.png")
                for name in ("sample-A_photo.jpg", "sample-A_photo.json",
                             "sample-B_photo.tif"):
                    if pick() < .5:
                        files.append(f"{micr}_{name}")
    return sorted(set(files))


def _is_data(rel):
    """Whether a filter judges `rel` as a data file, and whether it has
    companions (a recording)."""
    from brainfilter._names import parse_path

    path, parsed = PureBidsPath(rel), parse_path(rel)
    data = rel.startswith("sub-") and path.suffix is not None and (
        not path.is_metadata or parsed.is_companion
    )
    return data, data and parsed.has_companions


@pytest.mark.parametrize("seed", range(40))
def test_companions_and_sidecars_are_what_the_filter_keeps(memory_store, seed):
    """For each data file, `companions` and `sidecars` together are exactly
    what `BidsFilter` keeps with it, beyond what it keeps whatever it selects.
    """
    listing = _random_dataset(random.Random(seed))
    _write(BidsPath("memory://fuzz"), dict.fromkeys(listing, b""))
    root = BidsPath("memory://fuzz")
    nothing = BidsFilter(include=re.compile("^$"), bidsignore=False)
    always = set(nothing.select(listing))
    for rel in listing:
        path = root / rel
        data, recording = _is_data(rel)
        if not recording and rel.startswith("sub-"):
            # a companion has no companions; a top-level file is the dataset's
            assert path.companions == ()
        if not data:
            continue
        only = BidsFilter(include=re.compile(f"^{re.escape(rel)}$"),
                          bidsignore=False)
        selected = set(only.select(listing))
        assert rel in selected
        kept = selected - {rel}
        companions = _rel(path.companions, root)
        sidecars = _rel(path.sidecars, root)
        found = set(companions) | set(sidecars)
        assert len(found) == len(companions) + len(sidecars)
        assert found <= kept, (rel, found - kept)
        assert kept - always <= found, (rel, kept - always - found)
