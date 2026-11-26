import json
from collections import ChainMap

import pytest

from brainfilter import bidspath as B
from brainfilter._names import applies_to
from brainfilter.bidspath import BidsPath

T1W = "sub-01/ses-1/anat/sub-01_ses-1_acq-mp_T1w.nii.gz"
BOLD = "sub-01/ses-1/func/sub-01_ses-1_task-rest_run-1_bold.nii.gz"

FILES = {
    "dataset_description.json": {"Name": "ds", "BIDSVersion": "1.10.0"},
    "participants.tsv": "participant_id\tage\tsex\nsub-01\t30\tF\nsub-02\tn/a\tM\n",
    "participants.json": {"age": {"Units": "year"}},
    # dataset level
    "T1w.json": {"Level": "root", "RootOnly": 1, "MagneticFieldStrength": 3},
    "task-rest_bold.json": {"Level": "root", "TaskName": "rest"},
    "task-other_bold.json": {"TaskName": "other"},   # entity mismatch
    "dwi.json": {"Level": "wrong-suffix"},            # suffix mismatch
    # subject level
    "sub-01/sub-01_T1w.json": {"Level": "subject", "SubjectOnly": 1},
    "sub-01/sub-02_T1w.json": {"Level": "other-subject"},
    # session level
    "sub-01/ses-1/sub-01_ses-1_T1w.json": {"Level": "session"},
    "sub-01/ses-1/sub-01_ses-1_task-rest_events.json": {"Level": "events"},
    # datatype level
    "sub-01/ses-1/anat/sub-01_ses-1_acq-mp_T1w.json": {"Level": "datatype"},
    "sub-01/ses-1/anat/sub-01_ses-1_acq-other_T1w.json": {"Level": "acq"},
    "sub-01/ses-1/anat/sub-01_ses-1_T2w.json": {"Level": "T2w"},
    T1W: b"nifti",
    BOLD: b"nifti",
    "sub-01/ses-1/func/sub-01_ses-1_task-rest_events.tsv": "onset\tduration\n0\t1\n",
    "sub-02/anat/sub-02_T1w.nii.gz": b"nifti",
}


def _populate(root):
    """Write the files of `FILES` below `root`, whatever its mode."""
    top = root.with_mode("w")
    for rel, content in FILES.items():
        path = top / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, str):
            path.write_text(content)
        else:
            path.write_text(json.dumps(content))
    return root


@pytest.fixture
def local_ds(tmp_path):
    return _populate(BidsPath(str(tmp_path / "ds")))


@pytest.fixture
def memory_ds():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    yield _populate(BidsPath("memory://ds"))
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(params=["local", "memory"])
def ds(request):
    return request.getfixturevalue(f"{request.param}_ds")


# -- tree navigation -----------------------------------------------------------

def test_navigation(ds):
    anat = ds["sub-01"]["ses-1"]["anat"]
    assert isinstance(anat, BidsPath)
    assert anat == ds / "sub-01" / "ses-1" / "anat"
    assert anat.datatype is None and anat.subject == "01"
    t1w = anat["sub-01_ses-1_acq-mp_T1w.nii.gz"]
    assert t1w == ds / T1W
    assert type(ds["participants.tsv"]) is B.BidsParticipantsFile
    assert type(ds["dataset_description.json"]) is B.BidsDatasetDescriptionFile


def test_keys_and_iteration(ds):
    assert ds["sub-01"].keys() == ["ses-1", "sub-01_T1w.json", "sub-02_T1w.json"]
    assert list(ds["sub-01"]) == ds["sub-01"].keys()
    assert "sub-02" in ds and "sub-03" not in ds
    assert [c.name for c in ds["sub-02"].values()] == ["anat"]
    assert dict(ds["sub-02"].items()) == {"anat": ds / "sub-02" / "anat"}


def test_missing_directory(ds):
    with pytest.raises(OSError):
        (ds / "nope").keys()
    # a directory that is not there holds no sidecar; the root's apply
    assert [s.name for s in (ds / "nope" / "sub-01_T1w.nii.gz").sidecars] == [
        "T1w.json"]


def test_missing_child(ds):
    with pytest.raises(KeyError):
        ds["sub-03"]
    with pytest.raises(KeyError):
        ds["sub-01/ses-1"]   # one level at a time
    assert ds.get("sub-03") is None


