"""Writes and transactions, on a local and a memory:// tree."""
import json
from collections import ChainMap

import pytest
from bagof.paths import CommitError

from brainfilter import BidsPath, ReadOnlyError, Table, Transaction, TransactionError
from brainfilter.tests.test_tree import FILES, T1W, _populate

PARTICIPANTS = "participant_id\tage\tsex\nsub-01\t30\tF\nsub-02\tn/a\tM\n"


@pytest.fixture
def local_ds(tmp_path):
    return _populate(BidsPath(str(tmp_path / "ds"), mode="w"))


@pytest.fixture
def memory_ds():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    yield _populate(BidsPath("memory://ds", mode="w"))
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


# -- with path: --------------------------------------------------------------------

def test_with_path_gives_the_path(ds):
    with ds as entered:
        assert entered is ds
        ds["T1w.json"]["RepetitionTime"] = 2.3
        assert on_disk(ds / "T1w.json") == FILES["T1w.json"]   # kept
    assert on_disk(ds / "T1w.json")["RepetitionTime"] == 2.3


def test_transaction_gives_the_transaction(ds):
    with ds.transaction() as tx:
        assert isinstance(tx, Transaction) and tx.root == ds
        ds["T1w.json"]["RepetitionTime"] = 2.3
        assert tx.changed == [ds / "T1w.json"]
    assert tx.written == [ds / "T1w.json"]
    assert repr(tx) == f"Transaction({str(ds)!r})"


def test_with_path_discards_on_exception(ds):
    with pytest.raises(RuntimeError, match="boom"):
        with ds:
            ds["T1w.json"]["RepetitionTime"] = 2.3
            raise RuntimeError("boom")
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


def test_with_path_does_not_nest(ds):
    with ds:
        with pytest.raises(RuntimeError, match="already open"):
            with ds:
                pass
        with pytest.raises(RuntimeError, match="already open"):
            with ds["sub-01"]:
                pass
        ds["T1w.json"]["A"] = 1
    assert on_disk(ds / "T1w.json")["A"] == 1


def test_exit_without_enter(ds):
    with pytest.raises(RuntimeError, match="no transaction"):
        ds.__exit__(None, None, None)


def test_writes_through_any_path_object_are_kept(ds):
    by_string = BidsPath(str(ds / "T1w.json"), mode="w")
    if not ds.is_local():
        by_string = BidsPath("memory://ds/T1w.json", mode="w")
    read_only = by_string.with_mode("r")
    with ds as tx_root:
        by_string["Other"] = 1                     # not derived from ds
        assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
        assert tx_root["T1w.json"]["Other"] == 1
        assert read_only["Other"] == 1             # reads see it, any path
        with pytest.raises(ReadOnlyError):
            read_only["Other"] = 2                 # but cannot write
    assert on_disk(ds / "T1w.json")["Other"] == 1


# -- JSON writes in a transaction --------------------------------------------------

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
    with ds:
        ds["T1w.json"].write({"Only": "this"})
        assert dict(ds["T1w.json"]) == {"Only": "this"}
    assert on_disk(ds / "T1w.json") == {"Only": "this"}


def test_write_copies_and_checks_content(ds):
    content = {"A": [1]}
    with ds:
        ds["T1w.json"].write(content)
        content["A"].append(2)          # the caller's object is not held
        with pytest.raises(TypeError, match="serializable"):
            ds["T1w.json"].write({"bad": object()})
        value = {"B": [1]}
        ds["T1w.json"]["V"] = value
        value["B"].append(2)            # nor is a value set
    assert on_disk(ds / "T1w.json") == {"A": [1], "V": {"B": [1]}}


def test_as_dict_in_a_transaction_is_a_copy(ds):
    with ds:
        content = ds["participants.json"].as_dict()
        content["age"]["Units"] = "years"            # not an edit
        assert ds["participants.json"].as_dict() == FILES["participants.json"]
        ds["participants.json"]["New"] = 1
        held = ds["participants.json"].as_dict()
        held["New"] = 2
        assert ds["participants.json"]["New"] == 1
    assert on_disk(ds / "participants.json") == {**FILES["participants.json"],
                                                 "New": 1}


def test_missing_key(ds):
    with ds:
        with pytest.raises(KeyError):
            del ds["T1w.json"]["Nope"]
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


# -- TSV writes in a transaction ---------------------------------------------------

def test_columns(ds):
    table = ds["participants.tsv"]
    with ds:
        table["handedness"] = ["R", None]            # a new, last column
        table["sex"] = ["M", "M"]                    # a column replaced
        del table["age"]
        assert table.keys() == ["participant_id", "sex", "handedness"]
        assert table["handedness"] == ["R", None]
        assert table.read_text() == PARTICIPANTS     # nothing written yet
        with pytest.raises(ValueError, match="one value per row"):
            table["x"] = [1]
        with pytest.raises(KeyError):
            del table["nope"]
    assert table.read_text() == (
        "participant_id\tsex\thandedness\n"
        "sub-01\tM\tR\n"
        "sub-02\tM\tn/a\n"
    )


def test_rows_in_a_transaction_are_copies(ds):
    table = ds["participants.tsv"]
    with ds:
        rows = table.as_list()
        rows[0]["sex"] = "M"                          # not an edit
        rows.append({"participant_id": "sub-03"})
        next(table.rows())["sex"] = "M"
        table.as_dict()["sex"][0] = "M"
        assert table["sex"] == ["F", "M"]
        table.write([*rows])                          # written back
        assert table["sex"] == ["M", "M", None]
        assert len(table.as_list()) == 3
    assert table.read_text() == (
        "participant_id\tage\tsex\n"
        "sub-01\t30\tM\n"
        "sub-02\tn/a\tM\n"
        "sub-03\tn/a\tn/a\n"
    )


def test_dataframe_in_a_transaction(ds):
    pytest.importorskip("pandas")
    table = ds["participants.tsv"]
    with ds:
        table["sex"] = ["M", "M"]
        frame = table.as_dataframe()
        assert frame["sex"].tolist() == ["M", "M"]
        assert frame["age"].isna().tolist() == [False, True]
        frame.loc[0, "sex"] = "F"                     # a copy
        assert table["sex"] == ["M", "M"]


def test_replace_table(ds):
    with ds:
        ds["participants.tsv"].write(
            [{"participant_id": "sub-09", "age": None}], columns=["age"]
        )
    assert ds["participants.tsv"].read_text() == (
        "age\tparticipant_id\nn/a\tsub-09\n"
    )


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
    assert ds["sub-03_sessions.tsv"].as_list() == [{"session_id": "ses-1"}]


def test_key_set_on_a_missing_file_creates_it(ds):
    with ds:
        (ds / "sub-01" / "sub-01_bold.json")["TaskName"] = "rest"
    assert on_disk(ds / "sub-01" / "sub-01_bold.json") == {"TaskName": "rest"}


def test_first_column_of_a_new_table_sets_the_rows(ds):
    table = ds / "sub-01" / "sub-01_scans.tsv"
    with ds:
        table["filename"] = ["anat/a.nii.gz", "anat/b.nii.gz"]
        table["acq_time"] = [None, None]
    assert table.read_text() == (
        "filename\tacq_time\nanat/a.nii.gz\tn/a\nanat/b.nii.gz\tn/a\n"
    )


def test_new_dataset(tmp_path):
    ds = BidsPath(str(tmp_path / "new"), mode="w")
    with ds:
        ds["dataset_description.json"] = {"Name": "new", "BIDSVersion": "1.10.0"}
        ds["T1w.json"] = {"Level": "root"}
        data = ds / "sub-01" / "anat" / "sub-01_T1w.nii.gz"
        assert data.sidecar == ChainMap({"Level": "root"})
    assert on_disk(ds / "dataset_description.json")["Name"] == "new"


