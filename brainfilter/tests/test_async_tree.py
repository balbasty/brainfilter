"""The async family: the sync tree tests, mirrored with coroutines."""
from collections import ChainMap

import pytest

from brainfilter import bidspath as B
from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.tests.test_bidspath import DISPATCH
from brainfilter.tests.test_tree import BOLD, FILES, T1W, _populate

pytestmark = pytest.mark.anyio


@pytest.fixture
def local_ds(tmp_path):
    _populate(BidsPath(str(tmp_path / "ds")))
    return AsyncBidsPath(str(tmp_path / "ds"))


@pytest.fixture
def memory_ds(memory_store, async_memory):
    ds = AsyncBidsPath("memory://ds")
    assert type(ds.wrapped).__name__ == "AsyncFSPath"   # the native driver
    return ds


@pytest.fixture
def memory_store():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    _populate(BidsPath("memory://ds"))   # before memory:// turns async
    yield
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(params=["local", "memory"])
def ds(request):
    return request.getfixturevalue(f"{request.param}_ds")


# -- the family ----------------------------------------------------------------

@pytest.mark.parametrize("rel,kind", DISPATCH.items())
def test_dispatch(rel, kind):
    p = AsyncBidsPath(f"ds/{rel}")
    assert type(p) is getattr(B, f"AsyncBids{kind}")
    assert type(AsyncBidsPath("ds") / rel) is getattr(B, f"AsyncBids{kind}")


@pytest.mark.parametrize("rel,kind", DISPATCH.items())
def test_dispatch_native_async(async_memory, rel, kind):
    p = AsyncBidsPath(f"memory://ds/{rel}")
    assert type(p.wrapped).__name__ == "AsyncFSPath"
    assert type(p) is getattr(B, f"AsyncBids{kind}")
    assert type(AsyncBidsPath("memory://ds") / rel) is getattr(B, f"AsyncBids{kind}")


def test_unknown_name_is_untyped():
    # neither a file nor a directory can be told from these names
    for name in ("sub-01", "README", "sub-01_T1w.nii.gz"):
        assert type(AsyncBidsPath(f"ds/{name}")) is AsyncBidsPath


def test_lexical_surface_is_shared():
    p = AsyncBidsPath("ds/sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz")
    assert isinstance(p, B.BidsPathMixin)
    assert p.entities == {"sub": "01", "ses": "1"}
    assert (p.suffix, p.extension, p.datatype) == ("T1w", ".nii.gz", "anat")
    moved = p.with_subject("02")
    assert type(moved) is AsyncBidsPath
    assert str(moved) == "ds/sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz"
    assert type(p.with_suffix("scans").with_extension(".tsv")) is (
        B.AsyncBidsScansFile
    )
    assert p == BidsPath(str(p))


# -- tree navigation -----------------------------------------------------------

async def test_navigation(ds):
    anat = await (await (await ds.child("sub-01")).child("ses-1")).child("anat")
    assert isinstance(anat, AsyncBidsPath)
    assert anat == ds / "sub-01" / "ses-1" / "anat"
    assert anat.datatype is None and anat.subject == "01"
    t1w = await anat.child("sub-01_ses-1_acq-mp_T1w.nii.gz")
    assert t1w == ds / T1W
    assert type(await ds.child("participants.tsv")) is B.AsyncBidsParticipantsFile
    assert type(await ds.child("dataset_description.json")) is (
        B.AsyncBidsDatasetDescriptionFile
    )


async def test_keys_and_iteration(ds):
    sub = ds / "sub-01"
    assert await sub.keys() == ["ses-1", "sub-01_T1w.json", "sub-02_T1w.json"]
    assert [name async for name in sub] == await sub.keys()
    assert await ds.has("sub-02") and not await ds.has("sub-03")
    assert [c.name for c in await (ds / "sub-02").values()] == ["anat"]
    assert dict(await (ds / "sub-02").items()) == {"anat": ds / "sub-02" / "anat"}


async def test_missing_child(ds):
    with pytest.raises(KeyError):
        await ds.child("sub-03")
    with pytest.raises(KeyError):
        await ds.child("sub-01/ses-1")   # one level at a time
    assert await ds.get("sub-03") is None


async def test_sync_mapping_syntax_points_to_the_coroutines(ds):
    with pytest.raises(TypeError, match=r"await path\.child"):
        ds["sub-01"]
    with pytest.raises(TypeError, match=r"await path\.has"):
        "sub-01" in ds
    with pytest.raises(TypeError, match=r"await path\.get"):
        (ds / "T1w.json")["Level"]


async def test_read_only(ds):
    with pytest.raises(TypeError, match=r"await \(path / name\)\.write"):
        ds["sub-03.json"] = {}
    with pytest.raises(TypeError, match="does not delete"):
        del ds["sub-01"]
    with pytest.raises(TypeError, match="read-only outside a transaction"):
        await (ds / "T1w.json").set("Level", "x")


# -- contents ------------------------------------------------------------------

