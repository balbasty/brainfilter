"""`path // name`: a BIDS file name put where BIDS says it belongs."""
import os
from pathlib import PurePosixPath

import pytest

from brainfilter.bidspath import (
    AsyncBidsPath,
    BidsNameError,
    BidsPath,
    PureBidsPath,
)
from brainfilter.tests.test_tree import memory_ds  # noqa: F401


@pytest.fixture(params=["pure", "memory"])
def ds(request):
    if request.param == "pure":
        return PureBidsPath("ds")
    return request.getfixturevalue("memory_ds")


def rel(path, ds):
    return str(path)[len(str(ds)) + 1:]


@pytest.mark.parametrize("left, name, expected", [
    ("", "sub-01_ses-1_T1w.nii.gz", "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz"),
    ("", "sub-01_T1w.nii.gz", "sub-01/anat/sub-01_T1w.nii.gz"),
    ("", "func/sub-01_task-rest_events.tsv",
     "sub-01/func/sub-01_task-rest_events.tsv"),
    ("", "func/sub-01_task-rest_bold.nii.gz",
     "sub-01/func/sub-01_task-rest_bold.nii.gz"),
    ("sub-01", "sub-01_ses-1_T1w.nii.gz",
     "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz"),
    ("sub-01/ses-1", "sub-01_ses-1_T1w.nii.gz",
     "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz"),
    ("sub-01/ses-1/anat", "sub-01_ses-1_T1w.nii.gz",
     "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz"),
    ("sub-01/func", "sub-01_task-rest_events.tsv",
     "sub-01/func/sub-01_task-rest_events.tsv"),
    ("sub-01/func", "func/sub-01_task-rest_events.tsv",
     "sub-01/func/sub-01_task-rest_events.tsv"),
    ("", "task-rest_bold.json", "task-rest_bold.json"),
    ("", "participants.tsv", "participants.tsv"),
    ("", "sub-01_sessions.tsv", "sub-01/sub-01_sessions.tsv"),
    ("sub-01", "sub-01_sessions.tsv", "sub-01/sub-01_sessions.tsv"),
    ("", "sub-01_ses-1_scans.tsv", "sub-01/ses-1/sub-01_ses-1_scans.tsv"),
    ("", "sub-01_scans.tsv", "sub-01/sub-01_scans.tsv"),
])
def test_placed(ds, left, name, expected):
    start = ds / left if left else ds
    placed = start // name
    assert rel(placed, ds) == expected
    assert type(placed) is type(ds / expected)
    assert placed.mode == (ds / expected).mode


def test_pathlike_operand():
    ds = PureBidsPath("ds")
    assert ds // PurePosixPath("sub-01_T1w.nii.gz") == ds // "sub-01_T1w.nii.gz"
    assert isinstance(PurePosixPath("x"), os.PathLike)


def test_other_operands_are_not_supported():
    with pytest.raises(TypeError):
        PureBidsPath("ds") // 3


def test_reuses_existing_directories(memory_ds):  # noqa: F811
    left = memory_ds["sub-01"]["ses-1"]["anat"]
    assert str(left // "sub-01_ses-1_T1w.nii.gz") == str(
        memory_ds / "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz"
    )


def test_mode_follows_slash(memory_ds):  # noqa: F811
    writable = memory_ds.with_mode("w")
    assert (writable // "sub-01_T1w.nii.gz").mode == (writable / "x").mode


@pytest.mark.parametrize("left, name, message", [
    ("", "sub-01_events.tsv", "<datatype>/sub-01_events.tsv"),
    ("", "sub-01_physio.tsv.gz", "<datatype>/"),
    ("", "sub-01_channels.tsv", "<datatype>/"),
    ("", "a/b/sub-01_T1w.nii.gz", "path /"),
    ("", "code/sub-01_T1w.nii.gz", "datatype directory"),
    ("", "/sub-01_T1w.nii.gz", "path /"),
    ("", "README", "not the BIDS name of a file"),
    ("", "sub-01", "not the BIDS name of a file"),
    ("", "anat", "not the BIDS name of a file"),
    ("", "ses-1_T1w.nii.gz", "no subject"),
    ("", "anat/task-rest_bold.json", "top of the dataset"),
    ("", "anat/sub-01_task-rest_bold.nii.gz", "belongs in func"),
    ("", "func/sub-01_events.tsv/x", "path /"),
    ("", "anat/sub-01_scans.tsv", "no datatype directory"),
    ("", "sub-01_ses-1_sessions.tsv", "no session entity"),
    ("", "sub-01_foo.nii.gz", "no datatype for the suffix"),
    ("sub-02", "sub-01_T1w.nii.gz", "sub-01"),
    ("sub-01/ses-2", "sub-01_ses-1_T1w.nii.gz", "sub-01/ses-1"),
    ("sub-01/ses-1", "sub-01_T1w.nii.gz", "sub-01/<datatype>"),
    ("sub-01/anat", "sub-01_task-rest_bold.nii.gz", "belongs in func"),
    ("sub-01/func", "anat/sub-01_task-rest_events.tsv", "already in"),
    ("sub-01/anat", "sub-01_sessions.tsv", "sub-01 of the dataset"),
    ("sub-01", "task-rest_bold.json", "the top of the dataset"),
    ("anat", "sub-01_T1w.nii.gz", "inside a subject directory"),
    ("sub-01/anat/sub-01_T1w.nii.gz", "sub-01_T1w.json", "it is a file"),
])
def test_refused(ds, left, name, message):
    start = ds / left if left else ds
    with pytest.raises(BidsNameError, match="cannot place") as info:
        start // name
    assert message in str(info.value)


def test_ambiguous_lists_candidates():
    with pytest.raises(BidsNameError) as info:
        PureBidsPath("ds") // "sub-01_task-rest_events.tsv"
    assert "beh, eeg, emg, func, ieeg, meg, motion, mrs, nirs, pet" in str(
        info.value
    )


def test_sync_path_local(tmp_path):
    ds = BidsPath(str(tmp_path / "ds"))
    assert str(ds // "sub-01_T1w.nii.gz") == str(
        tmp_path / "ds/sub-01/anat/sub-01_T1w.nii.gz"
    )


@pytest.mark.anyio
async def test_async_path(tmp_path):
    ds = AsyncBidsPath(str(tmp_path / "ds"))
    placed = ds // "func/sub-01_task-rest_events.tsv"
    expected = ds / "sub-01/func/sub-01_task-rest_events.tsv"
    assert str(placed) == str(expected)
    assert type(placed) is type(expected)
