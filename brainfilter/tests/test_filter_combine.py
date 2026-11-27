"""Filters combined with `&`, `|` and `~` (#61).

The operators combine what each filter says about a data file; the
metadata of the kept data files follows once, and a metadata file that
describes no data file (rule 3) is judged by each filter in the same
expression. Every walk is checked against `select` on the full listing.
"""
import pickle
import re

import pytest

import brainfilter.filter as bf
from brainfilter import BidsFilter as F
from brainfilter import Missing, Not, Present
from brainfilter.bidspath import AsyncBidsPath, BidsPath

FILES = {
    "dataset_description.json": "{}",
    "participants.tsv": "participant_id\tgroup\nsub-01\ta\nsub-02\tb\nsub-03\ta\n",
    "README": "x",
    "task-rest_bold.json": '{"RepetitionTime": 2}',
    # describes no image of the dataset (rule 3)
    "T2w.json": "{}",
    "acq-z_T1w.json": "{}",
    # describes sub-01's acq-c image only
    "acq-c_T1w.json": "{}",
    "sub-01/ses-1/anat/sub-01_ses-1_acq-a_run-1_T1w.nii.gz": "x",
    "sub-01/ses-1/anat/sub-01_ses-1_acq-b_run-2_T1w.nii.gz": "x",
    "sub-01/ses-1/anat/sub-01_ses-1_acq-b_run-2_T1w.json": "{}",
    "sub-01/ses-2/anat/sub-01_ses-2_acq-c_run-1_T1w.nii.gz": "x",
    "sub-01/ses-1/func/sub-01_ses-1_task-rest_bold.nii.gz": "x",
    "sub-01/ses-1/func/sub-01_ses-1_task-nback_bold.nii.gz": "x",
    "sub-01/ses-1/func/sub-01_ses-1_task-nback_bold.json": '{"RepetitionTime": 1.5}',
    "sub-01/ses-1/func/sub-01_ses-1_task-nback_events.tsv": "onset\n0\n",
    "sub-02/ses-1/anat/sub-02_ses-1_acq-a_run-1_T1w.nii.gz": "x",
    "sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz": "x",
    "sub-02/ses-2/anat/sub-02_ses-2_acq-b_T1w.nii.gz": "x",
    "sub-02/ses-2/func/sub-02_ses-2_task-nback_bold.nii.gz": "x",
    "sub-02/ses-2/func/sub-02_ses-2_task-nback_bold.json": '{"RepetitionTime": 1.5}',
    "sub-03/anat/sub-03_acq-a_T1w.nii.gz": "x",
    "sub-03/func/sub-03_task-rest_bold.nii.gz": "x",
}
ROOT = "memory://combine"


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
    yield BidsPath(ROOT)
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


def _rel(paths, root):
    return [p.relative_to(root).as_posix() for p in paths]


def _kept(f, root):
    """What a walk keeps, checked against `select` on the full listing."""
    walked = _rel(f.walk(root), root)
    assert walked == _rel(f.select([root / r for r in FILES], root=root), root)
    return walked


def _images(kept):
    return [p for p in kept if p.endswith(".nii.gz")]


# -- the examples of the issue -----------------------------------------------

def test_any_of_acquisitions_and_a_run_or_a_session(store):
    f = F(acq={"a", "b"}) & (F(run=1) | F(ses=2))
    kept = _kept(f, store)
    assert _images(kept) == [
        "sub-01/ses-1/anat/sub-01_ses-1_acq-a_run-1_T1w.nii.gz",
        "sub-02/ses-1/anat/sub-02_ses-1_acq-a_run-1_T1w.nii.gz",
        "sub-02/ses-2/anat/sub-02_ses-2_acq-b_T1w.nii.gz",
    ]
    assert _rel(store.filter(f), store) == kept
    assert f(list(FILES)) == f.select(list(FILES))
    assert [p for p in f.select(list(FILES)) if p.endswith(".nii.gz")] == (
        _images(kept)
    )


