"""Read/write mode: inherited by derived paths, and guarding the writes."""
import copy
import inspect
import pickle

import pytest
from bagof.paths import AsyncPath, Path

from brainfilter import AsyncBidsPath, BidsPath, Filter, PureBidsPath, ReadOnlyError
from brainfilter import bidspath as B
from brainfilter.tests.test_filter import LISTING, _make
from brainfilter.tests.test_tree import T1W, _populate

FAMILIES = [BidsPath, PureBidsPath, AsyncBidsPath]
READ_ONLY = r"read-only; get a writable path with path\.with_mode\('w'\)"


# -- the mode ----------------------------------------------------------------------

@pytest.mark.parametrize("cls", FAMILIES)
def test_read_only_by_default(cls):
    assert cls("ds").mode == "r"
    assert cls("ds", mode="w").mode == "w"
    assert cls("ds", mode="r").mode == "r"


@pytest.mark.parametrize("cls", FAMILIES)
def test_with_mode(cls):
    p = cls("ds/sub-01/anat/sub-01_T1w.json")
    w = p.with_mode("w")
    assert w.mode == "w" and p.mode == "r"         # a new path
    assert type(w) is type(p) and w == p           # the same place and class
    assert w.with_mode("r").mode == "r"
    with pytest.raises(ValueError, match="mode='r'.*mode='w'"):
        p.with_mode("rw")
    with pytest.raises(ValueError, match="invalid mode"):
        cls("ds", mode="a")


@pytest.mark.parametrize("cls", FAMILIES)
def test_repr_shows_a_writable_mode(cls):
    name = cls.__name__
    assert repr(cls("ds")) == f"{name}('ds')"
    assert repr(cls("ds", mode="w")) == f"{name}('ds', mode='w')"


@pytest.mark.parametrize("cls", FAMILIES)
def test_mode_survives_copy_and_pickle(cls):
    p = cls("ds/T1w.json", mode="w")
    for other in (copy.copy(p), copy.deepcopy(p), pickle.loads(pickle.dumps(p))):
        assert other.mode == "w" and type(other) is type(p) and other == p


def test_mode_is_not_identity():
    assert BidsPath("ds") == BidsPath("ds", mode="w")
    assert hash(BidsPath("ds")) == hash(BidsPath("ds", mode="w"))


@pytest.mark.parametrize("source", FAMILIES)
@pytest.mark.parametrize("target", FAMILIES)
def test_a_path_built_from_another_keeps_its_mode(source, target):
    assert target(source("ds", mode="w")).mode == "w"
    assert target(source("ds")).mode == "r"
    assert target(source("ds", mode="w"), mode="r").mode == "r"   # unless asked
    assert target(source("ds"), mode="w").mode == "w"


def test_a_plain_path_gives_read_only():
    assert BidsPath(Path("ds")).mode == "r"
    assert AsyncBidsPath(AsyncPath("ds")).mode == "r"
    assert BidsPath(Path("ds"), mode="w").mode == "w"


def test_a_remote_pure_path_keeps_its_mode():
    pytest.importorskip("upath")
    pure = PureBidsPath("memory://ds/sub-01", mode="w")
    assert BidsPath(str(pure), mode=pure.mode).mode == "w"
    assert BidsPath(pure).mode == "w"
    assert (pure / "anat").mode == "w"


# -- derived paths -----------------------------------------------------------------

def _derived(p):
    """Every lexical way to derive a path from a BIDS file path."""
    return {
        "/": p.parent / "x.json",
        "joinpath": p.parent.joinpath("a", "b"),
        "parent": p.parent,
        "parents": p.parents[-1],
        "with_name": p.with_name("sub-01_T2w.nii.gz"),
        "with_stem": p.with_stem("sub-01_T2w.nii"),
        "with_subject": p.with_subject("02"),
        "with_session": p.with_session("2"),
        "with_entities": p.with_entities(run="1", keep_existing=True),
        "with_suffix": p.with_suffix("T2w"),
        "with_extension": p.with_extension(".json"),
        "with_basename": p.with_basename("sub-01_T2w"),
        "without_query": p.without_query(),
    }


@pytest.mark.parametrize("cls", FAMILIES)
@pytest.mark.parametrize("mode", ["r", "w"])
def test_derived_paths_inherit_the_mode(cls, mode):
    p = cls("ds/sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz", mode=mode)
    for how, derived in _derived(p).items():
        assert derived.mode == mode, how
        assert isinstance(derived, cls), how


