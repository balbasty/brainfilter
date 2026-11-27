import re
import typing

import pytest

from brainfilter._names import applies_to, parse_path
from brainfilter.bidspath import BidsPath, PureBidsPath
from brainfilter.conditions import And, Glob, Or, Regex
from brainfilter.filter import BidsFilter

# -- ported from brainspresso tests/test_bids_select.py ------------------------

# Layout modelled on ds000224 (top-level sidecars, sessions, scans)
LISTING = [
    ".bidsignore",
    ".datalad/config",
    ".gitattributes",
    "CHANGES",
    "README",
    "dataset_description.json",
    "participants.json",
    "participants.tsv",
    "T1w.json",
    "T2w.json",
    "magnitude1.json",
    "task-rest_bold.json",
    "task-motor_bold.json",
    "bold_group.html",
    "phenotype/NEO_FFI.tsv",
    "derivatives/surfaces/sub-01/x.gii",
    "sourcedata/raw.zip",
    "sub-01/sub-01_sessions.tsv",
    "sub-01/ses-1/sub-01_ses-1_scans.tsv",
    "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz",
    "sub-01/ses-1/anat/sub-01_ses-1_T2w.nii.gz",
    "sub-01/ses-1/anat/sub-01_ses-1_T2w.json",
    "sub-01/ses-1/fmap/sub-01_ses-1_magnitude1.nii.gz",
    "sub-01/ses-2/sub-01_ses-2_scans.tsv",
    "sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz",
    "sub-01/ses-2/func/sub-01_ses-2_task-motor_bold.nii.gz",
    "sub-01/ses-2/func/sub-01_ses-2_task-motor_events.tsv",
    "sub-02/sub-02_sessions.tsv",
    "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz",
    "sub-02/ses-1/dwi/sub-02_ses-1_dwi.nii.gz",
    "sub-02/ses-1/dwi/sub-02_ses-1_dwi.bval",
    "sub-02/ses-1/dwi/sub-02_ses-1_dwi.bvec",
]
ALWAYS = {
    ".bidsignore", "CHANGES", "README", "dataset_description.json",
    "participants.json", "participants.tsv", "bold_group.html",
    "phenotype/NEO_FFI.tsv",
}


def test_parse_name():
    name = parse_path("sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz")
    assert name.entities == {"sub": "01", "ses": "2", "task": "rest"}
    assert name.suffix == "bold"
    assert name.extension == ".nii.gz"
    assert name.datatype == "func"
    assert not name.is_metadata
    top = parse_path("T1w.json")
    assert top.entities == {} and top.suffix == "T1w" and top.is_metadata


def test_select_all_skips_hidden_and_optional_folders():
    kept = set(BidsFilter().select(LISTING))
    assert ".datalad/config" not in kept
    assert ".gitattributes" not in kept
    assert not any(p.startswith(("derivatives/", "sourcedata/")) for p in kept)
    assert ALWAYS <= kept
    # every sidecar applies to some data file
    assert {"T1w.json", "T2w.json", "magnitude1.json",
            "task-rest_bold.json", "task-motor_bold.json"} <= kept


def test_select_optional_folders():
    kept = set(BidsFilter(folders=["derivatives"]).select(LISTING))
    assert "derivatives/surfaces/sub-01/x.gii" in kept
    assert "sourcedata/raw.zip" not in kept


def test_select_suffix_with_inheritance():
    kept = set(BidsFilter(suffixes=["T1w"]).select(LISTING))
    assert kept == ALWAYS | {
        "T1w.json",
        "sub-01/sub-01_sessions.tsv",
        "sub-01/ses-1/sub-01_ses-1_scans.tsv",
        "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz",
        "sub-02/sub-02_sessions.tsv",
        "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz",
    }


def test_select_task_includes_matching_sidecars_and_events():
    kept = set(BidsFilter(tasks=["motor"]).select(LISTING))
    assert "sub-01/ses-2/func/sub-01_ses-2_task-motor_bold.nii.gz" in kept
    assert "sub-01/ses-2/func/sub-01_ses-2_task-motor_events.tsv" in kept
    assert "task-motor_bold.json" in kept
    assert "task-rest_bold.json" not in kept
    assert "sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz" not in kept
    assert "T1w.json" not in kept
    assert "sub-01/ses-1/sub-01_ses-1_scans.tsv" not in kept


def test_select_subjects_sessions_datatypes():
    kept = set(BidsFilter(subjects=["sub-02"], datatypes=["dwi"]).select(LISTING))
    assert {
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.nii.gz",
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.bval",
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.bvec",
        "sub-02/sub-02_sessions.tsv",
    } <= kept
    assert not any(p.startswith("sub-01") for p in kept)

    kept = set(
        BidsFilter(exclude_subjects=["02"], sessions=["2"]).select(LISTING)
    )
    data = {p for p in kept if p.endswith(".nii.gz")}
    assert data == {
        "sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz",
        "sub-01/ses-2/func/sub-01_ses-2_task-motor_bold.nii.gz",
    }


def test_select_globs():
    kept = set(BidsFilter(
        include=["sub-*/ses-1/anat/*"], exclude=["*.html", "README"]
    ).select(LISTING))
    data = {p for p in kept if p.endswith(".nii.gz")}
    assert data == {
        "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz",
        "sub-01/ses-1/anat/sub-01_ses-1_T2w.nii.gz",
        "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz",
    }
    assert "bold_group.html" not in kept and "README" not in kept
    assert "dataset_description.json" in kept
    # same-name sidecar next to the data file
    assert "sub-01/ses-1/anat/sub-01_ses-1_T2w.json" in kept


def test_unknown_folder():
    with pytest.raises(ValueError):
        BidsFilter(folders=["models"])


# -- brainfilter additions -----------------------------------------------------

NII = {p for p in LISTING if p.endswith(".nii.gz")}


def _data(kept):
    return {p for p in kept if p.endswith(".nii.gz")}


