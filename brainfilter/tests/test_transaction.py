"""Write transactions and single-file edits, on a local and a memory:// tree."""
import json
from collections import ChainMap

import pytest
from bagof.paths import CommitError

from brainfilter.bidspath import BidsPath, Table
from brainfilter.tests.test_tree import FILES, T1W, _populate
from brainfilter.transaction import Transaction, TransactionError

PARTICIPANTS = "participant_id\tage\tsex\nsub-01\t30\tF\nsub-02\tn/a\tM\n"


@pytest.fixture
def local_ds(tmp_path):
    return _populate(BidsPath(str(tmp_path / "ds")))


@pytest.fixture
def memory_ds():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    yield _populate(BidsPath("memory://ds"))
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(params=["local", "memory"])
def ds(request):
    return request.getfixturevalue(f"{request.param}_ds")


def on_disk(path):
    """The stored content of a JSON file, read past any transaction."""
    return json.loads(path.read_text())


def staging_leftovers(ds):
    if not ds.is_local():
        return []
    return [p for p in ds.rglob(".*") if "staging" in p.name or ".old-" in p.name]


# -- JSON edits ------------------------------------------------------------------

def test_set_and_delete_keys(ds):
    sidecar = ds["T1w.json"]
    with ds.transaction() as tx:
        sidecar["RepetitionTime"] = 2.3
        del sidecar["RootOnly"]
        sidecar.update(EchoTime=0.03)
        assert on_disk(sidecar) == FILES["T1w.json"]   # nothing written yet
    assert tx.written == [sidecar]
    assert on_disk(sidecar) == {
        "Level": "root", "MagneticFieldStrength": 3,
        "RepetitionTime": 2.3, "EchoTime": 0.03,
    }
    assert staging_leftovers(ds) == []


def test_replace_content(ds):
    with ds.transaction():
        ds["T1w.json"].write({"Only": "this"})
        assert dict(ds["T1w.json"]) == {"Only": "this"}
    assert on_disk(ds / "T1w.json") == {"Only": "this"}


def test_write_copies_and_checks_content(ds):
    content = {"A": [1]}
    with ds.transaction():
        ds["T1w.json"].write(content)
        content["A"].append(2)          # the caller's object is not held
        with pytest.raises(TypeError):
            ds["T1w.json"].write({"bad": object()})
    assert on_disk(ds / "T1w.json") == {"A": [1]}


def test_content_is_edited_in_place(ds):
    with ds.transaction():
        content = ds["participants.json"].read()
        content["age"]["Units"] = "years"   # a nested value
    assert on_disk(ds / "participants.json") == {"age": {"Units": "years"}}


def test_missing_key(ds):
    with ds.transaction():
        with pytest.raises(KeyError):
            del ds["T1w.json"]["Nope"]
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


# -- TSV edits -------------------------------------------------------------------

def test_rows_and_columns(ds):
    table = ds["participants.tsv"]
    with ds.transaction():
        rows = table.read()
        assert isinstance(rows, Table)
        rows.append({"participant_id": "sub-03", "age": 41})
        rows[0]["sex"] = "M"
        del rows[1]
        rows.add_column("handedness", ["R", None])
        rows.drop_column("age")
        assert table.read() is rows
        assert list(table) == rows
    assert table.read_text() == (
        "participant_id\tsex\thandedness\n"
        "sub-01\tM\tR\n"
        "sub-03\tn/a\tn/a\n"
    )


def test_replace_table(ds):
    with ds.transaction():
        ds["participants.tsv"].write(
            [{"participant_id": "sub-09", "age": None}], columns=["age"]
        )
    assert ds["participants.tsv"].read_text() == (
        "age\tparticipant_id\nn/a\tsub-09\n"
    )


def test_table_is_not_a_mapping(ds):
    with ds.transaction():
        with pytest.raises(TypeError, match="read()"):
            ds["participants.tsv"]["age"] = []
        with pytest.raises(TypeError, match="read()"):
            del ds["participants.tsv"]["age"]


