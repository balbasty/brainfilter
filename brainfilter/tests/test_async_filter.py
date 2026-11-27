"""`BidsFilter.awalk`: the sync walk tests, mirrored with coroutines."""
import pytest

from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.filter import BidsFilter
from brainfilter.tests.test_filter import LISTING, SET_UP, _make

pytestmark = pytest.mark.anyio

FILTERS = [BidsFilter(), BidsFilter(subjects="02"), BidsFilter(folders="derivatives"),
           BidsFilter(datatypes="anat"), BidsFilter(tasks="rest", exclude="*.tsv")]


async def test_awalk_local(tmp_path):
    _make(tmp_path, LISTING)
    root = AsyncBidsPath(str(tmp_path))
    for f in FILTERS:
        kept = await f.awalk(str(tmp_path))
        assert all(isinstance(p, AsyncBidsPath) for p in kept)
        assert [p.relative_to(root).as_posix() for p in kept] == f.select(LISTING)
        assert kept == f.walk(str(tmp_path))
        assert await f.awalk(root) == kept


@pytest.fixture
def memory_listing():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    _make(BidsPath("memory:///brainfilter-walk"), LISTING)
    yield "memory:///brainfilter-walk"
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


async def test_awalk_memory_native_async(memory_listing, async_memory):
    root = AsyncBidsPath(memory_listing)
    assert type(root.wrapped).__name__ == "AsyncFSPath"   # the native driver
    for f in FILTERS:
        kept = await f.awalk(root)
        assert all(isinstance(p, AsyncBidsPath) for p in kept)
        assert all(type(p.wrapped).__name__ == "AsyncFSPath" for p in kept)
        assert [p.relative_to(root).as_posix() for p in kept] == f.select(LISTING)
        assert await f.awalk(memory_listing) == kept


async def test_awalk_companion_files(tmp_path):
    _make(tmp_path, SET_UP)
    root = AsyncBidsPath(str(tmp_path))
    for f in (BidsFilter(tasks="rest"), BidsFilter(sessions="2"),
              BidsFilter(suffixes="pet"), BidsFilter(acq="crosstalk")):
        kept = await f.awalk(root)
        assert [p.relative_to(root).as_posix() for p in kept] == f.select(SET_UP)


