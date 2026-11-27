"""The top-level API, and the user-facing docs that import from it."""
import ast
import importlib
import importlib.metadata
import pkgutil
import re
import subprocess
import sys
from pathlib import Path

import pytest

import brainfilter

PUBLIC = [
    "AsyncBidsPath",
    "AsyncTransaction",
    "BidsEntities",
    "BidsNameError",
    "BidsPath",
    "BidsFilter",
    "Glob",
    "Missing",
    "Not",
    "Present",
    "PureBidsPath",
    "ReadOnlyError",
    "Regex",
    "Table",
    "Transaction",
    "TransactionError",
    "Version",
    "__version__",
]


def test_all_lists_the_public_api():
    assert sorted(brainfilter.__all__) == sorted(PUBLIC)


@pytest.mark.parametrize("name", PUBLIC)
def test_each_name_imports_from_the_top(name):
    namespace = {}
    exec(f"from brainfilter import {name}", namespace)
    assert namespace[name] is getattr(brainfilter, name)


def test_top_level_names_are_the_submodules_own():
    from brainfilter import bidspath, conditions, filter, transaction, versioning

    assert brainfilter.BidsPath is bidspath.BidsPath
    assert brainfilter.Glob is conditions.Glob
    assert brainfilter.BidsFilter is filter.BidsFilter
    assert brainfilter.Transaction is transaction.Transaction
    assert brainfilter.Version is versioning.Version
    assert isinstance(brainfilter.__version__, str)


def test_specialised_classes_stay_in_their_submodule():
    from brainfilter.bidspath import BidsJSONFile, BidsParticipantsFile  # noqa: F401

    for name in ("BidsJSONFile", "BidsParticipantsFile", "TreeMixin", "Edit",
                 "AsyncEdit", "DATATYPES"):
        assert name not in brainfilter.__all__
        assert not hasattr(brainfilter, name)


def test_no_optional_dependency_at_import():
    # bagof-paths may load a backend it finds; brainfilter adds none
    code = (
        "import sys, bagof.paths; before = set(sys.modules); "
        "import brainfilter; "
        "print(sorted(m for m in set(sys.modules) - before "
        "if m.split('.')[0] in ('pandas', 'upath', 'fsspec', 'anyio')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "[]"


# -- user-facing docs import from the top ------------------------------------------

SUBMODULE_IMPORT = re.compile(r"\bfrom\s+brainfilter\.|\bimport\s+brainfilter\.")
CROSS_REFERENCE = re.compile(r"\]\[(brainfilter\.[\w.]+)\]")


def _readme():
    source = Path(brainfilter.__file__).parent.parent / "README.md"
    if source.is_file():
        return source.read_text(encoding="utf-8")
    # an installed package: the README is its long description
    return importlib.metadata.metadata("brainfilter").get_payload()


def _docstrings():
    """`(where, docstring)` of every module, class and function of the package."""
    found = []
    for info in pkgutil.walk_packages(brainfilter.__path__, "brainfilter."):
        if info.name.startswith("brainfilter.tests"):
            continue
        module = importlib.import_module(info.name)
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                if doc:
                    found.append((f"{info.name}:{getattr(node, 'name', '')}", doc))
    module = brainfilter
    found.append(("brainfilter", module.__doc__ or ""))
    return found


def test_readme_imports_from_the_top():
    readme = _readme()
    assert "from brainfilter import" in readme
    assert SUBMODULE_IMPORT.findall(readme) == []


def test_docstrings_import_from_the_top():
    docstrings = _docstrings()
    assert len(docstrings) > 100
    bad = [where for where, doc in docstrings if SUBMODULE_IMPORT.search(doc)]
    assert bad == []


def test_cross_references_name_top_level_names():
    targets = {
        target for _, doc in [*_docstrings(), ("README", _readme())]
        for target in CROSS_REFERENCE.findall(doc)
    }
    assert targets
    assert {t for t in targets if t.split(".", 1)[1] not in PUBLIC} == set()


def test_the_check_catches_a_submodule_import():
    assert SUBMODULE_IMPORT.search("from brainfilter.bidspath import BidsPath")
    assert SUBMODULE_IMPORT.search("import brainfilter.filter")
    assert not SUBMODULE_IMPORT.search("from brainfilter import BidsPath")