# -- new files -------------------------------------------------------------------

def test_new_files(ds):
    with ds.transaction() as tx:
        ds["sub-03_sessions.tsv"] = [{"session_id": "ses-1"}]
        anat = ds / "sub-03" / "anat"
        (anat / "sub-03_T1w.json").write({"Level": "new"})
        # listed, and reachable through the tree, before they are written
        assert "sub-03" in ds and "sub-03_sessions.tsv" in ds
        assert ds["sub-03"].keys() == ["anat"]
        assert ds["sub-03"]["anat"]["sub-03_T1w.json"]["Level"] == "new"
        assert not (anat / "sub-03_T1w.json").exists()
    assert [p.name for p in tx.written] == [
        "sub-03_sessions.tsv", "sub-03_T1w.json",
    ]
    assert on_disk(anat / "sub-03_T1w.json") == {"Level": "new"}
    assert ds["sub-03_sessions.tsv"].read() == [{"session_id": "ses-1"}]


def test_key_set_on_a_missing_file_creates_it(ds):
    with ds.transaction():
        (ds / "sub-01" / "sub-01_bold.json")["TaskName"] = "rest"
    assert on_disk(ds / "sub-01" / "sub-01_bold.json") == {"TaskName": "rest"}


def test_new_dataset(tmp_path):
    ds = BidsPath(str(tmp_path / "new"))
    with ds.transaction():
        ds["dataset_description.json"] = {"Name": "new", "BIDSVersion": "1.10.0"}
        ds["T1w.json"] = {"Level": "root"}
        data = ds / "sub-01" / "anat" / "sub-01_T1w.nii.gz"
        assert data.metadata == ChainMap({"Level": "root"})
    assert on_disk(ds / "dataset_description.json")["Name"] == "new"


def test_read_of_a_missing_file_raises(ds):
    with ds.transaction() as tx:
        with pytest.raises(FileNotFoundError):
            (ds / "nope.json").read()
        assert "nope.json" not in ds
    assert tx.written == []


def test_only_json_and_tsv_can_be_written(ds):
    with ds.transaction():
        with pytest.raises(TypeError, match="only JSON and TSV"):
            ds["README"] = "text"
        with pytest.raises(TypeError, match="does not delete"):
            del ds["T1w.json"]


# -- rollback --------------------------------------------------------------------

def test_exception_writes_nothing(ds):
    with pytest.raises(RuntimeError, match="boom"):
        with ds.transaction() as tx:
            ds["T1w.json"]["RepetitionTime"] = 2.3
            ds["participants.tsv"].read().append({"participant_id": "sub-03"})
            ds["new.json"] = {"x": 1}
            raise RuntimeError("boom")
    assert tx.written == []
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS
    assert "new.json" not in ds and not (ds / "new.json").exists()
    assert staging_leftovers(ds) == []


def test_unwritable_content_writes_nothing(ds):
    with pytest.raises(TypeError, match="serializable"):
        with ds.transaction():
            ds["T1w.json"]["RepetitionTime"] = 2.3      # fine
            ds["dwi.json"]["Bad"] = object()            # cannot be written
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


def test_unchanged_files_are_not_written(ds):
    with ds.transaction() as tx:
        ds["T1w.json"].read()
        ds["T1w.json"]["Level"] = "root"                 # the same value
        list(ds["participants.tsv"])
        (ds / T1W).metadata
        assert tx.changed == []
    assert tx.written == []


# -- read your writes --------------------------------------------------------------

def test_reads_see_the_edits(ds):
    with ds.transaction():
        ds["T1w.json"]["RepetitionTime"] = 2.3
        del ds["T1w.json"]["RootOnly"]
        sidecar = ds["T1w.json"]
        assert sidecar["RepetitionTime"] == 2.3
        assert "RootOnly" not in sidecar and sidecar.get("RootOnly") is None
        assert "RepetitionTime" in sidecar.keys()
        assert sidecar.read() == {**sidecar}
        ds["participants.tsv"].read().append({"participant_id": "sub-03"})
        assert len(ds["participants.tsv"].read()) == 3