def test_a_datatype_but_a_task(store):
    f = F(datatype="func") & ~F(task="rest")
    kept = _kept(f, store)
    assert _images(kept) == [
        "sub-01/ses-1/func/sub-01_ses-1_task-nback_bold.nii.gz",
        "sub-02/ses-2/func/sub-02_ses-2_task-nback_bold.nii.gz",
    ]
    # the rest sidecar describes only what the filter leaves out
    assert "task-rest_bold.json" not in kept
    assert "sub-01/ses-1/func/sub-01_ses-1_task-nback_events.tsv" in kept


COMBINATIONS = [
    F(acq={"a", "b"}) & (F(run=1) | F(ses=2)),
    F(datatype="func") & ~F(task="rest"),
    F(participants={"group": "a"}) | F(RepetitionTime=1.5),
    ~F(sub="01") & ~F(RepetitionTime=2),
    F(sub="02", suffix="T1w") | F(sub="03", exclude="*.json"),
]


@pytest.mark.anyio
async def test_awalk_keeps_what_walk_keeps(store, request):
    expected = [_kept(f, store) for f in COMBINATIONS]
    root = AsyncBidsPath(ROOT)      # a synchronous store, in a thread
    for f, kept in zip(COMBINATIONS, expected):
        assert _rel(await f.awalk(root), root) == kept
    request.getfixturevalue("async_memory")     # now natively async
    root = AsyncBidsPath(ROOT)
    assert type(root.wrapped).__name__ == "AsyncFSPath"
    for f, kept in zip(COMBINATIONS, expected):
        assert _rel(await f.awalk(root), root) == kept
        assert _rel(await root.filter(f), root) == kept


# -- what the operators mean ---------------------------------------------------

FILTERS = [
    F(sub="01"), F(ses="2"), F(datatype="anat"), F(task="rest"),
    F(acq={"a", Missing}), F(RepetitionTime=2), F(RepetitionTime=Missing),
    F(participants={"group": "b"}), F(acq=Present), F(suffix="T2w"),
]


def test_de_morgan(store):
    for f, g in zip(FILTERS, FILTERS[3:] + FILTERS[:3]):
        assert _kept(~(f | g), store) == _kept(~f & ~g, store)
        assert _kept(~(f & g), store) == _kept(~f | ~g, store)


def test_or_keeps_what_either_keeps(store):
    for f, g in zip(FILTERS, FILTERS[1:]):
        assert set(_kept(f | g, store)) == set(_kept(f, store)) | set(
            _kept(g, store)
        )


def test_and_of_different_keywords_is_one_filter(store):
    assert _kept(F(sub="01") & F(datatype="anat"), store) == _kept(
        F(sub="01", datatype="anat"), store
    )
    assert _kept(F(participants={"group": "a"}) & F(RepetitionTime=2), store) == (
        _kept(F(participants={"group": "a"}, RepetitionTime=2), store)
    )
    assert _kept(F(acq="z") & F(suffix="T1w"), store) == _kept(
        F(acq="z", suffix="T1w"), store
    )


def test_not_keeps_the_other_data_files(store):
    for f in FILTERS:
        images = set(_images(FILES))
        assert set(_images(_kept(~f, store))) == images - set(
            _images(_kept(f, store))
        )


def test_the_metadata_follows_the_kept_data_once(store):
    # the rest sidecar describes images kept through either side
    kept = _kept(F(sub="01", task="rest") | F(sub="03", task="rest"), store)
    assert kept.count("task-rest_bold.json") == 1
    assert len(kept) == len(set(kept))
    # and an image kept by both sides is kept once
    kept = _kept(F(sub="01") | F(task="rest"), store)
    assert len(kept) == len(set(kept))
    # a sidecar of images that every side leaves out is not kept
    assert "task-rest_bold.json" not in _kept(
        F(datatype="anat") | ~F(task="rest"), store
    )


def test_metadata_that_describes_nothing_is_judged_by_each_filter(store):
    # T2w.json and acq-z_T1w.json describe no image (rule 3)
    assert "T2w.json" in _kept(F(acq="a"), store)          # no acq: lenient
    assert "T2w.json" not in _kept(~F(acq="a"), store)
    assert "T2w.json" not in _kept(F(acq=Present), store)
    assert "T2w.json" in _kept(~F(acq=Present), store)
    assert "acq-z_T1w.json" in _kept(F(acq="z") | F(sub="01"), store)
    assert "acq-z_T1w.json" not in _kept(F(acq="z") & F(datatype="func"), store)
    assert "acq-z_T1w.json" in _kept(F(acq="z") & F(suffix="T1w"), store)
    # `~` turns the verdict around, which is not the same as `Not`
    assert "T2w.json" in _kept(F(acq=Not("a")), store)