async def test_json_reads_as_mapping(ds):
    sidecar = await ds.child("T1w.json")
    assert isinstance(sidecar, B.AsyncBidsJSONFile)
    assert await sidecar.read() == FILES["T1w.json"]
    assert await sidecar.get("MagneticFieldStrength") == 3
    assert {k: v for k, v in await sidecar.items()} == FILES["T1w.json"]
    assert [key async for key in sidecar] == list(FILES["T1w.json"])
    assert await sidecar.has("Level") and not await sidecar.has("Nope")
    assert await sidecar.get("Nope", 0) == 0
    assert set(await sidecar.keys()) == set(FILES["T1w.json"])
    assert list(await sidecar.values()) == list(FILES["T1w.json"].values())
    assert await (ds / "dataset_description.json").get("Name") == "ds"


async def test_json_not_an_object(tmp_path):
    path = AsyncBidsPath(str(tmp_path / "list.json"))
    await path.write_text("[1, 2]")
    assert await path.read() == [1, 2]
    with pytest.raises(TypeError, match="JSON object"):
        await path.keys()


async def test_tsv_reads_as_rows(ds):
    table = await ds.child("participants.tsv")
    rows = await table.read()
    assert rows == [
        {"participant_id": "sub-01", "age": "30", "sex": "F"},
        {"participant_id": "sub-02", "age": None, "sex": "M"},
    ]
    assert [row async for row in table] == rows
    with pytest.raises(TypeError, match=r"await read\(\)"):
        table["age"]


async def test_tsv_dataframe(ds):
    pd = pytest.importorskip("pandas")
    df = await (ds / "participants.tsv").read_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["participant_id", "age", "sex"]
    assert df["age"].isna().tolist() == [False, True]


async def test_tsv_dataframe_without_pandas(ds, monkeypatch):
    import builtins

    real = builtins.__import__

    def no_pandas(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pandas)
    with pytest.raises(ImportError, match="pandas"):
        await (ds / "participants.tsv").read_dataframe()


# -- sidecar inheritance -------------------------------------------------------

async def test_sidecars_nearest_first(ds):
    names = [s.name for s in await (ds / T1W).sidecars()]
    assert names == [
        "sub-01_ses-1_acq-mp_T1w.json",   # datatype
        "sub-01_ses-1_T1w.json",          # session
        "sub-01_T1w.json",                # subject
        "T1w.json",                       # dataset root
    ]
    sidecars = await (ds / T1W).sidecars()
    assert all(isinstance(s, B.AsyncBidsSidecarFile) for s in sidecars)


async def test_metadata_chainmap(ds):
    meta = await (ds / T1W).read_metadata()
    assert isinstance(meta, ChainMap)
    assert meta["Level"] == "datatype"        # nearest wins
    assert meta["SubjectOnly"] == 1           # inherited from subject level
    assert meta["RootOnly"] == 1              # inherited from the root
    assert meta.maps[-1] == FILES["T1w.json"]
    assert "TaskName" not in meta


async def test_metadata_entity_subset_and_suffix(ds):
    bold = ds / BOLD
    meta = await bold.read_metadata()
    assert [s.name for s in await bold.sidecars()] == ["task-rest_bold.json"]
    assert meta["TaskName"] == "rest"
    events = ds / "sub-01/ses-1/func/sub-01_ses-1_task-rest_events.tsv"
    assert (await events.read_metadata())["Level"] == "events"
    other = ds / "sub-02/anat/sub-02_T1w.nii.gz"
    assert [s.name for s in await other.sidecars()] == ["T1w.json"]


async def test_metadata_of_table_and_unsuffixed(ds):
    assert (await (ds / "participants.tsv").read_metadata())["age"] == {
        "Units": "year"
    }
    assert await (ds / "dataset_description.json").read_metadata() == ChainMap()
    sidecar = ds / "sub-01/sub-01_T1w.json"
    assert [s.name for s in await sidecar.sidecars()] == ["T1w.json"]


async def test_explicit_root(ds):
    t1w = ds / T1W
    names = [s.name for s in await t1w.sidecars(root=ds / "sub-01")]
    assert names[-1] == "sub-01_T1w.json"
    meta = await t1w.read_metadata(root=str(ds / "sub-01"))
    assert meta["Level"] == "datatype"
    with pytest.raises(ValueError, match="not an ancestor"):
        await t1w.sidecars(root=ds / "sub-02")


async def test_no_dataset_root(tmp_path):
    path = AsyncBidsPath(str(tmp_path / "loose" / "sub-01_T1w.nii.gz"))
    await path.parent.mkdir()
    await path.write_bytes(b"")
    with pytest.raises(ValueError, match="dataset_description.json"):
        await path.read_metadata()


async def test_each_directory_listed_once(ds, monkeypatch):
    calls = []
    real = AsyncBidsPath.iterdir

    def iterdir(self):
        calls.append(str(self))
        return real(self)

    monkeypatch.setattr(AsyncBidsPath, "iterdir", iterdir)
    await (ds / T1W).sidecars()
    assert len(calls) == len(set(calls)) == 4   # anat, ses-1, sub-01, ds

