"""A walk, and the other listings, inside a transaction see its files."""
import json
import threading

import pytest

from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.filter import BidsFilter

BOLD = "sub-{s}/func/sub-{s}_task-rest_bold"

FILES = {
    "dataset_description.json": {"Name": "x", "BIDSVersion": "1.10.0"},
    "participants.tsv": "participant_id\tgroup\nsub-01\tcontrol\nsub-02\tcontrol\n",
    f"{BOLD.format(s='01')}.nii.gz": "x",
    f"{BOLD.format(s='02')}.nii.gz": "x",
    "sub-02/anat/sub-02_T1w.nii.gz": "x",
}


def _write(root, files):
    root = root.with_mode("w")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            path.write_text(json.dumps(content))
        else:
            path.write_text(content)


@pytest.fixture
def memory_store():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    yield
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(params=["local", "memory"])
def where(request, tmp_path):
    """The dataset's URL, written with `FILES`."""
    if request.param == "memory":
        request.getfixturevalue("memory_store")
        url = "memory://ds"
    else:
        url = str(tmp_path / "ds")
    _write(BidsPath(url), FILES)
    return url


@pytest.fixture
def ds(where):
    return BidsPath(where, mode="w")


@pytest.fixture
def ads(where, request):
    if where.startswith("memory://"):
        request.getfixturevalue("async_memory")
    return AsyncBidsPath(where, mode="w")


def _rel(paths, root):
    return [p.relative_to(root).as_posix() for p in paths]


def _bold_json(root, s="01"):
    return root / f"{BOLD.format(s=s)}.json"


# -- sync ------------------------------------------------------------------------

def test_a_new_sidecar_in_a_block_decides_the_selection(ds):
    f = BidsFilter(RepetitionTime=2)
    with ds:
        ds["sub-01"]["func"]["sub-01_task-rest_bold.json"] = {"RepetitionTime": 2}
        kept = _rel(f.walk(ds), ds)
        assert kept == [
            "dataset_description.json", "participants.tsv",
            f"{BOLD.format(s='01')}.json", f"{BOLD.format(s='01')}.nii.gz",
        ]
        assert _rel(ds.filter(f), ds) == kept
        assert all(p.mode == "w" for p in f.walk(ds))
    # Written now: the same walk finds it on the store.
    assert _rel(f.walk(ds), ds) == kept


def test_an_edited_value_in_a_block_decides_the_selection(ds):
    _bold_json(ds).write({"RepetitionTime": 3})
    f = BidsFilter(RepetitionTime=2)
    assert f"{BOLD.format(s='01')}.nii.gz" not in _rel(f.walk(ds), ds)
    with ds:
        _bold_json(ds)["RepetitionTime"] = 2
        assert f"{BOLD.format(s='01')}.nii.gz" in _rel(f.walk(ds), ds)


def test_new_files_and_folders_in_a_block_are_listed_and_kept(ds):
    beh = "sub-03/beh/sub-03_task-stroop_beh"
    with ds:
        (ds / f"{beh}.tsv").write([{"response_time": 0.5}])
        (ds / f"{beh}.json").write({"TaskName": "stroop"})
        assert _rel(ds.filter(sub="03"), ds) == [
            "dataset_description.json", "participants.tsv",
            f"{beh}.json", f"{beh}.tsv",
        ]
        assert _rel(ds.filter(suffix="beh"), ds)[-1] == f"{beh}.tsv"
        assert ds.subjects() == ["01", "02", "03"]
        assert ds["sub-03"].sessions() == []
        # A filter on its label that leaves the folder out still does.
        assert f"{beh}.tsv" not in _rel(ds.filter(sub="01"), ds)


def test_a_new_session_folder_in_a_block_is_listed(ds):
    with ds:
        (ds / "sub-02/ses-9/anat/sub-02_ses-9_T1w.json").write({"Level": 1})
        assert ds.sessions() == ["9"]
        assert ds["sub-02"].sessions() == ["9"]
        assert "sub-02/ses-9/anat/sub-02_ses-9_T1w.json" in _rel(
            ds.filter(ses="9"), ds
        )


def test_a_whole_dataset_made_in_a_block_is_walked(where):
    new = BidsPath(f"{where}-new", mode="w")
    with new:
        new["dataset_description.json"] = {"Name": "n", "BIDSVersion": "1.10.0"}
        (new / "sub-01/anat/sub-01_T1w.json").write({"Level": 1})
        assert _rel(new.filter(), new) == [
            "dataset_description.json", "sub-01/anat/sub-01_T1w.json",
        ]
        assert new.subjects() == ["01"]


def test_participants_edited_in_a_block_decide_the_selection(ds):
    f = BidsFilter(participants={"group": "patient"}, suffix="bold")
    with ds:
        ds["participants.tsv"]["group"][1] = "patient"
        assert _rel(f.walk(ds), ds)[-1] == f"{BOLD.format(s='02')}.nii.gz"
        assert f"{BOLD.format(s='01')}.nii.gz" not in _rel(f.walk(ds), ds)


def test_participants_made_in_a_block_are_read(where):
    root = BidsPath(f"{where}-p", mode="w")
    _write(root, {k: v for k, v in FILES.items() if k != "participants.tsv"})
    f = BidsFilter(participants={"group": "patient"}, suffix="bold")
    with pytest.raises(FileNotFoundError, match="participants.tsv"):
        f.walk(root)
    with root:
        (root / "participants.tsv").write([
            {"participant_id": "sub-01", "group": "patient"},
        ])
        assert _rel(f.walk(root), root)[-1] == f"{BOLD.format(s='01')}.nii.gz"