def test_read_of_a_missing_file_raises(ds):
    with ds.transaction() as tx:
        with pytest.raises(FileNotFoundError):
            (ds / "nope.json").as_dict()
        with pytest.raises(FileNotFoundError):
            (ds / "nope.tsv").as_list()
        assert "nope.json" not in ds
    assert tx.written == []


def test_only_json_and_tsv_can_be_written(ds):
    with pytest.raises(TypeError, match="only JSON and TSV"):
        ds["README"] = "text"
    with pytest.raises(TypeError, match="does not delete"):
        del ds["T1w.json"]
    with ds:
        with pytest.raises(TypeError, match="only JSON and TSV"):
            ds["README"] = "text"


# -- rollback --------------------------------------------------------------------

def test_exception_writes_nothing(ds):
    with pytest.raises(RuntimeError, match="boom"):
        with ds.transaction() as tx:
            ds["T1w.json"]["RepetitionTime"] = 2.3
            ds["participants.tsv"]["extra"] = [1, 2]
            ds["new.json"] = {"x": 1}
            raise RuntimeError("boom")
    assert tx.written == []
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS
    assert "new.json" not in ds and not (ds / "new.json").exists()
    assert staging_leftovers(ds) == []


def test_unwritable_content_writes_nothing(ds):
    with pytest.raises(ValueError, match="tab or a line break"):
        with ds:
            ds["T1w.json"]["RepetitionTime"] = 2.3              # fine
            ds["participants.tsv"]["note"] = ["a\tb", "c"]      # cannot be
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS


def test_unchanged_files_are_not_written(ds):
    with ds.transaction() as tx:
        ds["T1w.json"].as_dict()
        ds["T1w.json"]["Level"] = "root"                 # the same value
        ds["participants.tsv"].as_list()
        ds["participants.tsv"]["sex"] = ["F", "M"]       # the same values
        (ds / T1W).sidecar
        assert tx.changed == []
    assert tx.written == []


def test_a_write_to_a_list_that_raises_puts_it_back(ds):
    listed = ds / "list.json"
    listed.write_text("[1, 2]")
    with ds.transaction() as tx:
        with pytest.raises(TypeError, match="JSON object"):
            listed["a"] = 1
        entry = tx._buffer.get(listed)
        assert entry.content == [1, 2]
        entry.content.append(3)                 # as a failed write could
        restore = entry.snapshot()
        entry.content.append(4)
        restore()
        assert entry.content == [1, 2, 3]
        assert tx.changed == [listed]
        entry.content[:] = [1, 2]
    assert tx.written == []


def test_a_new_file_that_cannot_be_written_is_listed(ds):
    with pytest.raises(ValueError, match="tab or a line break"):
        with ds:
            (ds / "new.tsv")["x"] = ["a\tb"]
            assert "new.tsv" in ds              # it will be written, or fail
    assert not (ds / "new.tsv").exists()


def test_a_transaction_covers_one_store(local_ds):
    pytest.importorskip("upath")
    tx = local_ds.transaction()
    assert tx.covers(local_ds / "T1w.json")
    assert not tx.covers(BidsPath("memory://ds/T1w.json"))
    assert not tx.covers(local_ds.parent / "elsewhere.json")


def test_a_write_that_raises_leaves_the_content(ds):
    """A write that fails partway inside a transaction is undone."""
    with ds.transaction() as tx:
        ds["T1w.json"]["Before"] = 1
        with pytest.raises(ValueError):
            # the first pair is applied, the second is not a pair
            ds["T1w.json"].update([("Partial", 1), ("x",)])
        assert "Partial" not in ds["T1w.json"]
        table = ds["participants.tsv"]
        with pytest.raises(ValueError, match="one value per row"):
            table["extra"] = [1, 2, 3]
        assert table.keys() == ["participant_id", "age", "sex"]
        with pytest.raises(KeyError):
            del (ds / "new.json")["k"]
        assert "new.json" not in ds
    assert tx.written == [ds / "T1w.json"]
    assert on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "Before": 1}
    assert ds["participants.tsv"].read_text() == PARTICIPANTS
    assert not (ds / "new.json").exists()


def test_snapshot_puts_content_back_in_place(ds):
    from brainfilter import transaction as T

    with ds.transaction() as tx:
        ds["T1w.json"]["A"] = 1
        ds["participants.tsv"]["sex"] = ["M", "M"]
        entries = [tx._buffer.get(ds / name)
                   for name in ("T1w.json", "participants.tsv")]
        held = [entry.content for entry in entries]
        restores = [entry.snapshot() for entry in entries]
        ds["T1w.json"]["B"] = 2
        ds["participants.tsv"]["sex"] = ["F", "F"]
        del ds["participants.tsv"]["age"]
        for restore in restores:
            restore()
        assert [entry.content for entry in entries] == held    # same objects
        assert all(a is b for a, b in zip(
            [entry.content for entry in entries], held))
        assert "B" not in ds["T1w.json"]
        assert ds["participants.tsv"]["sex"] == ["M", "M"]
        assert "age" in ds["participants.tsv"]
        assert isinstance(T._Buffer().get(ds), type(None))


# -- read your writes --------------------------------------------------------------

def test_reads_see_the_edits(ds):
    with ds:
        ds["T1w.json"]["RepetitionTime"] = 2.3
        del ds["T1w.json"]["RootOnly"]
        sidecar = ds["T1w.json"]
        assert sidecar["RepetitionTime"] == 2.3
        assert "RootOnly" not in sidecar and sidecar.get("RootOnly") is None
        assert "RepetitionTime" in sidecar.keys()
        assert sidecar.as_dict() == {**sidecar}
        ds["participants.tsv"].write(
            [*ds["participants.tsv"].as_list(), {"participant_id": "sub-03"}]
        )
        assert len(ds["participants.tsv"].as_list()) == 3
        assert ds["participants.tsv"].as_list(raw=True)[2]["age"] == "n/a"


def test_sidecar_sees_the_edits(ds):
    data = ds / T1W
    with ds:
        ds["T1w.json"]["RepetitionTime"] = 2.3
        del ds["T1w.json"]["RootOnly"]
        # a new sidecar, nearer than every existing one
        (data.parent / "sub-01_ses-1_acq-mp_run-1_T1w.json").write({"Run": 1})
        run = data.with_entities(run="1", keep_existing=True)
        meta = run.sidecar
        assert meta["Run"] == 1
        assert meta["RepetitionTime"] == 2.3
        assert "RootOnly" not in meta
        assert data.sidecar["Level"] == "datatype"
        # a write through the ChainMap edits the nearest sidecar
        data.sidecar["Level"] = "edited"
        assert ds["sub-01"]["ses-1"]["anat"][
            "sub-01_ses-1_acq-mp_T1w.json"]["Level"] == "edited"
    assert on_disk(data.parent / "sub-01_ses-1_acq-mp_T1w.json") == {
        "Level": "edited"
    }
    assert data.with_entities(run="1", keep_existing=True).sidecar["Run"] == 1


def test_sidecar_as_dict_in_a_transaction_is_a_copy(ds):
    data = ds / T1W
    with ds:
        data.sidecar["EchoTime"] = 0.03
        flat = data.sidecar.as_dict()
        assert flat["EchoTime"] == 0.03 and flat["Level"] == "datatype"
        flat["EchoTime"] = 1.0
        data.sidecar.maps[0]["EchoTime"] = 1.0      # a map is a copy too
        assert data.sidecar["EchoTime"] == 0.03
    assert on_disk(data.sidecars[0])["EchoTime"] == 0.03