def test_metadata_sees_the_edits(ds):
    data = ds / T1W
    with ds.transaction():
        ds["T1w.json"]["RepetitionTime"] = 2.3
        del ds["T1w.json"]["RootOnly"]
        # a new sidecar, nearer than every existing one
        (data.parent / "sub-01_ses-1_acq-mp_run-1_T1w.json").write({"Run": 1})
        run = data.with_entities(run="1", keep_existing=True)
        meta = run.metadata
        assert meta["Run"] == 1
        assert meta["RepetitionTime"] == 2.3
        assert "RootOnly" not in meta
        assert data.metadata["Level"] == "datatype"
        # a write through the ChainMap edits the nearest sidecar
        data.metadata["Level"] = "edited"
        assert ds["sub-01"]["ses-1"]["anat"][
            "sub-01_ses-1_acq-mp_T1w.json"]["Level"] == "edited"
    assert on_disk(data.parent / "sub-01_ses-1_acq-mp_T1w.json") == {
        "Level": "edited"
    }
    assert data.with_entities(run="1", keep_existing=True).metadata["Run"] == 1


# -- nothing hidden ----------------------------------------------------------------

def test_read_only_outside_a_transaction(ds):
    sidecar = ds["T1w.json"]
    for edit in (
        lambda: sidecar.__setitem__("Level", "x"),
        lambda: sidecar.__delitem__("Level"),
        lambda: sidecar.update(Level="x"),
        lambda: sidecar.write({}),
        lambda: ds["participants.tsv"].write([]),
        lambda: ds.__setitem__("new.json", {}),
    ):
        with pytest.raises(TypeError, match="read-only outside a transaction"):
            edit()
    content = sidecar.read()
    content["Level"] = "x"                  # a plain dict: goes nowhere
    assert on_disk(sidecar) == FILES["T1w.json"]


def test_content_read_in_a_transaction_is_dead_after_it(ds):
    with ds.transaction():
        content = ds["T1w.json"].read()
    content["Level"] = "late"
    with ds.transaction() as tx:
        assert ds["T1w.json"]["Level"] == "root"
    assert tx.written == []
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


def test_tracking_module_is_gone():
    with pytest.raises(ImportError):
        import brainfilter.tracking  # noqa: F401


# -- transaction scope -------------------------------------------------------------

def test_transactions_do_not_nest(ds):
    with ds.transaction():
        with pytest.raises(RuntimeError, match="already open"):
            ds["sub-01"].transaction().__enter__()
    with ds["sub-01"].transaction():
        with pytest.raises(RuntimeError, match="already open"):
            ds.transaction().__enter__()
        with ds["sub-02"].transaction():          # disjoint: fine
            ds["sub-02"]["sub-02_T1w.json"] = {"A": 1}
        with pytest.raises(TypeError, match="read-only"):
            ds["T1w.json"]["Level"] = "x"         # not covered
    tx = ds.transaction()
    with tx:
        pass
    with pytest.raises(RuntimeError, match="once"):
        tx.__enter__()


def test_transaction_type(ds):
    tx = ds.transaction()
    assert isinstance(tx, Transaction) and tx.root == ds
    assert repr(tx) == f"Transaction({str(ds)!r})"


# -- partial commit ----------------------------------------------------------------

EDITED = ["T1w.json", "participants.tsv", "dwi.json"]


def _edit_three(ds):
    ds["T1w.json"]["Edited"] = 1
    ds["participants.tsv"].read().append({"participant_id": "sub-03"})
    ds["dwi.json"]["Edited"] = 1


