"""One companion by name (`companion`), and the per-suffix shortcuts."""
import copy
import json
import pickle
import warnings

import pytest

from brainfilter import AsyncBidsPath, BidsPath, PureBidsPath
from brainfilter import bidspath as B

FUNC = "sub-01/func/sub-01_"
DWI_DIR = "sub-01/dwi/sub-01_"
PERF = "sub-01/perf/sub-01_"
EEG_DIR = "sub-01/eeg/sub-01_"
MEG_DIR = "sub-01/ses-1/meg/sub-01_ses-1_"
PET_DIR = "sub-01/pet/sub-01_"
MRS_DIR = "sub-01/mrs/sub-01_"

RUN1 = f"{FUNC}task-rest_run-01_bold.nii.gz"
RUN2 = f"{FUNC}task-rest_run-2_bold.nii.gz"
OTHER = f"{FUNC}task-other_bold.nii.gz"
DWI = f"{DWI_DIR}dwi.nii.gz"
MULTI = "sub-02/dwi/sub-02_acq-multi_dwi.nii.gz"   # no gradients of its own
ASL = f"{PERF}asl.nii.gz"
ASL_B = f"{PERF}acq-b_asl.nii.gz"
EEG = f"{EEG_DIR}task-rest_eeg.edf"
T1W = "sub-01/anat/sub-01_T1w.nii.gz"
MEG = f"{MEG_DIR}task-rest_meg.fif"
MEG_ACQ = f"{MEG_DIR}task-rest_acq-b_meg.fif"
PET = f"{PET_DIR}pet.nii.gz"
SVS = f"{MRS_DIR}svs.nii.gz"
MRSI = f"{MRS_DIR}acq-grid_mrsi.nii.gz"
UNLOC = f"{MRS_DIR}unloc.nii.gz"

FILES = {
    "dataset_description.json": {"Name": "companion", "BIDSVersion": "1.10.0"},
    # dataset level: inherited by the files below
    "task-rest_events.tsv": "onset\tduration\n",
    "task-rest_events.json": {"onset": {}},          # describes the table
    "acq-multi_dwi.bval": "0 1000",
    "acq-multi_dwi.bvec": "0 1\n0 0\n0 0\n",
    "aslcontext.tsv": "volume_type\n",
    # func
    RUN1: b"",
    f"{FUNC}task-rest_run-1_events.tsv": "onset\n",  # run-1 is run-01
    f"{FUNC}task-rest_run-1_sbref.nii.gz": b"",
    f"{FUNC}task-rest_run-1_sbref.json": {},
    RUN2: b"",
    f"{FUNC}task-rest_run-3_sbref.nii.gz": b"",      # another run's
    OTHER: b"",
    # dwi
    DWI: b"",
    f"{DWI_DIR}dwi.bval": "0 1000",
    f"{DWI_DIR}dwi.bvec": "0 1\n0 0\n0 0\n",
    f"{DWI_DIR}sbref.nii.gz": b"",
    f"{DWI_DIR}sbref.json": {},
    f"{DWI_DIR}dir-AP_sbref.nii.gz": b"",            # more entities
    MULTI: b"",
    "sub-02/dwi/sub-02_acq-multi_sbref.nii": b"",    # uncompressed
    # perf
    ASL: b"",
    f"{PERF}m0scan.nii.gz": b"",
    f"{PERF}m0scan.json": {},
    ASL_B: b"",
    f"{PERF}acq-b_aslcontext.tsv": "volume_type\n",
    # eeg: electrodes in two spaces
    EEG: b"",
    f"{EEG_DIR}space-CapTrak_electrodes.tsv": "name\n",
    f"{EEG_DIR}space-Other_electrodes.tsv": "name\n",
    f"{EEG_DIR}space-CapTrak_coordsystem.json": {},
    f"{EEG_DIR}task-rest_recording-cardiac_physio.tsv.gz": b"",
    f"{EEG_DIR}task-rest_recording-cardiac_physio.json": {},
    # meg: the session's set-up files and two recordings
    MEG: b"",
    MEG_ACQ: b"",
    f"{MEG_DIR}acq-calibration_meg.dat": b"",
    f"{MEG_DIR}acq-crosstalk_meg.fif": b"",
    f"{MEG_DIR}headshape.pos": b"",
    f"{MEG_DIR}photo.jpg": b"",
    f"{MEG_DIR}task-rest_markers.mrk": b"",
    # pet: two blood recordings
    PET: b"",
    f"{PET_DIR}recording-manual_blood.tsv": "time\n",
    f"{PET_DIR}recording-manual_blood.json": {},
    f"{PET_DIR}recording-auto_blood.tsv": "time\n",
    # mrs: a reference scan for the single-voxel and the grid scans
    SVS: b"",
    f"{MRS_DIR}mrsref.nii.gz": b"",
    MRSI: b"",
    f"{MRS_DIR}acq-grid_mrsref.nii.gz": b"",
    UNLOC: b"",
    # anat
    T1W: b"",
}

