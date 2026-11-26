import pathlib

import pytest

from brainfilter import bidspath as B
from brainfilter._names import format_name, parse_name
from brainfilter.bidspath import (
    BidsEntities,
    BidsNameError,
    BidsPath,
    PureBidsPath,
)

# -- parsing -------------------------------------------------------------------

BIDS_NAMES = [
    "sub-01_ses-2_task-rest_bold.nii.gz",
    "sub-01_T1w.nii",
    "sub-01_acq-a-b_T1w.nii.gz",     # a label may hold a dash
    "sub-01_ses-1_scans.tsv",
    "task-rest_bold.json",
    "T1w.json",
    "participants.tsv",
    "README",
    "sub-01",                         # a directory: entities, no suffix
    "sub-01_ses-1",
    "desc-x_sub-01_T1w.nii",          # non-canonical order is kept
]


@pytest.mark.parametrize("name", BIDS_NAMES)
def test_parse_round_trip(name):
    parsed = parse_name(name)
    assert parsed.is_bids
    assert format_name(parsed.entities, parsed.suffix, parsed.extension) == name
    path = PureBidsPath(name)
    assert path.with_entities(path.entities).name == name
    assert path.basename + path.extension == name


def test_parse_components():
    p = PureBidsPath("sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz")
    assert p.entities == {"sub": "01", "ses": "2", "task": "rest"}
    assert isinstance(p.entities, BidsEntities)
    assert p.suffix == "bold"
    assert p.extension == ".nii.gz"
    assert p.basename == "sub-01_ses-2_task-rest_bold"
    assert p.datatype == "func"
    assert p.subject == "01"
    assert p.session == "2"
    assert not p.is_metadata
    top = PureBidsPath("T1w.json")
    assert top.entities == {} and top.suffix == "T1w" and top.is_metadata
    assert top.datatype is None and top.subject is None


# name -> (entities, suffix, extension), as brainspresso's BidsName.parse gives
BRAINSPRESSO_CASES = {
    "dataset_description.json": ({}, None, ".json"),
    "genetic_info.json": ({}, None, ".json"),
    "foo_bar.txt": ({}, None, ".txt"),
    "sub-01__T1w.nii": ({}, None, ".nii"),
    "sub-01_T1w_extra.nii": ({}, None, ".nii"),
    "_T1w.json": ({}, None, ".json"),
    "NEO_FFI.tsv": ({}, None, ".tsv"),
    "README": ({}, "README", ""),
    "CHANGES": ({}, "CHANGES", ""),
    "CITATION.cff": ({}, "CITATION", ".cff"),
    "participants.tsv": ({}, "participants", ".tsv"),
    "bold_group.html": ({}, None, ".html"),
    "sub-01": ({"sub": "01"}, None, ""),
    "sub-01_T1w": ({"sub": "01"}, "T1w", ""),
    "sub-01_acq-a-b_T1w.nii.gz": ({"sub": "01", "acq": "a-b"}, "T1w", ".nii.gz"),
    "my data.csv": ({}, "my data", ".csv"),
}

# Where brainfilter is stricter than brainspresso, on degenerate names.
STRICTER_CASES = {
    # brainspresso: suffix "", extension ".bidsignore"
    ".bidsignore": ({}, None, ""),
    ".hidden.json": ({}, None, ".json"),
    # brainspresso: suffix "x-" / "-x"
    "sub-01_x-.nii": ({}, None, ".nii"),
    "sub-01_-x.nii": ({}, None, ".nii"),
    # brainspresso: the last label wins
    "sub-01_sub-02_T1w.nii": ({}, None, ".nii"),
    "": ({}, None, ""),
}


@pytest.mark.parametrize(
    "name,expected", {**BRAINSPRESSO_CASES, **STRICTER_CASES}.items()
)
def test_parse_non_bids_and_edge_names(name, expected):
    parsed = parse_name(name)
    assert (parsed.entities, parsed.suffix, parsed.extension) == expected


def test_hidden_name_keeps_its_dot_in_the_basename():
    p = PureBidsPath("ds/.bidsignore")
    assert p.basename == ".bidsignore"
    assert p.extension == ""


@pytest.mark.parametrize("name", ["dataset_description.json", "foo_bar.txt"])
def test_non_bids_name_parses_without_raising(name):
    p = PureBidsPath(f"ds/{name}")
    assert p.entities == {}
    assert p.suffix is None
    assert p.subject is None


def test_datatype_and_metadata():
    assert PureBidsPath("sub-01/dwi/sub-01_dwi.bval").is_metadata
    assert PureBidsPath("sub-01/dwi/sub-01_dwi.bval").datatype == "dwi"
    assert PureBidsPath("sub-01/foo/sub-01_dwi.nii").datatype is None
    assert PureBidsPath("sub-01_physio.tsv.gz").is_metadata is False


