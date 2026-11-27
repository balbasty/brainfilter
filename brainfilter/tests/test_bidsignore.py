"""`.bidsignore`: the files it names are not part of the dataset."""
import re
import typing

import pytest

from brainfilter.bidspath import AsyncBidsPath, BidsPath, PureBidsPath
from brainfilter.filter import Filter, _BidsIgnore

# -- the patterns -------------------------------------------------------------


@pytest.mark.parametrize("text, rel, is_dir, ignored", [
    # a name at any depth
    ("extra", "extra", False, True),
    ("extra", "sub-01/extra", True, True),
    ("extra", "sub-01/extra/x.txt", False, True),      # inside an ignored dir
    ("extra", "sub-01/extras", False, False),
    # globs
    ("*.txt", "sub-01/anat/notes.txt", False, True),
    ("*.txt", "sub-01/anat/notes.txt.gz", False, False),
    ("sub-0?", "sub-01/x", False, True),
    ("sub-0[12]", "sub-02/x", False, True),
    ("sub-0[!12]", "sub-02/x", False, False),
    ("sub-0[!12]", "sub-03/x", False, True),
    # a slash at the start or in the middle anchors at the root
    ("/extra", "extra/x", False, True),
    ("/extra", "sub-01/extra/x", False, False),
    ("sub-01/anat", "sub-01/anat/x.nii", False, True),
    ("anat/x.nii", "sub-01/anat/x.nii", False, False),
    ("*/anat/*.json", "sub-01/anat/x.json", False, True),
    ("*/anat/*.json", "sub-01/ses-1/anat/x.json", False, False),
    # a trailing slash matches directories only
    ("anat/", "sub-01/anat/x.nii", False, True),
    ("anat/", "sub-01/func/anat", False, False),
    ("anat/", "sub-01/func/anat", True, True),
    # double stars
    ("**/anat/*.json", "sub-01/ses-1/anat/x.json", False, True),
    ("**/anat/*.json", "anat/x.json", False, True),
    ("sub-01/**/x.json", "sub-01/x.json", False, True),
    ("sub-01/**/x.json", "sub-01/ses-1/anat/x.json", False, True),
    ("sub-01/**", "sub-01/ses-1/anat/x.json", False, True),
    ("sub-01/**", "sub-01", True, False),
    ("**", "anything/at/all", False, True),
    # comments, blank lines, escapes
    ("# extra\n\nother", "# extra", False, False),
    ("\\#extra", "#extra", False, True),
    ("\\!extra", "!extra", False, True),
    ("extra   ", "extra", False, True),                 # trailing spaces
    ("ex\\*", "ex*", False, True),
    ("ex\\*", "exa", False, False),
    # `!` re-includes, and the last matching pattern decides
    ("*.json\n!keep.json", "sub-01/keep.json", False, False),
    ("*.json\n!keep.json", "sub-01/drop.json", False, True),
    ("!keep.json\n*.json", "sub-01/keep.json", False, True),
    # ... but not a file inside an ignored directory
    ("extra/\n!extra/keep.json", "extra/keep.json", False, True),
    ("extra/*\n!extra/keep.json", "extra/keep.json", False, False),
    # trailing spaces are dropped, unless escaped
    ("trail\\ ", "trail ", False, True),
    ("trail\\ ", "trail", False, False),
    ("trail ", "trail ", False, False),
    ("trail\\\\ ", "trail\\", False, True),        # an escaped backslash
    # classes, as git reads them (each checked against `git check-ignore`)
    ("foo[!x]bar", "foo/bar", False, False),            # never matches /
    ("foo[!x]bar", "fooybar", False, True),
    ("[!/]x", "ax", False, True),
    ("[/]x", "ax", False, False),
    ("[\\d]x", "dx", False, True),                       # backslash escapes
    ("[\\d]x", "\\x", False, False),
    ("[\\d]x", "5x", False, False),
    ("[[]x", "[x", False, True),
    ("[]]x", "]x", False, True),                         # ] first is literal
    ("[!]]x", "ax", False, True),
    ("[!]]x", "]x", False, False),
    ("[a-]x", "-x", False, True),
    ("[[:digit:]]x", "5x", False, True),
    ("[[:digit:]]x", "dx", False, False),
    ("[[:alpha:]-z]x", "-x", False, True),
    ("[z-a]x", "zx", False, True),                       # a reversed range
    ("[z-a]x", "bx", False, False),                      # ... is its start
    ("[z-ab]x", "bx", False, True),
    # what git cannot match matches nothing
    ("foo[bar", "foo[bar", False, False),                # unterminated
    ("[[:bogus:]]x", "ax", False, False),                # unknown class
    ("trail\\", "trail\\", False, False),               # trailing backslash
    # never ignored
    ("*", "dataset_description.json", False, False),
    ("*", ".bidsignore", False, False),
    ("*", "sub-01/dataset_description.json", False, True),
])
def test_patterns(text, rel, is_dir, ignored):
    ignore = _BidsIgnore.parse(text)   # None when no pattern can match
    assert (ignore is not None and ignore.ignores(rel, is_dir)) is ignored


def test_no_patterns():
    assert _BidsIgnore.parse("") is None
    assert _BidsIgnore.parse("# only a comment\n\n   \n/\n") is None


@pytest.mark.parametrize("pattern", [
    "[z-a]*", "[[]x", "foo[bar", "[[:bogus:]]x", "x[", "\\", "[\\",
])
def test_odd_patterns_neither_raise_nor_warn(pattern, recwarn):
    re.purge()      # a regex already compiled would not warn again
    ignore = _BidsIgnore.parse(f"{pattern}\nextra\n")
    for rel in ("zz", "[x", "foo[bar", "ax", "x[", "\\"):
        ignore.ignores(rel)
    assert ignore.ignores("extra")
    assert not recwarn.list


