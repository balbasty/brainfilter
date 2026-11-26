import re

import pytest

from brainfilter._names import applies_to, parse_path
from brainfilter.bidspath import BidsPath, PureBidsPath
from brainfilter.conditions import And, Glob, Or, Regex
from brainfilter.filter import Filter

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
    kept = set(Filter().select(LISTING))
    assert ".datalad/config" not in kept
    assert ".gitattributes" not in kept
    assert not any(p.startswith(("derivatives/", "sourcedata/")) for p in kept)
    assert ALWAYS <= kept
    # every sidecar applies to some data file
    assert {"T1w.json", "T2w.json", "magnitude1.json",
            "task-rest_bold.json", "task-motor_bold.json"} <= kept


def test_select_optional_folders():
    kept = set(Filter(folders=["derivatives"]).select(LISTING))
    assert "derivatives/surfaces/sub-01/x.gii" in kept
    assert "sourcedata/raw.zip" not in kept


def test_select_suffix_with_inheritance():
    kept = set(Filter(suffixes=["T1w"]).select(LISTING))
    assert kept == ALWAYS | {
        "T1w.json",
        "sub-01/sub-01_sessions.tsv",
        "sub-01/ses-1/sub-01_ses-1_scans.tsv",
        "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz",
        "sub-02/sub-02_sessions.tsv",
        "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz",
    }


def test_select_task_includes_matching_sidecars_and_events():
    kept = set(Filter(tasks=["motor"]).select(LISTING))
    assert "sub-01/ses-2/func/sub-01_ses-2_task-motor_bold.nii.gz" in kept
    assert "sub-01/ses-2/func/sub-01_ses-2_task-motor_events.tsv" in kept
    assert "task-motor_bold.json" in kept
    assert "task-rest_bold.json" not in kept
    assert "sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz" not in kept
    assert "T1w.json" not in kept
    assert "sub-01/ses-1/sub-01_ses-1_scans.tsv" not in kept


def test_select_subjects_sessions_datatypes():
    kept = set(Filter(subjects=["sub-02"], datatypes=["dwi"]).select(LISTING))
    assert {
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.nii.gz",
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.bval",
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.bvec",
        "sub-02/sub-02_sessions.tsv",
    } <= kept
    assert not any(p.startswith("sub-01") for p in kept)

    kept = set(
        Filter(exclude_subjects=["02"], sessions=["2"]).select(LISTING)
    )
    data = {p for p in kept if p.endswith(".nii.gz")}
    assert data == {
        "sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz",
        "sub-01/ses-2/func/sub-01_ses-2_task-motor_bold.nii.gz",
    }