# -- writes at once -----------------------------------------------------------------

def test_json_writes_at_once(ds):
    sidecar = ds["T1w.json"]
    sidecar["RepetitionTime"] = 2.3
    assert on_disk(sidecar)["RepetitionTime"] == 2.3
    del sidecar["RootOnly"]
    assert "RootOnly" not in on_disk(sidecar)
    sidecar.update({"EchoTime": 0.03}, Flip=9)
    assert on_disk(sidecar) == {
        "Level": "root", "MagneticFieldStrength": 3,
        "RepetitionTime": 2.3, "EchoTime": 0.03, "Flip": 9,
    }
    ds["new.json"] = {"New": 1}
    assert on_disk(ds / "new.json") == {"New": 1}
    sidecar.write({"Only": 1})
    assert on_disk(sidecar) == {"Only": 1}
    assert staging_leftovers(ds) == []


def test_tsv_writes_at_once(ds):
    table = ds["participants.tsv"]
    table["handedness"] = ["R", "L"]
    assert table.read_text() == (
        "participant_id\tage\tsex\thandedness\n"
        "sub-01\t30\tF\tR\n"
        "sub-02\tn/a\tM\tL\n"
    )
    del table["handedness"]
    assert table.read_text() == PARTICIPANTS
    table.write([*table.as_list(), {"participant_id": "sub-03", "age": 41}])
    assert table.read_text() == PARTICIPANTS + "sub-03\t41\tn/a\n"
    with pytest.raises(ValueError, match="one value per row"):
        table["x"] = [1]
    assert staging_leftovers(ds) == []


def test_each_write_is_one_atomic_replace(ds, monkeypatch):
    from brainfilter import transaction as T

    writes = []
    real = T.write_file

    def write_file(path, data):
        writes.append(path)
        return real(path, data)

    monkeypatch.setattr(T, "write_file", write_file)
    ds["T1w.json"].update(A=1, B=2)
    ds["participants.tsv"]["x"] = [1, 2]
    (ds / T1W).sidecar.update(C=3, D=4)
    assert writes == [ds / "T1w.json", ds / "participants.tsv",
                      ds / "sub-01/ses-1/anat/sub-01_ses-1_acq-mp_T1w.json"]


def test_nested_change_is_not_saved(ds):
    content = ds["participants.json"]["age"]
    content["Units"] = "years"
    assert on_disk(ds / "participants.json") == FILES["participants.json"]
    ds["participants.json"].as_dict()["age"]["Units"] = "years"
    assert on_disk(ds / "participants.json") == FILES["participants.json"]
    rows = ds["participants.tsv"].as_list()
    rows[0]["age"] = 99
    assert ds["participants.tsv"].read_text() == PARTICIPANTS


def test_sidecar_writes_go_to_the_nearest(ds):
    data = ds / T1W
    nearest = data.sidecars[0]
    meta = data.sidecar
    meta["EchoTime"] = 0.03
    assert on_disk(nearest) == {"Level": "datatype", "EchoTime": 0.03}
    assert meta["EchoTime"] == 0.03 and meta.maps[0]["EchoTime"] == 0.03
    del meta["Level"]
    assert on_disk(nearest) == {"EchoTime": 0.03}
    assert meta["Level"] == "session"         # the next sidecar shows through
    meta.update(A=1)
    meta |= {"B": 2}
    assert meta.pop("A") == 1 and meta.pop("A", None) is None
    with pytest.raises(KeyError):
        meta.pop("A")
    assert meta.setdefault("C", 3) == 3 and meta.setdefault("C", 4) == 3
    assert meta.popitem() == ("C", 3)
    assert on_disk(nearest) == {"EchoTime": 0.03, "B": 2}
    meta.clear()
    assert on_disk(nearest) == {} and meta.maps[0] == {}
    with pytest.raises(KeyError):
        meta.popitem()
    assert meta["Level"] == "session"


def test_sidecar_views(ds):
    data = ds / T1W
    meta = data.sidecar
    parents = meta.parents
    assert type(parents) is type(meta)
    assert parents.sidecars == data.sidecars[1:]
    parents["P"] = 1                          # the next sidecar
    assert on_disk(data.sidecars[1])["P"] == 1
    detached = meta.copy()
    assert type(detached) is ChainMap and dict(detached) == dict(meta)
    detached["Level"] = "x"
    assert on_disk(data.sidecars[0])["Level"] == "datatype"
    child = meta.new_child({"Child": 1}, More=2)
    assert type(child) is ChainMap and child["Child"] == 1 and child["More"] == 2
    assert meta.new_child(Kw=1)["Kw"] == 1
    assert dict(meta | {"Level": "or"})["Level"] == "or"


def test_failed_write_raises_and_changes_nothing(ds, fail_nth):
    fail_nth(1)
    with pytest.raises(CommitError) as info:
        ds["T1w.json"]["Level"] = "x"
    assert info.value.target == ds / "T1w.json"
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert staging_leftovers(ds) == []


def test_bad_content_writes_nothing(ds):
    with pytest.raises(TypeError, match="serializable"):
        ds["T1w.json"]["Bad"] = object()
    with pytest.raises(ValueError, match="tab or a line break"):
        ds["participants.tsv"]["note"] = ["a\tb", "c"]
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS


def test_new_file_is_created_only_when_set(ds):
    new = ds / "new.json"
    with pytest.raises(KeyError):
        del new["k"]                 # nothing to delete: nothing written
    assert not new.exists()
    with ds.transaction() as tx:
        with pytest.raises(KeyError):
            del new["k"]
        assert "new.json" not in ds and ds.get("new.json") is None
        with pytest.raises(FileNotFoundError):
            new.as_dict()
        new["k"] = 1
        del new["k"]                 # set, then emptied: still nothing
        assert tx.changed == []
    assert tx.written == [] and not new.exists()
    table = ds / "sub-01" / "sub-01_scans.tsv"
    with pytest.raises(KeyError):
        del table["filename"]
    assert not table.exists()
    with ds:
        new.write({})                # replaced: written, even empty
        table.write([])
    assert on_disk(new) == {} and table.exists()


# -- read-only paths ---------------------------------------------------------------

def test_read_only_refuses_every_write(ds):
    ro = ds.with_mode("r")
    sidecar = ro["T1w.json"]
    table = ro["participants.tsv"]
    assert sidecar.mode == table.mode == "r"
    for write in (
        lambda: sidecar.__setitem__("Level", "x"),
        lambda: sidecar.__delitem__("Level"),
        lambda: sidecar.update(Level="x"),
        lambda: sidecar.write({}),
        lambda: table.__setitem__("age", [1, 2]),
        lambda: table.__delitem__("age"),
        lambda: table.write([]),
        lambda: ro.__setitem__("new.json", {}),
        lambda: (ro / T1W).sidecar.__setitem__("Level", "x"),
        lambda: (ro / T1W).sidecar.update(Level="x"),
        lambda: ro.transaction(),
        lambda: ro.__enter__(),
    ):
        with pytest.raises(ReadOnlyError, match=r"read-only.*with_mode\('w'\)"):
            write()
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS
    assert not (ds / "new.json").exists()
    with pytest.raises(ReadOnlyError, match="open a transaction"):
        with ro:
            pass


def test_read_only_error_is_a_permission_error(ds):
    with pytest.raises(PermissionError):
        ds.with_mode("r")["T1w.json"]["Level"] = "x"