def test_resolved_paths_inherit_the_mode(tmp_path):
    p = BidsPath(str(tmp_path / "ds"), mode="w")
    assert p.absolute().mode == p.resolve().mode == "w"
    assert p.expanduser().mode == "w"


@pytest.fixture
def local_ds(tmp_path):
    return _populate(BidsPath(str(tmp_path / "ds")))


@pytest.mark.parametrize("mode", ["r", "w"])
def test_listed_paths_inherit_the_mode(local_ds, mode):
    ds = local_ds.with_mode(mode)
    listed = [
        *ds.iterdir(), *ds.glob("*.json"), *ds.rglob("*.tsv"),
        *(dirpath for dirpath, _, _ in ds.walk()),
        *ds.values(), ds["sub-01"], ds.get("sub-01"),
        *(child for _, child in ds.items()),
        *(ds / T1W).sidecars, *(ds / T1W).sidecar.sidecars,
        *(ds / T1W).sidecar.parents.sidecars,
    ]
    assert len(listed) > 20
    assert {p.mode for p in listed} == {mode}
    assert type(ds["participants.tsv"]) is B.BidsParticipantsFile


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["r", "w"])
async def test_async_listed_paths_inherit_the_mode(local_ds, mode):
    ds = AsyncBidsPath(str(local_ds), mode=mode)
    listed = [child async for child in ds.iterdir()]
    listed += [child async for child in ds.glob("*.json")]
    listed += [child async for child in ds.rglob("*.tsv")]
    listed += [dirpath async for dirpath, _, _ in ds.walk()]
    listed += [*await ds.values(), await ds.child("sub-01"), await ds.get("sub-01")]
    listed += [*await (ds / T1W).sidecars, *(await (ds / T1W).sidecar).sidecars]
    assert len(listed) > 20
    assert {p.mode for p in listed} == {mode}


@pytest.mark.anyio
async def test_native_async_listing_inherits_the_mode(async_memory):
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    try:
        ds = AsyncBidsPath("memory://mode", mode="w")
        assert type(ds.wrapped).__name__ == "AsyncFSPath"
        await (ds / "sub-01" / "sub-01_T1w.json").write({"A": 1})
        listed = [child async for child in ds.iterdir()]
        listed += [p async for p, _, _ in ds.walk()]
        listed += [p async for p in ds.rglob("*.json")]
        assert listed and {p.mode for p in listed} == {"w"}
        ro = ds.with_mode("r")
        assert {p.mode async for p in ro.iterdir()} == {"r"}
    finally:
        MemoryFileSystem.store.clear()
        MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.mark.parametrize("mode", ["r", "w"])
def test_filter_walk_keeps_the_mode(tmp_path, mode):
    _make(BidsPath(str(tmp_path)), LISTING)
    f = Filter(subjects="01")
    for root in (BidsPath(str(tmp_path), mode=mode),
                 PureBidsPath(str(tmp_path), mode=mode),
                 AsyncBidsPath(str(tmp_path), mode=mode)):
        kept = f.walk(root)
        assert kept and {p.mode for p in kept} == {mode}
        assert all(isinstance(p, BidsPath) for p in kept)
    assert {p.mode for p in f.walk(str(tmp_path))} == {"r"}


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["r", "w"])
async def test_filter_awalk_keeps_the_mode(tmp_path, mode):
    _make(BidsPath(str(tmp_path)), LISTING)
    f = Filter(subjects="01")
    for root in (AsyncBidsPath(str(tmp_path), mode=mode),
                 PureBidsPath(str(tmp_path), mode=mode),
                 BidsPath(str(tmp_path), mode=mode)):
        kept = await f.awalk(root)
        assert kept and {p.mode for p in kept} == {mode}
        assert all(isinstance(p, AsyncBidsPath) for p in kept)


# -- guarded members: sync ---------------------------------------------------------

@pytest.fixture
def tree(tmp_path):
    """A writable and a read-only path on a small local tree."""
    root = BidsPath(str(tmp_path / "ds"), mode="w")
    (root / "sub-01").mkdir(parents=True)
    (root / "T1w.json").write_text("{}")
    (root / "sub-01" / "sub-01_T1w.json").write_text('{"A": 1}')
    return root, root.with_mode("r")