def test_select_is_sorted_and_deduplicated():
    kept = BidsFilter().select(LISTING + LISTING)
    assert kept == sorted(set(kept))


def test_keep_subject():
    f = BidsFilter(subjects=["01", "02"], exclude_subjects="sub-02")
    assert f.keep_subject("01") and f.keep_subject("sub-01")
    assert not f.keep_subject("02") and not f.keep_subject("03")
    assert BidsFilter().keep_subject("03")


def test_entity_keywords():
    LIST = LISTING + [
        "sub-03/anat/sub-03_acq-mprage_run-1_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-mprage_run-2_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-space_run-1_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-mprage_T1w.json",
    ]
    kept = set(BidsFilter(acq="mprage").select(LIST))
    assert _data(kept) == {
        "sub-03/anat/sub-03_acq-mprage_run-1_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-mprage_run-2_T1w.nii.gz",
    }
    assert "sub-03/anat/sub-03_acq-mprage_T1w.json" in kept
    assert "T1w.json" in kept and "T2w.json" not in kept
    # numbers, prefixes, any-of
    kept = set(BidsFilter(acq="acq-mprage", run=[2]).select(LIST))
    assert _data(kept) == {"sub-03/anat/sub-03_acq-mprage_run-2_T1w.nii.gz"}
    # `sub=` is `subjects=`; `entities=` takes any key
    assert BidsFilter(sub="02").select(LIST) == BidsFilter(subjects="02").select(LIST)
    assert BidsFilter(entities={"acq": "space"}).select(LIST) == (
        BidsFilter(acq="space").select(LIST)
    )
    # a missing entity never matches
    assert not _data(BidsFilter(run="1").select(LISTING))


def test_patterns_as_values():
    kept = BidsFilter(subjects=Glob("0*"), tasks=re.compile("mot.*")).select(LISTING)
    assert _data(kept) == {
        "sub-01/ses-2/func/sub-01_ses-2_task-motor_bold.nii.gz",
    }
    kept = BidsFilter(suffixes=["dwi", Regex("T2.*")]).select(LISTING)
    assert _data(kept) == {
        "sub-01/ses-1/anat/sub-01_ses-1_T2w.nii.gz",
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.nii.gz",
    }
    # a regex must match the whole label, not a part of it
    assert not _data(BidsFilter(tasks=re.compile("^mot")).select(LISTING))
    assert not _data(BidsFilter(suffixes=Regex("T2")).select(LISTING))
    kept = BidsFilter(exclude_subjects=Glob("*1")).select(LISTING)
    assert not any(p.startswith("sub-01") for p in kept)


REGEX_LISTING = [
    "sub-1/anat/sub-1_T1w.nii.gz",
    "sub-10/anat/sub-10_T1w.nii.gz",
    "sub-1/ses-pre/func/sub-1_ses-pre_task-rest_bold.nii.gz",
    "sub-1/ses-post/func/sub-1_ses-post_task-restless_bold.nii.gz",
    "sub-1/dwi/sub-1_acq-b1000_dwi.nii.gz",
]


@pytest.mark.parametrize("kwargs, expected", [
    ({"subjects": re.compile("1")}, {0, 2, 3, 4}),
    ({"subjects": Regex("1")}, {0, 2, 3, 4}),
    ({"subjects": re.compile("1.*")}, {0, 1, 2, 3, 4}),
    ({"exclude_subjects": re.compile("1")}, {1}),
    ({"sessions": re.compile("p")}, set()),
    ({"sessions": re.compile("p.*")}, {2, 3}),
    ({"tasks": re.compile("rest")}, {2}),
    ({"suffixes": re.compile("T1")}, set()),
    ({"suffixes": re.compile("T1w|dwi")}, {0, 1, 4}),
    ({"datatypes": re.compile("an")}, set()),
    ({"datatypes": re.compile("an.*")}, {0, 1}),
    ({"acq": re.compile("b1")}, set()),
    ({"acq": re.compile(r"b\d+")}, {4}),
    # in any-of conditions too
    ({"tasks": Or(Regex("rest"), Regex("x"))}, {2}),
    ({"tasks": And(Regex("rest.*"), Regex(".*less"))}, {3}),
])
def test_label_regex_is_fullmatch(kwargs, expected):
    kept = BidsFilter(**kwargs).select(REGEX_LISTING)
    assert _data(kept) == {REGEX_LISTING[i] for i in expected}


def test_path_regex_is_search():
    # include/exclude regexes are found anywhere in the relative path
    kept = BidsFilter(include=re.compile("sub-1/")).select(REGEX_LISTING)
    assert _data(kept) == set(REGEX_LISTING) - {REGEX_LISTING[1]}
    kept = BidsFilter(exclude=re.compile("T1w")).select(REGEX_LISTING)
    assert _data(kept) == set(REGEX_LISTING[2:])
    # a glob must still match the whole path
    assert not _data(BidsFilter(include="sub-1").select(REGEX_LISTING))


INDEX_LISTING = [
    "sub-01/anat/sub-01_run-1_T1w.nii.gz",
    "sub-01/anat/sub-01_run-01_T1w.nii.gz",
    "sub-01/anat/sub-01_run-2_T1w.nii.gz",
    "sub-01/anat/sub-01_run-10_T1w.nii.gz",
    "sub-01/func/sub-01_task-x_echo-001_bold.nii.gz",
    "sub-01/func/sub-01_task-x_echo-2_bold.nii.gz",
    "sub-01/func/sub-01_task-01_bold.nii.gz",
]


