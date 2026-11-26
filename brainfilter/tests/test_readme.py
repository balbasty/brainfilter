"""The README's Python examples run, top to bottom, on a memory:// dataset.

Every ```python block of the README is run in order, in one namespace, so
a name a block binds is seen by the blocks after it, as a reader running
them one after the other would see it. A block with a top-level `await`
(the async section) is run as a coroutine on an event loop of its own.

The README reads and writes `memory://ds`; the dataset it is run on is
built by `README_DATASET` below (the one setup the examples need) and holds
only what they read.
"""
import ast
import asyncio
import importlib.metadata
import inspect
import json
import re
from pathlib import Path

import pytest

from brainfilter import BidsPath

# -- setup: the dataset the README's examples read ---------------------------------

README_DATASET = {
    "dataset_description.json": {"Name": "readme", "BIDSVersion": "1.10.0"},
    "participants.tsv": "participant_id\tage\tsex\nsub-01\t30\tF\nsub-02\tn/a\tM\n",
    "participants.json": {"age": {"Units": "year"}},
    "T1w.json": {"RepetitionTime": 2.0, "Obsolete": True},
    "task-rest_bold.json": {"TaskName": "rest"},
    "sub-01/anat/sub-01_T1w.nii.gz": b"nifti",
    "sub-01/anat/sub-01_T1w.json": {"EchoTime": 0.002},
    "sub-02/anat/sub-02_T1w.nii.gz": b"nifti",
}

_FENCE = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _readme() -> str:
    """The README: the checkout's, else the one installed as the description."""
    checkout = Path(__file__).resolve().parents[2]
    project = checkout / "pyproject.toml"
    if project.is_file() and 'name = "brainfilter"' in project.read_text():
        return (checkout / "README.md").read_text(encoding="utf-8")
    meta = importlib.metadata.metadata("brainfilter")
    text = meta.get_payload() or meta.get("Description") or ""
    assert "# brainfilter" in text, "the installed metadata holds no README"
    return text


def _blocks(text: str) -> list[str]:
    return [match.group(1) for match in _FENCE.finditer(text)]


@pytest.fixture
def readme_dataset():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    root = BidsPath("memory://ds", mode="w")
    for rel, content in README_DATASET.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, str):
            path.write_text(content)
        else:
            path.write_text(json.dumps(content))
    yield root
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


def test_the_readme_has_examples():
    blocks = _blocks(_readme())
    assert len(blocks) >= 8
    assert any("await " in block for block in blocks)


def test_the_readme_runs_top_to_bottom(readme_dataset):
    namespace: dict = {"__name__": "readme"}
    for number, block in enumerate(_blocks(_readme()), 1):
        code = compile(
            block, f"<README block {number}>", "exec",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
        if code.co_flags & inspect.CO_COROUTINE:
            asyncio.run(eval(code, namespace))
        else:
            exec(code, namespace)
    # What the writes left, read past the README's own paths.
    ds = readme_dataset
    assert json.loads((ds / "sub-03" / "sub-03_T1w.json").read_text()) == {
        "Level": "new"
    }
    table = ds["participants.tsv"]
    assert table["participant_id"] == ["sub-01", "sub-02", "sub-03"]
    assert "sex" not in table.keys()


def test_the_readme_names_every_refused_member():
    from brainfilter._mode import _MEMBERS

    text = " ".join(_readme().split())
    start = text.index("members that change the filesystem:")
    listed = text[start:text.index("The mode is a brainfilter rule", start)]
    for name in [*_MEMBERS, "rmtree"]:
        assert f"`{name}`" in listed, name
    for handle in ("`path.wrapped`", "`path.fs`", "`path.client`"):
        assert handle in text