# -- nothing hidden ----------------------------------------------------------------

def test_tracking_module_is_gone():
    with pytest.raises(ImportError):
        import brainfilter.tracking  # noqa: F401


def test_edit_is_gone(ds):
    import brainfilter.transaction as T

    assert not hasattr(ds["T1w.json"], "edit")
    assert not hasattr(T, "Edit") and not hasattr(T, "AsyncEdit")


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
        ds["T1w.json"]["Level"] = "x"             # not covered: written now
        assert on_disk(ds / "T1w.json")["Level"] == "x"
    tx = ds.transaction()
    with tx:
        pass
    with pytest.raises(RuntimeError, match="once"):
        tx.__enter__()


# -- partial commit ----------------------------------------------------------------

EDITED = ["T1w.json", "participants.tsv", "dwi.json"]


def _edit_three(ds):
    ds["T1w.json"]["Edited"] = 1
    ds["participants.tsv"]["Edited"] = [1, 1]
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
        assert "Edited" in (ds / name).read_text()
    assert on_disk(ds / "T1w.json").get("Edited") == (1 if n > 1 else None)
    assert ("Edited" in ds["participants.tsv"].read_text()) == (n > 2)
    assert on_disk(ds / "dwi.json") == FILES["dwi.json"]
    assert staging_leftovers(ds) == []


def test_failure_on_a_new_directory(ds, fail_nth):
    fail_nth(2)
    with pytest.raises(TransactionError) as info:
        with ds:
            ds["T1w.json"]["Edited"] = 1
            (ds / "sub-09" / "sub-09_T1w.json").write({"A": 1})
    assert info.value.failed == ds / "sub-09" / "sub-09_T1w.json"
    assert on_disk(ds / "T1w.json")["Edited"] == 1
    assert not (ds / "sub-09" / "sub-09_T1w.json").exists()


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
    table.add_column("d", ["x", "y"])
    table.add_column("e")
    assert table.columns == ["a", "c", "d", "e"]
    assert [row["d"] for row in table] == ["x", "y"]
    assert [row["e"] for row in table] == [None, None]
    copy = Table(table)
    assert copy == table and copy.columns == table.columns
    assert copy[0] is not table[0]
    assert repr(Table([], ["x"])) == "Table([], columns=['x'])"


def test_write_a_table_keeps_its_column_order(ds):
    ds["participants.tsv"].write(
        Table([{"participant_id": "sub-01"}], columns=["sex", "participant_id"])
    )
    assert ds["participants.tsv"].read_text() == (
        "sex\tparticipant_id\nn/a\tsub-01\n"
    )


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
        inside.run((ds / "participants.tsv").__setitem__, "x", [1, 2])
    # a read sees the files, and a new transaction can be opened there
    assert inside.run(late.as_dict) == FILES["T1w.json"]

    def again():
        with ds:
            late["Again"] = 1

    inside.run(again)
    assert on_disk(late) == {**FILES["T1w.json"], "Again": 1}


def test_write_during_the_commit_raises(ds, monkeypatch):
    import contextvars

    from brainfilter import transaction as T

    real = T.write_file
    seen = []

    def write_file(path, data):
        try:
            inside.run(ds["dwi.json"].__setitem__, "Late", 1)
        except RuntimeError as error:
            seen.append(str(error))
        real(path, data)

    monkeypatch.setattr(T, "write_file", write_file)
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
        assert ds["T1w.json"].as_dict() == other.as_dict()
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


def test_dot_dot_write_at_once_goes_to_the_clean_name(ds):
    (ds / "sub-01" / ".." / "new.json")["A"] = 1
    assert on_disk(ds / "new.json") == {"A": 1}
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
    with ds["sub-01"].transaction() as tx:
        (ds / "sub-01" / ".." / "T1w.json")["Level"] = "x"   # written now
        assert on_disk(ds / "T1w.json")["Level"] == "x"
    assert tx.written == []


# -- an interrupted commit ---------------------------------------------------------