@pytest.mark.parametrize("kwargs, expected", [
    ({"run": 1}, {0, 1}),
    ({"run": "1"}, {0, 1}),
    ({"run": "01"}, {0, 1}),
    ({"run": "run-001"}, {0, 1}),
    ({"run": [2, "10"]}, {2, 3}),
    ({"run": 3}, set()),
    ({"echo": 1}, {4}),
    ({"entities": {"echo": "02"}}, {5}),
    # globs and regexes see the label as written
    ({"run": Glob("0*")}, {1}),
    ({"run": re.compile("1")}, {0}),
    ({"run": re.compile("0?1")}, {0, 1}),
    ({"run": Glob("1*")}, {0, 3}),
    # label entities compare exact strings
    ({"tasks": "01"}, {6}),
    ({"tasks": "1"}, set()),
    # ... but an int matches by number on any entity (`task-01` is 1)
    ({"tasks": 1}, {6}),
    ({"subjects": "1"}, set()),
])
def test_index_entities_compare_by_value(kwargs, expected):
    kept = BidsFilter(**kwargs).select(INDEX_LISTING)
    assert _data(kept) == {INDEX_LISTING[i] for i in expected}


def test_index_entities_from_schema():
    from brainfilter._names import INDEX_ENTITIES, SORTED_ENTITIES
    assert INDEX_ENTITIES == {"chunk", "echo", "flip", "inv", "run", "split"}
    assert INDEX_ENTITIES <= set(SORTED_ENTITIES)


def test_include_exclude_regex():
    kept = set(BidsFilter(
        include=re.compile(r"_T1w\."), exclude=[re.compile(r"\.html$"), "*"]
    ).select(LISTING))
    # `exclude="*"` removes everything but dataset_description.json
    assert kept == {"dataset_description.json"}
    kept = set(BidsFilter(include=re.compile(r"_T1w\.")).select(LISTING))
    assert _data(kept) == {
        "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz",
        "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz",
    }


def test_unknown_keyword():
    with pytest.raises(TypeError, match="subs"):
        BidsFilter(subs=["01"])
    with pytest.raises(TypeError):
        BidsFilter(subjects="01", sub="01")


def test_other_top_level_folders_are_skipped():
    kept = BidsFilter().select(["models/x.json", "README", "./CHANGES"])
    assert kept == ["./CHANGES", "README"]


def test_select_path_objects():
    root = PureBidsPath("ds")
    paths = [root / p for p in LISTING]
    kept = BidsFilter(suffixes="T1w").select(paths, root=root)
    assert kept == [root / p for p in BidsFilter(suffixes="T1w").select(LISTING)]
    assert all(isinstance(p, PureBidsPath) for p in kept)
    # already relative
    rel = [PureBidsPath(p) for p in LISTING]
    assert [str(p) for p in BidsFilter(tasks="rest").select(rel)] == (
        BidsFilter(tasks="rest").select(LISTING)
    )
    # strings under a root
    kept = BidsFilter(tasks="rest").select([f"ds/{p}" for p in LISTING], root="ds")
    assert kept == [f"ds/{p}" for p in BidsFilter(tasks="rest").select(LISTING)]


def _make(root, listing):
    if isinstance(root, BidsPath):
        root = root.with_mode("w")
    for rel in listing:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def test_walk_local(tmp_path):
    _make(tmp_path, LISTING)
    for f in (
        BidsFilter(), BidsFilter(subjects="02"), BidsFilter(folders="derivatives")
    ):
        kept = f.walk(str(tmp_path))
        assert all(isinstance(p, BidsPath) for p in kept)
        root = BidsPath(str(tmp_path))
        assert [str(p.relative_to(root)) for p in kept] == f.select(LISTING)


def test_walk_memory():
    pytest.importorskip("upath")
    root = BidsPath("memory:///brainfilter-walk")
    _make(root, LISTING)
    try:
        f = BidsFilter(datatypes="anat")
        kept = f.walk(root)
        assert [str(p.relative_to(root)) for p in kept] == f.select(LISTING)
        assert f.walk("memory:///brainfilter-walk") == kept
    finally:
        import fsspec
        fsspec.filesystem("memory").rm("/brainfilter-walk", recursive=True)


# -- applies_to ----------------------------------------------------------------

@pytest.mark.parametrize("meta, data, expected", [
    ("T1w.json", "sub-01/anat/sub-01_T1w.nii.gz", True),
    ("sub-01/sub-01_T1w.json", "sub-01/anat/sub-01_T1w.nii.gz", True),
    ("sub-01/anat/sub-01_T1w.json", "sub-01/anat/sub-01_T1w.nii.gz", True),
    # not an ancestor directory
    ("sub-02/sub-01_T1w.json", "sub-01/anat/sub-01_T1w.nii.gz", False),
    ("sub-01/anat/x/sub-01_T1w.json", "sub-01/anat/sub-01_T1w.nii.gz", False),
    # entities must be a subset
    ("acq-a_T1w.json", "sub-01/anat/sub-01_acq-b_T1w.nii.gz", False),
    ("sub-01_run-1_T1w.json", "sub-01/anat/sub-01_T1w.nii.gz", False),
    # suffix: same, or a companion
    ("T2w.json", "sub-01/anat/sub-01_T1w.nii.gz", False),
    ("sub-01/sub-01_scans.tsv", "sub-01/anat/sub-01_T1w.nii.gz", True),
    ("task-x_events.tsv", "sub-01/func/sub-01_task-x_bold.nii.gz", True),
    # datatype
    ("sub-01/func/sub-01_T1w.json", "sub-01/anat/sub-01_T1w.nii.gz", False),
])
def test_applies_to(meta, data, expected):
    assert applies_to(meta, data) is expected
    assert applies_to(PureBidsPath(meta), PureBidsPath(data)) is expected


