"""The async family: the sync tree tests, mirrored with coroutines."""
import json
from collections import ChainMap

import pytest

from brainfilter import bidspath as B
from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.tests.test_bidspath import DISPATCH
from brainfilter.tests.test_tree import (
    BOLD,
    COLUMNS,
    FILES,
    LOOSE_DATA,
    RAW_ROWS,
    ROWS,
    T1W,
    _populate,
    _populate_loose,
)

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


async def test_missing_directory(ds):
    with pytest.raises(OSError):
        await (ds / "nope").keys()
    sidecars = await (ds / "nope" / "sub-01_T1w.nii.gz").sidecars
    assert [s.name for s in sidecars] == ["T1w.json"]


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
    assert ds.mode == "r"
    with pytest.raises(TypeError, match=r"await \(path / name\)\.write"):
        ds["sub-03.json"] = {}
    with pytest.raises(TypeError, match="does not delete"):
        del ds["sub-01"]
    with pytest.raises(B.ReadOnlyError, match="read-only.*with_mode"):
        await (ds / "T1w.json").set("Level", "x")
    assert await (ds / "T1w.json").as_dict() == FILES["T1w.json"]


# -- contents ------------------------------------------------------------------

async def test_json_reads_as_mapping(ds):
    sidecar = await ds.child("T1w.json")
    assert isinstance(sidecar, B.AsyncBidsJSONFile)
    assert await sidecar.as_dict() == FILES["T1w.json"]
    assert type(await sidecar.as_dict()) is dict
    assert await sidecar.get("MagneticFieldStrength") == 3
    assert {k: v for k, v in await sidecar.items()} == FILES["T1w.json"]
    assert [key async for key in sidecar] == list(FILES["T1w.json"])
    assert await sidecar.has("Level") and not await sidecar.has("Nope")
    assert await sidecar.get("Nope", 0) == 0
    assert set(await sidecar.keys()) == set(FILES["T1w.json"])
    assert list(await sidecar.values()) == list(FILES["T1w.json"].values())
    assert await (ds / "dataset_description.json").get("Name") == "ds"


async def test_json_not_an_object(tmp_path):
    path = AsyncBidsPath(str(tmp_path / "list.json"), mode="w")
    await path.write_text("[1, 2]")
    with pytest.raises(TypeError, match="JSON object"):
        await path.as_dict()
    with pytest.raises(TypeError, match="JSON object"):
        await path.keys()
    with pytest.raises(TypeError, match="JSON object"):
        await path.set("a", 1)


async def test_tsv_loads_as_rows_and_columns(ds):
    table = await ds.child("participants.tsv")
    assert await table.as_list() == ROWS
    assert [row async for row in table.rows()] == ROWS
    assert await table.as_list(raw=True) == RAW_ROWS
    assert [row async for row in table.rows(raw=True)] == RAW_ROWS
    assert await table.as_dict() == await table.columns() == COLUMNS
    assert (await table.columns(raw=True))["age"] == ["30", "n/a"]
    assert (await table.as_dict(raw=True))["age"] == ["30", "n/a"]


async def test_tsv_is_a_mapping_of_columns(ds):
    table = ds / "participants.tsv"
    assert await table.get("age") == [30.0, None]
    assert await table.get("hand") is None and await table.get("hand", 0) == 0
    assert await table.keys() == ["participant_id", "age", "sex"]
    assert [name async for name in table] == await table.keys()
    assert await table.has("sex") and not await table.has("hand")
    assert await table.values() == list(COLUMNS.values())
    assert await table.items() == list(COLUMNS.items())
    with pytest.raises(TypeError, match=r"await table\.get"):
        table["age"]
    with pytest.raises(TypeError, match=r"await table\.set"):
        table["age"] = [1, 2]
    with pytest.raises(TypeError, match=r"await table\.delete"):
        del table["age"]
    with pytest.raises(TypeError, match=r"await table\.has"):
        "age" in table


async def test_tsv_dataframe(ds):
    pd = pytest.importorskip("pandas")
    df = await (ds / "participants.tsv").as_dataframe()
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
        await (ds / "participants.tsv").as_dataframe()


# -- sidecar inheritance -------------------------------------------------------

async def test_sidecars_nearest_first(ds):
    sidecars = await (ds / T1W).sidecars
    assert isinstance(sidecars, tuple)
    names = [s.name for s in sidecars]
    assert names == [
        "sub-01_ses-1_acq-mp_T1w.json",   # datatype
        "sub-01_ses-1_T1w.json",          # session
        "sub-01_T1w.json",                # subject
        "T1w.json",                       # dataset root
    ]
    assert all(isinstance(s, B.AsyncBidsSidecarFile) for s in sidecars)


async def test_sidecar_chainmap(ds):
    meta = await (ds / T1W).sidecar
    assert isinstance(meta, ChainMap)
    assert meta["Level"] == "datatype"        # nearest wins
    assert meta["SubjectOnly"] == 1           # inherited from subject level
    assert meta["RootOnly"] == 1              # inherited from the root
    assert meta.maps[-1] == FILES["T1w.json"]
    assert meta.sidecars == await (ds / T1W).sidecars
    assert "TaskName" not in meta
    flat = meta.as_dict()
    assert type(flat) is dict and flat["Level"] == "datatype"
    flat["Level"] = "x"
    assert meta["Level"] == "datatype"