async def test_awalk_results_read_asynchronously(tmp_path):
    (tmp_path / "dataset_description.json").write_text('{"Name": "x"}')
    (tmp_path / "participants.tsv").write_text("participant_id\nsub-01\n")
    (tmp_path / "sub-01" / "anat").mkdir(parents=True)
    (tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz").write_bytes(b"")
    kept = {p.name: p for p in await BidsFilter().awalk(str(tmp_path))}
    assert await kept["dataset_description.json"].get("Name") == "x"
    assert await kept["participants.tsv"].as_list() == [
        {"participant_id": "sub-01"}
    ]
    assert all(p.mode == "r" for p in kept.values())


@pytest.fixture
def count_listings(monkeypatch):
    """Record each directory the in-process memory store lists, and how many
    listings were running at once at most."""
    import threading
    import time

    from fsspec.implementations.memory import MemoryFileSystem

    listed = []
    running = [0, 0]   # now, most
    lock = threading.Lock()
    real = MemoryFileSystem.ls

    def ls(self, path, *args, **kwargs):
        with lock:
            listed.append(MemoryFileSystem._strip_protocol(path).rstrip("/"))
            running[0] += 1
            running[1] = max(running)
        try:
            time.sleep(0.02)   # long enough for siblings to overlap
            return real(self, path, *args, **kwargs)
        finally:
            with lock:
                running[0] -= 1

    monkeypatch.setattr(MemoryFileSystem, "ls", ls)
    return listed, running


WALKED = {"", "sub-01", "sub-01/ses-1", "sub-01/ses-1/anat",
          "sub-01/ses-1/fmap", "sub-01/ses-2", "sub-01/ses-2/func", "sub-02",
          "sub-02/ses-1", "sub-02/ses-1/anat", "sub-02/ses-1/dwi", "phenotype"}


def _sync_memory(monkeypatch):
    """Make memory:// synchronous again (the store is the same)."""
    import sys

    from fsspec.implementations.memory import MemoryFileSystem

    registry = sys.modules["fsspec.registry"]._registry
    monkeypatch.setitem(registry, "memory", MemoryFileSystem)


async def test_awalk_native_async_prunes_and_lists_levels_at_once(
    memory_listing, async_memory, count_listings, monkeypatch
):
    from fsspec.implementations.memory import MemoryFileSystem

    # a deep hidden tree and skipped folders that must never be listed
    for rel in [f".git/objects/{a}/{b}" for a in "abcd" for b in "xyz"] + [
        "derivatives/a/b/c/d.txt", "sourcedata/a/b/c.zip",
    ]:
        MemoryFileSystem().pipe_file(f"/brainfilter-walk/{rel}", b"")
    listed, running = count_listings
    root = AsyncBidsPath(memory_listing)
    assert type(root.wrapped).__name__ == "AsyncFSPath"
    kept = await BidsFilter().awalk(root)
    assert [p.relative_to(root).as_posix() for p in kept] == (
        BidsFilter().select(LISTING)
    )
    prefix = "/brainfilter-walk"
    assert sorted(listed) == sorted(
        (prefix + "/" + d).rstrip("/") for d in WALKED
    )
    assert running[1] > 1           # one level's directories at once
    # the sync walk lists the same directories, on the synchronous store
    _sync_memory(monkeypatch)
    listed.clear()
    assert BidsFilter().walk(memory_listing) == [
        BidsPath(memory_listing) / p.relative_to(root).as_posix() for p in kept
    ]
    assert sorted(set(listed)) == sorted(
        (prefix + "/" + d).rstrip("/") for d in WALKED
    )


async def test_awalk_lists_folders_asked_for(memory_listing, async_memory,
                                             count_listings):
    listed, _ = count_listings
    kept = await BidsFilter(folders="derivatives").awalk(memory_listing)
    assert "/brainfilter-walk/derivatives/surfaces/sub-01" in listed
    assert any(p.name == "x.gii" for p in kept)


async def test_walk_and_awalk_rebuild_a_root_of_the_other_family(
    memory_listing, async_memory, monkeypatch
):
    f = BidsFilter(subjects="01")
    expected = f.select(LISTING)
    native = AsyncBidsPath(memory_listing)
    assert type(native.wrapped).__name__ == "AsyncFSPath"
    # a synchronous root, listed on the native async driver
    kept = await f.awalk(BidsPath(memory_listing))
    assert all(type(p.wrapped).__name__ == "AsyncFSPath" for p in kept)
    assert [p.relative_to(native).as_posix() for p in kept] == expected
    # a native async root, listed synchronously
    _sync_memory(monkeypatch)
    kept = f.walk(native)
    assert all(isinstance(p, BidsPath) for p in kept)
    assert [p.relative_to(BidsPath(memory_listing)).as_posix() for p in kept] == (
        expected
    )


def test_rebuilt_root_keeps_storage_options():
    pytest.importorskip("upath")
    from brainfilter._family import in_family

    root = BidsPath("memory:///ds", storage_options={"skip_instance_cache": True})
    rebuilt = in_family(root, AsyncBidsPath)
    assert isinstance(rebuilt, AsyncBidsPath) and str(rebuilt) == str(root)
    assert dict(rebuilt.storage_options) == {"skip_instance_cache": True}
    assert in_family(rebuilt, BidsPath).storage_options == root.storage_options
    assert rebuilt.mode == "r"
    writable = in_family(root.with_mode("w"), AsyncBidsPath)
    assert writable.mode == "w"
    assert in_family(writable, BidsPath).mode == "w"
    assert dict(writable.storage_options) == {"skip_instance_cache": True}