def test_read_only(ds):
    # read-only by default; see test_transaction.py for the writes
    assert ds.mode == "r"
    with pytest.raises(B.ReadOnlyError, match="read-only.*with_mode"):
        ds["sub-03.json"] = {}
    with pytest.raises(TypeError, match="only JSON and TSV"):
        ds["sub-03"] = {}
    with pytest.raises(TypeError, match="does not delete"):
        del ds["sub-01"]
    with pytest.raises(B.ReadOnlyError, match="read-only"):
        ds["T1w.json"]["Level"] = "x"
    assert json.loads((ds / "T1w.json").read_text()) == FILES["T1w.json"]
    assert "sub-03.json" not in ds


# -- contents ------------------------------------------------------------------

def test_json_reads_as_mapping(ds):
    sidecar = ds["T1w.json"]
    assert isinstance(sidecar, B.BidsJSONFile)
    assert sidecar.as_dict() == FILES["T1w.json"]
    assert type(sidecar.as_dict()) is dict
    assert sidecar["MagneticFieldStrength"] == 3
    assert dict(sidecar) == FILES["T1w.json"]
    assert "Level" in sidecar and "Nope" not in sidecar
    assert sidecar.get("Nope", 0) == 0
    assert set(sidecar.keys()) == set(FILES["T1w.json"])
    assert list(sidecar) == list(FILES["T1w.json"])
    assert list(sidecar.values()) == list(FILES["T1w.json"].values())
    assert dict(sidecar.items()) == FILES["T1w.json"]
    with pytest.raises(KeyError):
        sidecar["Nope"]
    assert ds["dataset_description.json"]["Name"] == "ds"


ROWS = [
    {"participant_id": "sub-01", "age": 30.0, "sex": "F"},   # BIDS: number
    {"participant_id": "sub-02", "age": None, "sex": "M"},
]
RAW_ROWS = [
    {"participant_id": "sub-01", "age": "30", "sex": "F"},
    {"participant_id": "sub-02", "age": "n/a", "sex": "M"},
]
COLUMNS = {"participant_id": ["sub-01", "sub-02"], "age": [30.0, None],
           "sex": ["F", "M"]}


def test_tsv_loads_as_rows_and_columns(ds):
    table = ds["participants.tsv"]
    assert table.as_list() == ROWS
    assert type(table.as_list()) is list
    assert list(table.rows()) == ROWS
    assert table.as_list(raw=True) == list(table.rows(raw=True)) == RAW_ROWS
    assert table.as_dict() == table.columns() == COLUMNS
    assert list(table.as_dict()) == ["participant_id", "age", "sex"]
    assert table.as_dict(raw=True)["age"] == table.columns(raw=True)["age"] == [
        "30", "n/a"]


def test_tsv_is_a_mapping_of_columns(ds):
    table = ds["participants.tsv"]
    assert table["age"] == [30.0, None]           # typed
    assert table.keys() == list(table) == ["participant_id", "age", "sex"]
    assert "sex" in table and "hand" not in table
    assert table.get("hand") is None and table.get("hand", []) == []
    assert table.get("sex") == ["F", "M"]
    assert table.values() == list(COLUMNS.values())
    assert table.items() == list(COLUMNS.items())
    with pytest.raises(KeyError):
        table["hand"]


def test_tsv_dataframe(ds):
    pd = pytest.importorskip("pandas")
    df = ds["participants.tsv"].as_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["participant_id", "age", "sex"]
    assert df["age"].isna().tolist() == [False, True]


def test_tsv_dataframe_without_pandas(ds, monkeypatch):
    import builtins

    real = builtins.__import__

    def no_pandas(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pandas)
    with pytest.raises(ImportError, match="pandas"):
        ds["participants.tsv"].as_dataframe()


def test_pandas_not_imported_at_import():
    import subprocess
    import sys

    code = "import brainfilter, sys; print('pandas' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "False"


# -- sidecar inheritance -------------------------------------------------------

def test_sidecars_nearest_first(ds):
    sidecars = (ds / T1W).sidecars
    assert isinstance(sidecars, tuple)
    names = [s.name for s in sidecars]
    assert names == [
        "sub-01_ses-1_acq-mp_T1w.json",   # datatype
        "sub-01_ses-1_T1w.json",          # session
        "sub-01_T1w.json",                # subject
        "T1w.json",                       # dataset root
    ]


