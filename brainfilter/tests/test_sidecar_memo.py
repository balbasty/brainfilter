"""How often the sidecar search lists a directory, across reads and blocks."""
import json
import pickle

import pytest

from brainfilter.bidspath import AsyncBidsPath, BidsPath

EVENTS = "sub-01/func/sub-01_task-rest_events"

FILES = {
    "dataset_description.json": {"Name": "x", "BIDSVersion": "1.10.0"},
    "sub-01/func/sub-01_task-rest_bold.nii.gz": "x",
    f"{EVENTS}.tsv": "onset\tduration\tcode\n1\t2\t1\n3\t2\t2\n",
}


@pytest.fixture
def ds(listed_dirs):
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    root = BidsPath("memory://ds", mode="w")
    for rel, content in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(content) if isinstance(content, dict) else content
        )
    listed_dirs.clear()
    yield root
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


THREE = ["/ds/sub-01/func", "/ds/sub-01", "/ds"]


def test_typed_reads_of_one_table_search_once(ds, listed_dirs):
    events = ds / f"{EVENTS}.tsv"
    for _ in range(3):
        assert events["onset"] == [1.0, 3.0]
    assert events.as_dict()["code"] == [1, 2]
    assert len(events.as_list()) == 2
    assert listed_dirs == THREE
    # Each new path object searches for itself.
    assert (ds / f"{EVENTS}.tsv")["onset"] == [1.0, 3.0]
    assert listed_dirs == THREE * 2


def test_a_sidecar_written_between_reads_is_seen(ds, listed_dirs):
    events = ds / f"{EVENTS}.tsv"
    assert events["code"] == [1, 2]
    (ds / f"{EVENTS}.json").write({"code": {"Levels": {"1": "a", "2": "b"}}})
    assert events["code"] == ["1", "2"]
    # A write to any other file makes the next read search again too.
    listed_dirs.clear()
    (ds / "sub-01/anat").mkdir(parents=True)
    assert events["code"] == ["1", "2"]
    assert listed_dirs == THREE


def test_a_sidecar_removed_between_reads_is_searched_for_again(ds):
    from fsspec.implementations.memory import MemoryFileSystem

    events = ds / f"{EVENTS}.tsv"
    (ds / f"{EVENTS}.json").write({"code": {"Levels": {"1": "a", "2": "b"}}})
    assert events["code"] == ["1", "2"]
    # Removed by another program: brainfilter is not told, and finds out.
    MemoryFileSystem.store.pop(f"/ds/{EVENTS}.json")
    assert events["code"] == [1, 2]


def test_a_sidecar_added_by_another_program_is_seen_by_a_new_path(ds):
    from fsspec.implementations.memory import MemoryFileSystem

    events = ds / f"{EVENTS}.tsv"
    assert events["code"] == [1, 2]
    MemoryFileSystem().pipe_file(
        f"/ds/{EVENTS}.json", b'{"code": {"Levels": {"1": "a", "2": "b"}}}'
    )
    assert events["code"] == [1, 2]
    assert (ds / f"{EVENTS}.tsv")["code"] == ["1", "2"]
    assert events.sidecars                        # the property searches anew


def test_a_copy_and_a_pickle_of_the_path(ds, listed_dirs):
    events = ds / f"{EVENTS}.tsv"
    assert events["onset"] == [1.0, 3.0]
    assert events.with_mode("r")["onset"] == [1.0, 3.0]   # the same file
    assert (events.parent / events.name)["onset"] == [1.0, 3.0]
    assert listed_dirs == THREE
    # A derived path is another file: what it remembers is not used there.
    other = events.with_name("sub-01_task-rest_bold.json")
    assert other._sidecar_memo is events._sidecar_memo
    assert pickle.loads(pickle.dumps(events))._sidecar_memo is None


def test_the_properties_search_each_time_outside_a_block(ds, listed_dirs):
    bold = ds / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    bold.sidecars
    bold.sidecars
    assert listed_dirs == THREE * 2