DATA = [RUN1, RUN2, OTHER, DWI, MULTI, ASL, ASL_B, EEG, T1W, MEG, MEG_ACQ,
        PET, SVS, MRSI, UNLOC]


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


def _rel(path, root):
    return None if path is None else path.relative_to(root).as_posix()


# -- the shortcuts ------------------------------------------------------------------

@pytest.mark.parametrize("rel,attr,expected", [
    # in the file's own directory
    (RUN1, "events", f"{FUNC}task-rest_run-1_events.tsv"),
    (DWI, "bval", f"{DWI_DIR}dwi.bval"),
    (DWI, "bvec", f"{DWI_DIR}dwi.bvec"),
    (ASL_B, "aslcontext", f"{PERF}acq-b_aslcontext.tsv"),
    # inherited from the dataset root
    (RUN2, "events", "task-rest_events.tsv"),
    (MULTI, "bval", "acq-multi_dwi.bval"),
    (MULTI, "bvec", "acq-multi_dwi.bvec"),
    (ASL, "aslcontext", "aslcontext.tsv"),
    # none applies
    (OTHER, "events", None),
])
def test_metadata_shortcuts(ds, rel, attr, expected):
    path = ds / rel
    assert _rel(getattr(path, attr), ds) == expected
    assert getattr(path, attr) == path.companion(attr)


@pytest.mark.parametrize("rel,attr,expected", [
    (RUN1, "sbref", f"{FUNC}task-rest_run-1_sbref.nii.gz"),   # run-1 is run-01
    (DWI, "sbref", f"{DWI_DIR}sbref.nii.gz"),                 # not dir-AP's
    (MULTI, "sbref", "sub-02/dwi/sub-02_acq-multi_sbref.nii"),  # a .nii too
    (ASL, "m0scan", f"{PERF}m0scan.nii.gz"),
    (RUN2, "sbref", None),               # run-3's is another run's
    (OTHER, "sbref", None),
    (ASL_B, "m0scan", None),             # acq-b has none
])
def test_paired_image_shortcuts(ds, rel, attr, expected):
    path = ds / rel
    assert _rel(getattr(path, attr), ds) == expected
    assert getattr(path, attr) == path.companion(attr)


def test_a_paired_image_is_an_image_not_its_json(ds):
    sbref = (ds / DWI).sbref
    assert sbref.extension == ".nii.gz"
    assert type(sbref) is BidsPath            # an image of its own
    assert (ds / DWI).companion("sbref", dir="AP") is None


def test_paired_images_are_not_companions(ds):
    for rel, attr in [(RUN1, "sbref"), (DWI, "sbref"), (ASL, "m0scan")]:
        path = ds / rel
        assert getattr(path, attr) not in path.companions


def test_a_paired_image_needs_a_suffix_the_schema_pairs(ds):
    # an sbref of a T1w, or an m0scan of a bold, is no such pair
    _write(ds, {"sub-01/anat/sub-01_sbref.nii.gz": b""})
    assert (ds / T1W).companion("sbref") is None
    assert (ds / RUN1).companion("m0scan") is None