def test_sidecar_chainmap(ds):
    meta = (ds / T1W).sidecar
    assert isinstance(meta, ChainMap)
    assert meta["Level"] == "datatype"        # nearest wins
    assert meta["SubjectOnly"] == 1           # inherited from subject level
    assert meta["RootOnly"] == 1              # inherited from the root
    assert meta.maps[-1] == FILES["T1w.json"]
    assert meta.sidecars == (ds / T1W).sidecars
    assert "TaskName" not in meta


def test_sidecar_as_dict(ds):
    meta = (ds / T1W).sidecar
    flat = meta.as_dict()
    assert type(flat) is dict
    assert flat == {
        "Level": "datatype", "SubjectOnly": 1, "RootOnly": 1,
        "MagneticFieldStrength": 3,
    }
    flat["Level"] = "changed"                  # a copy
    assert meta["Level"] == "datatype"
    assert (ds / "sub-02/anat/sub-02_T2w.nii.gz").sidecar.as_dict() == {}


def test_metadata_entity_subset_and_suffix(ds):
    bold = ds / BOLD
    meta = bold.sidecar
    assert [s.name for s in bold.sidecars] == ["task-rest_bold.json"]
    assert meta["TaskName"] == "rest"         # not task-other, not events.json
    # a companion file gets its own sidecar, not the data file's
    events = ds / "sub-01/ses-1/func/sub-01_ses-1_task-rest_events.tsv"
    assert events.sidecar["Level"] == "events"
    # another subject inherits only the dataset level
    other = ds / "sub-02/anat/sub-02_T1w.nii.gz"
    assert [s.name for s in other.sidecars] == ["T1w.json"]


def test_sidecar_of_table_and_unsuffixed(ds):
    assert ds["participants.tsv"].sidecar["age"] == {"Units": "year"}
    assert ds["dataset_description.json"].sidecar == ChainMap()
    assert ds["dataset_description.json"].sidecars == ()
    assert ds.sidecars == ()                   # a directory has no suffix
    # a sidecar is not its own sidecar
    sidecar = ds / "sub-01/sub-01_T1w.json"
    assert [s.name for s in sidecar.sidecars] == ["T1w.json"]


def test_root_is_not_an_argument(ds):
    with pytest.raises(TypeError):
        (ds / T1W).sidecars(root=ds)          # a tuple, not a method
    for gone in ("read", "read_dataframe", "read_metadata", "metadata",
                 "edit"):
        assert not hasattr(ds["participants.tsv"], gone)
        assert not hasattr(ds["T1w.json"], gone)
        assert not hasattr(ds / T1W, gone)


# A directory with no dataset root above it: its own sidecars apply, and
# not those above it.
LOOSE = {
    "T1w.json": {"Above": 1},                               # not inherited
    "loose/sub-01_T1w.json": {"Level": "own"},
    "loose/T1w.json": {"Level": "generic", "Generic": 1},
    "loose/sub-02_T1w.json": {"Level": "other-subject"},   # entity mismatch
    "loose/sub-01_bold.json": {"Level": "wrong-suffix"},
    "loose/sub-01_T1w.nii.gz": b"nifti",
}
LOOSE_DATA = "loose/sub-01_T1w.nii.gz"


def _populate_loose(top):
    for rel, content in LOOSE.items():
        path = top.with_mode("w") / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(json.dumps(content))
    return top


def test_no_dataset_root_uses_own_directory(tmp_path):
    top = _populate_loose(BidsPath(str(tmp_path)))
    data = top / LOOSE_DATA
    assert [s.name for s in data.sidecars] == ["sub-01_T1w.json", "T1w.json"]
    meta = data.sidecar
    assert meta["Level"] == "own" and meta["Generic"] == 1
    assert "Above" not in meta


def test_no_dataset_root_sidecar_write(tmp_path):
    top = _populate_loose(BidsPath(str(tmp_path), mode="w"))
    data = top / LOOSE_DATA
    with data.parent.transaction() as tx:
        data.sidecar["EchoTime"] = 0.03
    assert tx.written == [top / "loose/sub-01_T1w.json"]
    assert json.loads((top / "loose/sub-01_T1w.json").read_text()) == {
        "Level": "own", "EchoTime": 0.03,
    }


