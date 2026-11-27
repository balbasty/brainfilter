"""`ds.filter(...)`, `ds.subjects()` and `ds.sessions()`, sync and async."""
import pytest

from brainfilter.bidspath import AsyncBidsPath, BidsPath, PureBidsPath
from brainfilter.filter import BidsFilter

FILES = {
    "dataset_description.json": "{}",
    "sub-10/ses-2/anat/sub-10_ses-2_T1w.nii.gz": "x",
    "sub-10/ses-10/anat/sub-10_ses-10_T1w.nii.gz": "x",
    "sub-2/ses-1/func/sub-2_ses-1_task-rest_bold.nii.gz": "x",
    "sub-2/ses-2/anat/sub-2_ses-2_T1w.nii.gz": "x",
    "sub-2/ses-x.txt": "not a directory",
    "sub-3.txt": "not a directory",
    ".hidden/sub-99/ses-9/anat/sub-99_ses-9_T1w.nii.gz": "x",
    "derivatives/fmriprep/sub-10/ses-2/anat/"
    "sub-10_ses-2_space-MNI_desc-preproc_T1w.nii.gz": "x",
    "derivatives/sub-98/ses-8/anat/sub-98_ses-8_T1w.nii.gz": "x",
}


def _populate(root):
    top = root.with_mode("w")
    for rel, content in FILES.items():
        path = top / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


@pytest.fixture
def memory_store():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    _populate(BidsPath("memory://ds"))
    yield
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(params=["local", "memory"])
def ds(request, tmp_path):
    if request.param == "memory":
        request.getfixturevalue("memory_store")
        return BidsPath("memory://ds")
    return _populate(BidsPath(str(tmp_path / "ds")))


@pytest.fixture(params=["local", "memory"])
def ads(request, tmp_path):
    if request.param == "memory":
        request.getfixturevalue("memory_store")
        request.getfixturevalue("async_memory")
        return AsyncBidsPath("memory://ds")
    _populate(BidsPath(str(tmp_path / "ds")))
    return AsyncBidsPath(str(tmp_path / "ds"))


def _rel(paths, root):
    """The data files among `paths`, relative to `root`."""
    return [p.relative_to(root).as_posix() for p in paths
            if p.name.endswith(".nii.gz")]


# -- filter --------------------------------------------------------------------

def test_filter_keywords_and_instance(ds):
    assert ds.mode == "r"      # listing works on a read-only path
    got = ds.filter(sub="2", suffix="bold")
    assert _rel(got, ds) == [
        "sub-2/ses-1/func/sub-2_ses-1_task-rest_bold.nii.gz"
    ]
    assert all(isinstance(p, BidsPath) for p in got)
    f = BidsFilter(sub="2", suffix="bold")
    assert ds.filter(f) == f.walk(ds) == got


def test_filter_derivatives(ds):
    got = ds["derivatives"]["fmriprep"].filter(sub=10, desc="preproc")
    assert len(_rel(got, ds)) == 1
    assert not any(r.startswith("derivatives/")
                   for r in _rel(ds.filter(), ds))
    assert any(r.startswith("derivatives/")
               for r in _rel(ds.filter(folders=["derivatives"]), ds))


@pytest.mark.parametrize("args,kwargs", [
    ((BidsFilter(),), {"sub": 1}),
    ((BidsFilter(), BidsFilter()), {}),
    (("sub-01",), {}),
])
def test_filter_bad_arguments(ds, args, kwargs):
    with pytest.raises(TypeError):
        ds.filter(*args, **kwargs)


def test_not_on_pure_paths():
    p = PureBidsPath("ds")
    for name in ("filter", "subjects", "sessions"):
        assert not hasattr(p, name)


# -- subjects / sessions -------------------------------------------------------

def test_subjects_sessions(ds):
    assert ds.subjects() == ["2", "10"]
    assert ds.sessions() == ["1", "2", "10"]
    assert ds["sub-2"].sessions() == ["1", "2"]
    assert ds["sub-10"].sessions() == ["2", "10"]


def test_text_labels_sort_as_text(tmp_path):
    root = BidsPath(str(tmp_path)).with_mode("w")
    for name in ("sub-b", "sub-10", "sub-a"):
        (root / name).mkdir()
    assert root.subjects() == ["10", "a", "b"]


@pytest.mark.anyio
async def test_async(ads):
    assert ads.mode == "r"
    got = await ads.filter(sub="2", suffix="bold")
    assert all(isinstance(p, AsyncBidsPath) for p in got)
    assert _rel(got, ads) == [
        "sub-2/ses-1/func/sub-2_ses-1_task-rest_bold.nii.gz"
    ]
    assert await ads.filter(BidsFilter(sub="2", suffix="bold")) == got
    with pytest.raises(TypeError):
        await ads.filter(BidsFilter(), sub=1)
    assert await ads.subjects() == ["2", "10"]
    assert await ads.sessions() == ["1", "2", "10"]
    assert await (ads / "sub-2").sessions() == ["1", "2"]