def test_another_thread_does_not_see_the_block(ds):
    f = BidsFilter(RepetitionTime=2)
    seen = []
    with ds:
        _bold_json(ds).write({"RepetitionTime": 2})
        thread = threading.Thread(target=lambda: seen.append(f.walk(ds)))
        thread.start()
        thread.join()
        assert len(f.walk(ds)) == 4
    assert _rel(seen[0], ds) == ["dataset_description.json", "participants.tsv"]


def test_a_discarded_block_leaves_nothing_to_list(ds):
    f = BidsFilter(RepetitionTime=2)
    with pytest.raises(ZeroDivisionError), ds:
        _bold_json(ds).write({"RepetitionTime": 2})
        (ds / "sub-03/anat/sub-03_T1w.json").write({})
        kept = _rel(f.walk(ds), ds)
        assert f"{BOLD.format(s='01')}.nii.gz" in kept
        assert "sub-03/anat/sub-03_T1w.json" in kept
        1 / 0
    assert _rel(f.walk(ds), ds) == ["dataset_description.json", "participants.tsv"]
    assert ds.subjects() == ["01", "02"]
    assert not (ds / "sub-03").exists()


def test_the_store_listings_do_not_see_the_block(ds):
    with ds:
        _bold_json(ds).write({"RepetitionTime": 2})
        func = ds["sub-01"]["func"]
        # The brainfilter listing sees the new file; the store's does not.
        assert "sub-01_task-rest_bold.json" in func.keys()
        assert "sub-01_task-rest_bold.json" not in {
            p.name for p in func.iterdir()
        }
        assert not list(func.glob("*.json"))
        assert not _bold_json(ds).exists()


@pytest.mark.parametrize("kwargs", [
    {"RepetitionTime": 2},
    {"sub": "01"},
    {"sub": "03", "RepetitionTime": 2},
    {"participants": {"group": "patient"}},
    {"suffix": "beh"},
    {"ses": "9"},
])
def test_a_walk_in_a_block_keeps_what_select_keeps(ds, kwargs):
    with ds:
        _bold_json(ds).write({"RepetitionTime": 2})
        (ds / "task-rest_bold.json").write({"RepetitionTime": 2})
        (ds / "sub-03/beh/sub-03_task-x_beh.tsv").write([{"a": 1}])
        (ds / "sub-03/ses-9/func/sub-03_ses-9_task-rest_bold.json").write(
            {"RepetitionTime": 2}
        )
        ds["participants.tsv"]["group"][0] = "patient"
        listing = _block_listing(ds)
        assert "sub-03/beh/sub-03_task-x_beh.tsv" in _rel(listing, ds)
        f = BidsFilter(**kwargs)
        assert _rel(f.walk(ds), ds) == _rel(f.select(listing, root=ds), ds)


def _block_listing(ds):
    """Every file of the block's view: the store's, and those it holds."""
    found = {p for p in ds.rglob("*") if p.is_file()}
    pending = [
        "sub-01/func/sub-01_task-rest_bold.json", "task-rest_bold.json",
        "sub-03/beh/sub-03_task-x_beh.tsv",
        "sub-03/ses-9/func/sub-03_ses-9_task-rest_bold.json",
    ]
    return sorted(found | {ds / rel for rel in pending}, key=str)


# -- async -----------------------------------------------------------------------

@pytest.mark.anyio
async def test_async_a_new_sidecar_in_a_block_decides_the_selection(ads):
    f = BidsFilter(RepetitionTime=2)
    async with ads:
        await _bold_json(ads).write({"RepetitionTime": 2})
        kept = _rel(await f.awalk(ads), ads)
        assert kept == [
            "dataset_description.json", "participants.tsv",
            f"{BOLD.format(s='01')}.json", f"{BOLD.format(s='01')}.nii.gz",
        ]
        assert _rel(await ads.filter(f), ads) == kept
    assert _rel(await f.awalk(ads), ads) == kept


@pytest.mark.anyio
async def test_async_new_files_and_participants_in_a_block(ads):
    beh = "sub-03/beh/sub-03_task-stroop_beh"
    f = BidsFilter(participants={"group": "patient"})
    async with ads:
        await (ads / f"{beh}.tsv").write([{"response_time": 0.5}])
        await (ads / "participants.tsv").write([
            {"participant_id": "sub-03", "group": "patient"},
        ])
        assert _rel(await ads.filter(sub="03"), ads)[-1] == f"{beh}.tsv"
        assert _rel(await f.awalk(ads), ads)[-1] == f"{beh}.tsv"
        assert await ads.subjects() == ["01", "02", "03"]
        assert await ads.sessions() == []
        assert BOLD.format(s="01") + ".nii.gz" not in _rel(
            await f.awalk(ads), ads
        )


@pytest.mark.anyio
async def test_async_a_discarded_block_leaves_nothing(ads):
    f = BidsFilter(RepetitionTime=2)
    with pytest.raises(ZeroDivisionError):
        async with ads:
            await _bold_json(ads).write({"RepetitionTime": 2})
            assert len(await f.awalk(ads)) == 4
            1 / 0
    assert _rel(await f.awalk(ads), ads) == [
        "dataset_description.json", "participants.tsv",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("kwargs", [
    {"RepetitionTime": 2}, {"sub": "03"}, {"participants": {"group": "patient"}},
])
async def test_async_awalk_in_a_block_is_the_committed_walk(ads, kwargs):
    f = BidsFilter(**kwargs)
    async with ads:
        await _bold_json(ads).write({"RepetitionTime": 2})
        await (ads / "sub-03/ses-9/func/sub-03_ses-9_task-rest_bold.json").write(
            {"RepetitionTime": 2}
        )
        await (ads / "participants.tsv").set("group", ["patient", "control"])
        got = _rel(await f.awalk(ads), ads)
    assert got == _rel(await f.awalk(ads), ads)