@pytest.mark.parametrize("rel,missing", [
    (T1W, ["bval", "bvec", "sbref", "events", "aslcontext", "m0scan"]),
    (RUN1, ["bval", "bvec", "aslcontext", "m0scan"]),
    (DWI, ["events", "aslcontext", "m0scan"]),
    (ASL, ["bval", "bvec", "sbref", "events"]),
    (EEG, ["bval", "bvec", "sbref", "events", "aslcontext", "m0scan"]),
    ("sub-01", ["bval", "events", "m0scan"]),
    (f"{DWI_DIR}dwi.bval", ["bval", "bvec", "sbref"]),
    (f"{FUNC}task-rest_run-1_bold.json", ["events", "sbref"]),
])
def test_other_files_have_no_shortcut(ds, rel, missing):
    path = ds / rel
    for attr in missing:
        assert not hasattr(path, attr)
        with pytest.raises(AttributeError):
            getattr(path, attr)


def test_shortcuts_follow_the_mode(ds):
    assert (ds / DWI).bval.mode == "r"
    assert (ds.with_mode("w") / DWI).bval.mode == "w"
    assert (ds.with_mode("w") / RUN1).sbref.mode == "w"


# -- companion(name) ---------------------------------------------------------------

def test_a_table_or_recording_rather_than_its_json(ds):
    # events.json at the root describes events.tsv; the table is the companion
    assert (ds / RUN2).companion("events").name == "task-rest_events.tsv"
    physio = (ds / EEG).companion("physio")
    assert physio.name == "sub-01_task-rest_recording-cardiac_physio.tsv.gz"
    assert [p.name for p in physio.sidecars] == [
        "sub-01_task-rest_recording-cardiac_physio.json",
    ]
    # a coordinate system is a JSON file
    assert (ds / EEG).companion("coordsystem").name == (
        "sub-01_space-CapTrak_coordsystem.json"
    )


def test_two_candidates_in_one_directory_are_an_error(ds):
    eeg = ds / EEG
    with pytest.raises(ValueError, match=(
        r"2 'electrodes' companions.*sub-01_space-CapTrak_electrodes\.tsv, "
        r"sub-01_space-Other_electrodes\.tsv.*companion\('electrodes', "
        r"space='CapTrak'\)"
    )):
        eeg.companion("electrodes")
    assert eeg.companion("electrodes", space="CapTrak").name == (
        "sub-01_space-CapTrak_electrodes.tsv"
    )
    assert eeg.companion("electrodes", space="Other").name == (
        "sub-01_space-Other_electrodes.tsv"
    )
    assert eeg.companion("electrodes", space="MNI") is None
    assert eeg.companion("electrodes", space=None) is None


def test_entities_narrow_the_search_upwards(ds):
    _write(ds, {"sub-01/sub-01_task-rest_run-02_events.tsv": "onset\n"})
    run2 = ds / RUN2
    # the nearest is the subject's, which names the run
    assert _rel(run2.events, ds) == "sub-01/sub-01_task-rest_run-02_events.tsv"
    assert _rel(run2.companion("events", run=None), ds) == "task-rest_events.tsv"
    # index entities compare by number
    assert run2.companion("events", run=2) == run2.events
    assert run2.companion("events", run="0002") == run2.events
    assert (ds / RUN1).companion("events", run=1) == (ds / RUN1).events
    assert (ds / RUN1).companion("sbref", run="1") == (ds / RUN1).sbref
    assert (ds / RUN1).companion("sbref", run="2") is None


def test_two_images_of_one_pair_are_an_error(ds):
    _write(ds, {f"{DWI_DIR}sbref.nii": b""})
    with pytest.raises(ValueError, match=(
        r"2 'sbref' companions.*sub-01_sbref\.nii, sub-01_sbref\.nii\.gz; "
        r"they differ only in their extension"
    )):
        (ds / DWI).sbref


