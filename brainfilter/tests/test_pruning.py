"""Walks do not list the subject and session folders the filters leave out.

Pruning changes what is listed, never what is kept: every walk below is
checked against `select` on the full listing, and against a walk that
prunes nothing.
"""
import re
import typing

import pytest
import typing_extensions

from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.conditions import Glob, Not
from brainfilter.filter import BidsFilter

FILES = {
    "dataset_description.json": "{}",
    "participants.tsv": (
        "participant_id\tgroup\nsub-01\ta\nsub-02\tb\nsub-001\ta\nsub-10\tb\n"
    ),
    "README": "x",
    # describes sub-01's image only, so its fate depends on sub-01
    "T2w.json": "{}",
    "task-rest_bold.json": '{"RepetitionTime": 2}',
    "sub-01/sub-01_sessions.tsv": "session_id\nses-1\nses-2\n",
    "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz": "x",
    "sub-01/ses-1/anat/sub-01_ses-1_T2w.nii.gz": "x",
    "sub-01/ses-2/func/sub-01_ses-2_task-rest_bold.nii.gz": "x",
    # describes ses-2 only, so its fate depends on ses-2
    "sub-01/sub-01_task-rest_bold.json": "{}",
    "sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz": "x",
    "sub-001/anat/sub-001_T1w.nii.gz": "x",
    "sub-10/ses-1/func/sub-10_ses-1_task-rest_bold.nii.gz": "x",
    "sub-10/ses-1/func/sub-10_ses-1_task-rest_events.tsv": "onset\n0\n",
    "sub-10/ses-1/beh/sub-10_ses-1_task-x_events.tsv": "onset\n0\n",
    "sub-10/ses-2/anat/sub-10_ses-2_T1w.nii.gz": "x",
    # names without the subject or the session of their folders
    "sub-02/notes.txt": "x",
    "sub-01/ses-2/anat/sub-01_T1w.nii.gz": "x",
}
ROOT = "memory://pruned"

PRUNING = [
    BidsFilter(sub="01"),
    BidsFilter(sub=1),
    BidsFilter(sub="02"),
    BidsFilter(sub=Glob("0*")),
    BidsFilter(sub=re.compile("1.")),
    BidsFilter(sub={typing_extensions.Never, "02"}),
    BidsFilter(sub=lambda s: s.endswith("1")),
    BidsFilter(sub=Not(["01", "10"])),
    BidsFilter(sub=Not("02")),
    BidsFilter(sub=typing_extensions.Never),
    BidsFilter(sub={typing_extensions.Never, "01"}),
    BidsFilter(sub="01", ses="1"),
    BidsFilter(ses="1"),
    BidsFilter(ses=2),
    BidsFilter(ses=typing_extensions.Never),
    BidsFilter(ses={"2", typing_extensions.Never}),
    BidsFilter(sub="10", ses="1"),
    BidsFilter(participants={"group": "a"}),
    BidsFilter(participants={"group": "b"}, ses="1"),
]
NOT_PRUNING = [
    BidsFilter(),
    BidsFilter(sub=typing.Any),
    BidsFilter(ses=typing.Any),
    BidsFilter(datatype="anat"),
    BidsFilter(participants={"group": {"a", "b"}}),
]


@pytest.fixture
def store():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    root = BidsPath(ROOT, mode="w")
    for rel, content in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content)
    yield
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


def _rel(paths, root):
    return [p.relative_to(root).as_posix() for p in paths]


@pytest.fixture
def no_pruning(monkeypatch):
    """Call to make every walk list every subject and session folder."""
    def disable():
        monkeypatch.setattr(BidsFilter, "_may_hold", lambda self, *args: True)
    return disable


def _expected(f):
    """What `select` keeps of the full listing, reading the store."""
    root = BidsPath(ROOT)
    return _rel(f.select([root / rel for rel in FILES], root=root), root)


def test_walk_prunes_without_changing_results(store, listed_dirs, no_pruning):
    root = BidsPath(ROOT)
    pruned = {}
    for f in PRUNING + NOT_PRUNING:
        listed_dirs.clear()
        pruned[id(f)] = (_rel(f.walk(root), root), len(listed_dirs))
    expected = {id(f): _expected(f) for f in PRUNING + NOT_PRUNING}
    no_pruning()
    for f in PRUNING + NOT_PRUNING:
        listed_dirs.clear()
        kept = _rel(f.walk(root), root)
        assert pruned[id(f)][0] == kept == expected[id(f)]
        if f in PRUNING:
            assert pruned[id(f)][1] < len(listed_dirs)
        else:
            assert pruned[id(f)][1] == len(listed_dirs)


def test_a_file_takes_the_labels_of_its_folders():
    # a name without the subject (session) has its folder's, in select as in
    # a walk, which prunes by folder
    assert BidsFilter(sub=Not("02")).select(["sub-02/notes.txt"]) == []
    assert BidsFilter(sub="02").select(["sub-02/notes.txt"]) == [
        "sub-02/notes.txt"
    ]
    assert BidsFilter(sub=typing_extensions.Never).select(
        ["sub-02/notes.txt"]
    ) == []
    t1w = ["sub-01/ses-2/anat/sub-01_T1w.nii.gz"]
    assert BidsFilter(ses=typing_extensions.Never).select(t1w) == []
    assert BidsFilter(ses="2").select(t1w) == t1w
    assert BidsFilter(ses="1").select(t1w) == []
    assert BidsFilter().keep_data(t1w[0])
    assert not BidsFilter(ses="1").keep_data(t1w[0])