@pytest.mark.parametrize("meta, data, expected", [
    # index entities compare by number, as the filters do
    ("sub-01/anat/sub-01_run-1_T1w.json",
     "sub-01/anat/sub-01_run-01_T1w.nii.gz", True),
    ("run-02_T1w.json", "sub-01/anat/sub-01_run-2_T1w.nii.gz", True),
    ("run-1_T1w.json", "sub-01/anat/sub-01_run-10_T1w.nii.gz", False),
    ("task-01_bold.json", "sub-01/func/sub-01_task-1_bold.nii.gz", False),
    # a companion's own space or recording is not on the data file
    ("sub-01/eeg/sub-01_space-CapTrak_electrodes.tsv",
     "sub-01/eeg/sub-01_task-x_eeg.edf", True),
    ("sub-01/eeg/sub-01_space-CapTrak_coordsystem.json",
     "sub-01/eeg/sub-01_task-x_eeg.edf", True),
    ("sub-01/func/sub-01_task-x_recording-cardiac_physio.tsv.gz",
     "sub-01/func/sub-01_task-x_bold.nii.gz", True),
    ("sub-01/nirs/sub-01_optodes.tsv", "sub-01/nirs/sub-01_task-x_nirs.snirf",
     True),
    # ... but must agree with one the data file has
    ("sub-01/emg/sub-01_recording-a_channels.tsv",
     "sub-01/emg/sub-01_task-x_recording-b_emg.edf", False),
    # ... and only a companion may lack it
    ("sub-01/eeg/sub-01_space-CapTrak_eeg.json",
     "sub-01/eeg/sub-01_task-x_eeg.edf", False),
    ("sub-01/anat/sub-01_space-x_T1w.json",
     "sub-01/anat/sub-01_T1w.nii.gz", False),
    # files inside a directory-shaped data file belong to it
    ("sub-01/meg/sub-01_task-x_meg.json",
     "sub-01/meg/sub-01_task-x_meg.ds/BadChannels", True),
    # a photo, a headshape, markers or a blood recording is a companion
    ("sub-01/eeg/sub-01_photo.jpg", "sub-01/eeg/sub-01_task-x_eeg.edf", True),
    ("sub-01/emg/sub-01_recording-a_photo.png",
     "sub-01/emg/sub-01_task-x_emg.edf", True),
    ("sub-01/eeg/sub-01_acq-NAS_photo.jpg",
     "sub-01/eeg/sub-01_task-x_eeg.edf", False),
    ("sub-01/meg/sub-01_headshape.pos", "sub-01/meg/sub-01_task-x_meg.fif",
     True),
    ("sub-01/meg/sub-01_task-x_space-CapTrak_markers.mrk",
     "sub-01/meg/sub-01_task-x_run-1_meg.fif", True),
    ("sub-01/meg/sub-01_task-y_markers.mrk",
     "sub-01/meg/sub-01_task-x_meg.fif", False),
    ("sub-01/pet/sub-01_recording-manual_blood.tsv",
     "sub-01/pet/sub-01_pet.nii.gz", True),
    ("sub-01/pet/sub-01_trc-a_recording-manual_blood.json",
     "sub-01/pet/sub-01_trc-b_pet.nii.gz", False),
    # a MEG system file, of every MEG recording, whatever its `acq`
    ("sub-01/meg/sub-01_acq-crosstalk_meg.fif",
     "sub-01/meg/sub-01_task-x_meg.fif", True),
    ("sub-01/meg/sub-01_acq-calibration_meg.dat",
     "sub-01/meg/sub-01_task-x_acq-a_meg.fif", True),
    ("sub-01/meg/sub-01_acq-calibration_meg.dat",
     "sub-01/meg/sub-01_task-x_meg.ds/BadChannels", True),
    ("sub-01/ses-1/meg/sub-01_ses-1_acq-crosstalk_meg.fif",
     "sub-01/ses-1/meg/sub-01_ses-1_task-x_meg.fif", True),
    ("sub-01/ses-1/meg/sub-01_ses-1_acq-crosstalk_meg.fif",
     "sub-01/ses-2/meg/sub-01_ses-2_task-x_meg.fif", False),
    ("sub-01/meg/sub-01_acq-crosstalk_meg.fif",
     "sub-02/meg/sub-02_task-x_meg.fif", False),
    ("sub-01/meg/sub-01_acq-crosstalk_meg.fif",
     "sub-01/meg/sub-01_task-x_physio.tsv.gz", False),
    ("sub-01/meg/sub-01_acq-crosstalk_meg.fif",
     "sub-01/meg/sub-01_acq-calibration_meg.dat", False),
    # ... with the extension the schema gives it, and no task
    ("sub-01/meg/sub-01_acq-crosstalk_meg.dat",
     "sub-01/meg/sub-01_task-x_meg.fif", False),
    ("sub-01/meg/sub-01_task-x_acq-crosstalk_meg.fif",
     "sub-01/meg/sub-01_task-x_meg.fif", False),
])
def test_applies_to_index_and_companion_entities(meta, data, expected):
    assert applies_to(meta, data) is expected


def test_closure_compares_index_entities_by_number():
    listing = [
        "dataset_description.json",
        "run-1_T1w.json",
        "sub-01/anat/sub-01_run-01_T1w.nii.gz",
        "sub-02/anat/sub-02_run-1_T1w.nii.gz",
        "sub-01/anat/sub-01_run-1_T1w.json",
    ]
    # `run-1_T1w.json` applies to sub-02 (dropped) and, by number, to sub-01
    assert BidsFilter(subjects="01").select(listing) == [
        "dataset_description.json",
        "run-1_T1w.json",
        "sub-01/anat/sub-01_run-01_T1w.nii.gz",
        "sub-01/anat/sub-01_run-1_T1w.json",
    ]