@pytest.mark.parametrize("n", [1, 2, 3])
def test_partial_failure_report(ds, fail_nth, n):
    calls = fail_nth(n)
    with pytest.raises(TransactionError) as info:
        with ds.transaction() as tx:
            _edit_three(ds)
    error = info.value
    assert isinstance(error, OSError) and error.errno == 13
    assert error.root == ds
    assert [p.name for p in error.written] == EDITED[:n - 1]
    assert error.failed == ds / EDITED[n - 1]
    assert [p.name for p in error.not_written] == EDITED[n - 1:]
    assert tx.written == error.written
    # the store's refusal, as bagof-paths reports it
    assert isinstance(error.error, CommitError)
    assert error.__cause__ is error.error
    assert error.error.target == ds / EDITED[n - 1]
    assert isinstance(error.error.__cause__, PermissionError)
    assert EDITED[n - 1] in str(error) and "not written" in str(error)
    # the commit stopped: the files after the failure were not attempted
    assert len(calls) == n
    for name in EDITED[:n - 1]:
        assert "Edited" in (ds / name).read_text() or "sub-03" in (
            ds / name).read_text()
    assert on_disk(ds / "T1w.json").get("Edited") == (1 if n > 1 else None)
    assert ("sub-03" in ds["participants.tsv"].read_text()) == (n > 2)
    assert on_disk(ds / "dwi.json") == FILES["dwi.json"]
    assert staging_leftovers(ds) == []


def test_failure_on_a_new_directory(ds, fail_nth):
    fail_nth(2)
    with pytest.raises(TransactionError) as info:
        with ds.transaction():
            ds["T1w.json"]["Edited"] = 1
            (ds / "sub-09" / "sub-09_T1w.json").write({"A": 1})
    assert info.value.failed == ds / "sub-09" / "sub-09_T1w.json"
    assert on_disk(ds / "T1w.json")["Edited"] == 1
    assert not (ds / "sub-09" / "sub-09_T1w.json").exists()


# -- single-file edits -------------------------------------------------------------

def test_edit_json(ds):
    sidecar = ds["T1w.json"]
    with sidecar.edit() as content:
        assert content == FILES["T1w.json"]
        content["RepetitionTime"] = 2.3
        assert sidecar["RepetitionTime"] == 2.3        # reads see it
        assert on_disk(sidecar) == FILES["T1w.json"]
    assert on_disk(sidecar)["RepetitionTime"] == 2.3
    with pytest.raises(TypeError, match="read-only"):
        sidecar["Level"] = "x"                          # the edit is over


def test_edit_tsv_and_new_file(ds):
    with ds["participants.tsv"].edit() as rows:
        rows.add_column("group", ["a", "b"])
    assert ds["participants.tsv"].read()[1]["group"] == "b"
    new = ds / "sub-01" / "sub-01_scans.tsv"
    with new.edit() as rows:
        assert rows == [] and isinstance(rows, Table)
        rows.append({"filename": "anat/x.nii.gz"})
    assert new.read() == [{"filename": "anat/x.nii.gz"}]


def test_edit_discards_on_exception(ds):
    with pytest.raises(ValueError):
        with ds["T1w.json"].edit() as content:
            content["Level"] = "x"
            raise ValueError
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    with pytest.raises(ValueError):
        with (ds / "brand-new.json").edit():
            raise ValueError
    assert not (ds / "brand-new.json").exists()


def test_edit_raises_the_commit_error(ds, fail_nth):
    fail_nth(1)
    with pytest.raises(CommitError) as info:
        with ds["T1w.json"].edit() as content:
            content["Level"] = "x"
    assert info.value.target == ds / "T1w.json"
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


def test_edit_joins_a_transaction(ds):
    with ds.transaction() as tx:
        with ds["T1w.json"].edit() as content:
            content["Level"] = "x"
        assert on_disk(ds / "T1w.json") == FILES["T1w.json"]   # deferred
        assert ds["T1w.json"]["Level"] == "x"
    assert tx.written == [ds / "T1w.json"]
    assert on_disk(ds / "T1w.json")["Level"] == "x"