def test_a_name_that_contradicts_its_folder_is_judged_on_the_name(store):
    # not valid BIDS: select judges it on its name; a walk prunes by folder,
    # and so misses it when the folder's label fails (documented in walk)
    odd = "sub-01/anat/sub-02_T1w.nii.gz"
    root = BidsPath(ROOT, mode="w")
    (root / odd).parent.mkdir(parents=True, exist_ok=True)
    (root / odd).write_text("x")
    assert BidsFilter(sub="02").select([odd]) == [odd]
    assert BidsFilter(sub="01").select([odd]) == []
    assert odd not in _rel(BidsFilter(sub="01").walk(ROOT), root)
    assert odd not in _rel(BidsFilter(sub="02").walk(ROOT), root)


def test_pruned_folders_are_not_listed(store, listed_dirs):
    BidsFilter(sub="02", datatype="anat").walk(ROOT)
    assert "/pruned/sub-02/ses-1/anat" in listed_dirs
    assert not any(d.startswith(("/pruned/sub-01", "/pruned/sub-10"))
                   for d in listed_dirs)
    listed_dirs.clear()
    BidsFilter(ses="1", datatype="anat").walk(ROOT)
    assert "/pruned/sub-10/ses-1" in listed_dirs
    assert not any("ses-2" in d for d in listed_dirs)
    listed_dirs.clear()
    BidsFilter(participants={"group": "b"}, datatype="anat").walk(ROOT)
    assert not any(d.startswith(("/pruned/sub-01", "/pruned/sub-001"))
                   for d in listed_dirs)


def test_a_pruned_folder_is_listed_when_metadata_above_depends_on_it(
    store, listed_dirs
):
    # T2w.json applies to an image of sub-01 only; with sub-01 left out,
    # the walk looks into sub-01 to find it, and drops T2w.json as select
    # does. Nothing below sub-02 needs this.
    kept = _rel(BidsFilter(sub="02").walk(ROOT), BidsPath(ROOT))
    assert "T2w.json" not in kept
    assert "/pruned/sub-01/ses-1/anat" in listed_dirs
    # task-rest_bold.json too, and sub-01 settles both: sub-10 is not listed
    assert "/pruned/sub-10" not in listed_dirs
    listed_dirs.clear()
    # a metadata file the other filters drop needs nothing listed
    BidsFilter(sub="02", suffix="T1w").walk(ROOT)
    assert not any(d.startswith("/pruned/sub-01") for d in listed_dirs)


@pytest.mark.anyio
async def test_awalk_prunes_without_changing_results(
    store, async_memory, listed_dirs, no_pruning
):
    root = AsyncBidsPath(ROOT)
    assert type(root.wrapped).__name__ == "AsyncFSPath"
    pruned = {}
    for f in PRUNING + NOT_PRUNING:
        listed_dirs.clear()
        pruned[id(f)] = (_rel(await f.awalk(root), root), len(listed_dirs))
    no_pruning()
    for f in PRUNING + NOT_PRUNING:
        listed_dirs.clear()
        kept = _rel(await f.awalk(root), root)
        assert pruned[id(f)][0] == kept
        if f in PRUNING:
            assert pruned[id(f)][1] < len(listed_dirs)
        else:
            assert pruned[id(f)][1] == len(listed_dirs)


@pytest.mark.anyio
async def test_awalk_matches_walk_when_pruning(store, async_memory, monkeypatch):
    import sys

    from fsspec.implementations.memory import MemoryFileSystem

    results = [_rel(await f.awalk(ROOT), AsyncBidsPath(ROOT)) for f in PRUNING]
    registry = sys.modules["fsspec.registry"]._registry
    monkeypatch.setitem(registry, "memory", MemoryFileSystem)
    assert results == [_rel(f.walk(ROOT), BidsPath(ROOT)) for f in PRUNING]


# A headshape of the subject named by its `acq` label: whether it applies to
# the recording of session 2 depends on the recording of session 1, which
# has that label.
TAGGED = {
    "dataset_description.json": "{}",
    "sub-01/sub-01_acq-a_headshape.pos": "x",
    "sub-01/ses-1/meg/sub-01_ses-1_task-x_acq-a_meg.fif": "x",
    "sub-01/ses-2/meg/sub-01_ses-2_task-x_meg.fif": "x",
}


@pytest.mark.parametrize("acq", ["a", "b"])
def test_a_pruned_folder_is_listed_when_an_acq_tag_depends_on_it(
    store, listed_dirs, acq
):
    root = BidsPath("memory://tagged", mode="w")
    files = {k.replace("acq-a_meg", f"acq-{acq}_meg"): v
             for k, v in TAGGED.items()}
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content)
    f = BidsFilter(ses="2")
    listed_dirs.clear()
    kept = _rel(f.walk("memory://tagged"), root)
    assert kept == _rel(f.select([root / r for r in files], root=root), root)
    # with acq-a in session 1, the headshape is that recording's alone
    assert ("sub-01/sub-01_acq-a_headshape.pos" in kept) is (acq == "b")
    # either way, the walk has to look into session 1 to tell
    assert "/tagged/sub-01/ses-1/meg" in listed_dirs
