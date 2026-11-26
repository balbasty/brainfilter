"""Async writes and transactions: local, and memory:// on the native driver."""
import asyncio
import json
from collections import ChainMap

import pytest
from bagof.paths import CommitError

from brainfilter import (
    AsyncBidsPath,
    AsyncTransaction,
    BidsPath,
    ReadOnlyError,
    TransactionError,
)
from brainfilter.tests.test_transaction import EDITED, PARTICIPANTS
from brainfilter.tests.test_tree import FILES, T1W, _populate

pytestmark = pytest.mark.anyio


@pytest.fixture
def local_ds(tmp_path):
    _populate(BidsPath(str(tmp_path / "ds")))
    return AsyncBidsPath(str(tmp_path / "ds"), mode="w")


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
    ds = AsyncBidsPath("memory://ds", mode="w")
    assert type(ds.wrapped).__name__ == "AsyncFSPath"   # the native driver
    return ds


@pytest.fixture(params=["local", "memory"])
def ds(request):
    return request.getfixturevalue(f"{request.param}_ds")


async def on_disk(path):
    """The stored content of a JSON file, read past any transaction."""
    return json.loads(await path.read_text())


# -- async with path: --------------------------------------------------------------

async def test_async_with_path_gives_the_path(ds):
    async with ds as entered:
        assert entered is ds
        await (ds / "T1w.json").set("RepetitionTime", 2.3)
        assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert (await on_disk(ds / "T1w.json"))["RepetitionTime"] == 2.3


async def test_async_with_path_discards_on_exception(ds):
    with pytest.raises(RuntimeError):
        async with ds:
            await (ds / "T1w.json").set("RepetitionTime", 2.3)
            raise RuntimeError
    assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]


async def test_exit_without_enter(ds):
    with pytest.raises(RuntimeError, match="no transaction"):
        await ds.__aexit__(None, None, None)


# -- JSON and TSV writes in a transaction ------------------------------------------

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


async def test_as_dict_in_a_transaction_is_a_copy(ds):
    sidecar = ds / "participants.json"
    async with ds:
        content = await sidecar.as_dict()
        content["age"]["Units"] = "years"                 # not an edit
        (await sidecar.get("age"))["Units"] = "years"     # nor this
        await sidecar.set("New", 1)
        held = await sidecar.as_dict()
        held["New"] = 2
        assert await sidecar.get("New") == 1
        assert (await sidecar.get("age"))["Units"] == "year"
    assert await on_disk(sidecar) == {**FILES["participants.json"], "New": 1}


async def test_columns(ds):
    table = ds / "participants.tsv"
    async with ds:
        await table.set("handedness", ["R", None])
        await table.set("sex", ["M", "M"])
        await table.delete("age")
        assert await table.keys() == ["participant_id", "sex", "handedness"]
        with pytest.raises(ValueError, match="one value per row"):
            await table.set("x", [1])
        with pytest.raises(KeyError):
            await table.delete("nope")
        assert await table.read_text() == PARTICIPANTS
    assert await table.read_text() == (
        "participant_id\tsex\thandedness\n"
        "sub-01\tM\tR\n"
        "sub-02\tM\tn/a\n"
    )


async def test_rows_in_a_transaction_are_copies(ds):
    table = ds / "participants.tsv"
    async with ds:
        rows = await table.as_list()
        rows[0]["sex"] = "M"
        async for row in table.rows():
            row["sex"] = "M"
        (await table.as_dict())["sex"][0] = "M"
        assert await table.get("sex") == ["F", "M"]
        rows.append({"participant_id": "sub-03", "age": 41})
        await table.write(rows)
        assert await table.get("sex") == ["M", "M", None]
    assert await table.read_text() == (
        "participant_id\tage\tsex\n"
        "sub-01\t30\tM\n"
        "sub-02\tn/a\tM\n"
        "sub-03\t41\tn/a\n"
    )
    await table.write([{"a": "1"}])
    assert await table.as_list() == [{"a": 1}]   # inferred as int


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


async def test_dataframe_in_a_transaction(ds):
    pytest.importorskip("pandas")
    table = ds / "participants.tsv"
    async with ds:
        await table.set("sex", ["M", "M"])
        frame = await table.as_dataframe()
        assert frame["sex"].tolist() == ["M", "M"]
    assert "M\n" in await table.read_text()