# Files from outside imaging: tables that are recordings, companions with
# entities their data lacks, continuous recordings and an events file alone.
OTHER_DATA = [
    "dataset_description.json",
    "sub-01/beh/sub-01_task-x_beh.tsv",
    "sub-01/beh/sub-01_task-x_beh.json",
    "sub-01/motion/sub-01_task-x_tracksys-imu_motion.tsv",
    "sub-01/motion/sub-01_task-x_tracksys-imu_motion.json",
    "sub-01/motion/sub-01_task-x_tracksys-imu_channels.tsv",
    "sub-01/pet/sub-01_pet.nii.gz",
    "sub-01/pet/sub-01_pet.json",
    "sub-01/pet/sub-01_recording-manual_blood.tsv",
    "sub-01/pet/sub-01_recording-manual_blood.json",
    "sub-01/nirs/sub-01_task-x_nirs.snirf",
    "sub-01/nirs/sub-01_optodes.tsv",
    "sub-01/nirs/sub-01_coordsystem.json",
    "sub-01/eeg/sub-01_task-x_eeg.edf",
    "sub-01/eeg/sub-01_task-x_eeg.json",
    "sub-01/eeg/sub-01_task-x_channels.tsv",
    "sub-01/eeg/sub-01_space-CapTrak_electrodes.tsv",
    "sub-01/eeg/sub-01_space-CapTrak_coordsystem.json",
    "sub-01/func/sub-01_task-x_bold.nii.gz",
    "sub-01/func/sub-01_task-x_recording-cardiac_physio.tsv.gz",
    "sub-01/func/sub-01_task-x_recording-cardiac_physio.json",
    "sub-02/beh/sub-02_task-y_events.tsv",
    "sub-02/beh/sub-02_task-y_events.json",
]


def _under(listing, *prefixes):
    return {"dataset_description.json"} | {
        p for p in listing if p.startswith(prefixes)
    }


def test_select_all_keeps_non_imaging_data():
    assert BidsFilter().select(OTHER_DATA) == sorted(OTHER_DATA)


@pytest.mark.parametrize("kwargs, prefixes", [
    ({"datatypes": "beh"}, ("sub-01/beh/", "sub-02/beh/")),
    ({"datatypes": "motion"}, ("sub-01/motion/",)),
    ({"datatypes": "pet"}, ("sub-01/pet/",)),
    ({"datatypes": "nirs"}, ("sub-01/nirs/",)),
    ({"subjects": "01", "datatypes": "eeg"}, ("sub-01/eeg/",)),
    # electrodes and coordsystem have `space`, the recording has not
    ({"tasks": "x", "datatypes": "eeg"}, ("sub-01/eeg/",)),
    # a recording table is chosen by its own suffix
    ({"suffixes": "blood"}, ("sub-01/pet/sub-01_recording-manual_blood",)),
    ({"suffixes": "beh"}, ("sub-01/beh/",)),
    # physio is data, and a companion of the bold run
    ({"suffixes": "physio"}, ("sub-01/func/sub-01_task-x_recording",)),
    ({"suffixes": "bold"}, ("sub-01/func/",)),
    # the events alone in sub-02 are a data file with no `recording`
    ({"recording": "cardiac"}, ("sub-01/func/sub-01_task-x_recording",)),
    # a companion is a data file a filter selects, with its JSON sidecar
    ({"suffixes": "events"}, ("sub-02/beh/",)),
    ({"suffixes": "channels"}, ("sub-01/motion/sub-01_task-x_tracksys-imu_ch",
                                "sub-01/eeg/sub-01_task-x_channels")),
    ({"suffixes": "coordsystem"}, ("sub-01/nirs/sub-01_coordsystem",
                                   "sub-01/eeg/sub-01_space-CapTrak_coord")),
])
def test_select_non_imaging_data(kwargs, prefixes):
    assert set(BidsFilter(**kwargs).select(OTHER_DATA)) == (
        _under(OTHER_DATA, *prefixes)
    )


def test_a_companion_with_no_recording_is_judged_as_data():
    # `sub-02/beh/*_events.tsv` describes no recording of the listing
    events = _under(OTHER_DATA, "sub-02/")
    assert set(BidsFilter(subjects="02").select(OTHER_DATA)) == events
    assert set(BidsFilter(tasks="y").select(OTHER_DATA)) == events
    assert set(BidsFilter(suffixes="events").select(OTHER_DATA)) == events
    assert not set(BidsFilter(tasks="x").select(OTHER_DATA)) & (
        events - {"dataset_description.json"}
    )
    assert set(BidsFilter(suffixes="T1w").select(OTHER_DATA)) == {
        "dataset_description.json"
    }
    # an entity filter on an entity it lacks rejects it, as any data file;
    # its directories name its subject; it needs no dataset root
    desc = ["dataset_description.json"]
    alone = ["sub-03/ses-1/beh/task-z_events.tsv"]
    assert BidsFilter(subjects="03", sessions="1").select(desc + alone) == (
        desc + alone
    )
    assert BidsFilter(subjects="03", run=2).select(desc + alone) == desc
    assert BidsFilter(subjects="01").select(desc + alone) == desc
    assert BidsFilter(sessions="2").select(desc + alone) == desc
    assert BidsFilter(subjects="03").select(alone) == alone


def test_metadata_with_no_data_is_judged_on_what_it_names():
    # a sidecar that describes no data file of the listing
    desc = ["dataset_description.json"]
    alone = ["sub-03/ses-1/beh/task-z_beh.json"]
    f = BidsFilter(subjects="03", sessions="1", run=2)
    assert f.select(desc + alone) == desc + alone
    assert BidsFilter(subjects="01").select(desc + alone) == desc
    assert BidsFilter(sessions="2").select(desc + alone) == desc
    assert BidsFilter(suffixes="beh").select(desc + alone) == desc + alone
    # outside every dataset root it is never kept on its own
    assert not f.select(alone)


def test_recording_tables_are_data():
    for path in ("sub-01/beh/sub-01_task-x_beh.tsv",
                 "sub-01/motion/sub-01_task-x_motion.tsv",
                 "sub-01/pet/sub-01_recording-manual_blood.tsv"):
        assert not parse_path(path).is_metadata
        assert not PureBidsPath(path).is_metadata
    for path in ("sub-01/beh/sub-01_task-x_beh.json",
                 "sub-01/eeg/sub-01_task-x_channels.tsv",
                 "sub-01/func/sub-01_task-x_events.tsv"):
        assert parse_path(path).is_metadata
        assert PureBidsPath(path).is_metadata


