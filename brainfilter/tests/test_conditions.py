import re
from pathlib import Path

import pytest

from brainfilter.conditions import (
    And, AndGlob, Glob, Globish, NotACondition, Or, OrGlob, Regex, Regexish,
)


def test_glob_call():
    g = Glob("sub-*/anat/*.nii.gz")
    assert g("sub-01/anat/sub-01_T1w.nii.gz")
    assert g(Path("sub-01/anat/sub-01_T1w.nii.gz"))
    assert not g("sub-01/func/sub-01_bold.nii.gz")


def test_glob_absolute():
    g = Glob("/data/*.json")
    assert g.root == Path("/")
    assert g("/data/x.json")
    assert not g("data/x.json")


def test_glob_truediv():
    g = Glob("sub-*") / "anat" / Glob("*.json")
    assert isinstance(g, Glob)
    assert str(g) == str(Path("sub-*/anat/*.json"))
    g = "/data" / Glob("**/*.json")
    assert isinstance(g, Glob)
    assert str(g) == str(Path("/data/**/*.json"))
    g = Glob("sub-*") / OrGlob("*.json", "*.tsv")
    assert isinstance(g, OrGlob)
    assert g("sub-01/x.tsv") and not g("sub-01/x.nii")


def test_glob_iter(tmp_path):
    for name in ("a.json", "b.json", "c.tsv"):
        (tmp_path / name).touch()
    assert set(tmp_path / Glob("*.json")) == {
        tmp_path / "a.json", tmp_path / "b.json"
    }
    assert set(tmp_path / OrGlob("a.*", "c.*")) == {
        tmp_path / "a.json", tmp_path / "c.tsv"
    }
    both = AndGlob(tmp_path / Glob("*.json"), tmp_path / Glob("a.*"))
    assert set(both) == {tmp_path / "a.json"}


def test_regex():
    r = Regex(r"sub-\d+")
    assert r("data/sub-01/anat")
    assert not r("data/sub-xx/anat")
    assert Regex(re.compile("anat"))("sub-01/anat")


def test_factories():
    g = Glob("*.json")
    assert Globish(g) is g and g.pattern == "*.json"
    assert isinstance(Globish("*.json"), Glob)
    assert isinstance(Globish("*.json", "*.tsv"), OrGlob)
    r = Regex("x")
    assert Regexish(r) is r and r.pattern.pattern == "x"
    assert isinstance(Regexish("x"), Regex)
    assert isinstance(Regexish("x", "y"), And)
    with pytest.raises(ValueError):
        Globish()
    with pytest.raises(ValueError):
        Regexish()


def test_and_or():
    cond = And("sub-*", re.compile(r"\.json$"))
    assert isinstance(cond.cond[0], Glob) and isinstance(cond.cond[1], Regex)
    assert cond("sub-01_T1w.json")
    assert not cond("sub-01_T1w.nii")
    assert not cond("ses-01.json")
    cond = Or("*.json", Regex(r"\.tsv$"))
    assert cond("a.json") and cond("a.tsv") and not cond("a.nii")
    with pytest.raises(NotACondition.Error):
        And(1)
    with pytest.raises(NotACondition.Error):
        Or(1)