def test_a_recording_by_its_recording_entity(ds):
    eeg = ds / EEG
    assert eeg.companion("physio", recording="cardiac") == eeg.companion("physio")
    assert eeg.companion("physio", recording="resp") is None


@pytest.mark.parametrize("rel", [MEG, MEG_ACQ])
@pytest.mark.parametrize("name,expected", [
    ("calibration", "acq-calibration_meg.dat"),
    ("crosstalk", "acq-crosstalk_meg.fif"),
    ("headshape", "headshape.pos"),
    ("photo", "photo.jpg"),
    ("markers", "task-rest_markers.mrk"),
])
def test_meg_set_up_files(ds, rel, name, expected):
    # the system files belong to every recording, whatever its own `acq`
    assert _rel((ds / rel).companion(name), ds) == f"{MEG_DIR}{expected}"
    assert (ds / rel).companion(name) in (ds / rel).companions


def test_meg_system_files_belong_to_meg_recordings_only(ds):
    for rel in (EEG, RUN1, PET, T1W):
        assert (ds / rel).companion("calibration") is None
        assert (ds / rel).companion("crosstalk") is None
    for rel in ("acq-crosstalk_meg.fif", "acq-calibration_meg.dat",
                "photo.jpg"):
        path = ds / f"{MEG_DIR}{rel}"
        assert path.companion("crosstalk") is None
        assert path.companion("photo") is None


def test_two_blood_recordings_are_an_error(ds):
    pet = ds / PET
    with pytest.raises(ValueError, match=(
        r"2 'blood' companions.*sub-01_recording-auto_blood\.tsv, "
        r"sub-01_recording-manual_blood\.tsv.*companion\('blood', "
        r"recording='auto'\)"
    )):
        pet.companion("blood")
    blood = pet.companion("blood", recording="manual")
    assert _rel(blood, ds) == f"{PET_DIR}recording-manual_blood.tsv"   # not .json
    assert blood in pet.companions
    assert [p.name for p in blood.sidecars] == ["sub-01_recording-manual_blood.json"]
    assert pet.companion("blood", recording="other") is None


@pytest.mark.parametrize("rel,expected", [
    (SVS, f"{MRS_DIR}mrsref.nii.gz"),
    (MRSI, f"{MRS_DIR}acq-grid_mrsref.nii.gz"),
    (UNLOC, None),                     # a localiser has no reference scan
])
def test_mrs_reference_scan(ds, rel, expected):
    path = ds / rel
    assert _rel(path.companion("mrsref"), ds) == expected
    assert path.companion("mrsref") not in path.companions


def test_unknown_name():
    path = BidsPath("ds/sub-01/dwi/sub-01_dwi.nii.gz")    # raised before any I/O
    with pytest.raises(ValueError, match=(
        r"unknown companion 'bvals': name one of aslcontext, asllabeling, "
        r"blood, bval, bvec, calibration, .*crosstalk, .*headshape, m0scan, "
        r"markers, mrsref, .*photo, .*sbref, scans, sessions, stim"
    )):
        path.companion("bvals")
    for name in ("dwi", "json", "tsv", "sidecar", ".bval"):
        with pytest.raises(ValueError, match="unknown companion"):
            path.companion(name)


def test_invalid_entity():
    path = BidsPath("ds/sub-01/dwi/sub-01_dwi.nii.gz")
    with pytest.raises(ValueError, match="invalid BIDS entity"):
        path.companion("bval", acq="a_b")


def test_not_a_data_file_has_none(ds):
    for rel in ("sub-01", f"{DWI_DIR}dwi.bval", "task-rest_events.tsv"):
        assert (ds / rel).companion("events") is None
        assert (ds / rel).companion("sbref") is None


def test_a_missing_file_has_none(tmp_path):
    path = BidsPath(str(tmp_path / "nowhere" / "sub-01_dwi.nii.gz"))
    assert path.bval is None and path.sbref is None


