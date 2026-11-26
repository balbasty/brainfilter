"""Async transactions and edits: local, and memory:// on the native driver."""
import asyncio
import json

import pytest
from bagof.paths import CommitError

from brainfilter.bidspath import AsyncBidsPath, BidsPath, Table
from brainfilter.tests.test_transaction import EDITED, PARTICIPANTS
from brainfilter.tests.test_tree import FILES, T1W, _populate
from brainfilter.transaction import AsyncTransaction, TransactionError

pytestmark = pytest.mark.anyio


@pytest.fixture
def local_ds(tmp_path):
    _populate(BidsPath(str(tmp_path / "ds")))
    return AsyncBidsPath(str(tmp_path / "ds"))


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


@pytest.fixture
def memory_ds(memory_store, async_memory):
    ds = AsyncBidsPath("memory://ds")
    assert type(ds.wrapped).__name__ == "AsyncFSPath"   # the native driver
    return ds


@pytest.fixture(params=["local", "memory"])
def ds(request):
    return request.getfixturevalue(f"{request.param}_ds")


async def on_disk(path):
    """The stored content of a JSON file, read past any transaction."""
    return json.loads(await path.read_text())


# -- edits -----------------------------------------------------------------------

async def test_set_delete_update_write(ds):
    sidecar = ds / "T1w.json"
    async with ds.transaction() as tx:
        assert isinstance(tx, AsyncTransaction)
        await sidecar.set("RepetitionTime", 2.3)
        await sidecar.delete("RootOnly")
        await sidecar.update(EchoTime=0.03)
        with pytest.raises(KeyError):
            await sidecar.delete("Nope")
        assert await on_disk(sidecar) == FILES["T1w.json"]
        await (ds / "dwi.json").write({"Only": "this"})
    assert tx.written == [sidecar, ds / "dwi.json"]
    assert await on_disk(sidecar) == {
        "Level": "root", "MagneticFieldStrength": 3,
        "RepetitionTime": 2.3, "EchoTime": 0.03,
    }
    assert await on_disk(ds / "dwi.json") == {"Only": "this"}


async def test_content_is_edited_in_place(ds):
    async with ds.transaction():
        content = await (ds / "participants.json").read()
        content["age"]["Units"] = "years"
    assert await on_disk(ds / "participants.json") == {"age": {"Units": "years"}}


async def test_rows_and_columns(ds):
    table = ds / "participants.tsv"
    async with ds.transaction():
        rows = await table.read()
        assert isinstance(rows, Table)
        rows.append({"participant_id": "sub-03", "age": 41})
        del rows[1]
        rows.add_column("handedness", ["R", None])
        rows.drop_column("sex")
        assert [row async for row in table] == rows
    assert await table.read_text() == (
        "participant_id\tage\thandedness\n"
        "sub-01\t30\tR\n"
        "sub-03\t41\tn/a\n"
    )
    async with ds.transaction():
        await table.write([{"a": "1"}])
    assert await table.read() == [{"a": 1}]   # inferred as int


async def test_new_files(ds):
    async with ds.transaction() as tx:
        new = ds / "sub-03" / "anat" / "sub-03_T1w.json"
        await new.write({"Level": "new"})
        await (new.parent / "x.json").set("A", 1)     # created by a key
        assert await ds.has("sub-03")
        sub = await ds.child("sub-03")
        assert await sub.keys() == ["anat"]
        anat = await sub.child("anat")
        assert await anat.keys() == ["sub-03_T1w.json", "x.json"]
        assert await (await anat.child("sub-03_T1w.json")).get("Level") == "new"
        assert not await new.exists()
    assert [p.name for p in tx.written] == ["sub-03_T1w.json", "x.json"]
    assert await on_disk(new) == {"Level": "new"}


async def test_unsupported(ds):
    async with ds.transaction():
        with pytest.raises(TypeError, match=r"await path\.set"):
            (ds / "T1w.json")["Level"] = "x"
        with pytest.raises(TypeError, match=r"await path\.delete"):
            del (ds / "T1w.json")["Level"]
        with pytest.raises(TypeError, match="read()"):
            (ds / "participants.tsv")["age"] = []
        with pytest.raises(FileNotFoundError):
            await (ds / "nope.json").read()


# -- rollback and nothing hidden ---------------------------------------------------

async def test_exception_writes_nothing(ds):
    with pytest.raises(RuntimeError, match="boom"):
        async with ds.transaction() as tx:
            await (ds / "T1w.json").set("RepetitionTime", 2.3)
            (await (ds / "participants.tsv").read()).append({"x": "1"})
            await (ds / "new.json").write({"x": 1})
            raise RuntimeError("boom")
    assert tx.written == []
    assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert await (ds / "participants.tsv").read_text() == PARTICIPANTS
    assert not await ds.has("new.json")