async def test_unsupported(ds):
    async with ds:
        with pytest.raises(TypeError, match=r"await path\.set"):
            (ds / "T1w.json")["Level"] = "x"
        with pytest.raises(TypeError, match=r"await path\.delete"):
            del (ds / "T1w.json")["Level"]
        with pytest.raises(TypeError, match=r"await path\.has"):
            "Level" in (ds / "T1w.json")
        with pytest.raises(FileNotFoundError):
            await (ds / "nope.json").as_dict()
        with pytest.raises(FileNotFoundError):
            await (ds / "nope.tsv").as_dataframe()


# -- rollback ----------------------------------------------------------------------

async def test_exception_writes_nothing(ds):
    with pytest.raises(RuntimeError, match="boom"):
        async with ds.transaction() as tx:
            await (ds / "T1w.json").set("RepetitionTime", 2.3)
            await (ds / "participants.tsv").set("x", ["1", "2"])
            await (ds / "new.json").write({"x": 1})
            raise RuntimeError("boom")
    assert tx.written == []
    assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert await (ds / "participants.tsv").read_text() == PARTICIPANTS
    assert not await ds.has("new.json")


async def test_unchanged_files_are_not_written(ds):
    async with ds.transaction() as tx:
        await (ds / "T1w.json").as_dict()
        await (ds / "T1w.json").set("Level", "root")
        await (ds / "participants.tsv").set("sex", ["F", "M"])
        await (ds / T1W).sidecar
    assert tx.written == []


async def test_a_write_that_raises_leaves_the_content(ds):
    async with ds.transaction() as tx:
        await (ds / "T1w.json").set("Before", 1)
        with pytest.raises(ValueError):
            await (ds / "T1w.json").update([("Partial", 1), ("x",)])
        assert not await (ds / "T1w.json").has("Partial")
        with pytest.raises(ValueError, match="one value per row"):
            await (ds / "participants.tsv").set("extra", [1, 2, 3])
        assert await (ds / "participants.tsv").keys() == [
            "participant_id", "age", "sex"]
    assert tx.written == [ds / "T1w.json"]
    assert await on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "Before": 1}
    assert await (ds / "participants.tsv").read_text() == PARTICIPANTS


# -- read your writes --------------------------------------------------------------

async def test_sidecar_sees_the_edits(ds):
    data = ds / T1W
    async with ds.transaction():
        await (ds / "T1w.json").set("RepetitionTime", 2.3)
        await (ds / "T1w.json").delete("RootOnly")
        await (data.parent / "sub-01_ses-1_acq-mp_run-1_T1w.json").write(
            {"Run": 1}
        )
        run = data.with_entities(run="1", keep_existing=True)
        meta = await run.sidecar
        assert meta["Run"] == 1 and meta["RepetitionTime"] == 2.3
        assert "RootOnly" not in meta
        await (await data.sidecar).set("Level", "edited")
        assert await (data.parent / data.with_extension(".json").name).get(
            "Level") == "edited"
        flat = (await data.sidecar).as_dict()
        flat["Level"] = "copy"
        assert (await data.sidecar)["Level"] == "edited"
    assert await on_disk(data.with_extension(".json")) == {"Level": "edited"}


async def test_concurrent_edits_of_one_file(ds):
    sidecar = ds / "T1w.json"
    async with ds.transaction():
        await asyncio.gather(*(sidecar.set(f"K{i}", i) for i in range(5)))
    content = await on_disk(sidecar)
    assert all(content[f"K{i}"] == i for i in range(5))


# -- writes at once -----------------------------------------------------------------

async def test_writes_at_once(ds):
    sidecar = ds / "T1w.json"
    await sidecar.set("RepetitionTime", 2.3)
    assert (await on_disk(sidecar))["RepetitionTime"] == 2.3
    await sidecar.delete("RootOnly")
    await sidecar.update({"EchoTime": 0.03})
    assert await on_disk(sidecar) == {
        "Level": "root", "MagneticFieldStrength": 3,
        "RepetitionTime": 2.3, "EchoTime": 0.03,
    }
    table = ds / "participants.tsv"
    await table.set("handedness", ["R", "L"])
    assert "handedness" in await table.read_text()
    await table.delete("handedness")
    assert await table.read_text() == PARTICIPANTS
    await (ds / "sub-09" / "sub-09_T1w.json").write({"New": 1})
    assert await on_disk(ds / "sub-09" / "sub-09_T1w.json") == {"New": 1}