@pytest.mark.parametrize("rel", DATA)
def test_a_companion_is_one_of_the_companions(ds, rel):
    from brainfilter._associated import companion_names
    from brainfilter._names import PAIRED_IMAGES

    path = ds / rel
    companions = path.companions
    for name in companion_names():
        if name in PAIRED_IMAGES:
            continue
        try:
            found = path.companion(name)
        except ValueError:
            continue
        assert found is None or found in companions


def test_companion_sees_a_transaction(tmp_path):
    _write(BidsPath(str(tmp_path / "ds")), FILES)
    ds = BidsPath(str(tmp_path / "ds"), mode="w")
    other = ds / OTHER
    name = "sub-01_task-other_events.tsv"
    with ds:
        (ds / "sub-01" / "func" / name).write([{"onset": 0}])
        assert other.events.name == name
    assert other.events.name == name


# -- dispatch -----------------------------------------------------------------------

@pytest.mark.parametrize("rel,kind", [
    (DWI, "DwiFile"), (RUN1, "BoldFile"), (ASL, "AslFile"),
    (f"{DWI_DIR}dwi.nii", "DwiFile"),
    (f"{DWI_DIR}dwi.json", "SidecarFile"),
    (f"{DWI_DIR}dwi.bval", "Path"),
    (f"{FUNC}task-rest_bold", "Path"),          # no extension
    (f"{FUNC}task-rest_bold.ds", "Path"),       # shaped like a directory
    (T1W, "Path"),
    ("sub-01/meg/sub-01_task-x_meg.ds", "Path"),
])
def test_dispatch(rel, kind):
    for family, cls in (("Bids", BidsPath), ("PureBids", PureBidsPath),
                        ("AsyncBids", AsyncBidsPath)):
        expected = getattr(B, f"{family}{kind}")
        assert type(cls(f"ds/{rel}")) is expected
        assert type(cls("ds") / rel) is expected
        assert type(cls(f"memory://ds/{rel}")) is expected