async def test_read_only_outside_a_transaction(ds):
    sidecar = ds / "T1w.json"
    for edit in (
        sidecar.set("Level", "x"),
        sidecar.delete("Level"),
        sidecar.update(Level="x"),
        sidecar.write({}),
        (ds / "participants.tsv").write([]),
    ):
        with pytest.raises(TypeError, match="async with dataset.transaction"):
            await edit
    assert await on_disk(sidecar) == FILES["T1w.json"]


async def test_families_do_not_share_a_transaction(ds):
    sync = BidsPath(str(ds)) if ds.is_local() else None
    if sync is None:
        pytest.skip("the sync memory:// driver is replaced by the async one")
    with sync.transaction():
        with pytest.raises(TypeError, match="read-only"):
            await (ds / "T1w.json").set("Level", "x")


async def test_unchanged_files_are_not_written(ds):
    async with ds.transaction() as tx:
        await (ds / "T1w.json").read()
        await (ds / "T1w.json").set("Level", "root")
        await (ds / T1W).read_metadata()
    assert tx.written == []


# -- read your writes --------------------------------------------------------------

async def test_metadata_sees_the_edits(ds):
    data = ds / T1W
    async with ds.transaction():
        await (ds / "T1w.json").set("RepetitionTime", 2.3)
        await (ds / "T1w.json").delete("RootOnly")
        await (data.parent / "sub-01_ses-1_acq-mp_run-1_T1w.json").write(
            {"Run": 1}
        )
        run = data.with_entities(run="1", keep_existing=True)
        meta = await run.read_metadata()
        assert meta["Run"] == 1 and meta["RepetitionTime"] == 2.3
        assert "RootOnly" not in meta
        (await data.read_metadata())["Level"] = "edited"
        assert await (data.parent / data.with_extension(".json").name).get(
            "Level") == "edited"
    assert await on_disk(data.with_extension(".json")) == {"Level": "edited"}


async def test_concurrent_edits_of_one_file(ds):
    sidecar = ds / "T1w.json"
    async with ds.transaction():
        await asyncio.gather(*(sidecar.set(f"K{i}", i) for i in range(5)))
    content = await on_disk(sidecar)
    assert all(content[f"K{i}"] == i for i in range(5))


# -- partial commit ----------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3])
async def test_partial_failure_report(ds, fail_nth, n):
    calls = fail_nth(n)
    with pytest.raises(TransactionError) as info:
        async with ds.transaction():
            await (ds / "T1w.json").set("Edited", 1)
            (await (ds / "participants.tsv").read()).append(
                {"participant_id": "sub-03"}
            )
            await (ds / "dwi.json").set("Edited", 1)
    error = info.value
    assert [p.name for p in error.written] == EDITED[:n - 1]
    assert error.failed == ds / EDITED[n - 1]
    assert [p.name for p in error.not_written] == EDITED[n - 1:]
    assert isinstance(error.error, CommitError)
    assert error.__cause__ is error.error and error.errno == 13
    assert len(calls) == n
    assert (await on_disk(ds / "T1w.json")).get("Edited") == (
        1 if n > 1 else None
    )
    assert ("sub-03" in await (ds / "participants.tsv").read_text()) == (n > 2)
    assert await on_disk(ds / "dwi.json") == FILES["dwi.json"]


# -- single-file edits -------------------------------------------------------------

async def test_edit(ds):
    sidecar = ds / "T1w.json"
    async with sidecar.edit() as content:
        content["RepetitionTime"] = 2.3
        assert await sidecar.get("RepetitionTime") == 2.3
        assert await on_disk(sidecar) == FILES["T1w.json"]
    assert (await on_disk(sidecar))["RepetitionTime"] == 2.3
    new = ds / "sub-01" / "sub-01_scans.tsv"
    async with new.edit() as rows:
        rows.append({"filename": "anat/x.nii.gz"})
    assert await new.read() == [{"filename": "anat/x.nii.gz"}]


async def test_edit_discards_on_exception(ds):
    with pytest.raises(ValueError):
        async with (ds / "T1w.json").edit() as content:
            content["Level"] = "x"
            raise ValueError
    assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]


async def test_edit_raises_the_commit_error(ds, fail_nth):
    fail_nth(1)
    with pytest.raises(CommitError):
        async with (ds / "T1w.json").edit() as content:
            content["Level"] = "x"
    assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]


async def test_edit_joins_a_transaction(ds):
    async with ds.transaction() as tx:
        async with (ds / "T1w.json").edit() as content:
            content["Level"] = "x"
        assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert tx.written == [ds / "T1w.json"]