def test_subject_and_session_from_directories():
    p = PureBidsPath("ds/sub-01/ses-a/anat")
    assert p.subject == "01"
    assert p.session == "a"
    assert PureBidsPath("ds/sub-01/ses-a").session == "a"
    assert PureBidsPath("ds/derivatives").subject is None


# -- entities ------------------------------------------------------------------


def test_entities_inheritance_comparisons():
    data = BidsEntities(sub="01", ses="1", task="rest")
    meta = BidsEntities(task="rest")
    other = BidsEntities(task="motor")
    assert data < meta and data <= meta
    assert meta > data and meta >= data
    assert not data < other
    assert not data < BidsEntities(data)
    assert data <= BidsEntities(data)
    assert data < {}


def test_entities_sorted():
    ents = BidsEntities(desc="x", foo="y", run="1", sub="01")
    assert list(ents.sorted()) == ["sub", "run", "desc", "foo"]


# -- editing -------------------------------------------------------------------

T1W = "ds/sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz"


def test_with_entities_replace_and_keep():
    p = PureBidsPath(T1W)
    assert p.with_entities({"acq": "x"}).name == "acq-x_T1w.nii.gz"
    assert p.with_entities(acq="x", sub="02").name == "acq-x_sub-02_T1w.nii.gz"
    assert (
        p.with_entities(run=1, acq="x", keep_existing=True).name
        == "sub-01_ses-1_acq-x_run-1_T1w.nii.gz"
    )
    assert (
        p.with_entities(run=1, keep_existing=True, sort=False).name
        == "sub-01_ses-1_run-1_T1w.nii.gz"
    )
    assert (
        p.with_entities(acq="x", sub="02", sort=True).name
        == "sub-02_acq-x_T1w.nii.gz"
    )
    assert (
        p.with_entities(ses=None, keep_existing=True).name
        == "sub-01_T1w.nii.gz"
    )
    assert str(p.with_entities(run=1).parent) == "ds/sub-01/ses-1/anat"


def test_sort_unknown_entities_last():
    p = PureBidsPath("foo-1_desc-a_sub-01_T1w.nii")
    assert (
        p.with_entities(keep_existing=True).name
        == "sub-01_desc-a_foo-1_T1w.nii"
    )


@pytest.mark.parametrize(
    "entity", [{"acq": "a_b"}, {"acq": ""}, {"a-b": "x"}, {"acq": "x.y"}]
)
def test_with_entities_rejects_unparseable_entities(entity):
    with pytest.raises(ValueError, match="invalid BIDS entity"):
        PureBidsPath("sub-01_T1w.nii").with_entities(entity)


def test_with_entities_empty_name():
    with pytest.raises(ValueError, match="no name"):
        PureBidsPath("ds/sub-01").with_entities(sub=None, keep_existing=True)


def test_with_suffix_and_extension():
    p = PureBidsPath(T1W)
    assert p.with_suffix("T2w").name == "sub-01_ses-1_T2w.nii.gz"
    assert p.with_extension(".json").name == "sub-01_ses-1_T1w.json"
    assert p.with_extension("").name == "sub-01_ses-1_T1w"
    assert PureBidsPath("ds/sub-01").with_suffix("T1w").name == "sub-01_T1w"
    assert p.with_basename("sub-02_T1w").name == "sub-02_T1w.nii.gz"
    with pytest.raises(ValueError, match="with_extension"):
        p.with_suffix(".nii")
    with pytest.raises(ValueError, match="invalid BIDS suffix"):
        p.with_suffix("a_b")
    with pytest.raises(ValueError, match="invalid extension"):
        p.with_extension("json")


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p.with_entities(sub="01"),
        lambda p: p.with_suffix("T1w"),
        lambda p: p.with_subject("01"),
        lambda p: p.with_session("01"),
    ],
)
def test_editors_raise_on_non_bids_names(edit):
    with pytest.raises(BidsNameError, match="not a BIDS name"):
        edit(PureBidsPath("ds/dataset_description.json"))


def test_with_extension_on_non_bids_name():
    p = PureBidsPath("ds/dataset_description.json")
    assert p.with_extension(".yaml").name == "dataset_description.yaml"


def test_with_subject_rewrites_directories():
    p = PureBidsPath(T1W)
    assert str(p.with_subject("02")) == (
        "ds/sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz"
    )
    assert str(p.with_session("b")) == (
        "ds/sub-01/ses-b/anat/sub-01_ses-b_T1w.nii.gz"
    )
    # a directory path: only the directories change
    assert str(PureBidsPath("ds/sub-01/anat").with_subject("02")) == (
        "ds/sub-02/anat"
    )
    # the path is itself the subject directory
    assert str(PureBidsPath("ds/sub-01").with_subject("02")) == "ds/sub-02"
    # no subject anywhere: the entity is added, in canonical order
    assert str(PureBidsPath("ds/task-rest_bold.json").with_subject(3)) == (
        "ds/sub-3_task-rest_bold.json"
    )
    # sub-01 in the path but not in the name: the name is left alone
    assert str(PureBidsPath("ds/sub-01/sub-01/x.txt").with_subject("02")) == (
        "ds/sub-02/sub-02/x.txt"
    )