def test_derived_paths_are_dispatched_again():
    dwi = BidsPath("ds") / "sub-01" / "dwi" / "sub-01_dwi.nii.gz"
    assert type(dwi) is B.BidsDwiFile
    assert isinstance(dwi, (BidsPath, B.BidsFile))
    assert type(dwi.with_entities(acq="multi", keep_existing=True)) is B.BidsDwiFile
    assert type(dwi.with_subject("02")) is B.BidsDwiFile
    assert type(dwi.with_suffix("bold")) is B.BidsBoldFile
    assert type(dwi.with_name("sub-01_asl.nii.gz")) is B.BidsAslFile
    assert type(dwi.with_suffix("T1w")) is BidsPath
    assert type(dwi.with_extension(".bval")) is BidsPath
    assert type(dwi.with_extension(".json")) is B.BidsSidecarFile
    assert type(dwi.parent) is BidsPath
    assert type(BidsPath("ds") // "sub-01_dwi.nii.gz") is B.BidsDwiFile
    assert type(B.BidsFile("ds/sub-01_bold.nii.gz")) is B.BidsBoldFile


def test_families_convert_into_each_other():
    pure = PureBidsPath("ds/sub-01_dwi.nii.gz", mode="w")
    assert type(BidsPath(pure)) is B.BidsDwiFile
    assert BidsPath(pure).mode == "w"
    assert type(AsyncBidsPath(BidsPath(pure))) is B.AsyncBidsDwiFile
    assert type(PureBidsPath(AsyncBidsPath(pure))) is B.PureBidsDwiFile


@pytest.mark.parametrize("cls", [BidsPath, AsyncBidsPath, PureBidsPath])
def test_copy_and_pickle_keep_the_class_and_mode(cls):
    p = cls("ds/sub-01/func/sub-01_task-rest_bold.nii.gz", mode="w")
    for other in (copy.copy(p), copy.deepcopy(p), pickle.loads(pickle.dumps(p))):
        assert type(other) is type(p) and other == p and other.mode == "w"


def test_pure_paths_have_no_shortcuts():
    pure = PureBidsPath(DWI)
    assert type(pure) is B.PureBidsDwiFile
    for attr in ("companion", "bval", "bvec", "sbref"):
        assert not hasattr(pure, attr)
    for attr in ("events", "aslcontext", "m0scan"):
        assert not hasattr(PureBidsPath(RUN1), attr)
        assert not hasattr(PureBidsPath(ASL), attr)


def test_a_subclass_of_ones_own_keeps_its_type(ds):
    class MyPath(BidsPath):
        __slots__ = ()

    class MyDwi(B.BidsDwiFile):
        __slots__ = ()

    mine = MyPath(str(ds / DWI))
    assert type(mine) is MyPath
    assert not hasattr(mine, "bval")              # no shortcut, as written
    assert mine.companion("bval") == (ds / DWI).bval
    dwi = MyDwi(str(ds / DWI))
    assert type(dwi) is MyDwi
    assert type(dwi.with_name("sub-01_T1w.nii.gz")) is MyDwi
    assert dwi.bval == (ds / DWI).bval


# -- async --------------------------------------------------------------------------

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


SHORTCUTS = {
    "dwi": ("bval", "bvec", "sbref"),
    "bold": ("events", "sbref"),
    "asl": ("aslcontext", "m0scan"),
}


@pytest.mark.anyio
@pytest.mark.parametrize("rel", DATA)
async def test_async_matches_sync(ads, tmp_path, rel):
    sync = BidsPath(str(tmp_path / "sync"))
    _write(sync, FILES)
    path, spath = ads / rel, sync / rel
    for attr in SHORTCUTS.get(path.suffix, ()):
        found = await getattr(path, attr)
        assert found is None or isinstance(found, AsyncBidsPath)
        assert _rel(found, ads) == _rel(getattr(spath, attr), sync)
        assert _rel(await path.companion(attr), ads) == _rel(
            spath.companion(attr), sync
        )
    for name in ("events", "physio", "coordsystem", "bval", "sbref",
                 "crosstalk", "calibration", "photo", "headshape", "mrsref"):
        assert _rel(await path.companion(name), ads) == _rel(
            spath.companion(name), sync
        )


@pytest.mark.anyio
async def test_async_classes_and_attributes(ads):
    assert type(ads / DWI) is B.AsyncBidsDwiFile
    assert type(ads / RUN1) is B.AsyncBidsBoldFile
    assert type(ads / ASL) is B.AsyncBidsAslFile
    assert not hasattr(ads / T1W, "bval")
    assert not hasattr(ads / RUN1, "bval")


@pytest.mark.anyio
async def test_async_errors(ads):
    eeg = ads / EEG
    with pytest.raises(ValueError, match="unknown companion"):
        eeg.companion("nope")                     # at once, not awaited
    with pytest.raises(ValueError, match="space='CapTrak'"):
        await eeg.companion("electrodes")
    found = await eeg.companion("electrodes", space="Other")
    assert found.name == "sub-01_space-Other_electrodes.tsv"
    with pytest.raises(ValueError, match="recording='auto'"):
        await (ads / PET).companion("blood")
    found = await (ads / PET).companion("blood", recording="auto")
    assert found.name == "sub-01_recording-auto_blood.tsv"


@pytest.mark.anyio
async def test_async_awaitables_start_when_awaited(ads):
    import gc

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        (ads / DWI).bval                          # read, never awaited
        (ads / RUN1).events
        (ads / ASL).m0scan
        (ads / EEG).companion("electrodes")       # would raise if awaited
        gc.collect()


@pytest.mark.anyio
async def test_async_sees_a_transaction(tmp_path):
    _write(BidsPath(str(tmp_path / "ds")), FILES)
    ds = AsyncBidsPath(str(tmp_path / "ds"), mode="w")
    name = "sub-01_task-other_events.tsv"
    async with ds:
        await (ds / "sub-01" / "func" / name).write([{"onset": 0}])
        assert (await (ds / OTHER).events).name == name
    assert (await (ds / OTHER).events).name == name
