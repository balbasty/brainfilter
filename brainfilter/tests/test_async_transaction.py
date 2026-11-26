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


# -- a transaction only while it is open -------------------------------------------

async def test_task_outliving_the_transaction_raises(ds):
    sidecar = ds / "T1w.json"
    started, go = asyncio.Event(), asyncio.Event()

    async def late():
        started.set()
        await go.wait()
        await sidecar.set("Late", 1)

    async with ds.transaction():
        task = asyncio.create_task(late())
        await started.wait()
    go.set()
    with pytest.raises(RuntimeError, match="already closed.*would be lost"):
        await task
    assert await on_disk(sidecar) == FILES["T1w.json"]


async def test_late_task_can_read_and_open_its_own(ds):
    sidecar = ds / "T1w.json"
    go = asyncio.Event()

    async def late():
        await go.wait()
        with pytest.raises(RuntimeError, match="already closed"):
            async with sidecar.edit():
                pass
        assert (await sidecar.read())["Level"] == "root"
        async with ds.transaction():
            await sidecar.set("Again", 1)

    async with ds.transaction():
        task = asyncio.create_task(late())
    go.set()
    await task
    assert (await on_disk(sidecar))["Again"] == 1


async def test_write_during_the_commit_raises(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T._awrite_file
    committing, done = asyncio.Event(), asyncio.Event()

    async def awrite(path, data):
        committing.set()
        await done.wait()
        await real(path, data)

    async def late():
        await committing.wait()
        try:
            await (ds / "dwi.json").set("Late", 1)
        finally:
            done.set()

    monkeypatch.setattr(T, "_awrite_file", awrite)
    async with ds.transaction():
        await (ds / "T1w.json").set("Edited", 1)
        task = asyncio.create_task(late())
    with pytest.raises(RuntimeError, match="being committed"):
        await task
    assert await on_disk(ds / "dwi.json") == FILES["dwi.json"]
    assert (await on_disk(ds / "T1w.json"))["Edited"] == 1


# -- one entry per file -----------------------------------------------------------

async def test_two_names_for_one_file_share_an_entry(ds):
    other = ds / "sub-01" / ".." / "T1w.json"
    async with ds.transaction() as tx:
        await other.set("A", 1)
        await (ds / "T1w.json").set("B", 2)
        assert await other.read() is await (ds / "T1w.json").read()
    assert tx.written == [ds / "T1w.json"]
    assert await on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "A": 1, "B": 2}


# -- a joined edit that fails ------------------------------------------------------

async def test_failed_edit_in_a_transaction_is_undone(ds):
    async with ds.transaction() as tx:
        await (ds / "T1w.json").set("Before", 1)
        with pytest.raises(ValueError):
            async with (ds / "T1w.json").edit() as content:
                content["Partial"] = 1
                raise ValueError
        assert "Partial" not in await (ds / "T1w.json").read()
        rows = await (ds / "participants.tsv").read()
        with pytest.raises(ValueError):
            async with (ds / "participants.tsv").edit() as table:
                table[0]["sex"] = "M"
                del table[1]
                raise ValueError
        assert await (ds / "participants.tsv").read() is rows
    assert tx.written == [ds / "T1w.json"]
    assert await on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "Before": 1}
    assert await (ds / "participants.tsv").read_text() == PARTICIPANTS


# -- sync and async transactions do not overlap ------------------------------------

async def test_sync_and_async_transactions_do_not_overlap(local_ds):
    sync = BidsPath(str(local_ds))
    with sync.transaction():
        with pytest.raises(RuntimeError, match="already open"):
            async with local_ds.transaction():
                pass
        with pytest.raises(RuntimeError, match="already open"):
            async with (local_ds / "T1w.json").edit():
                pass
    async with (local_ds / "sub-01").transaction():
        with pytest.raises(RuntimeError, match="already open"):
            with sync.transaction():
                pass
        with pytest.raises(RuntimeError, match="already open"):
            with (sync / "sub-01" / "sub-01_T1w.json").edit():
                pass
        with (sync / "sub-02").transaction():        # disjoint: fine
            sync["sub-02"]["sub-02_T1w.json"] = {"A": 1}
    assert await on_disk(local_ds / "T1w.json") == FILES["T1w.json"]


# -- an interrupted commit ---------------------------------------------------------

async def test_cancelled_commit_reports_and_propagates(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T._awrite_file
    calls = []
    blocked = asyncio.Event()

    async def awrite(path, data):
        calls.append(path)
        if len(calls) == 2:
            blocked.set()
            await asyncio.Event().wait()        # until cancelled
        await real(path, data)

    monkeypatch.setattr(T, "_awrite_file", awrite)
    holder, raised = [], []

    async def run():
        try:
            async with ds.transaction() as tx:
                holder.append(tx)
                await (ds / "T1w.json").set("Edited", 1)
                (await (ds / "participants.tsv").read()).append(
                    {"participant_id": "sub-03"}
                )
                await (ds / "dwi.json").set("Edited", 1)
        except BaseException as error:
            raised.append(error)
            raise

    task = asyncio.create_task(run())
    await blocked.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # what left the transaction: the cancellation itself, with a note
    assert type(raised[0]) is asyncio.CancelledError
    notes = getattr(raised[0], "__notes__", [])
    assert len(notes) == 1 and "interrupted writing" in notes[0]
    assert f"written: {str(ds / 'T1w.json')!r}" in notes[0]
    assert f"not written: {str(ds / 'participants.tsv')!r}" in notes[0]
    assert holder[0].written == [ds / "T1w.json"]
    assert await on_disk(ds / "dwi.json") == FILES["dwi.json"]


# -- a new file only when it is given content --------------------------------------

async def test_new_file_is_created_only_when_set(ds):
    new = ds / "new.json"
    async with new.edit():
        pass
    assert not await new.exists()
    async with ds.transaction() as tx:
        with pytest.raises(KeyError):
            await new.delete("k")
        assert not await ds.has("new.json")
        with pytest.raises(FileNotFoundError):
            await new.read()
    assert tx.written == [] and not await new.exists()
    async with ds.transaction():
        await new.write({})
    assert await on_disk(new) == {}


# -- metadata with no sidecar ------------------------------------------------------

async def test_metadata_without_a_sidecar_refuses_writes(ds):
    data = ds / "sub-02" / "anat" / "sub-02_T2w.nii.gz"
    async with ds.transaction() as tx:
        meta = await data.read_metadata()
        assert dict(meta) == {}
        with pytest.raises(TypeError, match="no JSON sidecar.*sub-02_T2w.json"):
            meta["EchoTime"] = 0.03
    assert tx.written == []