def test_system_files_need_a_companion():
    meta = "sub-01/meg/sub-01_acq-crosstalk_meg.fif"
    data = "sub-01/meg/sub-01_task-x_meg.fif"
    assert applies_to(meta, data)
    assert not applies_to(meta, data, companions=False)   # not a sidecar


# The files of a MEG session's set-up, a PET image with its blood recordings,
# and a session holding set-up files alone.
SET_UP = [
    "dataset_description.json",
    "sub-01/ses-1/meg/sub-01_ses-1_task-rest_meg.fif",
    "sub-01/ses-1/meg/sub-01_ses-1_task-rest_meg.json",
    "sub-01/ses-1/meg/sub-01_ses-1_task-noise_acq-b_meg.fif",
    "sub-01/ses-1/meg/sub-01_ses-1_acq-calibration_meg.dat",
    "sub-01/ses-1/meg/sub-01_ses-1_acq-crosstalk_meg.fif",
    "sub-01/ses-1/meg/sub-01_ses-1_headshape.pos",
    "sub-01/ses-1/meg/sub-01_ses-1_photo.jpg",
    "sub-01/ses-1/meg/sub-01_ses-1_acq-NAS_photo.jpg",
    "sub-01/ses-1/meg/sub-01_ses-1_acq-b_headshape.pos",
    "sub-01/ses-1/meg/sub-01_ses-1_task-rest_markers.mrk",
    "sub-01/ses-1/meg/sub-01_ses-1_task-rest_channels.tsv",
    "sub-01/ses-2/meg/sub-01_ses-2_acq-crosstalk_meg.fif",
    "sub-01/ses-2/meg/sub-01_ses-2_headshape.pos",
    "sub-01/pet/sub-01_trc-FDG_pet.nii.gz",
    "sub-01/pet/sub-01_trc-FDG_recording-manual_blood.tsv",
    "sub-01/pet/sub-01_trc-FDG_recording-manual_blood.json",
    "sub-01/pet/sub-01_trc-FDG_recording-auto_blood.tsv",
    "sub-01/pet/sub-01_trc-other_recording-auto_blood.tsv",
]
MEG1 = "sub-01/ses-1/meg/sub-01_ses-1_"
MEG2 = "sub-01/ses-2/meg/sub-01_ses-2_"
PET = "sub-01/pet/sub-01_trc-"


def _named(*names):
    return {"dataset_description.json", *names}


SYSTEM = (f"{MEG1}acq-calibration_meg.dat", f"{MEG1}acq-crosstalk_meg.fif",
          f"{MEG1}headshape.pos", f"{MEG1}photo.jpg",
          f"{MEG1}acq-NAS_photo.jpg")      # no recording has acq-NAS
NOISE = f"{MEG1}task-noise_acq-b_meg.fif"
ACQ_B = f"{MEG1}acq-b_headshape.pos"     # the noise recording has acq-b
REST = (f"{MEG1}task-rest_meg.fif", f"{MEG1}task-rest_meg.json",
        f"{MEG1}task-rest_markers.mrk", f"{MEG1}task-rest_channels.tsv")


@pytest.mark.parametrize("kwargs, expected", [
    # the set-up files come along with each recording of the session; the
    # markers and channels of its task too; a headshape whose `acq` one of
    # the recordings has, with that recording alone
    ({"tasks": "rest", "sessions": "1"}, _named(*SYSTEM, *REST)),
    ({"tasks": "noise", "sessions": "1"}, _named(*SYSTEM, NOISE, ACQ_B)),
    ({"suffixes": "meg", "sessions": "1"}, _named(*SYSTEM, *REST, NOISE, ACQ_B)),
    ({"acq": "b", "sessions": "1"}, _named(*SYSTEM, NOISE, ACQ_B)),
    # a companion is a data file too: a filter that names it selects it,
    # and not the recordings it describes
    ({"acq": "calibration", "sessions": "1"}, _named(SYSTEM[0])),
    ({"acq": "crosstalk", "sessions": "1"}, _named(SYSTEM[1])),
    ({"acq": "NAS"}, _named(f"{MEG1}acq-NAS_photo.jpg")),
    ({"suffixes": "photo", "sessions": "1"}, _named(
        f"{MEG1}photo.jpg", f"{MEG1}acq-NAS_photo.jpg",
    )),
    ({"suffixes": "headshape"}, _named(
        f"{MEG1}headshape.pos", ACQ_B, f"{MEG2}headshape.pos",
    )),
    ({"suffixes": "markers"}, _named(f"{MEG1}task-rest_markers.mrk")),
    # a session with set-up files alone: judged as data files
    ({"sessions": "2"}, _named(
        f"{MEG2}acq-crosstalk_meg.fif", f"{MEG2}headshape.pos",
    )),
    ({"sessions": "2", "suffixes": "meg"}, _named(f"{MEG2}acq-crosstalk_meg.fif")),
    ({"sessions": "2", "acq": "crosstalk"}, _named(f"{MEG2}acq-crosstalk_meg.fif")),
    ({"sessions": "2", "acq": typing.Any}, _named(f"{MEG2}acq-crosstalk_meg.fif")),
    ({"sessions": "2", "tasks": "rest"}, _named()),
    # blood recordings come along with their PET image, and are data too
    ({"suffixes": "pet"}, _named(
        f"{PET}FDG_pet.nii.gz", f"{PET}FDG_recording-manual_blood.tsv",
        f"{PET}FDG_recording-manual_blood.json",
        f"{PET}FDG_recording-auto_blood.tsv",
    )),
    ({"suffixes": "blood", "recording": "auto"}, _named(
        f"{PET}FDG_recording-auto_blood.tsv",
        f"{PET}other_recording-auto_blood.tsv",
    )),
    ({"trc": "other"}, _named(f"{PET}other_recording-auto_blood.tsv")),
    ({"subjects": "02"}, _named()),
])
def test_select_companion_files(kwargs, expected):
    assert set(BidsFilter(**kwargs).select(SET_UP)) == expected