SYNC_REFUSED = {
    "write_text": lambda p: (p / "x.json").write_text("{}"),
    "write_text atomic": lambda p: (p / "x.json").write_text("{}", atomic=True),
    "write_bytes": lambda p: (p / "x.json").write_bytes(b"{}"),
    "open w": lambda p: (p / "T1w.json").open("w"),
    "open a": lambda p: (p / "T1w.json").open("a"),
    "open x": lambda p: (p / "x.json").open(mode="x"),
    "open r+": lambda p: (p / "T1w.json").open("r+"),
    "open wb": lambda p: (p / "T1w.json").open("wb", atomic=True),
    "touch": lambda p: (p / "x.json").touch(),
    "mkdir": lambda p: (p / "sub-02").mkdir(),
    "unlink": lambda p: (p / "T1w.json").unlink(),
    "rmdir": lambda p: (p / "sub-01").rmdir(recursive=True),
    "rmtree": lambda p: (p / "sub-01").rmtree(),
    "rename": lambda p: (p / "T1w.json").rename(str(p / "T2w.json")),
    "replace": lambda p: (p / "T1w.json").replace(str(p / "T2w.json")),
    "symlink_to": lambda p: (p / "link.json").symlink_to(p / "T1w.json"),
    "hardlink_to": lambda p: (p / "link.json").hardlink_to(p / "T1w.json"),
    "chmod": lambda p: (p / "T1w.json").chmod(0o644),
    "lchmod": lambda p: (p / "T1w.json").lchmod(0o644),
    "staged": lambda p: (p / "T1w.json").staged(),
    "move": lambda p: (p / "T1w.json").move(str(p / "T2w.json")),
    "move_into": lambda p: (p / "T1w.json").move_into(str(p / "sub-01")),
    "upload_from": lambda p: (p / "T1w.json").upload_from("x"),
}


@pytest.mark.parametrize("name", SYNC_REFUSED)
def test_read_only_refuses_the_mutating_members(tree, name):
    _, ro = tree
    before = sorted(str(p) for p in ro.rglob("*"))
    with pytest.raises(ReadOnlyError, match=READ_ONLY) as info:
        SYNC_REFUSED[name](ro)
    message = str(info.value)
    assert "cannot " in message
    for internal in (" _mode", "._mode", "guard", "require", "super",
                     "brainfilter."):
        assert internal not in message
    assert sorted(str(p) for p in ro.rglob("*")) == before
    assert (ro / "T1w.json").read_text() == "{}"


def test_messages_name_the_operation(tree):
    _, ro = tree
    with pytest.raises(ReadOnlyError, match="cannot write to .*x.json"):
        (ro / "x.json").write_text("")
    with pytest.raises(ReadOnlyError, match="cannot open for writing"):
        (ro / "T1w.json").open("w")
    with pytest.raises(ReadOnlyError, match="cannot remove the directory"):
        (ro / "sub-01").rmdir()
    with pytest.raises(ReadOnlyError, match="cannot copy onto"):
        (ro / "T1w.json").copy(ro / "T2w.json")
    with pytest.raises(ReadOnlyError, match="cannot move .*T1w.json"):
        (ro / "T1w.json").move(ro.with_mode("w") / "T2w.json")


def test_read_only_reads(tree):
    _, ro = tree
    with (ro / "T1w.json").open() as f:
        assert f.read() == "{}"
    with (ro / "T1w.json").open("rb") as f:
        assert f.read() == b"{}"
    assert (ro / "T1w.json").read_bytes() == b"{}"
    assert (ro / "T1w.json").exists() and (ro / "sub-01").is_dir()
    assert (ro / "T1w.json").stat().st_size == 2


def test_copy_and_move_onto_a_read_only_path(tree):
    root, ro = tree
    with pytest.raises(ReadOnlyError, match="copy onto"):
        (root / "T1w.json").copy(ro / "T2w.json")
    with pytest.raises(ReadOnlyError, match="copy onto"):
        (root / "T1w.json").copytree(ro / "T2w.json")
    with pytest.raises(ReadOnlyError, match="copy into"):
        (root / "T1w.json").copy_into(ro / "sub-01")
    with pytest.raises(ReadOnlyError, match="move"):
        (root / "T1w.json").move(ro / "T2w.json")
    with pytest.raises(ReadOnlyError, match="move into"):
        (root / "T1w.json").move_into(ro / "sub-01")
    with pytest.raises(ReadOnlyError, match="rename"):
        (root / "T1w.json").rename(ro / "T2w.json")
    with pytest.raises(ReadOnlyError, match="rename"):
        (root / "T1w.json").replace(target=ro / "T2w.json")
    with pytest.raises(ReadOnlyError, match="hard link"):
        (root / "T1w.json").link_to(ro / "T2w.json")
    with pytest.raises(ReadOnlyError, match="download to"):
        (root / "T1w.json").download_to(ro / "T2w.json")
    assert not (root / "T2w.json").exists()
    assert (root / "T1w.json").exists()


