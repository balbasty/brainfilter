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
        ds["participants.json"]["age"]["Units"] = "years"   # nor this
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
        table["sex"][0] = "M"
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