def test_select_globs():
    kept = set(Filter(
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
        Filter(folders=["models"])


# -- brainfilter additions -----------------------------------------------------

NII = {p for p in LISTING if p.endswith(".nii.gz")}


def _data(kept):
    return {p for p in kept if p.endswith(".nii.gz")}


def test_select_is_sorted_and_deduplicated():
    kept = Filter().select(LISTING + LISTING)
    assert kept == sorted(set(kept))


def test_keep_subject():
    f = Filter(subjects=["01", "02"], exclude_subjects="sub-02")
    assert f.keep_subject("01") and f.keep_subject("sub-01")
    assert not f.keep_subject("02") and not f.keep_subject("03")
    assert Filter().keep_subject("03")


def test_entity_keywords():
    LIST = LISTING + [
        "sub-03/anat/sub-03_acq-mprage_run-1_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-mprage_run-2_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-space_run-1_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-mprage_T1w.json",
    ]
    kept = set(Filter(acq="mprage").select(LIST))
    assert _data(kept) == {
        "sub-03/anat/sub-03_acq-mprage_run-1_T1w.nii.gz",
        "sub-03/anat/sub-03_acq-mprage_run-2_T1w.nii.gz",
    }
    assert "sub-03/anat/sub-03_acq-mprage_T1w.json" in kept
    assert "T1w.json" in kept and "T2w.json" not in kept
    # numbers, prefixes, any-of
    kept = set(Filter(acq="acq-mprage", run=[2]).select(LIST))
    assert _data(kept) == {"sub-03/anat/sub-03_acq-mprage_run-2_T1w.nii.gz"}
    # `sub=` is `subjects=`; `entities=` takes any key
    assert Filter(sub="02").select(LIST) == Filter(subjects="02").select(LIST)
    assert Filter(entities={"acq": "space"}).select(LIST) == (
        Filter(acq="space").select(LIST)
    )
    # a missing entity never matches
    assert not _data(Filter(run="1").select(LISTING))


def test_patterns_as_values():
    kept = Filter(subjects=Glob("0*"), tasks=re.compile("mot.*")).select(LISTING)
    assert _data(kept) == {
        "sub-01/ses-2/func/sub-01_ses-2_task-motor_bold.nii.gz",
    }
    kept = Filter(suffixes=["dwi", Regex("T2.*")]).select(LISTING)
    assert _data(kept) == {
        "sub-01/ses-1/anat/sub-01_ses-1_T2w.nii.gz",
        "sub-02/ses-1/dwi/sub-02_ses-1_dwi.nii.gz",
    }
    # a regex must match the whole label, not a part of it
    assert not _data(Filter(tasks=re.compile("^mot")).select(LISTING))
    assert not _data(Filter(suffixes=Regex("T2")).select(LISTING))
    kept = Filter(exclude_subjects=Glob("*1")).select(LISTING)
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
    kept = Filter(**kwargs).select(REGEX_LISTING)
    assert _data(kept) == {REGEX_LISTING[i] for i in expected}


def test_path_regex_is_search():
    # include/exclude regexes are found anywhere in the relative path
    kept = Filter(include=re.compile("sub-1/")).select(REGEX_LISTING)
    assert _data(kept) == set(REGEX_LISTING) - {REGEX_LISTING[1]}
    kept = Filter(exclude=re.compile("T1w")).select(REGEX_LISTING)
    assert _data(kept) == set(REGEX_LISTING[2:])
    # a glob must still match the whole path
    assert not _data(Filter(include="sub-1").select(REGEX_LISTING))


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
    ({"tasks": 1}, set()),
    ({"subjects": "1"}, set()),
])
def test_index_entities_compare_by_value(kwargs, expected):
    kept = Filter(**kwargs).select(INDEX_LISTING)
    assert _data(kept) == {INDEX_LISTING[i] for i in expected}


def test_index_entities_from_schema():
    from brainfilter._names import INDEX_ENTITIES, SORTED_ENTITIES
    assert INDEX_ENTITIES == {"chunk", "echo", "flip", "inv", "run", "split"}
    assert INDEX_ENTITIES <= set(SORTED_ENTITIES)


def test_include_exclude_regex():
    kept = set(Filter(
        include=re.compile(r"_T1w\."), exclude=[re.compile(r"\.html$"), "*"]
    ).select(LISTING))
    # `exclude="*"` removes everything but dataset_description.json
    assert kept == {"dataset_description.json"}
    kept = set(Filter(include=re.compile(r"_T1w\.")).select(LISTING))
    assert _data(kept) == {
        "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz",
        "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz",
    }


def test_unknown_keyword():
    with pytest.raises(TypeError, match="subs"):
        Filter(subs=["01"])
    with pytest.raises(TypeError):
        Filter(subjects="01", sub="01")


def test_other_top_level_folders_are_skipped():
    kept = Filter().select(["models/x.json", "README", "./CHANGES"])
    assert kept == ["./CHANGES", "README"]


def test_select_path_objects():
    root = PureBidsPath("ds")
    paths = [root / p for p in LISTING]
    kept = Filter(suffixes="T1w").select(paths, root=root)
    assert kept == [root / p for p in Filter(suffixes="T1w").select(LISTING)]
    assert all(isinstance(p, PureBidsPath) for p in kept)
    # already relative
    rel = [PureBidsPath(p) for p in LISTING]
    assert [str(p) for p in Filter(tasks="rest").select(rel)] == (
        Filter(tasks="rest").select(LISTING)
    )
    # strings under a root
    kept = Filter(tasks="rest").select([f"ds/{p}" for p in LISTING], root="ds")
    assert kept == [f"ds/{p}" for p in Filter(tasks="rest").select(LISTING)]


def _make(root, listing):
    for rel in listing:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def test_walk_local(tmp_path):
    _make(tmp_path, LISTING)
    for f in (Filter(), Filter(subjects="02"), Filter(folders="derivatives")):
        kept = f.walk(str(tmp_path))
        assert all(isinstance(p, BidsPath) for p in kept)
        root = BidsPath(str(tmp_path))
        assert [str(p.relative_to(root)) for p in kept] == f.select(LISTING)


def test_walk_memory():
    pytest.importorskip("upath")
    root = BidsPath("memory:///brainfilter-walk")
    _make(root, LISTING)
    try:
        f = Filter(datatypes="anat")
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
