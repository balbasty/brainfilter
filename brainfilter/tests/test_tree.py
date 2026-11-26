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
    for rel, content in FILES.items():
        path = root / rel
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


def test_missing_child(ds):
    with pytest.raises(KeyError):
        ds["sub-03"]
    with pytest.raises(KeyError):
        ds["sub-01/ses-1"]   # one level at a time
    assert ds.get("sub-03") is None


def test_read_only(ds):
    # outside a transaction; see test_transaction.py for the edits
    with pytest.raises(TypeError, match="read-only.*transaction"):
        ds["sub-03.json"] = {}
    with pytest.raises(TypeError, match="only JSON and TSV"):
        ds["sub-03"] = {}
    with pytest.raises(TypeError, match="does not delete"):
        del ds["sub-01"]
    with pytest.raises(TypeError, match="read-only"):
        ds["T1w.json"]["Level"] = "x"


# -- contents ------------------------------------------------------------------

def test_json_reads_as_mapping(ds):
    sidecar = ds["T1w.json"]
    assert isinstance(sidecar, B.BidsJSONFile)
    assert sidecar.read() == FILES["T1w.json"]
    assert sidecar["MagneticFieldStrength"] == 3
    assert dict(sidecar) == FILES["T1w.json"]
    assert "Level" in sidecar and "Nope" not in sidecar
    assert sidecar.get("Nope", 0) == 0
    assert set(sidecar.keys()) == set(FILES["T1w.json"])
    with pytest.raises(KeyError):
        sidecar["Nope"]
    assert ds["dataset_description.json"]["Name"] == "ds"


def test_tsv_reads_as_rows(ds):
    table = ds["participants.tsv"]
    rows = table.read()
    assert rows == [
        {"participant_id": "sub-01", "age": 30.0, "sex": "F"},   # BIDS: number
        {"participant_id": "sub-02", "age": None, "sex": "M"},
    ]
    assert table.read(raw=True) == [
        {"participant_id": "sub-01", "age": "30", "sex": "F"},
        {"participant_id": "sub-02", "age": "n/a", "sex": "M"},
    ]
    assert list(table) == rows
    with pytest.raises(TypeError, match="read()"):
        table["age"]


def test_tsv_dataframe(ds):
    pd = pytest.importorskip("pandas")
    df = ds["participants.tsv"].read_dataframe()
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
        ds["participants.tsv"].read_dataframe()


def test_pandas_not_imported_at_import():
    import subprocess
    import sys

    code = "import brainfilter.bidspath, sys; print('pandas' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "False"


# -- sidecar inheritance -------------------------------------------------------

def test_sidecars_nearest_first(ds):
    names = [s.name for s in (ds / T1W).sidecars()]
    assert names == [
        "sub-01_ses-1_acq-mp_T1w.json",   # datatype
        "sub-01_ses-1_T1w.json",          # session
        "sub-01_T1w.json",                # subject
        "T1w.json",                       # dataset root
    ]


def test_metadata_chainmap(ds):
    meta = (ds / T1W).metadata
    assert isinstance(meta, ChainMap)
    assert meta["Level"] == "datatype"        # nearest wins
    assert meta["SubjectOnly"] == 1           # inherited from subject level
    assert meta["RootOnly"] == 1              # inherited from the root
    assert meta.maps[-1] == FILES["T1w.json"]
    assert "TaskName" not in meta


def test_metadata_entity_subset_and_suffix(ds):
    bold = ds / BOLD
    meta = bold.metadata
    assert [s.name for s in bold.sidecars()] == ["task-rest_bold.json"]
    assert meta["TaskName"] == "rest"         # not task-other, not events.json
    # a companion file gets its own sidecar, not the data file's
    events = ds / "sub-01/ses-1/func/sub-01_ses-1_task-rest_events.tsv"
    assert events.metadata["Level"] == "events"
    # another subject inherits only the dataset level
    other = ds / "sub-02/anat/sub-02_T1w.nii.gz"
    assert [s.name for s in other.sidecars()] == ["T1w.json"]


def test_metadata_of_table_and_unsuffixed(ds):
    assert ds["participants.tsv"].metadata["age"] == {"Units": "year"}
    assert ds["dataset_description.json"].metadata == ChainMap()
    # a sidecar is not its own metadata
    sidecar = ds / "sub-01/sub-01_T1w.json"
    assert [s.name for s in sidecar.sidecars()] == ["T1w.json"]


def test_explicit_root(ds):
    t1w = ds / T1W
    names = [s.name for s in t1w.sidecars(root=ds / "sub-01")]
    assert names[-1] == "sub-01_T1w.json"
    assert t1w.read_metadata(root=str(ds / "sub-01"))["Level"] == "datatype"
    with pytest.raises(ValueError, match="not an ancestor"):
        t1w.sidecars(root=ds / "sub-02")


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
        path = top / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(json.dumps(content))
    return top


def test_no_dataset_root_uses_own_directory(tmp_path):
    top = _populate_loose(BidsPath(str(tmp_path)))
    data = top / LOOSE_DATA
    assert [s.name for s in data.sidecars()] == ["sub-01_T1w.json", "T1w.json"]
    meta = data.metadata
    assert meta["Level"] == "own" and meta["Generic"] == 1
    assert "Above" not in meta
    # an explicit root still reaches above
    assert data.read_metadata(root=top)["Above"] == 1
    with pytest.raises(ValueError, match="not an ancestor"):
        data.sidecars(root=top / "elsewhere")


def test_no_dataset_root_metadata_write(tmp_path):
    top = _populate_loose(BidsPath(str(tmp_path)))
    data = top / LOOSE_DATA
    with data.parent.transaction() as tx:
        data.metadata["EchoTime"] = 0.03
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
    assert [s.name for s in data.sidecars()] == ["sub-01_T1w.json", "T1w.json"]
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
    (memory_ds / T1W).sidecars()
    assert len(calls) == len(set(calls)) == 4   # anat, ses-1, sub-01, ds


def test_applies_to_companions_flag():
    meta = "sub-01/sub-01_task-rest_events.json"
    data = "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert applies_to(meta, data)
    assert not applies_to(meta, data, companions=False)