# -- Table -------------------------------------------------------------------------

def test_table():
    table = Table([{"a": "1"}], columns=["a", "b"])
    assert table.columns == ["a", "b"]
    table.append({"c": 3})
    assert table.columns == ["a", "b", "c"]
    with pytest.raises(ValueError, match="already"):
        table.add_column("a")
    with pytest.raises(ValueError, match="2 rows"):
        table.add_column("d", [1])
    with pytest.raises(KeyError):
        table.drop_column("z")
    table.drop_column("b")
    assert table.columns == ["a", "c"]
    copy = Table(table)
    assert copy == table and copy.columns == table.columns
    assert copy[0] is not table[0]
    assert repr(Table([], ["x"])) == "Table([], columns=['x'])"


# -- a transaction only while it is open -------------------------------------------

def test_write_after_the_transaction_closed_raises(ds):
    import contextvars

    with ds.transaction():
        # what a thread or a task started inside the block runs in
        inside = contextvars.copy_context()
    late = ds / "T1w.json"
    with pytest.raises(RuntimeError, match="already closed.*would be lost"):
        inside.run(late.__setitem__, "Late", 1)
    with pytest.raises(RuntimeError, match="already closed"):
        inside.run(late.write, {"Late": 1})
    with pytest.raises(RuntimeError, match="already closed"):
        inside.run(late.edit().__enter__)
    # a read sees the files, and a new transaction can be opened there
    assert inside.run(late.read) == FILES["T1w.json"]

    def again():
        with ds.transaction():
            late["Again"] = 1

    inside.run(again)
    assert on_disk(late) == {**FILES["T1w.json"], "Again": 1}


def test_write_during_the_commit_raises(ds, monkeypatch):
    import contextvars

    from brainfilter import transaction as T

    real = T._write_file
    seen = []

    def write_file(path, data):
        try:
            inside.run(ds["dwi.json"].__setitem__, "Late", 1)
        except RuntimeError as error:
            seen.append(str(error))
        real(path, data)

    monkeypatch.setattr(T, "_write_file", write_file)
    with ds.transaction():
        ds["T1w.json"]["Edited"] = 1
        inside = contextvars.copy_context()
    assert len(seen) == 1 and "being committed" in seen[0]
    assert on_disk(ds / "dwi.json") == FILES["dwi.json"]


# -- one entry per file -----------------------------------------------------------

def test_two_names_for_one_file_share_an_entry(ds):
    other = ds / "sub-01" / ".." / "T1w.json"
    with ds.transaction() as tx:
        other["A"] = 1
        ds["T1w.json"]["B"] = 2
        assert ds["T1w.json"]["A"] == 1 and other["B"] == 2
        assert ds["T1w.json"].read() is other.read()
        assert tx.changed == [ds / "T1w.json"]
    assert tx.written == [ds / "T1w.json"]
    assert on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "A": 1, "B": 2}


def test_dot_dot_new_file_is_listed_and_written_once(ds):
    with ds.transaction() as tx:
        (ds / "sub-01" / ".." / "new.json")["A"] = 1
        assert "new.json" in ds and ds["new.json"]["A"] == 1
    assert tx.written == [ds / "new.json"]
    assert on_disk(ds / "new.json") == {"A": 1}
    assert "new.json" in [p.name for p in ds.iterdir()]
    assert "new.json" not in ds["sub-01"].keys()


def test_a_symlink_and_its_target_share_an_entry(local_ds):
    import os

    link = local_ds / "link.json"
    os.symlink(os.fspath(local_ds / "T1w.json"), os.fspath(link))
    with local_ds.transaction() as tx:
        link["A"] = 1
        local_ds["T1w.json"]["B"] = 2
    assert len(tx.written) == 1
    assert on_disk(local_ds / "T1w.json") == {**FILES["T1w.json"], "A": 1, "B": 2}
    assert on_disk(link) == on_disk(local_ds / "T1w.json")