def test_interrupted_commit_reports_and_propagates(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T.write_file
    calls = []

    def write_file(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise KeyboardInterrupt
        real(path, data)

    monkeypatch.setattr(T, "write_file", write_file)
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


# -- a sidecar that is not there ---------------------------------------------------

def test_sidecar_without_a_sidecar_refuses_writes(ds):
    data = ds / "sub-02" / "anat" / "sub-02_T2w.nii.gz"
    with ds.transaction() as tx:
        meta = data.sidecar
        assert meta == ChainMap() and dict(meta) == {} and meta.sidecars == ()
        with pytest.raises(TypeError, match="no JSON sidecar.*sub-02_T2w.json"):
            meta["EchoTime"] = 0.03
        with pytest.raises(TypeError, match="no JSON sidecar"):
            meta.update(EchoTime=0.03)
        with pytest.raises(TypeError, match="no BIDS suffix"):
            (ds / "sub-01_ses-1.nii").sidecar["x"] = 1
        with pytest.raises(TypeError, match="no JSON sidecar"):
            (ds / "T2w.json").sidecar["x"] = 1
    assert tx.written == []
    with pytest.raises(TypeError, match="no JSON sidecar"):
        data.sidecar["EchoTime"] = 0.03


def test_farther_sidecars_name_what_is_missing(ds):
    meta = (ds / T1W).sidecar
    farthest = meta
    for _ in meta.sidecars:
        farthest = farthest.parents
    assert farthest.sidecars == () and dict(farthest) == {}
    for write in (
        lambda: farthest.__setitem__("x", 1),
        lambda: farthest.__delitem__("x"),
        lambda: farthest.update(x=1),
        lambda: farthest.clear(),
    ):
        with pytest.raises(TypeError, match="no farther sidecar") as info:
            write()
        assert "no JSON sidecar applies" not in str(info.value)


# -- concurrent writes through ----------------------------------------------------

@pytest.fixture
def slow_writes(monkeypatch):
    """Widen the gap between reading a file and replacing it.

    Without a lock per file, every concurrent write then reads the file
    before any of them replaces it, and all but one change are lost.
    """
    import time

    from brainfilter import transaction as T

    real = T.write_file

    def write_file(path, data):
        time.sleep(0.005)
        real(path, data)

    monkeypatch.setattr(T, "write_file", write_file)


def test_threaded_writes_to_one_file_all_survive(ds, slow_writes):
    from concurrent.futures import ThreadPoolExecutor

    from brainfilter import transaction as T

    sidecar = ds / "T1w.json"
    other = ds / "sub-01" / ".." / "T1w.json"   # another name, one file
    with ThreadPoolExecutor(max_workers=8) as pool:
        done = [
            pool.submit((sidecar if i % 2 else other).__setitem__, f"K{i}", i)
            for i in range(16)
        ]
        for future in done:
            future.result()
    content = on_disk(sidecar)
    assert {f"K{i}": i for i in range(16)}.items() <= content.items()
    assert T._LOCKS == {}                       # nothing kept once done


def test_threaded_tsv_columns_all_survive(ds, slow_writes):
    from concurrent.futures import ThreadPoolExecutor

    table = ds / "participants.tsv"
    with ThreadPoolExecutor(max_workers=6) as pool:
        done = [
            pool.submit(table.__setitem__, f"c{i}", [i, i + 1]) for i in range(6)
        ]
        for future in done:
            future.result()
    keys = table.keys()                         # in the order they landed
    assert keys[:3] == ["participant_id", "age", "sex"]
    assert sorted(keys[3:]) == [f"c{i}" for i in range(6)]
    assert table.as_dict()["c3"] == [3, 4]


def test_a_failed_write_lets_go_of_its_lock(ds):
    from brainfilter import transaction as T

    with pytest.raises(ValueError, match="one value per row"):
        ds["participants.tsv"]["x"] = [1]
    assert T._LOCKS == {}
    ds["participants.tsv"]["x"] = [1, 2]        # not held by the failure
    assert ds["participants.tsv"]["x"] == [1, 2]


# -- a transaction is not joined from another thread --------------------------------

def test_a_thread_cannot_write_past_a_transaction(ds):
    from concurrent.futures import ThreadPoolExecutor

    def write(path, key):
        path[key] = 1

    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="boom"):
            with ds:
                ds["T1w.json"]["Inside"] = 1
                for path in (ds / "T1w.json", ds / "dwi.json",
                             ds / "sub-01" / "sub-01_new.json"):
                    future = pool.submit(write, path, "Thread")
                    with pytest.raises(RuntimeError) as info:
                        future.result()
                    message = str(info.value)
                    assert "another thread or task" in message
                    assert str(path) in message and str(ds) in message
                future = pool.submit(
                    (ds / "participants.tsv").__setitem__, "x", [1, 2]
                )
                with pytest.raises(RuntimeError, match="another thread"):
                    future.result()
                # nor does a transaction open there on the same files
                future = pool.submit(lambda: ds["sub-01"].__enter__())
                with pytest.raises(RuntimeError, match="already open in "
                                   "another thread or task"):
                    future.result()
                raise RuntimeError("boom")
        # nothing the thread tried was written, and nothing of the block
        assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
        assert on_disk(ds / "dwi.json") == FILES["dwi.json"]
        assert not (ds / "sub-01" / "sub-01_new.json").exists()
        assert "x" not in ds["participants.tsv"].keys()
        # once the block has ended, the thread writes through again
        pool.submit(write, ds / "dwi.json", "After").result()
    assert on_disk(ds / "dwi.json")["After"] == 1


def test_a_thread_writes_outside_the_transaction_root(ds):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        with ds["sub-01"].transaction() as tx:
            ds["sub-01"]["sub-01_T1w.json"]["Inside"] = 1
            # a file the block does not cover, and a disjoint transaction
            pool.submit(ds["T1w.json"].__setitem__, "Thread", 1).result()

            def disjoint():
                with ds["sub-02"]:
                    ds["sub-02"]["sub-02_T1w.json"] = {"Thread": 1}

            pool.submit(disjoint).result()
            assert on_disk(ds / "T1w.json")["Thread"] == 1
    assert tx.written == [ds / "sub-01" / "sub-01_T1w.json"]
    assert on_disk(ds / "sub-02" / "sub-02_T1w.json") == {"Thread": 1}


def test_a_write_during_the_commit_from_the_block_raises(ds, monkeypatch):
    from brainfilter import transaction as T

    real = T.write_file
    seen = []

    def write_file(path, data):
        # the context that opened the block, while it commits
        try:
            ds["dwi.json"]["Late"] = 1
        except RuntimeError as error:
            seen.append(str(error))
        real(path, data)

    monkeypatch.setattr(T, "write_file", write_file)
    with ds:
        ds["T1w.json"]["Edited"] = 1
    assert len(seen) == 1 and "being committed" in seen[0]
    assert on_disk(ds / "dwi.json") == FILES["dwi.json"]
    assert T._REGISTRY == []


# -- column values ------------------------------------------------------------------

@pytest.mark.parametrize("values", ["RL", b"RL", bytearray(b"RL"),
                                    {"a": 1, "b": 2}])
def test_a_column_is_not_split_from_a_string_or_mapping(ds, values):
    table = ds["participants.tsv"]
    with pytest.raises(TypeError, match="one value per row") as info:
        table["s"] = values
    assert type(values).__name__ in str(info.value)
    assert table.read_text() == PARTICIPANTS
    with ds:
        with pytest.raises(TypeError, match="one value per row"):
            table["s"] = values
    assert table.read_text() == PARTICIPANTS
    table["s"] = ("R", "L")                     # any other iterable is fine
    assert table["s"] == ["R", "L"]


# -- a table with a header and no row -------------------------------------------------

@pytest.mark.parametrize("in_transaction", [False, True])
def test_a_header_only_table_takes_its_first_column(ds, in_transaction):
    scans = ds / "sub-01" / "sub-01_scans.tsv"
    scans.write_text("filename\tacq_time\n")
    table = ds["sub-01"]["sub-01_scans.tsv"]
    assert table.as_list() == [] and table.keys() == ["filename", "acq_time"]

    def edit():
        table["filename"] = ["anat/a.nii", "anat/b.nii"]
        table["note"] = ["x", None]

    if in_transaction:
        with ds:
            edit()
    else:
        edit()
    assert scans.read_text() == (
        "filename\tacq_time\tnote\nanat/a.nii\tn/a\tx\nanat/b.nii\tn/a\tn/a\n"
    )
    with pytest.raises(ValueError, match="one value per row"):
        table["more"] = [1]


def test_a_header_only_table_takes_a_new_column(ds):
    scans = ds / "sub-01" / "sub-01_scans.tsv"
    scans.write_text("filename\n")
    ds["sub-01"]["sub-01_scans.tsv"]["extra"] = [1]
    assert scans.read_text() == "filename\textra\nn/a\t1\n"


# -- nested edits inside a block ----------------------------------------------------

def test_nested_json_edits_in_a_block_are_saved(ds):
    sidecar = ds / "T1w.json"
    sidecar.update(Extra={"Coils": [{"Name": "head"}]}, Notes=[])
    with sidecar:                                   # a block on the file itself
        sidecar["Extra"]["Coils"][0]["Name"] = "neck"   # dict in list in dict
        sidecar["Notes"].append("checked")
        sidecar.get("Extra")["Coils"].append({"Name": "spine"})
        # the same file, through a path built from a string
        BidsPath(str(sidecar), mode="w")["Notes"].append("twice")
        assert sidecar["Extra"]["Coils"][0]["Name"] == "neck"
        assert sidecar.as_dict()["Notes"] == ["checked", "twice"]
        assert on_disk(sidecar)["Notes"] == []      # kept until the end
    assert on_disk(sidecar) == {
        **FILES["T1w.json"],
        "Extra": {"Coils": [{"Name": "neck"}, {"Name": "spine"}]},
        "Notes": ["checked", "twice"],
    }


def test_nested_tsv_edits_in_a_block_keep_the_other_cells(ds):
    ds["participants.json"]["tags"] = {"Delimiter": ","}
    table = ds / "participants.tsv"
    table.write_text(
        "participant_id\tage\ttags\nsub-01\t30\ta,b\nsub-02\t007\tc\n"
    )
    with ds.transaction() as tx:
        table["age"][0] = 31
        table["tags"][0].append("x")                # a list a cell holds
        table.get("tags")[1][0] = "d"
        assert table["age"] == [31, 7.0]
        assert table.as_dict()["tags"] == [["a", "b", "x"], ["d"]]
    assert tx.written == [table]
    assert table.read_text() == (
        "participant_id\tage\ttags\nsub-01\t31\ta,b,x\nsub-02\t007\td\n"
    )


def test_live_values_read_but_unchanged_are_not_written(ds):
    ds["T1w.json"]["Extra"] = {"Coil": "head"}
    with ds.transaction() as tx:
        extra = ds["T1w.json"]["Extra"]
        ages = ds["participants.tsv"]["age"]
        assert extra == {"Coil": "head"} and ages == [30.0, None]
        extra["Coil"] = "neck"
        extra["Coil"] = "head"                      # put back
        ages[1] = None
    assert tx.written == []


def test_a_value_assigned_in_a_block_is_copied(ds):
    value = {"Coils": ["head"]}
    with ds:
        ds["T1w.json"]["Extra"] = value
        value["Coils"].append("caller's")
        ds["dwi.json"]["Extra"] = ds["T1w.json"]["Extra"]
        ds["dwi.json"]["Extra"]["Coils"].append("dwi")
        ages = [1, 2]
        ds["participants.tsv"]["age"] = ages
        ages[0] = 99
        cell = ["a"]
        ds["participants.tsv"]["sex"][0] = cell
        cell.append("b")
        assert ds["T1w.json"]["Extra"] == {"Coils": ["head"]}
        assert ds["participants.tsv"]["sex"] == [["a"], "M"]
        ds["participants.tsv"]["sex"][0] = "F"     # sex has no Delimiter
    assert ds["participants.tsv"]["age"] == [1, 2]
    assert on_disk(ds / "T1w.json")["Extra"] == {"Coils": ["head"]}
    assert on_disk(ds / "dwi.json")["Extra"] == {"Coils": ["head", "dwi"]}


def test_other_reads_in_a_block_are_copies(ds):
    ds["participants.json"]["tags"] = {"Delimiter": ","}
    table = ds / "participants.tsv"
    table.write_text("participant_id\ttags\nsub-01\ta\n")
    with ds.transaction() as tx:
        ds["participants.json"].as_dict()["age"]["Units"] = "x"
        for read in (table.as_list(), list(table.rows()),
                     table.as_list(raw=True)):
            read[0]["participant_id"] = "x"
        for read in (table.as_dict(), table.columns(), dict(table.items())):
            read["tags"][0].append("x")
        table.values()[0][0] = "x"
        table.sidecar["tags"]["Delimiter"] = ";"    # the merged view
        list(ds["participants.json"].values())[0]["Units"] = "x"
        assert tx.changed == []
    assert tx.written == []


def test_a_read_only_path_reads_copies_in_a_block(ds):
    with ds:
        BidsPath(str(ds / "participants.json"))["age"]["Units"] = "x"
        assert ds["participants.json"]["age"]["Units"] == "year"
        column = BidsPath(str(ds / "participants.tsv"))["sex"]
        assert type(column) is list
        column[0] = "M"
        assert ds["participants.tsv"]["sex"] == ["F", "M"]
    assert on_disk(ds / "participants.json") == FILES["participants.json"]


def test_an_exception_discards_the_nested_edits(ds):
    with pytest.raises(ValueError, match="boom"):
        with ds:
            ds["participants.json"]["age"]["Units"] = "years"
            ds["participants.tsv"]["age"][0] = 31
            raise ValueError("boom")
    assert on_disk(ds / "participants.json") == FILES["participants.json"]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS


def test_a_write_that_raises_keeps_the_live_values(ds):
    ds["participants.json"]["tags"] = {"Delimiter": ","}
    (ds / "participants.tsv").write_text("participant_id\ttags\nsub-01\ta\n")
    with ds:
        age = ds["participants.json"]["age"]
        with pytest.raises(KeyError):
            del ds["participants.json"]["Nope"]
        age["Units"] = "years"                      # still the file's own
        cell = ds["participants.tsv"]["tags"][0]
        with pytest.raises(ValueError, match="one value per row"):
            ds["participants.tsv"]["extra"] = [1, 2]
        cell.append("b")
    assert on_disk(ds / "participants.json")["age"] == {"Units": "years"}
    assert ds["participants.tsv"]["tags"] == [["a", "b"]]


def test_a_live_column(ds):
    import copy
    import pickle
    from concurrent.futures import ThreadPoolExecutor

    from brainfilter._tree import LiveColumn

    table = ds / "participants.tsv"
    with ds:
        sex = table["sex"]
        assert isinstance(sex, LiveColumn) and isinstance(sex, list)
        assert table["sex"] is sex                  # one per column
        assert sex == ["F", "M"] and sex != ["F"] and sex != "FM"
        assert repr(sex) == "['F', 'M']" and len(sex) == 2
        assert list(sex) == ["F", "M"] and sex[-1] == "M" and sex[:1] == ["F"]
        assert json.dumps(sex) == '["F", "M"]'
        for plain in (sex + ["x"], sex * 2, sex.copy(), sex[:], sorted(sex),
                      copy.copy(sex), copy.deepcopy(sex),
                      pickle.loads(pickle.dumps(sex))):
            assert type(plain) is list
        assert sex + ["x"] == ["F", "M", "x"] and sex * 2 == ["F", "M"] * 2
        sex[:] = ["M", "F"]
        assert table.as_dict()["sex"] == ["M", "F"]
        sex.reverse()
        assert table.as_dict()["sex"] == ["F", "M"]
        sex.sort(reverse=True)
        assert sex == ["M", "F"] and table.as_dict()["sex"] == ["M", "F"]
        with pytest.raises(TypeError):
            sex.sort(key=lambda value: {})          # put back as it was
        assert sex == ["M", "F"] and table.as_dict()["sex"] == ["M", "F"]
        sex[::-1] = ["M", "F"]
        assert sex == ["F", "M"]

        def iadd():
            column = sex
            column += ["F"]

        def imul():
            column = sex
            column *= 2

        def setslice():
            sex[:] = ["M"]

        for change in (lambda: sex.append("F"), lambda: sex.extend(["F"]),
                       lambda: sex.insert(0, "F"), lambda: sex.pop(),
                       lambda: sex.remove("F"), lambda: sex.clear(),
                       lambda: sex.__delitem__(0), iadd, imul, setslice):
            with pytest.raises(TypeError, match="one value per row"):
                change()
        assert sex == ["F", "M"] and table.as_dict()["sex"] == ["F", "M"]
        with pytest.raises(IndexError):
            sex[2] = "F"
        with pytest.raises(KeyError):
            table["nope"]
        assert table.get("nope", "default") == "default"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(sex.__setitem__, 0, "x")
            with pytest.raises(RuntimeError, match="another thread"):
                future.result()
            assert pool.submit(lambda: sex[0]).result() == "F"   # a read
        assert sex == ["F", "M"]
    for use in (lambda: sex[0], lambda: list(sex), lambda: len(sex),
                lambda: repr(sex), lambda: sex == ["F", "M"],
                lambda: sex + [1], lambda: sex.copy(), lambda: sorted(sex)):
        with pytest.raises(RuntimeError, match="has already closed"):
            use()
    with pytest.raises(RuntimeError, match="has already closed"):
        sex[0] = "x"
    assert table.read_text() == PARTICIPANTS


def test_a_live_column_follows_the_table(ds):
    table = ds / "participants.tsv"
    with ds:
        sex = table["sex"]
        table["sex"] = ["M", "M"]                   # set through the file
        assert sex == ["M", "M"]
        with pytest.raises(ValueError, match="one value per row"):
            table["sex"] = ["F"]                    # raises: put back
        assert sex == ["M", "M"]
        del table["sex"]                            # dropped: KeyError
        for use in (lambda: sex[0], lambda: len(sex), lambda: list(sex)):
            with pytest.raises(KeyError):
                use()
        with pytest.raises(KeyError):
            sex[0] = "F"
        table["sex"] = ["F", "F"]                   # back: the file's column
        assert sex == ["F", "F"]
        sex[1] = "M"
        table.write([{"participant_id": "sub-09", "sex": "F"}])
        assert sex == ["F"]                         # the table was replaced
        sex[0] = "M"
        assert table.as_list() == [{"participant_id": "sub-09", "sex": "M"}]
        table.write([{"participant_id": "sub-09"}])
        with pytest.raises(KeyError):
            sex[0]
    assert table.read_text() == "participant_id\nsub-09\n"


def test_a_live_column_assigned_into_json_is_a_copy(ds):
    with ds:
        ages = ds["participants.tsv"]["age"]
        ds["T1w.json"]["Ages"] = ages
        ds["participants.tsv"]["sex"][0] = ages     # a cell takes a copy
        ages[0] = 99
        assert ds["T1w.json"]["Ages"] == [30.0, None]
        assert type(ds["T1w.json"]["Ages"]) is list
        ds["participants.tsv"]["sex"][0] = "F"
    assert on_disk(ds / "T1w.json")["Ages"] == [30.0, None]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS.replace(
        "30", "99"
    )


def test_a_live_column_after_a_block_that_raised(ds):
    with pytest.raises(ValueError, match="boom"):
        with ds:
            ages = ds["participants.tsv"]["age"]
            ages[0] = 99
            raise ValueError("boom")
    with pytest.raises(RuntimeError, match="has already closed"):
        list(ages)
    with pytest.raises(RuntimeError, match="has already closed"):
        ages[0]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS


def test_a_live_column_is_as_fast_as_a_list(ds):
    import time

    rows = 20000
    table = ds / "participants.tsv"
    table.write([{"participant_id": f"sub-{i:05d}", "age": i}
                 for i in range(rows)])
    with ds:
        ages = table["age"]
        start = time.perf_counter()
        for i in range(rows):
            ages[i] = ages[i] + 1
        elapsed = time.perf_counter() - start
    # one value read and set per row: about 20ms; a scan of the table for
    # each (as before) took minutes
    assert elapsed < 2.0
    assert table["age"][-1] == rows


def test_reads_outside_a_block_stay_copies(ds):
    ds["participants.json"]["age"]["Units"] = "years"
    column = ds["participants.tsv"]["sex"]
    assert type(column) is list
    column[0] = "M"
    assert on_disk(ds / "participants.json") == FILES["participants.json"]
    assert ds["participants.tsv"].read_text() == PARTICIPANTS


# -- raw writes inside a block ------------------------------------------------------

def _raw_writes(path, other):
    """Each raw write of `path`, a JSON or TSV file; `other` is another file."""
    return {
        "write_text": lambda: path.write_text("{}"),
        "write_bytes": lambda: path.write_bytes(b"{}"),
        "open-w": lambda: path.open("w"),
        "open-a": lambda: path.open("a"),
        "open-r+": lambda: path.open("r+"),
        "touch": lambda: path.touch(),
        "unlink": lambda: path.unlink(),
        "rename-source": lambda: path.rename(other),
        "rename-target": lambda: other.rename(path),
        "rename-target-string": lambda: other.rename(str(path)),
        "replace-source": lambda: path.replace(other),
        "replace-target": lambda: other.replace(path),
        "move-source": lambda: path.move(other),
        "move-target": lambda: other.move(path),
        "move_into": lambda: (other.parent / path.name).move_into(path.parent),
        "copy-target": lambda: other.copy(path),
        "copy_into": lambda: (other.parent / path.name).copy_into(path.parent),
        "copytree": lambda: other.copytree(path),
        "link_to": lambda: other.link_to(path),
        "symlink_to": lambda: path.symlink_to(other),
        "hardlink_to": lambda: path.hardlink_to(other),
        "chmod": lambda: path.chmod(0o600),
        "lchmod": lambda: path.lchmod(0o600),
        "staged": lambda: path.staged(),
        "upload_from": lambda: path.upload_from(str(other)),
        "download_to": lambda: other.download_to(path),
    }


@pytest.mark.parametrize("member", list(_raw_writes(None, None)))
@pytest.mark.parametrize("held", [True, False])
def test_a_raw_write_to_a_file_the_block_covers_is_refused(ds, member, held):
    target = ds / "T1w.json"
    outside = BidsPath(str(ds.parent), mode="w") / "outside"
    other = outside / "elsewhere" / "other.json"
    with ds.transaction() as tx:
        if held:
            target["Inside"] = 1
        with pytest.raises(RuntimeError) as info:
            _raw_writes(target, other)[member]()
        message = str(info.value)
        assert repr(str(target)) in message and repr(str(ds)) in message
        assert "after the block ends" in message
    assert on_disk(target) == ({**FILES["T1w.json"], "Inside": 1} if held
                               else FILES["T1w.json"])
    assert tx.written == ([target] if held else [])


@pytest.mark.parametrize("member", ["rmdir", "rmtree", "rename", "move",
                                    "staged", "copy-target"])
def test_a_raw_change_to_a_directory_holding_edits_is_refused(ds, member):
    held = ds / "sub-01" / "sub-01_T1w.json"
    directory = ds / "sub-01"
    elsewhere = BidsPath(str(ds.parent), mode="w") / "elsewhere"
    change = {
        "rmdir": lambda: directory.rmdir(),
        "rmtree": lambda: directory.rmtree(),
        "rename": lambda: directory.rename(elsewhere),
        "move": lambda: ds.move(elsewhere),          # an ancestor
        "staged": lambda: directory.staged(),
        "copy-target": lambda: (ds / "sub-02").copy(directory),
    }[member]
    with ds:
        held["Inside"] = 1
        with pytest.raises(RuntimeError, match="holds files in this "
                           "directory") as info:
            change()
        assert "after the block ends" in str(info.value)
    assert on_disk(held)["Inside"] == 1


def test_raw_writes_to_other_files_are_allowed_in_a_block(ds):
    nifti = ds / T1W
    with ds.transaction() as tx:
        ds["sub-01"]["sub-01_T1w.json"]["Inside"] = 1
        nifti.write_bytes(b"new")
        with nifti.open("ab") as handle:
            handle.write(b"!")
        with (nifti.parent / "new.nii.gz").staged() as staged:
            staged.write_bytes(b"staged")
        (nifti.parent / "new.nii.gz").rename(nifti.parent / "moved.nii.gz")
        (nifti.parent / "moved.nii.gz").unlink()
        (ds / "sub-03" / "anat").mkdir(parents=True)  # creating is not lost
        (ds / "sub-03").rmtree()                     # holds no held file
        (ds / "sub-02").rename(ds / "sub-04")        # nor does this one
        # a read of a file the block covers is not a write
        assert json.loads((ds / "T1w.json").read_text()) == FILES["T1w.json"]
        with (ds / "T1w.json").open() as handle:
            assert json.load(handle) == FILES["T1w.json"]
        assert (ds / "participants.tsv").read_bytes() == PARTICIPANTS.encode()
    assert tx.written == [ds / "sub-01" / "sub-01_T1w.json"]
    assert nifti.read_bytes() == b"new!"
    assert (ds / "sub-04" / "anat" / "sub-02_T1w.nii.gz").exists()


def test_a_raw_write_is_allowed_outside_the_root_and_after_the_block(local_ds):
    ds = local_ds
    outside = BidsPath(str(ds.parent), mode="w") / "outside.json"
    with ds["sub-01"]:
        ds["T1w.json"].write_text("{}")             # not below the root
        outside.write_text("{}")
        with pytest.raises(RuntimeError):
            ds["sub-01"]["sub-01_T1w.json"].write_text("{}")
    ds["sub-01"]["sub-01_T1w.json"].write_text("{}")
    assert on_disk(ds / "sub-01" / "sub-01_T1w.json") == {}


def test_a_raw_write_from_another_thread_is_refused(ds):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool, ds:
        path = BidsPath(str(ds / "T1w.json"), mode="w")
        future = pool.submit(path.write_text, "{}")
        with pytest.raises(RuntimeError, match="open in another thread or task"):
            future.result()
        pool.submit((ds / T1W).write_bytes, b"thread").result()
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    assert (ds / T1W).read_bytes() == b"thread"


def test_a_read_only_path_says_it_is_read_only_first(ds):
    with ds, pytest.raises(ReadOnlyError):
        BidsPath(str(ds / "T1w.json")).write_text("{}")


def test_a_raw_write_check_does_not_scan_the_held_files(local_ds):
    import time

    ds = local_ds
    count = 1500
    for i in range(count):
        (ds / f"sub-{i:04d}_T1w.json").write_text('{"A": 1}')

    def raw_writes(data):
        start = time.perf_counter()
        for i in range(count):
            (ds / f"sub-{i:04d}_T1w.nii.gz").write_bytes(data)
        return time.perf_counter() - start

    alone = raw_writes(b"x")
    with ds:
        for i in range(count):
            ds[f"sub-{i:04d}_T1w.json"]["A"] = 2
        held = raw_writes(b"y")
    # a scan of every held file for each write took about a minute here
    assert held < 5 * alone + 1.0


def test_touch_and_chmod_of_a_directory_holding_edits_are_allowed(local_ds):
    ds = local_ds
    with ds:
        ds["sub-01"]["sub-01_T1w.json"]["Inside"] = 1
        (ds / "sub-01").touch()
        (ds / "sub-01").chmod(0o755)
        ds.touch()
        with pytest.raises(RuntimeError, match="covers this file"):
            (ds / "sub-01" / "sub-01_T1w.json").touch()
        # a directory not made yet, for a new file: touch would make a file
        (ds / "sub-09" / "sub-09_T1w.json").write({"New": 1})
        with pytest.raises(RuntimeError, match="holds files in this"):
            (ds / "sub-09").touch()
    assert on_disk(ds / "sub-01" / "sub-01_T1w.json")["Inside"] == 1
    assert on_disk(ds / "sub-09" / "sub-09_T1w.json") == {"New": 1}


def test_download_to_a_directory_checks_the_file_it_writes(local_ds):
    from bagof.paths import UnsupportedPathOperation

    ds = local_ds
    source = BidsPath(str(ds.parent / "img.nii.gz"), mode="w")
    source.write_bytes(b"img")
    sidecar = BidsPath(str(ds.parent / "sub-01_T1w.json"), mode="w")
    sidecar.write_text("{}")
    with ds:
        ds["sub-01"]["sub-01_T1w.json"]["Inside"] = 1
        # the directory holds an edit, but the image it would write does not
        # replace it: not refused (the local driver cannot download)
        with pytest.raises(UnsupportedPathOperation):
            source.download_to(ds / "sub-01")
        for destination in (ds / "sub-01", ds / "sub-01" / "sub-01_T1w.json"):
            with pytest.raises(RuntimeError, match="covers this file"):
                sidecar.download_to(destination)


def test_mkdir_where_the_block_holds_a_file_is_refused(ds):
    with ds.transaction() as tx:
        ds["new.json"] = {"n": 1}
        for path in (ds / "new.json", ds / "new.json" / "below"):
            with pytest.raises(RuntimeError, match="holds a file at this "
                               "path") as info:
                path.mkdir(parents=True)
            assert "after the block ends" in str(info.value)
        (ds / "sub-09").mkdir()                     # elsewhere: allowed
        (ds / "other.json" / "x").mkdir(parents=True)  # held by nothing
    assert tx.written == [ds / "new.json"]
    assert on_disk(ds / "new.json") == {"n": 1}


def test_a_directory_where_the_commit_writes_writes_nothing(local_ds):
    import os

    ds = local_ds
    with pytest.raises(IsADirectoryError, match="nothing was written"):
        with ds.transaction() as tx:
            ds["T1w.json"]["Inside"] = 1
            ds["new.json"] = {"n": 1}
            os.mkdir(os.fspath(ds / "new.json"))    # past brainfilter
    assert tx.written == []
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]
    os.rmdir(os.fspath(ds / "new.json"))
    with pytest.raises(NotADirectoryError, match="nothing was written"):
        with ds:
            ds["T1w.json"]["Inside"] = 1
            (ds / "sub-09" / "sub-09_T1w.json").write({"n": 1})
            with open(os.fspath(ds / "sub-09"), "wb"):   # past brainfilter
                pass
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]