def test_copy_from_a_read_only_path(tree):
    root, ro = tree
    copied = (ro / "T1w.json").copy(root / "T2w.json")    # the source is read
    assert (root / "T2w.json").read_text() == "{}"
    assert copied == root / "T2w.json"
    (ro / "sub-01").copy_into(root / "sub-01" / ".." / "copies")
    assert (root / "copies" / "sub-01" / "sub-01_T1w.json").exists()
    (ro / "T1w.json").copy(str(root / "T3w.json"))        # a string target
    assert (root / "T3w.json").exists()


def test_writable_members_work(tree):
    root, _ = tree
    (root / "a.json").write_text("{}")
    (root / "b.json").write_bytes(b"{}")
    with (root / "a.json").open("a") as f:
        f.write(" ")
    (root / "c.json").touch()
    (root / "sub-02").mkdir()
    (root / "c.json").unlink()
    (root / "sub-02").rmdir()
    moved = (root / "a.json").rename(root / "a2.json")
    assert moved.mode == "w" and moved.exists()
    (root / "a2.json").replace(root / "a3.json")
    (root / "link.json").symlink_to(root / "a3.json")
    (root / "hard.json").hardlink_to(root / "a3.json")
    (root / "a3.json").chmod(0o644)
    with (root / "d.json").staged() as staged:
        assert staged.mode == "w"
        staged.write_text("{}")
    assert (root / "d.json").read_text() == "{}"
    assert (root / "d.json").move(root / "sub-01" / "d.json").mode == "w"
    (root / "b.json").move_into(root / "sub-01")
    (root / "sub-01").copy(root / "sub-03")
    assert (root / "sub-03" / "b.json").exists()
    (root / "sub-03").rmtree()
    assert not (root / "sub-03").exists()


def test_wrapped_bypasses_the_mode(tree):
    _, ro = tree
    (ro / "free.json").wrapped.write_text("{}")
    assert (ro / "free.json").read_text() == "{}"


def test_signatures_are_kept():
    for name in ("write_text", "open", "mkdir", "copy", "move", "staged"):
        assert inspect.signature(getattr(BidsPath, name)) == inspect.signature(
            getattr(Path, name))
        assert inspect.signature(getattr(AsyncBidsPath, name)) == (
            inspect.signature(getattr(AsyncPath, name)))
        assert getattr(BidsPath, name).__doc__ == getattr(Path, name).__doc__
    assert inspect.iscoroutinefunction(AsyncBidsPath.write_text)
    assert not inspect.iscoroutinefunction(AsyncBidsPath.staged)


def test_a_bad_call_raises_its_own_error(tree):
    _, ro = tree
    with pytest.raises(TypeError):
        (ro / "T1w.json").copy()          # no target: the member's own error
    with pytest.raises(TypeError):
        (ro / "T1w.json").open("r", 1, None, None, None, None, None)


def test_pure_paths_have_no_io():
    p = PureBidsPath("ds/T1w.json", mode="w")
    for name in ("write_text", "mkdir", "unlink"):
        assert not hasattr(p, name)


# -- guarded members: async --------------------------------------------------------

