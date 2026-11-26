"""`Filter.awalk`: the sync walk tests, mirrored with coroutines."""
import pytest

from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.filter import Filter
from brainfilter.tests.test_filter import LISTING, _make

pytestmark = pytest.mark.anyio

FILTERS = [Filter(), Filter(subjects="02"), Filter(folders="derivatives"),
           Filter(datatypes="anat"), Filter(tasks="rest", exclude="*.tsv")]


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


async def test_awalk_results_read_asynchronously(tmp_path):
    (tmp_path / "dataset_description.json").write_text('{"Name": "x"}')
    (tmp_path / "participants.tsv").write_text("participant_id\nsub-01\n")
    (tmp_path / "sub-01" / "anat").mkdir(parents=True)
    (tmp_path / "sub-01" / "anat" / "sub-01_T1w.nii.gz").write_bytes(b"")
    kept = {p.name: p for p in await Filter().awalk(str(tmp_path))}
    assert await kept["dataset_description.json"].get("Name") == "x"
    assert await kept["participants.tsv"].read() == [
        {"participant_id": "sub-01"}
    ]