async def test_sidecar_properties_start_when_awaited(ds):
    import gc
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        hasattr(ds / T1W, "sidecars")         # read, never awaited
        (ds / T1W).sidecar
        gc.collect()


async def test_metadata_entity_subset_and_suffix(ds):
    bold = ds / BOLD
    meta = await bold.sidecar
    assert [s.name for s in await bold.sidecars] == ["task-rest_bold.json"]
    assert meta["TaskName"] == "rest"
    events = ds / "sub-01/ses-1/func/sub-01_ses-1_task-rest_events.tsv"
    assert (await events.sidecar)["Level"] == "events"
    other = ds / "sub-02/anat/sub-02_T1w.nii.gz"
    assert [s.name for s in await other.sidecars] == ["T1w.json"]


async def test_sidecar_of_table_and_unsuffixed(ds):
    assert (await (ds / "participants.tsv").sidecar)["age"] == {
        "Units": "year"
    }
    assert await (ds / "dataset_description.json").sidecar == ChainMap()
    assert await ds.sidecars == ()
    sidecar = ds / "sub-01/sub-01_T1w.json"
    assert [s.name for s in await sidecar.sidecars] == ["T1w.json"]


async def test_removed_api(ds):
    for gone in ("read", "read_dataframe", "read_metadata", "metadata",
                 "edit"):
        assert not hasattr(ds / "participants.tsv", gone)
        assert not hasattr(ds / "T1w.json", gone)
        assert not hasattr(ds / T1W, gone)


async def test_no_dataset_root_uses_own_directory(tmp_path):
    _populate_loose(BidsPath(str(tmp_path)))
    top = AsyncBidsPath(str(tmp_path))
    data = top / LOOSE_DATA
    names = [s.name for s in await data.sidecars]
    assert names == ["sub-01_T1w.json", "T1w.json"]
    meta = await data.sidecar
    assert meta["Level"] == "own" and meta["Generic"] == 1
    assert "Above" not in meta


async def test_no_dataset_root_sidecar_write(tmp_path):
    _populate_loose(BidsPath(str(tmp_path)))
    top = AsyncBidsPath(str(tmp_path), mode="w")
    data = top / LOOSE_DATA
    async with data.parent.transaction() as tx:
        await (await data.sidecar).set("EchoTime", 0.03)
    assert tx.written == [top / "loose/sub-01_T1w.json"]
    assert json.loads(await (top / "loose/sub-01_T1w.json").read_text()) == {
        "Level": "own", "EchoTime": 0.03,
    }


async def test_each_directory_listed_once(ds, monkeypatch):
    calls = []
    real = AsyncBidsPath.iterdir

    def iterdir(self):
        calls.append(str(self))
        return real(self)

    monkeypatch.setattr(AsyncBidsPath, "iterdir", iterdir)
    await (ds / T1W).sidecars
    assert len(calls) == len(set(calls)) == 4   # anat, ses-1, sub-01, ds



# -- child names -------------------------------------------------------------------

@pytest.mark.parametrize("name", [".", "..", "", "a/b"])
async def test_dot_and_dot_dot_are_not_children(ds, name):
    with pytest.raises(KeyError):
        await ds.child(name)
    assert not await ds.has(name) and await ds.get(name) is None


async def test_dot_dot_is_not_covered_by_the_transaction(tmp_path):
    _populate(BidsPath(str(tmp_path / "ds")))
    ds = AsyncBidsPath(str(tmp_path / "ds"), mode="w")
    async with ds.transaction() as tx:
        await (ds / ".." / "outside.json").write({"Out": 1})   # written now
        assert (tmp_path / "outside.json").exists()
        await (ds / "sub-01" / ".." / ".." / "out2.json").set("Out", 2)
        assert json.loads((tmp_path / "out2.json").read_text()) == {"Out": 2}
    assert tx.written == []


# -- sidecar read errors -----------------------------------------------------------

async def test_metadata_raises_the_nearest_unreadable_sidecar(ds, monkeypatch):
    import asyncio

    near = ds / "sub-01/ses-1/anat/sub-01_ses-1_acq-mp_T1w.json"
    await near.with_mode("w").write_text("{near")
    await (ds / "T1w.json").with_mode("w").write_text("{far")
    real = type(near).read_text

    async def read_text(self, *args, **kwargs):
        if self.name == near.name:
            await asyncio.sleep(0.05)      # the nearest fails last
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(type(near), "read_text", read_text)
    with pytest.raises(json.JSONDecodeError) as info:
        await (ds / T1W).sidecar
    assert info.value.doc == "{near"


# -- typed reads ------------------------------------------------------------------

async def test_typed_read_finds_the_root_itself(tmp_path):
    from brainfilter.tests.test_tree import _loose_table

    _loose_table(BidsPath(str(tmp_path)))
    top = AsyncBidsPath(str(tmp_path), mode="w")
    table = top / "loose" / "sub-01_events.tsv"
    assert await table.as_list() == [{"code": 1}, {"code": 2}]
    await (top / "dataset_description.json").write_text("{}")
    assert await table.as_list() == [{"code": "1"}, {"code": "2"}]
    async with top:
        assert await table.get("code") == ["1", "2"]
    pytest.importorskip("pandas")
    assert (await table.as_dataframe())["code"].tolist() == ["1", "2"]