def test_dot_dot_out_of_the_root_is_not_covered(ds):
    with ds["sub-01"].transaction():
        with pytest.raises(TypeError, match="read-only"):
            (ds / "sub-01" / ".." / "T1w.json")["Level"] = "x"
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


# -- a joined edit that fails ------------------------------------------------------

def test_failed_edit_in_a_transaction_is_undone(ds):
    with ds.transaction() as tx:
        ds["T1w.json"]["Before"] = 1
        held = ds["T1w.json"].read()
        try:
            with ds["T1w.json"].edit() as content:
                content["Partial"] = 1
                del content["Level"]
                raise ValueError
        except ValueError:
            pass
        assert ds["T1w.json"].read() is held        # the same object, put back
        assert "Partial" not in held and held["Level"] == "root"
        rows = ds["participants.tsv"].read()
        try:
            with ds["participants.tsv"].edit() as table:
                table[0]["sex"] = "M"
                table.append({"participant_id": "sub-09"})
                table.add_column("extra")
                raise ValueError
        except ValueError:
            pass
        assert ds["participants.tsv"].read() is rows
        try:
            with (ds / "new.json").edit() as content:
                content["Partial"] = 1
                raise ValueError
        except ValueError:
            pass
        assert "new.json" not in ds
    assert tx.written == [ds / "T1w.json"]
    assert on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "Before": 1}
    assert ds["participants.tsv"].read_text() == PARTICIPANTS
    assert not (ds / "new.json").exists()


# -- an interrupted commit ---------------------------------------------------------

def test_interrupted_commit_reports_and_propagates(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T._write_file
    calls = []

    def write_file(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise KeyboardInterrupt
        real(path, data)

    monkeypatch.setattr(T, "_write_file", write_file)
    with pytest.raises(KeyboardInterrupt) as info:
        with ds.transaction() as tx:
            _edit_three(ds)
    notes = getattr(info.value, "__notes__", [])
    assert len(notes) == 1
    assert "interrupted writing" in notes[0]
    assert f"written: {str(ds / 'T1w.json')!r}" in notes[0]
    assert f"not written: {str(ds / 'participants.tsv')!r}" in notes[0]
    assert tx.written == [ds / "T1w.json"]
    assert on_disk(ds / "T1w.json")["Edited"] == 1
    assert on_disk(ds / "dwi.json") == FILES["dwi.json"]


# -- a new file only when it is given content --------------------------------------

def test_new_file_is_created_only_when_set(ds):
    new = ds / "new.json"
    with new.edit():
        pass
    assert not new.exists()
    with ds.transaction() as tx:
        with new.edit():
            pass
        with pytest.raises(KeyError):
            del new["k"]
        assert "new.json" not in ds and ds.get("new.json") is None
        with pytest.raises(FileNotFoundError):
            new.read()
        new["k"] = 1
        del new["k"]                 # set, then emptied: still nothing
        assert tx.changed == []
    assert tx.written == [] and not new.exists()
    table = ds / "sub-01" / "sub-01_scans.tsv"
    with table.edit():
        pass
    assert not table.exists()
    with ds.transaction():
        new.write({})                # replaced: written, even empty
        table.write([])
    assert on_disk(new) == {} and table.exists()


# -- metadata with no sidecar ------------------------------------------------------

def test_metadata_without_a_sidecar_refuses_writes(ds):
    data = ds / "sub-02" / "anat" / "sub-02_T2w.nii.gz"
    with ds.transaction() as tx:
        meta = data.metadata
        assert meta == ChainMap() and dict(meta) == {}
        with pytest.raises(TypeError, match="no JSON sidecar.*sub-02_T2w.json"):
            meta["EchoTime"] = 0.03
        with pytest.raises(TypeError, match="no JSON sidecar"):
            meta.update(EchoTime=0.03)
        with pytest.raises(TypeError, match="no BIDS suffix"):
            (ds / "sub-01_ses-1.nii").metadata["x"] = 1
    assert tx.written == []