ASYNC_REFUSED = {
    "write_text": lambda p: (p / "x.json").write_text("{}"),
    "write_bytes": lambda p: (p / "x.json").write_bytes(b"{}"),
    "open w": lambda p: (p / "T1w.json").open("w"),
    "open +": lambda p: (p / "T1w.json").open("rb+"),
    "touch": lambda p: (p / "x.json").touch(),
    "mkdir": lambda p: (p / "sub-02").mkdir(),
    "unlink": lambda p: (p / "T1w.json").unlink(),
    "rmdir": lambda p: (p / "sub-01").rmdir(recursive=True),
    "rmtree": lambda p: (p / "sub-01").rmtree(),
    "rename": lambda p: (p / "T1w.json").rename(str(p / "T2w.json")),
    "replace": lambda p: (p / "T1w.json").replace(str(p / "T2w.json")),
    "symlink_to": lambda p: (p / "link.json").symlink_to(p / "T1w.json"),
    "hardlink_to": lambda p: (p / "link.json").hardlink_to(p / "T1w.json"),
    "chmod": lambda p: (p / "T1w.json").chmod(0o644),
    "move": lambda p: (p / "T1w.json").move(str(p / "T2w.json")),
    "move_into": lambda p: (p / "T1w.json").move_into(str(p / "sub-01")),
    "copy onto": lambda p: (p.with_mode("w") / "T1w.json").copy(p / "T2w.json"),
    "copy_into onto": lambda p: (p.with_mode("w") / "T1w.json").copy_into(
        p / "sub-01"),
    "move onto": lambda p: (p.with_mode("w") / "T1w.json").move(p / "T2w.json"),
}


@pytest.mark.anyio
@pytest.mark.parametrize("name", ASYNC_REFUSED)
async def test_async_read_only_refuses_the_mutating_members(tree, name):
    root, _ = tree
    ro = AsyncBidsPath(str(root))
    with pytest.raises(ReadOnlyError, match=READ_ONLY):
        await ASYNC_REFUSED[name](ro)
    assert (root / "T1w.json").read_text() == "{}"
    assert not (root / "T2w.json").exists() and not (root / "x.json").exists()


@pytest.mark.anyio
async def test_async_staged_is_refused(tree):
    root, _ = tree
    ro = AsyncBidsPath(str(root))
    with pytest.raises(ReadOnlyError, match="stage"):
        ro.staged()                       # a plain method: refused at once


@pytest.mark.anyio
async def test_async_writable_members_work(tree):
    root, _ = tree
    w = AsyncBidsPath(str(root), mode="w")
    await (w / "a.json").write_text("{}")
    async with await (w / "a.json").open("a") as f:
        await f.write(" ")
    async with await (w / "T1w.json").open() as f:
        assert await f.read() == "{}"
    await (w / "sub-02").mkdir()
    async with (w / "d.json").staged() as staged:
        assert staged.mode == "w"
        await staged.write_text("{}")
    copied = await (w.with_mode("r") / "d.json").copy(w / "e.json")
    assert copied.mode == "r" and await (w / "e.json").exists()
    moved = await (w / "e.json").move(w / "sub-02" / "e.json")
    assert moved.mode == "w"
    await (w / "sub-02").rmtree()
    assert not (root / "sub-02").exists()


def test_a_member_the_class_lacks_is_not_guarded():
    from brainfilter._mode import guard_members

    class Plain:
        def write_text(self, data):
            return data

    @guard_members
    class Guarded(Plain):
        mode = "r"

    assert "write_text" in Guarded.__dict__ and "mkdir" not in Guarded.__dict__
    with pytest.raises(ReadOnlyError):
        Guarded().write_text("x")


def test_rebuilt_without_storage_options(monkeypatch):
    pytest.importorskip("upath")
    from bagof.paths import UnsupportedPathOperation

    from brainfilter._family import in_family

    def refuse(self):
        raise UnsupportedPathOperation("storage_options")

    root = AsyncBidsPath("memory://ds", mode="w")
    monkeypatch.setattr(AsyncPath, "storage_options", property(refuse))
    rebuilt = in_family(root, BidsPath)       # a driver with no options
    assert isinstance(rebuilt, BidsPath) and rebuilt.mode == "w"
    assert str(rebuilt) == str(root)


def test_the_guard_list_is_complete():
    from brainfilter._mode import _MEMBERS

    for cls in (BidsPath, AsyncBidsPath):
        for name in _MEMBERS:
            if hasattr(cls, name):
                assert name in cls.__dict__, (cls, name)
    assert "lchmod" in BidsPath.__dict__ and "link_to" in AsyncBidsPath.__dict__


def test_the_tree_writes_need_a_writable_path(tree):
    root, ro = tree
    with pytest.raises(ReadOnlyError, match="cannot write to"):
        ro["T1w.json"]["A"] = 1
    root["T1w.json"]["A"] = 1
    assert ro["T1w.json"].as_dict() == {"A": 1}