# -- a value that cannot be written ---------------------------------------------------

def test_a_nested_value_json_cannot_hold_names_its_file_and_key(ds):
    with pytest.raises(TypeError) as info:
        with ds:
            ds["participants.tsv"]["age"] = [31, 32]
            ds["T1w.json"]["Extra"] = {"Coils": [{"Name": "head"}]}
            ds["T1w.json"]["Extra"]["Coils"][0]["Name"] = {1, 2}
    message = str(info.value)
    assert message.startswith(f"{ds / 'T1w.json'}: Extra.Coils[0].Name: ")
    assert "Object of type set is not JSON serializable" in message
    assert isinstance(info.value.__cause__, TypeError)
    assert on_disk(ds / "T1w.json") == FILES["T1w.json"]   # nothing written
    assert ds["participants.tsv"].read_text() == PARTICIPANTS
    with pytest.raises(ValueError, match=r"participants\.tsv: row 0 of "
                       "column 'sex' holds a tab"):
        with ds:
            ds["participants.tsv"]["sex"][0] = "a\tb"
    assert ds["participants.tsv"].read_text() == PARTICIPANTS


# -- a write through that a block opened meanwhile covers -----------------------------

def test_a_write_through_that_got_there_first_is_read_by_the_block(
    ds, monkeypatch
):
    import threading
    import time

    from brainfilter import transaction as T

    real = T.write_file
    writing, go = threading.Event(), threading.Event()

    def write_file(path, data):
        if threading.current_thread().name == "writer":
            writing.set()
            go.wait(5)
            time.sleep(0.05)        # the block would read the old file now
        real(path, data)

    monkeypatch.setattr(T, "write_file", write_file)
    errors = []

    def writer():
        try:
            ds["T1w.json"]["Outside"] = 1
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    thread = threading.Thread(target=writer, name="writer")
    thread.start()
    assert writing.wait(5)
    with ds:
        go.set()
        ds["T1w.json"]["Inside"] = 1                # read once it is written
    thread.join()
    assert errors == []
    assert on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "Outside": 1,
                                        "Inside": 1}


def test_a_write_through_that_a_block_got_ahead_of_raises(ds, monkeypatch):
    import threading

    from brainfilter import transaction as T

    real = T.file_lock
    waiting, go = threading.Event(), threading.Event()

    def file_lock(path):
        if threading.current_thread().name == "writer":
            waiting.set()
            go.wait(5)              # checked: no block yet; not yet locked
        return real(path)

    monkeypatch.setattr(T, "file_lock", file_lock)
    errors = []

    def writer():
        try:
            ds["T1w.json"]["Outside"] = 1
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    thread = threading.Thread(target=writer, name="writer")
    thread.start()
    assert waiting.wait(5)
    with ds:
        ds["T1w.json"]["Inside"] = 1                # read first
        go.set()
        thread.join()
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    message = str(errors[0])
    assert "open in another thread or task" in message
    assert "staged()" not in message
    assert on_disk(ds / "T1w.json") == {**FILES["T1w.json"], "Inside": 1}