def test_no_dataset_root_lists_each_ancestor_once(memory_ds, monkeypatch):
    from fsspec.implementations.memory import MemoryFileSystem

    top = _populate_loose(BidsPath("memory://top"))
    data = top / LOOSE_DATA
    calls = []
    real = MemoryFileSystem.ls

    def ls(self, path, *args, **kwargs):
        calls.append(path)
        return real(self, path, *args, **kwargs)

    monkeypatch.setattr(MemoryFileSystem, "ls", ls)
    assert [s.name for s in data.sidecars] == ["sub-01_T1w.json", "T1w.json"]
    # one walk up: each ancestor is listed once, to learn there is no root
    assert len(calls) == len(set(calls)) == len(data.parents)


def test_each_directory_listed_once(memory_ds, monkeypatch):
    from fsspec.implementations.memory import MemoryFileSystem

    calls = []
    real = MemoryFileSystem.ls

    def ls(self, path, *args, **kwargs):
        calls.append(path)
        return real(self, path, *args, **kwargs)

    monkeypatch.setattr(MemoryFileSystem, "ls", ls)
    (memory_ds / T1W).sidecars
    assert len(calls) == len(set(calls)) == 4   # anat, ses-1, sub-01, ds


def test_applies_to_companions_flag():
    meta = "sub-01/sub-01_task-rest_events.json"
    data = "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert applies_to(meta, data)
    assert not applies_to(meta, data, companions=False)


# -- child names -------------------------------------------------------------------

@pytest.mark.parametrize("name", [".", "..", "", "a/b"])
def test_dot_and_dot_dot_are_not_children(ds, name):
    with pytest.raises(KeyError):
        ds[name]
    assert name not in ds and ds.get(name) is None
    ds = ds.with_mode("w")
    with pytest.raises(KeyError):
        ds[name] = {}
    with ds.transaction() as tx:
        with pytest.raises(KeyError):
            ds[name]
        with pytest.raises(KeyError):
            ds[name] = {}
        assert name not in ds
    assert tx.written == []


def test_dot_dot_is_not_covered_by_the_transaction(tmp_path):
    ds = _populate(BidsPath(str(tmp_path / "ds"), mode="w"))
    with ds.transaction() as tx:
        with pytest.raises(KeyError):
            ds[".."]["outside.json"] = {"Out": 1}
        # not covered: written at once, past the transaction
        (ds / "..")["outside.json"] = {"Out": 1}
        assert (tmp_path / "outside.json").exists()
        (ds / "sub-01" / ".." / ".." / "out2.json").write({"Out": 2})
        assert json.loads((tmp_path / "out2.json").read_text()) == {"Out": 2}
    assert tx.written == []


# -- sidecar read errors -----------------------------------------------------------

def test_metadata_raises_the_nearest_unreadable_sidecar(ds):
    near = ds / "sub-01/ses-1/anat/sub-01_ses-1_acq-mp_T1w.json"
    near.with_mode("w").write_text("{near")
    (ds / "T1w.json").with_mode("w").write_text("{far")
    with pytest.raises(json.JSONDecodeError) as info:
        (ds / T1W).sidecar
    assert info.value.doc == "{near"


# -- typed reads ------------------------------------------------------------------

def _loose_table(top):
    top = top.with_mode("w")
    (top / "events.json").write_text(json.dumps({"code": {"Format": "string"}}))
    (top / "loose").mkdir(parents=True, exist_ok=True)
    table = top / "loose" / "sub-01_events.tsv"
    table.write_text("code\n1\n2\n")
    return table


def test_typed_read_finds_the_root_itself(tmp_path):
    top = BidsPath(str(tmp_path))
    table = _loose_table(top)
    # no dataset root: only the table's own directory describes it
    assert table.as_list() == [{"code": 1}, {"code": 2}]      # inferred
    (top.with_mode("w") / "dataset_description.json").write_text("{}")
    assert table.as_list() == [{"code": "1"}, {"code": "2"}]  # described
    with top.with_mode("w"):
        assert table["code"] == ["1", "2"]
    pytest.importorskip("pandas")
    assert table.as_dataframe()["code"].tolist() == ["1", "2"]