def test_a_block_lists_each_directory_once(ds, listed_dirs):
    bold = ds / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    with ds:
        assert bold.sidecars == ()
        assert (ds / f"{EVENTS}.tsv")["onset"] == [1.0, 3.0]
        assert (ds / f"{EVENTS}.tsv").with_mode("r")["code"] == [1, 2]
        assert listed_dirs == THREE
        # A new sidecar is seen without listing again.
        (ds / "sub-01/func/sub-01_task-rest_bold.json").write({"Level": 1})
        (ds / "task-rest_bold.json").write({"Level": 0, "TaskName": "rest"})
        assert [s.name for s in bold.sidecars] == [
            "sub-01_task-rest_bold.json", "task-rest_bold.json",
        ]
        assert bold.sidecar.as_dict() == {"Level": 1, "TaskName": "rest"}
        assert listed_dirs == THREE
        # A change to the store through a path lists again.
        (ds / "sub-01/anat").mkdir()
        bold.sidecars
        assert listed_dirs == THREE * 2
    # After the block, a search lists the store again.
    bold.sidecars
    assert listed_dirs == THREE * 3


def test_a_block_does_not_remember_what_it_does_not_cover(ds, listed_dirs):
    bold = ds / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    with ds["sub-01"]:
        bold.sidecars
        bold.sidecars
    assert listed_dirs == THREE + ["/ds"]


def test_a_raw_change_in_a_block_is_seen(ds):
    bold = ds / "sub-05/func/sub-05_task-rest_bold.nii.gz"
    staged = ds / "staging/sub-05/func"
    staged.mkdir(parents=True)
    (staged / bold.name).write_text("x")
    (staged / "sub-05_task-rest_bold.json").write({"Level": 1})
    with ds:
        assert bold.sidecars == ()
        # Moved in by a path's own member, which the block allows.
        (ds / "staging/sub-05").rename(ds / "sub-05")
        assert [s.name for s in bold.sidecars] == ["sub-05_task-rest_bold.json"]


def test_a_root_is_found_without_listing_above_it(ds, listed_dirs):
    # A file outside every subject folder: its folder is listed, and the
    # folders above are asked for a description until one has it.
    (ds / "phenotype/survey.tsv").write([{"participant_id": "sub-01", "a": 1}])
    (ds / "phenotype/survey.json").write({"a": {"Levels": {"1": "x"}}})
    listed_dirs.clear()
    assert (ds / "phenotype/survey.tsv")["a"] == ["1"]
    assert listed_dirs == ["/ds/phenotype", "/ds"]


# -- async -----------------------------------------------------------------------

@pytest.fixture
def ads(ds, async_memory):
    return AsyncBidsPath("memory://ds", mode="w")


@pytest.mark.anyio
async def test_async_typed_reads_of_one_table_search_once(ads, listed_dirs):
    events = ads / f"{EVENTS}.tsv"
    for _ in range(3):
        assert await events.get("onset") == [1.0, 3.0]
    assert listed_dirs == THREE
    await (ads / f"{EVENTS}.json").write({"code": {"Levels": {"1": "a"}}})
    assert await events.get("code") == ["1", "2"]
    assert listed_dirs == THREE * 2


@pytest.mark.anyio
async def test_async_a_block_lists_each_directory_once(ads, listed_dirs):
    bold = ads / "sub-01/func/sub-01_task-rest_bold.nii.gz"
    async with ads:
        assert await bold.sidecars == ()
        await (ads / "task-rest_bold.json").write({"TaskName": "rest"})
        assert [s.name for s in await bold.sidecars] == ["task-rest_bold.json"]
        assert (await bold.sidecar).as_dict() == {"TaskName": "rest"}
        assert await (ads / f"{EVENTS}.tsv").get("onset") == [1.0, 3.0]
    assert listed_dirs == THREE