def test_walk_companion_files(tmp_path):
    _make(tmp_path, SET_UP)
    root = BidsPath(str(tmp_path))
    for f in (BidsFilter(), BidsFilter(tasks="rest"), BidsFilter(sessions="2"),
              BidsFilter(suffixes="pet"), BidsFilter(acq="crosstalk"),
              BidsFilter(subjects="02"), BidsFilter(suffixes="photo"),
              BidsFilter(tasks="noise", sessions="1")):
        kept = [p.relative_to(root).as_posix() for p in f.walk(root)]
        assert kept == f.select(SET_UP)


def test_ignored_companion_files_come_along_alone(tmp_path):
    _make(tmp_path, SET_UP)
    (tmp_path / ".bidsignore").write_text("*_acq-crosstalk_meg.fif\n")
    root = BidsPath(str(tmp_path))
    for f in (BidsFilter(tasks="rest", sessions={"1", "2"}),
              BidsFilter(sessions={"1", "2"})):
        kept = [p.relative_to(root).as_posix() for p in f.walk(root)]
        assert f"{MEG1}acq-crosstalk_meg.fif" in kept     # with its recording
        assert f"{MEG2}acq-crosstalk_meg.fif" not in kept  # never selected
    assert f"{MEG2}headshape.pos" in kept           # selected
    paths = [root / p for p in [*SET_UP, ".bidsignore"]]
    assert kept == [p.relative_to(root).as_posix() for p in f.select(paths, root)]


def test_companion_files_parse_as_such():
    for path in (f"{MEG1}acq-crosstalk_meg.fif", f"{MEG1}acq-calibration_meg.dat",
                 f"{MEG1}photo.jpg", f"{MEG1}headshape.pos",
                 f"{MEG1}task-rest_markers.mrk", "sub-01/micr/sub-01_photo.tif"):
        assert parse_path(path).is_companion_file
        assert not parse_path(path).is_metadata
    for path in (f"{MEG1}task-rest_meg.fif", f"{MEG1}acq-crosstalk_meg.dat",
                 f"{MEG1}task-rest_acq-crosstalk_meg.fif",
                 f"{PET}FDG_recording-auto_blood.tsv",
                 "sub-01/micr/sub-01_photo.json",       # metadata
                 "sub-01/meg/sub-01_task-x_meg.ds/sub-01_photo.jpg"):
        assert not parse_path(path).is_companion_file


# Data files that are directories: CTF MEG, a MEG directory with no
# extension (BTi/4D), OME-Zarr microscopy (hidden-named metadata inside)
DIRECTORY_DATA = [
    "dataset_description.json",
    "sub-01/meg/sub-01_task-x_meg.ds/BadChannels",
    "sub-01/meg/sub-01_task-x_meg.ds/sub-01_task-x_meg.res4",
    "sub-01/meg/sub-01_task-x_meg.ds/sub-01_task-x_meg.meg4",
    "sub-01/meg/sub-01_task-x_meg.json",
    "sub-01/meg/sub-01_task-x_channels.tsv",
    "sub-01/meg/sub-01_coordsystem.json",
    "sub-01/micr/sub-01_sample-A_BF.ome.zarr/.zattrs",
    "sub-01/micr/sub-01_sample-A_BF.ome.zarr/.zgroup",
    "sub-01/micr/sub-01_sample-A_BF.ome.zarr/0/.zarray",
    "sub-01/micr/sub-01_sample-A_BF.ome.zarr/0/0.0",
    "sub-01/micr/sub-01_sample-A_BF.ome.zarr/zarr.json",
    "sub-01/micr/sub-01_sample-A_BF.json",
    "sub-02/meg/sub-02_task-y_meg/config",
    "sub-02/meg/sub-02_task-y_meg/c,rfDC",
    "sub-02/meg/sub-02_task-y_meg.json",
]


def test_select_directory_shaped_data():
    assert BidsFilter().select(DIRECTORY_DATA) == sorted(DIRECTORY_DATA)
    hidden = DIRECTORY_DATA + [
        "sub-01/meg/.cache/x", "sub-01/micr/.sub-01_BF.ome.zarr/.zattrs",
    ]
    assert BidsFilter().select(hidden) == sorted(DIRECTORY_DATA)
    assert set(BidsFilter(datatypes="meg").select(DIRECTORY_DATA)) == (
        _under(DIRECTORY_DATA, "sub-01/meg/", "sub-02/meg/")
    )
    assert set(BidsFilter(subjects="01").select(DIRECTORY_DATA)) == (
        _under(DIRECTORY_DATA, "sub-01/")
    )
    assert set(BidsFilter(tasks="y").select(DIRECTORY_DATA)) == (
        _under(DIRECTORY_DATA, "sub-02/")
    )
    assert set(BidsFilter(suffixes="BF").select(DIRECTORY_DATA)) == (
        _under(DIRECTORY_DATA, "sub-01/micr/")
    )
    # the directory is one item: include matches it, not a file inside
    assert set(BidsFilter(include="*.ds").select(DIRECTORY_DATA)) == (
        _under(DIRECTORY_DATA, "sub-01/meg/")
    )
    # exclude still removes single files
    kept = BidsFilter(exclude="*.ome.zarr/.zattrs").select(DIRECTORY_DATA)
    assert "sub-01/micr/sub-01_sample-A_BF.ome.zarr/.zattrs" not in kept
    assert "sub-01/micr/sub-01_sample-A_BF.ome.zarr/0/.zarray" in kept