async def test_merged_sidecar_writes_at_once(ds):
    data = ds / T1W
    meta = await data.sidecar
    nearest = meta.sidecars[0]
    await meta.set("EchoTime", 0.03)
    assert await on_disk(nearest) == {"Level": "datatype", "EchoTime": 0.03}
    assert meta["EchoTime"] == 0.03
    await meta.delete("Level")
    assert meta["Level"] == "session"
    await meta.update(A=1)
    assert await on_disk(nearest) == {"EchoTime": 0.03, "A": 1}
    assert meta.parents.sidecars == meta.sidecars[1:]
    for write in (
        lambda: meta.__setitem__("A", 2),
        lambda: meta.__delitem__("A"),
        lambda: meta.pop("A"),
        lambda: meta.popitem(),
        lambda: meta.clear(),
        lambda: meta.setdefault("B", 1),
    ):
        with pytest.raises(TypeError, match=r"await chain\."):
            write()
    with pytest.raises(TypeError, match="no JSON sidecar"):
        await (await (ds / "sub-02/anat/sub-02_T2w.nii.gz").sidecar).set("A", 1)


async def test_failed_write_raises_and_changes_nothing(ds, fail_nth):
    fail_nth(1)
    with pytest.raises(CommitError):
        await (ds / "T1w.json").set("Level", "x")
    assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]


async def test_new_file_is_created_only_when_set(ds):
    new = ds / "new.json"
    with pytest.raises(KeyError):
        await new.delete("k")
    assert not await new.exists()
    async with ds.transaction() as tx:
        with pytest.raises(KeyError):
            await new.delete("k")
        assert not await ds.has("new.json")
        with pytest.raises(FileNotFoundError):
            await new.as_dict()
    assert tx.written == [] and not await new.exists()
    async with ds:
        await new.write({})
    assert await on_disk(new) == {}


# -- read-only paths ---------------------------------------------------------------

async def test_read_only_refuses_every_write(ds):
    ro = ds.with_mode("r")
    sidecar = ro / "T1w.json"
    table = ro / "participants.tsv"
    for write in (
        sidecar.set("Level", "x"),
        sidecar.delete("Level"),
        sidecar.update(Level="x"),
        sidecar.write({}),
        table.set("age", [1, 2]),
        table.delete("age"),
        table.write([]),
    ):
        with pytest.raises(ReadOnlyError, match=r"read-only.*with_mode\('w'\)"):
            await write
    with pytest.raises(ReadOnlyError):
        await (await (ro / T1W).sidecar).set("Level", "x")
    with pytest.raises(ReadOnlyError, match="open a transaction"):
        ro.transaction()
    with pytest.raises(ReadOnlyError, match="open a transaction"):
        async with ro:
            pass
    assert await on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert await (ds / "participants.tsv").read_text() == PARTICIPANTS


# -- partial commit ----------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3])
async def test_partial_failure_report(ds, fail_nth, n):
    calls = fail_nth(n)
    with pytest.raises(TransactionError) as info:
        async with ds.transaction():
            await (ds / "T1w.json").set("Edited", 1)
            await (ds / "participants.tsv").set("Edited", [1, 1])
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
    assert ("Edited" in await (ds / "participants.tsv").read_text()) == (n > 2)
    assert await on_disk(ds / "dwi.json") == FILES["dwi.json"]


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
            await sidecar.write({})
        assert (await sidecar.as_dict())["Level"] == "root"
        async with ds.transaction():
            await sidecar.set("Again", 1)

    async with ds.transaction():
        task = asyncio.create_task(late())
    go.set()
    await task
    assert (await on_disk(sidecar))["Again"] == 1


async def test_write_during_the_commit_raises(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T.awrite_file
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

    monkeypatch.setattr(T, "awrite_file", awrite)
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
        assert await other.as_dict() == await (ds / "T1w.json").as_dict()
    assert tx.written == [ds / "T1w.json"]
    assert await on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "A": 1, "B": 2}


# -- sync and async together -------------------------------------------------------