def test_participants_and_sidecar_values(store):
    f = F(participants={"group": "a"}) | F(RepetitionTime=1.5)
    images = _images(_kept(f, store))
    assert "sub-02/ses-2/func/sub-02_ses-2_task-nback_bold.nii.gz" in images
    assert "sub-02/ses-1/func/sub-02_ses-1_task-rest_bold.nii.gz" not in images
    assert all(not p.startswith("sub-02/") or "nback" in p for p in images)
    assert "sub-03/anat/sub-03_acq-a_T1w.nii.gz" in images
    negated = _images(_kept(~F(participants={"group": "a"}), store))
    assert negated and all(p.startswith("sub-02/") for p in negated)


def test_each_sidecar_is_read_once(store, monkeypatch):
    reads = []
    real = bf._read_json

    def counting(path):
        reads.append(path.relative_to(store).as_posix())
        return real(path)

    monkeypatch.setattr(bf, "_read_json", counting)
    F(RepetitionTime=2).walk(store)
    one = sorted(reads)
    reads.clear()
    (F(RepetitionTime=2) | F(RepetitionTime=1.5) | ~F(RepetitionTime=1)).walk(store)
    assert sorted(reads) == one and len(reads) == len(set(reads))
    # a sidecar is read only when it can change the answer
    reads.clear()
    (F(datatype="anat") | F(datatype="anat", RepetitionTime=2)).walk(store)
    assert reads == []


@pytest.mark.anyio
async def test_each_sidecar_is_read_once_asynchronously(
    store, async_memory, monkeypatch
):
    reads = []
    real = bf._aread_json

    async def counting(path):
        reads.append(path.name)
        return await real(path)

    monkeypatch.setattr(bf, "_aread_json", counting)
    await (F(RepetitionTime=2) | ~F(RepetitionTime=1.5)).awalk(ROOT)
    assert reads and len(reads) == len(set(reads))


# -- exclude -----------------------------------------------------------------

def test_exclude_removes_what_its_own_filter_keeps(store):
    f = F(sub="01", exclude="*.json") | F(sub="03")
    kept = _kept(f, store)
    assert not any(p.startswith("sub-01/") and p.endswith(".json") for p in kept)
    assert "sub-01/ses-1/func/sub-01_ses-1_task-nback_events.tsv" in kept
    # the rest sidecar comes along with sub-03, whose filter keeps it
    assert "task-rest_bold.json" in kept
    assert "task-rest_bold.json" not in _kept(
        F(sub="01", exclude="*.json") | F(sub="02", datatype="anat"), store
    )
    # either side's exclude applies to what both keep
    kept = _kept(F(sub="01") & F(datatype="func", exclude="*_events.tsv"), store)
    assert not any(p.endswith("_events.tsv") for p in kept)
    assert "sub-01/ses-1/func/sub-01_ses-1_task-nback_bold.json" in kept


def test_exclude_on_dataset_files(store):
    assert "README" not in _kept(F(exclude="README") & F(sub="01"), store)
    assert "README" in _kept(F(exclude="README") | F(sub="01"), store)
    assert "README" in _kept(F(exclude="README") | ~F(sub="01"), store)
    kept = _kept(
        F(exclude="*.json") & F(exclude="dataset_description.json"), store
    )
    assert "dataset_description.json" in kept


def test_exclude_cannot_be_turned_around():
    with pytest.raises(ValueError, match="exclude="):
        ~F(task="rest", exclude="*.tsv")
    with pytest.raises(ValueError, match="exclude="):
        ~(F(sub="01") | F(task="rest", exclude="*.tsv"))
    assert repr(~F(task="rest") & F(exclude="*.tsv")) == (
        "~BidsFilter(task='rest') & BidsFilter(exclude='*.tsv')"
    )


# -- options on the whole dataset ----------------------------------------------