def test_a_walk_survives_a_malformed_class(tmp_path):
    root = BidsPath(str(tmp_path))
    _write(root, {**FILES, ".bidsignore": "[z-a]*\n[[:bogus:]]\n"})
    assert _rel(Filter().walk(root), root) == _rel(
        Filter(bidsignore=False).walk(root), root
    )


# -- walking ------------------------------------------------------------------

FILES = {
    "dataset_description.json": "{}",
    "participants.tsv": "participant_id\nsub-01\nsub-02\n",
    "README": "x",
    "T2w.json": "{}",
    "sub-01/anat/sub-01_T1w.nii.gz": "x",
    "sub-01/anat/sub-01_T1w.json": "{}",
    "sub-01/anat/sub-01_T2w.nii.gz": "x",
    "sub-01/anat/sub-01_notes.txt": "x",
    "sub-01/extra/deep/file.nii.gz": "x",
    "sub-02/anat/sub-02_T1w.nii.gz": "x",
    "sub-02/anat/sub-02_T1w.json": "{}",
}
IGNORE = (
    "# not BIDS\n*.txt\nextra/\n*_T2w.nii.gz\n"
    "sub-02/anat/*\n!sub-02/anat/*.nii.gz\n"
)


def _write(root, files):
    root = root.with_mode("w")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
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
def ds(request, tmp_path):
    if request.param == "memory":
        request.getfixturevalue("memory_store")
        root = BidsPath("memory://ignored")
    else:
        root = BidsPath(str(tmp_path / "ignored"))
    _write(root, {**FILES, ".bidsignore": IGNORE})
    return root


def _rel(paths, root):
    return [p.relative_to(root).as_posix() for p in paths]


KEPT = [
    ".bidsignore", "README", "T2w.json", "dataset_description.json",
    "participants.tsv",
    "sub-01/anat/sub-01_T1w.json", "sub-01/anat/sub-01_T1w.nii.gz",
    "sub-02/anat/sub-02_T1w.nii.gz",
]


def test_walk_honours_bidsignore(ds):
    # T2w.json describes an image that is ignored: it applies to no data
    # file, and is judged on its own name
    assert _rel(Filter().walk(ds), ds) == KEPT
    assert _rel(Filter(bidsignore=False).walk(ds), ds) == sorted([
        ".bidsignore", "README", "T2w.json", "dataset_description.json",
        "participants.tsv", *[k for k in FILES if k.startswith("sub-")],
    ])
    assert _rel(Filter(suffixes="T2w").walk(ds), ds) == [
        ".bidsignore", "README", "T2w.json", "dataset_description.json",
        "participants.tsv",
    ]


def test_ignored_folders_are_not_listed(ds, listed_dirs):
    if ds.is_local():
        pytest.skip("counts the listings of the memory store")
    Filter().walk(ds)
    assert "/ignored/sub-01/extra" not in listed_dirs
    listed_dirs.clear()
    Filter(bidsignore=False).walk(ds)
    assert "/ignored/sub-01/extra/deep" in listed_dirs


def test_everything_ignored_but_the_description(tmp_path):
    root = BidsPath(str(tmp_path))
    _write(root, {**FILES, ".bidsignore": "*\n"})
    assert _rel(Filter().walk(root), root) == [
        ".bidsignore", "dataset_description.json"
    ]


def test_select_honours_a_bidsignore_it_can_read(ds):
    listing = [p for p in ds.rglob("*") if p.is_file()]
    assert _rel(Filter().select(listing, root=ds), ds) == KEPT
    if ds.is_local():
        strings = [str(p) for p in listing]
        assert _rel(map(BidsPath, Filter().select(strings, root=str(ds))),
                    ds) == KEPT
    # relative strings, or pure paths: there is nothing to read
    rel = _rel(listing, ds)
    assert Filter().select(rel) == Filter(bidsignore=False).select(rel)
    pure = [PureBidsPath(r) for r in rel]
    assert Filter().select(pure) == Filter(bidsignore=False).select(pure)
    # a listing without the file is not ignoring anything
    no_file = [p for p in listing if p.name != ".bidsignore"]
    assert Filter().select(no_file, root=ds) == (
        Filter(bidsignore=False).select(no_file, root=ds)
    )


def test_an_ignored_participants_table(tmp_path):
    root = BidsPath(str(tmp_path))
    _write(root, {**FILES, ".bidsignore": "participants.tsv\n"})
    assert "participants.tsv" not in _rel(Filter().walk(root), root)
    with pytest.raises(FileNotFoundError, match="participants.tsv"):
        Filter(participants={"participant_id": typing.Any}).walk(root)


@pytest.mark.anyio
@pytest.mark.parametrize("backend", ["local", "memory"])
async def test_awalk_honours_bidsignore(backend, tmp_path, request):
    if backend == "memory":
        request.getfixturevalue("memory_store")
        _write(BidsPath("memory://ignored"), {**FILES, ".bidsignore": IGNORE})
        request.getfixturevalue("async_memory")
        root = AsyncBidsPath("memory://ignored")
    else:
        _write(BidsPath(str(tmp_path)), {**FILES, ".bidsignore": IGNORE})
        root = AsyncBidsPath(str(tmp_path))
    assert _rel(await Filter().awalk(root), root) == KEPT
    assert len(await Filter(bidsignore=False).awalk(root)) > len(KEPT)