async def test_sync_and_async_transactions_do_not_overlap(local_ds):
    sync = BidsPath(str(local_ds), mode="w")
    with sync.transaction():
        with pytest.raises(RuntimeError, match="already open"):
            async with local_ds.transaction():
                pass
    async with (local_ds / "sub-01").transaction():
        with pytest.raises(RuntimeError, match="already open"):
            with sync.transaction():
                pass
        with pytest.raises(RuntimeError, match="already open"):
            with sync / "sub-01" / "sub-01_T1w.json":
                pass
        with (sync / "sub-02").transaction():        # disjoint: fine
            sync["sub-02"]["sub-02_T1w.json"] = {"A": 1}
    assert await on_disk(local_ds / "T1w.json") == FILES["T1w.json"]


async def test_a_sync_transaction_keeps_async_writes(local_ds):
    sync = BidsPath(str(local_ds), mode="w")
    reader = local_ds.with_mode("r")
    with sync as tx_root:
        await (local_ds / "T1w.json").set("Async", 1)
        await (reader / "dwi.json").as_dict()        # held, read-only
        await (local_ds / "dwi.json").set("Async", 2)
        assert tx_root["T1w.json"]["Async"] == 1     # the sync read sees it
        assert await on_disk(local_ds / "T1w.json") == FILES["T1w.json"]
    assert (await on_disk(local_ds / "T1w.json"))["Async"] == 1
    assert (await on_disk(local_ds / "dwi.json"))["Async"] == 2


async def test_an_async_transaction_keeps_sync_writes(local_ds):
    sync = BidsPath(str(local_ds), mode="w")
    async with local_ds:
        sync["T1w.json"]["Sync"] = 1
        sync["participants.tsv"]["x"] = [1, 2]
        assert await (local_ds / "T1w.json").get("Sync") == 1
        assert await on_disk(local_ds / "T1w.json") == FILES["T1w.json"]
    assert (await on_disk(local_ds / "T1w.json"))["Sync"] == 1
    assert "x" in await (local_ds / "participants.tsv").keys()


# -- an interrupted commit ---------------------------------------------------------