def test_folders_and_bidsignore_apply_to_the_whole_combination(store):
    root = BidsPath(ROOT, mode="w")
    (root / "derivatives/x/dataset_description.json").parent.mkdir(parents=True)
    (root / "derivatives/x/dataset_description.json").write_text("{}")
    (root / ".bidsignore").write_text("*_events.tsv\nsub-03/\n")
    f = F(sub="01", folders="derivatives") | F(sub="03")
    assert f.folders == frozenset({"derivatives"}) and f.bidsignore
    walked = _rel(f.walk(store), store)
    assert "derivatives/x/dataset_description.json" in walked
    assert not any(p.startswith("sub-03/") for p in walked)
    g = (F(sub="01") | F(sub="03")) & F(bidsignore=False)
    assert not g.bidsignore
    assert any(p.startswith("sub-03/") for p in _rel(g.walk(store), store))
    assert _rel(g.walk(store), store) == _rel(
        F(sub=["01", "03"], bidsignore=False).walk(store), store
    )


def test_disagreeing_options_are_refused():
    with pytest.raises(ValueError, match="folders="):
        F(folders="code") | F(folders="derivatives")
    with pytest.raises(ValueError, match="bidsignore="):
        F(bidsignore=True) & ~F(bidsignore=False)
    with pytest.raises(ValueError, match="folders="):
        (F(folders="code") & F(sub=1)) | F(folders=[])
    f = F(folders="code") | F(folders={"code"}) & F(bidsignore=False)
    assert f.folders == {"code"} and f.bidsignore is False
    assert F().folders == frozenset() and F().bidsignore is True


# -- the combination as an object ----------------------------------------------

def test_a_combination_is_a_filter():
    f, g, h = F(sub=1), F(ses=2), F(task="rest")
    for c in (f & g, f | g, ~f):
        assert isinstance(c, F)
    assert ~~f is f
    assert ~~(f | g) is not None and repr(~~(f | g)) == repr(f | g)
    assert repr(f & g & h) == repr(f & (g & h)) == (
        "BidsFilter(sub=1) & BidsFilter(ses=2) & BidsFilter(task='rest')"
    )
    assert repr((f | g) & h) == (
        "(BidsFilter(sub=1) | BidsFilter(ses=2)) & BidsFilter(task='rest')"
    )
    assert repr(f | g & h) == (
        "BidsFilter(sub=1) | BidsFilter(ses=2) & BidsFilter(task='rest')"
    )
    assert repr(~(f & g)) == "~(BidsFilter(sub=1) & BidsFilter(ses=2))"
    assert repr(F(sub=(s for s in ["01"]), RepetitionTime=2, folders="code")) == (
        "BidsFilter(sub=['01'], RepetitionTime=2, folders='code')"
    )
    assert repr(pickle.loads(pickle.dumps(~f | g))) == repr(~f | g)


def test_combining_with_something_else_is_refused():
    for other in (1, "sub-01", None, re.compile("x"), lambda p: True):
        with pytest.raises(TypeError, match="BidsFilter"):
            F() & other
        with pytest.raises(TypeError, match="BidsFilter"):
            other | F(sub=1) | F()


def test_keep_data_and_keep_subject():
    f = F(sub="01") | F(task="rest")
    assert f.keep_subject("01") and f.keep_subject("sub-02")
    assert not (F(sub="01") & F(task="rest")).keep_subject("02")
    assert not (~F(sub="01")).keep_subject("01")
    assert (~F(sub="01", task="rest")).keep_subject("01")
    assert (~F(participants={"group": "a"})).keep_subject("01")
    assert f.keep_data("sub-02/func/sub-02_task-rest_bold.nii.gz")
    assert not f.keep_data("sub-02/anat/sub-02_T1w.nii.gz")
    assert not (~f).keep_data("sub-02/func/sub-02_task-rest_bold.nii.gz")
    # a filter that reads files may keep a file its name does not rule out
    assert (~F(RepetitionTime=2)).keep_data("sub-02/anat/sub-02_T1w.nii.gz")


# -- pruning -------------------------------------------------------------------

def _subjects_listed(listed_dirs):
    return {d.split("/")[2] for d in listed_dirs if d.count("/") >= 2}