def test_with_subject_rejects_bad_labels():
    with pytest.raises(ValueError, match="invalid BIDS entity"):
        PureBidsPath(T1W).with_subject("0_1")


def test_with_subject_on_remote_url():
    p = PureBidsPath("s3://bucket/ds/sub-01/anat/sub-01_T1w.nii.gz")
    assert str(p.with_subject("02")) == (
        "s3://bucket/ds/sub-02/anat/sub-02_T1w.nii.gz"
    )


# -- dispatch ------------------------------------------------------------------

DISPATCH = {
    "dataset_description.json": "DatasetDescriptionFile",
    "participants.tsv": "ParticipantsFile",
    "participants.json": "ParticipantsSidecarFile",
    "samples.tsv": "SamplesFile",
    "samples.json": "SamplesSidecarFile",
    "sub-01/sub-01_sessions.tsv": "SessionsFile",
    "sub-01/sub-01_sessions.json": "SessionsSidecarFile",
    "sub-01/ses-1/sub-01_ses-1_scans.tsv": "ScansFile",
    "scans.json": "ScansSidecarFile",
    "phenotype/NEO_FFI.tsv": "PhenotypeFile",
    "phenotype/NEO_FFI.json": "PhenotypeSidecarFile",
    "code": "CodeDirectory",
    "T1w.json": "SidecarFile",
    "genetic_info.json": "SidecarFile",
    "sub-01/func/sub-01_task-x_events.tsv": "TSVFile",
    "sub-01/anat/sub-01_T1w.nii.gz": "Path",
    "sub-01": "Path",
    "README": "Path",
    "sub-01/func/sub-01_task-x_physio.tsv.gz": "Path",
}


@pytest.fixture
def no_local_io(monkeypatch):
    """Fail on any query of the local filesystem."""

    def boom(*args, **kwargs):
        raise AssertionError("dispatch touched the filesystem")

    for name in ("stat", "lstat", "exists", "is_dir", "is_file", "iterdir"):
        monkeypatch.setattr(pathlib.Path, name, boom)


@pytest.mark.parametrize("rel,kind", DISPATCH.items())
def test_dispatch_pure(rel, kind):
    p = PureBidsPath(f"ds/{rel}")
    assert type(p) is getattr(B, f"PureBids{kind}")
    remote = PureBidsPath(f"s3://bucket/ds/{rel}")
    assert type(remote) is getattr(B, f"PureBids{kind}")


@pytest.mark.parametrize("rel,kind", DISPATCH.items())
def test_dispatch_nonexistent_local(tmp_path, no_local_io, rel, kind):
    p = BidsPath(str(tmp_path / "missing" / rel))
    assert type(p) is getattr(B, f"Bids{kind}")
    assert isinstance(p, BidsPath)
    # also when the path is derived rather than constructed
    q = BidsPath(str(tmp_path / "missing")) / rel
    assert type(q) is getattr(B, f"Bids{kind}")


@pytest.fixture
def memory_root(monkeypatch):
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    yield "memory://ds"
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.mark.parametrize("rel,kind", DISPATCH.items())
def test_dispatch_memory(memory_root, monkeypatch, rel, kind):
    from fsspec.implementations.memory import MemoryFileSystem

    def boom(*args, **kwargs):
        raise AssertionError("dispatch touched the filesystem")

    for name in ("info", "ls", "exists", "isdir", "isfile"):
        monkeypatch.setattr(MemoryFileSystem, name, boom)
    p = BidsPath(f"{memory_root}/{rel}")
    assert type(p) is getattr(B, f"Bids{kind}")
    assert type(BidsPath(memory_root) / rel) is getattr(B, f"Bids{kind}")


def test_memory_listing_dispatches(memory_root):
    root = BidsPath(memory_root)
    (root / "participants.tsv").write_text("participant_id\nsub-01\n")
    (root / "sub-01" / "anat").mkdir(parents=True)
    (root / "sub-01" / "anat" / "sub-01_T1w.json").write_text("{}")
    kinds = {p.name: type(p) for p in root.iterdir()}
    assert kinds["participants.tsv"] is B.BidsParticipantsFile
    assert kinds["sub-01"] is BidsPath
    sidecar = next((root / "sub-01" / "anat").iterdir())
    assert type(sidecar) is B.BidsSidecarFile
    assert sidecar.subject == "01" and sidecar.datatype == "anat"
    moved = sidecar.with_subject("02")
    assert str(moved) == f"{memory_root}/sub-02/anat/sub-02_T1w.json"
    assert not moved.exists()