async def test_cancelled_commit_reports_and_propagates(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T.awrite_file
    calls = []
    blocked = asyncio.Event()

    async def awrite(path, data):
        calls.append(path)
        if len(calls) == 2:
            blocked.set()
            await asyncio.Event().wait()        # until cancelled
        await real(path, data)

    monkeypatch.setattr(T, "awrite_file", awrite)
    holder, raised = [], []

    async def run():
        try:
            async with ds.transaction() as tx:
                holder.append(tx)
                await (ds / "T1w.json").set("Edited", 1)
                await (ds / "participants.tsv").set("Edited", [1, 1])
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


# -- a sidecar that is not there ---------------------------------------------------

async def test_sidecar_without_a_sidecar_refuses_writes(ds):
    data = ds / "sub-02" / "anat" / "sub-02_T2w.nii.gz"
    async with ds.transaction() as tx:
        meta = await data.sidecar
        assert meta == ChainMap() and meta.as_dict() == {}
        with pytest.raises(TypeError, match="no JSON sidecar.*sub-02_T2w.json"):
            await meta.set("EchoTime", 0.03)
        with pytest.raises(TypeError, match="no JSON sidecar"):
            await meta.update(EchoTime=0.03)
        with pytest.raises(TypeError, match="no JSON sidecar"):
            await meta.delete("EchoTime")
    assert tx.written == []


async def test_farther_sidecars_name_what_is_missing(ds):
    meta = await (ds / T1W).sidecar
    farthest = meta
    for _ in meta.sidecars:
        farthest = farthest.parents
    assert type(farthest) is type(meta) and farthest.sidecars == ()
    with pytest.raises(TypeError, match="no farther sidecar"):
        await farthest.set("x", 1)
    with pytest.raises(TypeError, match="no farther sidecar"):
        await farthest.update(x=1)


# -- concurrent writes through ----------------------------------------------------

@pytest.fixture
def slow_writes(monkeypatch):
    """Widen the gap between reading a file and replacing it (see the sync)."""
    from brainfilter import transaction as T

    real = T.awrite_file

    async def awrite_file(path, data):
        await asyncio.sleep(0.005)
        await real(path, data)

    monkeypatch.setattr(T, "awrite_file", awrite_file)


async def test_concurrent_sets_all_survive(ds, slow_writes):
    from brainfilter import transaction as T

    sidecar = ds / "T1w.json"
    await asyncio.gather(*(sidecar.set(k, 1) for k in "abcdef"))
    content = await on_disk(sidecar)
    assert {k: 1 for k in "abcdef"}.items() <= content.items()
    assert asyncio.get_running_loop() not in T._ALOCKS   # nothing kept


async def test_concurrent_tsv_columns_all_survive(ds, slow_writes):
    table = ds / "participants.tsv"
    await asyncio.gather(
        table.set("x", [1, 2]), table.set("y", ["a", "b"]),
        (ds / "sub-01" / ".." / "participants.tsv").set("z", [3, 4]),
    )
    columns = await table.as_dict()
    assert columns["x"] == [1, 2] and columns["y"] == ["a", "b"]
    assert columns["z"] == [3, 4]


async def test_a_cancelled_write_lets_go_of_its_lock(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T.awrite_file
    writing, release = asyncio.Event(), asyncio.Event()

    async def awrite_file(path, data):
        writing.set()
        await release.wait()
        await real(path, data)

    monkeypatch.setattr(T, "awrite_file", awrite_file)
    sidecar = ds / "T1w.json"
    first = asyncio.create_task(sidecar.set("First", 1))
    await writing.wait()
    waiting = asyncio.create_task(sidecar.set("Cancelled", 1))
    await asyncio.sleep(0)                      # waits for the lock
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    release.set()
    await first
    content = await on_disk(sidecar)
    assert content["First"] == 1 and "Cancelled" not in content
    assert asyncio.get_running_loop() not in T._ALOCKS


def test_each_event_loop_has_its_own_locks(tmp_path):
    from brainfilter import transaction as T

    _populate(BidsPath(str(tmp_path / "ds")))
    ds = AsyncBidsPath(str(tmp_path / "ds"), mode="w")
    for run in range(2):                        # two loops, one after the other
        asyncio.run((ds / "T1w.json").set(f"Run{run}", run))
    content = json.loads((tmp_path / "ds" / "T1w.json").read_text())
    assert content["Run0"] == 0 and content["Run1"] == 1
    assert len(T._ALOCKS) == 0


# -- a transaction is not joined from another task or thread ------------------------

async def test_a_task_from_outside_cannot_write_past_a_transaction(ds):
    sidecar = ds / "T1w.json"
    go, done = asyncio.Event(), asyncio.Event()

    async def outside():
        await go.wait()
        try:
            await sidecar.set("Outside", 1)
        finally:
            done.set()

    task = asyncio.create_task(outside())       # started before the block
    with pytest.raises(RuntimeError, match="boom"):
        async with ds:
            await sidecar.set("Inside", 1)
            go.set()
            await done.wait()
            with pytest.raises(RuntimeError, match="another thread or task"):
                await task
            raise RuntimeError("boom")
    assert await on_disk(sidecar) == FILES["T1w.json"]


async def test_a_thread_cannot_write_past_an_async_transaction(local_ds):
    # local only: the sync family cannot use memory:// once it is async here
    import threading

    ds = local_ds
    raised = []

    def thread():
        try:
            BidsPath(str(ds), mode="w")["T1w.json"]["Thread"] = 1
        except RuntimeError as error:
            raised.append(error)

    async with ds:
        await (ds / "T1w.json").set("Inside", 1)
        worker = threading.Thread(target=thread)
        worker.start()
        await asyncio.to_thread(worker.join)
    assert len(raised) == 1 and "another thread or task" in str(raised[0])
    assert await on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "Inside": 1}


# -- column values, and a table with a header and no row -------------------------

@pytest.mark.parametrize("values", ["RL", b"RL", {"a": 1, "b": 2}])
async def test_a_column_is_not_split_from_a_string_or_mapping(ds, values):
    table = ds / "participants.tsv"
    with pytest.raises(TypeError, match="one value per row"):
        await table.set("s", values)
    async with ds:
        with pytest.raises(TypeError, match="one value per row"):
            await table.set("s", values)
    assert await table.read_text() == PARTICIPANTS


async def test_a_header_only_table_takes_its_first_column(ds):
    scans = ds / "sub-01" / "sub-01_scans.tsv"
    await scans.write_text("filename\tacq_time\n")
    await scans.set("filename", ["anat/a.nii"])
    assert await scans.read_text() == "filename\tacq_time\nanat/a.nii\tn/a\n"
    await scans.write_text("filename\n")
    async with ds:
        await scans.set("extra", [1, 2])
    assert await scans.read_text() == "filename\textra\nn/a\t1\nn/a\t2\n"