def test_or_lists_a_folder_either_side_may_keep(store, listed_dirs):
    _kept(F(sub="01") | F(sub="03"), store)
    listed_dirs.clear()
    (F(sub="01", datatype="anat") | F(sub="03", datatype="anat")).walk(store)
    assert _subjects_listed(listed_dirs) == {"sub-01", "sub-03"}
    listed_dirs.clear()
    (F(sub="01") | F(datatype="anat")).walk(store)
    assert _subjects_listed(listed_dirs) == {"sub-01", "sub-02", "sub-03"}


def test_and_lists_no_more_than_its_best_side(store, listed_dirs):
    for f, g in [
        (F(sub="01"), F(ses="1")), (F(datatype="anat"), F(sub=Not("02"))),
        (F(participants={"group": "a"}), F(ses="2")),
        (F(sub="02") | F(sub="03"), ~F(sub="03")),
    ]:
        counts = []
        for h in (f & g, f, g):
            listed_dirs.clear()
            _kept(h, store)
            counts.append(len(set(listed_dirs)))
        assert counts[0] <= min(counts[1:])


def test_not_prunes_only_what_its_filter_keeps_whole(store, listed_dirs):
    # every file of sub-01 passes F(sub="01"), so ~ keeps none of them
    _kept(~F(sub="01"), store)
    listed_dirs.clear()
    (~F(sub="01")).walk(store)
    assert not any(d.startswith("/combine/sub-01") for d in listed_dirs)
    listed_dirs.clear()
    (~F(sub="01", ses="1")).walk(store)
    assert "/combine/sub-01/ses-2" in listed_dirs
    assert not any(d.startswith("/combine/sub-01/ses-1") for d in listed_dirs)
    # and every file of a subject in group a passes the participants filter
    listed_dirs.clear()
    _kept(~F(participants={"group": "a"}), store)
    assert _subjects_listed(listed_dirs) == {"sub-02"}
    # here sub-01 may hold a file the filter keeps: its anatomy
    listed_dirs.clear()
    (~F(sub="01", datatype="func")).walk(store)
    assert "/combine/sub-01/ses-1/anat" in listed_dirs


def test_pruned_folders_are_listed_when_metadata_above_depends_on_them(
    store, listed_dirs
):
    # acq-c_T1w.json describes an image of sub-01 only: with sub-01 left
    # out, it would describe no image listed, and be kept for that (rule
    # 3), so the walk looks into sub-01 and drops it, as select does
    for f in (F(sub="02") & F(suffix="T1w"),
              F(sub="02", suffix="T1w") | F(sub="03", suffix="T1w")):
        listed_dirs.clear()
        assert "acq-c_T1w.json" not in _kept(f, store)
        assert "/combine/sub-01/ses-2/anat" in listed_dirs
    # a filter whose verdict drops it needs nothing listed
    listed_dirs.clear()
    assert "acq-c_T1w.json" not in _kept(F(sub="02") & F(datatype="anat"), store)
    assert not any(d.startswith("/combine/sub-01") for d in listed_dirs)


def test_a_companion_a_sidecar_filter_drops_follows_the_pruned_folders(
    tmp_path,
):
    # the headshape passes the names of F(ses={Missing, "1"}, X="a") but not
    # its sidecar filter, so whether it comes along with the ses-1 recording
    # depends on the acq-a recording in the pruned ses-2
    files = {
        "dataset_description.json": "{}",
        "sub-01/sub-01_acq-a_headshape.pos": "x",
        "sub-01/ses-1/meg/sub-01_ses-1_task-rest_meg.fif": "x",
        "sub-01/ses-1/meg/sub-01_ses-1_task-rest_meg.json": '{"X": "a"}',
        "sub-01/ses-2/meg/sub-01_ses-2_task-rest_acq-a_meg.fif": "x",
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content)
    root = BidsPath(str(tmp_path))
    for f in (F(ses={Missing, "1"}, X="a"), F(ses={Missing, "1"}) & F(X="a")):
        walked = _rel(f.walk(root), root)
        assert walked == _rel(f.select([root / r for r in files], root=root), root)
        assert "sub-01/sub-01_acq-a_headshape.pos" not in walked