def test_explicit_class():
    # a specialised class is honoured, and refined when the name calls for it
    assert type(B.BidsTSVFile("ds/participants.tsv")) is B.BidsParticipantsFile
    assert type(B.BidsTSVFile("ds/notes.json")) is B.BidsTSVFile
    # but a derived path is dispatched on its own name
    assert type(B.BidsTSVFile("ds/notes.json").parent) is BidsPath


# -- derived paths -------------------------------------------------------------


def test_derived_paths_reparse():
    p = BidsPath("ds/sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz")
    parent = p.parent
    assert type(parent) is BidsPath
    assert parent.name == "anat" and parent.entities == {}
    assert parent.session == "1"
    child = parent / "sub-01_ses-1_T2w.json"
    assert type(child) is B.BidsSidecarFile
    assert child.suffix == "T2w" and child.datatype == "anat"
    renamed = child.with_name("sub-01_ses-1_scans.tsv")
    assert type(renamed) is B.BidsScansFile
    assert renamed.entities == {"sub": "01", "ses": "1"}
    assert type(renamed.joinpath("x")) is BidsPath
    assert all(type(q) is BidsPath for q in p.parents)
    assert type(BidsPath("ds") / "dataset_description.json") is (
        B.BidsDatasetDescriptionFile
    )
    assert type(p.with_suffix("scans").with_extension(".tsv")) is B.BidsScansFile


def test_derived_pure_paths_reparse():
    p = PureBidsPath("s3://bucket/ds/phenotype/NEO_FFI.tsv")
    assert type(p) is B.PureBidsPhenotypeFile
    assert type(p.parent) is PureBidsPath
    assert type(p.with_extension(".json")) is B.PureBidsPhenotypeSidecarFile
    assert type(p.parent.parent / "participants.json") is (
        B.PureBidsParticipantsSidecarFile
    )


def test_pure_and_concrete_paths_are_equal():
    assert BidsPath("ds/participants.tsv") == PureBidsPath("ds/participants.tsv")


class TaggedBidsPath(BidsPath):
    """A downstream subclass with state: it keeps its type and state."""

    def __init__(self, path, *, tag=None, **kwargs):
        super().__init__(path, **kwargs)
        self.tag = tag


def test_user_subclass_keeps_type_and_state():
    p = TaggedBidsPath("ds/participants.tsv", tag="t")
    assert type(p) is TaggedBidsPath
    assert p.suffix == "participants"
    q = p.parent / "sub-01" / "sub-01_T1w.json"
    assert type(q) is TaggedBidsPath
    assert q.tag == "t" and q.subject == "01"


@pytest.mark.parametrize("path, edit", [
    ("ds/sub-01/anat", lambda p: p.with_session("02")),
    ("ds/sub-01", lambda p: p.with_session("02")),
    ("ds/README", lambda p: p.with_subject("02")),
    ("ds/README", lambda p: p.with_entities(sub="02")),
    ("ds/sub-01/ses-1/anat", lambda p: p.with_entities(run=1)),
    ("ds/sub-01", lambda p: p.with_entities(ses="1", keep_existing=True)),
])
def test_editors_add_no_entity_to_a_name_that_is_not_a_file(path, edit):
    # `anat`, `README` and `sub-01` parse as BIDS names, but are not names
    # of BIDS files: an entity added to one would corrupt the path
    with pytest.raises(BidsNameError, match="not a BIDS name of a file"):
        edit(PureBidsPath(path))


def test_editors_still_rename_directories_and_files():
    assert str(PureBidsPath("ds/sub-01/anat").with_subject("02")) == (
        "ds/sub-02/anat"
    )
    assert str(PureBidsPath("ds/sub-01/ses-1").with_session("2")) == (
        "ds/sub-01/ses-2"
    )
    assert str(PureBidsPath("ds/sub-01").with_entities(sub="02")) == "ds/sub-02"
    assert str(PureBidsPath("ds/README").with_entities({})) == "ds/README"
    assert str(PureBidsPath("ds/T1w.json").with_session("1")) == (
        "ds/ses-1_T1w.json"
    )
    assert str(PureBidsPath("ds/sub-01_T1w").with_session("1")) == (
        "ds/sub-01_ses-1_T1w"
    )


def test_is_file_name():
    assert parse_name("sub-01_T1w.nii.gz").is_file_name
    assert parse_name("T1w.json").is_file_name
    assert parse_name("sub-01_task-x_meg").is_file_name
    for name in ("anat", "README", "sub-01", "sub-01_ses-1", "a_b.txt"):
        assert not parse_name(name).is_file_name