def test_directory_shaped_data_parses_as_the_directory():
    name = parse_path("sub-01/meg/sub-01_task-x_meg.ds/BadChannels")
    assert name.item == "sub-01/meg/sub-01_task-x_meg.ds"
    assert (name.entities, name.suffix, name.extension, name.datatype) == (
        {"sub": "01", "task": "x"}, "meg", ".ds", "meg"
    )
    assert not name.is_metadata
    zarr = "sub-01/micr/sub-01_sample-A_BF.ome.zarr/0/.zarray"
    assert parse_path(zarr).datatype == "micr"
    assert not parse_path(zarr.replace("0/.zarray", "zarr.json")).is_metadata
    assert parse_path("sub-02/meg/sub-02_task-y_meg/config").suffix == "meg"
    # a directory with no extension is data only in a datatype directory
    assert parse_path("sub-02/sub-02_task-y_meg/config").item == (
        "sub-02/sub-02_task-y_meg/config"
    )
    p = PureBidsPath("ds/sub-01/meg/sub-01_task-x_meg.ds/BadChannels")
    assert p.datatype == "meg" and not p.is_metadata
    assert PureBidsPath(f"ds/{zarr}").datatype == "micr"
    assert PureBidsPath("ds/sub-01/meg/sub-01_task-x_meg.ds").datatype == "meg"


def test_walk_keeps_hidden_names_inside_data_directories(tmp_path):
    _make(tmp_path, DIRECTORY_DATA + [".git/HEAD", "sub-01/.cache/x"])
    for f in (BidsFilter(), BidsFilter(datatypes="micr"), BidsFilter(subjects="02")):
        kept = f.walk(str(tmp_path))
        root = BidsPath(str(tmp_path))
        assert [p.relative_to(root).as_posix() for p in kept] == (
            f.select(DIRECTORY_DATA)
        )
    names = {p.name for p in BidsFilter(datatypes="micr").walk(str(tmp_path))}
    assert {".zattrs", ".zgroup", ".zarray", "0.0", "zarr.json"} <= names


def _tree(tmp_path, listing):
    """Every path below `tmp_path` after making `listing`, dirs included."""
    _make(tmp_path, listing)
    return sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))


@pytest.mark.parametrize("f", [
    BidsFilter(), BidsFilter(subjects="02"), BidsFilter(datatypes="anat"),
    BidsFilter(sessions="1"), BidsFilter(suffixes="T1w"),
])
def test_select_skips_bids_directories(tmp_path, f):
    everything = _tree(tmp_path, LISTING)
    assert "derivatives" in everything and "sub-01/ses-1/anat" in everything
    assert f.select(everything) == f.select(LISTING)


def test_select_skips_top_level_directories():
    dirs = ["derivatives", "sourcedata", "code", "stimuli", "phenotype",
            "sub-01", "sub-02", "sub-01/ses-1", "sub-01/anat",
            "sub-01/ses-1/anat"]
    assert BidsFilter().select(dirs + ["README"]) == ["README"]
    assert BidsFilter(subjects="02").select(dirs) == []
    # a top-level file whose name starts like a subject is still a file
    desc = ["dataset_description.json"]
    assert BidsFilter().select(desc + ["sub-01_T1w.json"]) == desc + [
        "sub-01_T1w.json"
    ]


def test_label_regex_honours_explicit_full():
    # a regex that does not choose must match the whole label ...
    assert _data(BidsFilter(subjects=Regex("1")).select(REGEX_LISTING)) == {
        REGEX_LISTING[i] for i in (0, 2, 3, 4)
    }
    # ... but `full=False` is a search, as asked
    assert _data(
        BidsFilter(subjects=Regex("1", full=False)).select(REGEX_LISTING)
    ) == set(REGEX_LISTING)
    assert _data(
        BidsFilter(tasks=Or(Regex("rest", full=False))).select(REGEX_LISTING)
    ) == {REGEX_LISTING[2], REGEX_LISTING[3]}


def test_walk_any_family_root(tmp_path):
    from brainfilter.bidspath import AsyncBidsPath

    _make(tmp_path, LISTING)
    f = BidsFilter(subjects="01")
    expected = f.walk(str(tmp_path))
    for root in (AsyncBidsPath(str(tmp_path)), PureBidsPath(str(tmp_path))):
        kept = f.walk(root)
        assert kept == expected
        assert all(isinstance(p, BidsPath) for p in kept)


INT_LISTING = [
    "sub-1/anat/sub-1_T1w.nii.gz",
    "sub-01/anat/sub-01_T1w.nii.gz",
    "sub-001/ses-02/anat/sub-001_ses-02_acq-003_T1w.nii.gz",
    "sub-1a/ses-2/anat/sub-1a_ses-2_acq-3_T1w.nii.gz",
    "sub-2/ses-2a/anat/sub-2_ses-2a_acq-3b_T1w.nii.gz",
]


@pytest.mark.parametrize("kwargs, expected", [
    # an int matches any all-digit label equal to it, on any entity
    ({"subjects": 1}, {0, 1, 2}),
    ({"sub": 1}, {0, 1, 2}),
    ({"sessions": 2}, {2, 3}),
    ({"ses": 2}, {2, 3}),
    ({"acq": 3}, {2, 3}),
    ({"entities": {"acq": 3}}, {2, 3}),
    ({"subjects": [1, 2]}, {0, 1, 2, 4}),
    ({"exclude_subjects": 1}, {3, 4}),
    # a string on a label entity is exact text
    ({"subjects": "1"}, {0}),
    ({"subjects": "01"}, {1}),
    ({"subjects": "sub-001"}, {2}),
    ({"sessions": "2"}, {3}),
    ({"acq": "3"}, {3}),
    ({"subjects": ["1", 2]}, {0, 4}),
    # a bool is not a number
    ({"subjects": True}, set()),
])
def test_int_values_match_by_number_on_any_entity(kwargs, expected):
    kept = BidsFilter(**kwargs).select(INT_LISTING)
    assert _data(kept) == {INT_LISTING[i] for i in expected}


def test_int_subject_in_keep_subject():
    assert BidsFilter(subjects=1).keep_subject("sub-001")
    assert not BidsFilter(subjects="1").keep_subject("001")
    assert not BidsFilter(subjects=1).keep_subject("1a")
