"""Typed TSV values: how a column is typed, and how a table is written back."""
import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

from brainfilter._content import (
    STANDARD_COLUMNS,
    Table,
    dump_tsv,
    parse_tsv,
)
from brainfilter.bidspath import AsyncBidsPath, BidsPath

# -- the column descriptions and the rows of the test table -------------------

DESCRIPTIONS = {
    "age": {"Format": "integer"},             # (a) beats the schema's number
    "weight": {"Format": "number"},
    "flag": {"Format": "boolean"},
    "grp": {"Format": "integer", "Levels": {"1": "one", "2": "two"}},
    "channels": {"Delimiter": ","},
    "counts": {"Format": "integer", "Delimiter": "|"},
    "when": {"Format": "date"},
    "bad": {"Format": "integer"},             # does not parse: falls back
    "notes": {"Description": "no Format"},    # (b)/(c) still apply
}

HEADER = [
    "participant_id", "age", "weight", "score", "code", "ratio", "flag",
    "grp", "channels", "counts", "when", "onset", "trial_type", "bad",
    "notes",
]
LINES = [
    ["sub-01", "30", "70.50", "1", "02", "0.5", "true", "1", "C3,C4", "1|2",
     "2024-01-31", "1", "1", "1.5", "7"],
    ["sub-02", "n/a", "1e2", "2", "10", "1.25", "false", "2", "n/a", "",
     "n/a", "2.5", "2", "2", "8"],
]
TEXT = "".join("\t".join(cells) + "\n" for cells in [HEADER, *LINES])

TYPED = [
    {
        "participant_id": "sub-01", "age": 30, "weight": 70.5, "score": 1,
        "code": "02", "ratio": 0.5, "flag": True, "grp": "1",
        "channels": ["C3", "C4"], "counts": [1, 2],
        "when": date(2024, 1, 31), "onset": 1.0, "trial_type": "1",
        "bad": "1.5", "notes": 7,
    },
    {
        "participant_id": "sub-02", "age": None, "weight": 100.0, "score": 2,
        "code": "10", "ratio": 1.25, "flag": False, "grp": "2",
        "channels": None, "counts": [], "when": None, "onset": 2.5,
        "trial_type": "2", "bad": "2", "notes": 8,
    },
]


def _write_ds(top):
    (top / "dataset_description.json").write_text(json.dumps({"Name": "ds"}))
    (top / "participants.json").write_text(json.dumps(DESCRIPTIONS))
    (top / "participants.tsv").write_text(TEXT)
    return top


@pytest.fixture
def local_ds(tmp_path):
    top = BidsPath(str(tmp_path / "ds"), mode="w")
    top.mkdir()
    return _write_ds(top)


@pytest.fixture
def memory_ds():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    top = BidsPath("memory://ds", mode="w")
    top.mkdir(parents=True, exist_ok=True)
    yield _write_ds(top)
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(params=["local", "memory"])
def ds(request):
    return request.getfixturevalue(f"{request.param}_ds")


def column(texts, descriptions=None, name="col"):
    """The values a column of `texts` reads as (beside a key column)."""
    text = f"key\t{name}\n" + "".join(f"k\t{t}\n" for t in texts)
    return [row[name] for row in parse_tsv(text, descriptions)]


# -- precedence -----------------------------------------------------------------

def test_typed_read(ds):
    table = ds["participants.tsv"]
    rows = table.as_list()
    assert rows == TYPED
    for got, want in zip(rows, TYPED):
        assert [type(v) for v in got.values()] == [type(v) for v in want.values()]
    assert list(table.rows()) == rows
    assert list(table) == HEADER
    assert table["counts"] == [[1, 2], []]
    assert table.as_dict() == {c: [r[c] for r in TYPED] for c in HEADER}


def test_description_format_comes_first():
    # `age` is a number in BIDS; its own description says integer
    assert column(["30", "41"], {"age": {"Format": "integer"}}, "age") == [30, 41]
    # a description's string keeps a standard numeric column as text
    assert column(["1", "2"], {"onset": {"Format": "string"}}, "onset") == ["1", "2"]
    # other formats read as text
    assert column(["1", "2"], {"col": {"Format": "label"}}) == ["1", "2"]


def test_standard_columns_come_second():
    assert STANDARD_COLUMNS["age"] == "number"
    assert STANDARD_COLUMNS["participant_id"] == "string"
    assert column(["1", "2.5"], name="onset") == [1.0, 2.5]
    assert column(["1", "2"], name="trial_type") == ["1", "2"]   # not inferred
    assert column(["true", "false"], name="short_channel") == [True, False]
    assert column(["2024-01-31T10:00:00", "n/a"], name="acq_time") == [
        datetime(2024, 1, 31, 10), None,
    ]


def test_a_declared_type_that_does_not_parse_falls_back():
    # (a) fails, (b) is a number
    assert column(["1.5", "2"], {"age": {"Format": "integer"}}, "age") == [1.5, 2.0]
    # (a) fails, nothing in (b), (c) infers
    assert column(["a", "2"], {"col": {"Format": "integer"}}) == ["a", "2"]
    assert column(["10", "2"], {"col": {"Format": "boolean"}}) == [10, 2]
    # (b) fails, (c) infers text
    assert column(["young", "old"], name="age") == ["young", "old"]


# -- lossless inference -----------------------------------------------------------

@pytest.mark.parametrize("texts, values", [
    (["1", "-2", "30"], [1, -2, 30]),
    (["0.5", "-1.25", "1e-05"], [0.5, -1.25, 1e-05]),
    (["123456789012345678901234567890"], [123456789012345678901234567890]),
    (["1", "n/a"], [1, None]),
    # not written back the same way: kept as text
    (["02", "10"], ["02", "10"]),            # leading zero
    (["+3", "4"], ["+3", "4"]),
    (["-0", "1"], ["-0", "1"]),
    (["1e3", "1.5"], ["1e3", "1.5"]),        # scientific notation
    (["1.50", "2.5"], ["1.50", "2.5"]),      # trailing zero
    (["3", "1.5"], ["3", "1.5"]),            # mixed int and float
    (["1", "x"], ["1", "x"]),                # mixed number and text
    (["1_000"], ["1_000"]),
    (["nan", "inf"], ["nan", "inf"]),
    (["", "1"], ["", "1"]),
    # never guessed
    (["true", "false"], ["true", "false"]),
    (["2024-01-31"], ["2024-01-31"]),
    (["n/a", "n/a"], [None, None]),
])
def test_inference(texts, values):
    got = column(texts)
    assert got == values
    assert [type(v) for v in got] == [type(v) for v in values]


# -- Levels, Delimiter, n/a, dates ---------------------------------------------

def test_levels_keep_their_keys():
    levels = {"Levels": {"1": "a", "02": "b"}}
    assert column(["1", "02", "n/a"], {"col": levels}) == ["1", "02", None]
    # Levels win over a Format and over the standard definition
    levels = {"Levels": {"1": "a", "2": "b"}, "Format": "integer"}
    assert column(["1", "2"], {"age": levels}, "age") == ["1", "2"]


def test_delimiter_splits_into_lists():
    comma = {"col": {"Delimiter": ","}}
    assert column(["a,b", "c", "", "n/a"], comma) == [["a", "b"], ["c"], [], None]
    # the items are typed as the column: inferred here ...
    assert column(["1,2", "3"], comma) == [[1, 2], [3]]
    assert column(["1,02"], comma) == [["1", "02"]]
    # ... declared there, with n/a items as None
    typed = {"col": {"Delimiter": "|", "Format": "number"}}
    assert column(["1|2.5", "n/a|3"], typed) == [[1.0, 2.5], [None, 3.0]]


def test_dates_and_times():
    def fmt(name):
        return {"col": {"Format": name}}

    assert column(["2024-01-31"], fmt("date")) == [date(2024, 1, 31)]
    assert column(["10:20:30", "10:20:30.5"], fmt("time")) == [
        time(10, 20, 30), time(10, 20, 30, 500000),
    ]
    assert column(
        ["2024-01-31T10:00:00", "2024-01-31T10:00:00Z",
         "2024-01-31T10:00:00.25-05:30"],
        fmt("datetime"),
    ) == [
        datetime(2024, 1, 31, 10),
        datetime(2024, 1, 31, 10, tzinfo=timezone.utc),
        datetime(2024, 1, 31, 10, 0, 0, 250000,
                 tzinfo=timezone(-timedelta(hours=5, minutes=30))),
    ]
    # not unambiguous ISO 8601: the whole column stays text
    for texts, name in [
        (["2024-01-31", "31/01/2024"], "date"),
        (["2024-1-31"], "date"),
        (["2024-02-30"], "date"),
        (["2024-01-31 10:00:00"], "datetime"),
        (["10:00"], "time"),
        (["10:00:00.1234567"], "time"),
    ]:
        assert column(texts, fmt(name)) == texts


def test_raw_read(ds):
    rows = ds["participants.tsv"].as_list(raw=True)
    assert [list(row) for row in rows] == [HEADER, HEADER]
    assert [list(row.values()) for row in rows] == LINES
    assert dump_tsv(rows) == TEXT
    columns = ds["participants.tsv"].as_dict(raw=True)
    assert list(columns) == HEADER
    assert columns["weight"] == ["70.50", "1e2"]


# -- writing back ------------------------------------------------------------------

def test_unchanged_table_is_not_written(ds):
    with ds.transaction() as tx:
        assert ds["participants.tsv"].as_list() == TYPED
        ds["participants.tsv"].write(ds["participants.tsv"].as_list())
    assert tx.written == []
    assert dump_tsv(parse_tsv(TEXT, DESCRIPTIONS)) == TEXT


def test_edit_one_cell_keeps_the_others(ds):
    table = ds["participants.tsv"]
    with ds.transaction() as tx:
        table["weight"] = [70.5, 101.0]
    assert tx.written == [table]
    lines = [cells[:] for cells in LINES]
    lines[1][HEADER.index("weight")] = "101.0"
    want = "".join("\t".join(c) + "\n" for c in [HEADER, *lines])
    assert table.read_text() == want   # `70.50`, `1e2`, `n/a`, `` kept
    table["weight"] = [70.5, 102.0]    # the same, written at once
    assert table.read_text() == want.replace("101.0", "102.0")


def test_changed_and_new_cells_are_formatted(ds):
    table = ds["participants.tsv"]
    rows = table.as_list()
    rows[0]["channels"].append("Cz")          # a list changed
    rows[0]["weight"] = 70.5                  # equal value: text kept
    rows[0]["age"] = 30.0                     # equal, another type
    rows[0]["flag"] = False
    rows.append({
        "participant_id": "sub-03", "age": 41, "weight": 1e-7,
        "flag": True, "channels": ["C3"], "counts": [3, None],
        "when": date(2025, 2, 1), "onset": 0.1, "notes": "x y",
    })
    table.write(rows)
    out = table.as_list(raw=True)
    assert out[0]["channels"] == "C3,C4,Cz"
    assert out[0]["weight"] == "70.50"
    assert out[0]["age"] == "30.0"
    assert out[0]["flag"] == "false"
    assert out[1] == dict(zip(HEADER, LINES[1]))
    assert out[2] == {
        "participant_id": "sub-03", "age": "41", "weight": "1e-07",
        "score": "n/a", "code": "n/a", "ratio": "n/a", "flag": "true",
        "grp": "n/a", "channels": "C3", "counts": "3|n/a",
        "when": "2025-02-01", "onset": "0.1", "trial_type": "n/a",
        "bad": "n/a", "notes": "x y",
    }


def test_list_without_delimiter_is_refused(ds):
    table = ds["participants.tsv"]
    with pytest.raises(TypeError, match="no Delimiter"):
        table["notes"] = [[1, 2], 8]
    with pytest.raises(TypeError, match="no Delimiter"):
        with ds:
            table["notes"] = [[1, 2], 8]
    assert table.read_text() == TEXT   # nothing written


def test_copied_table_keeps_the_text():
    table = parse_tsv(TEXT, DESCRIPTIONS)
    assert dump_tsv(Table(table)) == TEXT
    del table[0]
    assert dump_tsv(Table(table)) == "".join(
        "\t".join(c) + "\n" for c in [HEADER, LINES[1]]
    )


@pytest.mark.parametrize("copy", [
    lambda rows: rows[::-1],                     # the rows, reordered
    lambda rows: [dict(r) for r in rows[::-1]],  # copies of them
    lambda rows: Table(rows)[::-1],              # rows of another table
])
@pytest.mark.parametrize("in_transaction", [False, True])
def test_rewritten_table_keeps_the_text(ds, copy, in_transaction):
    table = ds["participants.tsv"]
    if in_transaction:
        with ds:
            table.write(copy(table.as_list()))
    else:
        table.write(copy(table.as_list()))
    lines = table.read_text().splitlines()
    # each value is written as the file wrote it (`70.50`, `1e2`)
    assert lines[1:] == ["\t".join(c) for c in LINES[::-1]]


def test_rewritten_rows_keep_their_own_text():
    text = "x\ty\n1.50\ta\n1.5\tb\n2.0e0\tc\n"
    origin = parse_tsv(text, {"x": {"Format": "number"}})
    # rows in place: each keeps its text, even where a value is written
    # two ways in the column
    assert dump_tsv(Table([dict(r) for r in origin], _origin=origin)) == text
    # moved or new: a value written one way keeps it; one written two ways
    # keeps the text its place had, else is formatted
    moved = Table([dict(r) for r in origin[::-1]], _origin=origin)
    assert dump_tsv(moved) == "x\ty\n2.0e0\tc\n1.5\tb\n1.5\ta\n"
    added = Table([{"x": 2.0, "y": "d"}, {"x": 1.5, "y": "e"}], _origin=origin)
    assert dump_tsv(added) == "x\ty\n2.0e0\td\n1.5\te\n"
    # the table's own rows keep their own text
    assert dump_tsv(Table(origin[::-1], _origin=origin)) == (
        "x\ty\n2.0e0\tc\n1.5\tb\n1.50\ta\n"
    )


def test_rewritten_lists_keep_their_text():
    text = "id\tv\na\t1.50,2\nb\t3,4\n"
    descriptions = {"v": {"Format": "number", "Delimiter": ","}}
    origin = parse_tsv(text, descriptions)
    assert origin[0]["v"] == [1.5, 2.0]
    copies = [dict(r, v=list(r["v"])) for r in origin]
    assert dump_tsv(Table(copies, _origin=origin)) == text
    copies[0]["v"].append(5.0)                   # changed: formatted
    assert dump_tsv(Table(copies, _origin=origin)).splitlines()[1] == (
        "a\t1.5,2.0,5.0"
    )


def test_new_table_lists_use_the_sidecar_delimiter(ds):
    with ds:
        ds["participants.tsv"].write([{"participant_id": "sub-9",
                                       "channels": ["a", "b"]}])
    assert ds["participants.tsv"].read_text() == (
        "participant_id\tchannels\nsub-9\ta,b\n"
    )


def test_raw_read_in_a_transaction_is_a_copy(ds):
    table = ds["participants.tsv"]
    with ds.transaction() as tx:
        table["score"] = [5, 2]
        raw = table.as_list(raw=True)
        assert raw[0]["score"] == "5" and raw[0]["weight"] == "70.50"
        raw[0]["score"] = "6"                    # not an edit
        table.as_dict(raw=True)["score"][0] = "6"
        assert table.as_dict(raw=True)["score"] == ["5", "2"]
        assert table.keys() == HEADER
    assert tx.written == [table]
    assert table["score"] == [5, 2]


# -- pandas ------------------------------------------------------------------------

def test_dataframe_dtypes(ds):
    pytest.importorskip("pandas")
    df = ds["participants.tsv"].as_dataframe()
    dtypes = {name: str(dtype) for name, dtype in df.dtypes.items()}
    assert dtypes["age"] == "Int64"            # integer, with a missing value
    assert dtypes["score"] == "int64"
    assert dtypes["weight"] == dtypes["onset"] == "float64"
    assert dtypes["flag"] == "bool"
    for name in ("participant_id", "code", "grp", "trial_type", "channels",
                 "when"):
        assert dtypes[name] in ("object", "str"), name
    assert df["code"].tolist() == ["02", "10"]
    assert df["channels"][0] == ["C3", "C4"]
    assert df["age"].isna().tolist() == [False, True]
    # dtype= hands the typing back to pandas
    df = ds["participants.tsv"].as_dataframe(dtype={"code": int})
    assert df["code"].tolist() == [2, 10]


def test_dataframe_datetime():
    pd = pytest.importorskip("pandas")
    from brainfilter._content import tsv_dataframe

    text = "acq_time\tday\n2024-01-31T10:00:00\t2024-01-31\nn/a\tn/a\n"
    df = tsv_dataframe(text, {}, {"day": {"Format": "date"}})
    assert str(df["acq_time"].dtype).startswith("datetime64")
    assert df["acq_time"][0] == pd.Timestamp("2024-01-31T10:00:00")
    assert df["day"][0] == date(2024, 1, 31)


# -- async -------------------------------------------------------------------------

@pytest.fixture
def async_ds(local_ds):
    return AsyncBidsPath(str(local_ds), mode="w")


@pytest.mark.anyio
async def test_async_typed_read(async_ds):
    table = async_ds / "participants.tsv"
    assert await table.as_list() == TYPED
    assert [row async for row in table.rows()] == TYPED
    assert [name async for name in table] == HEADER
    raw = await table.as_list(raw=True)
    assert [list(row.values()) for row in raw] == LINES


@pytest.mark.anyio
async def test_async_edit_one_cell_keeps_the_others(async_ds):
    table = async_ds / "participants.tsv"
    async with async_ds.transaction() as tx:
        await table.set("score", [5, 2])
        assert (await table.as_list(raw=True))[0]["score"] == "5"
    assert tx.written == [table]
    lines = [cells[:] for cells in LINES]
    lines[0][HEADER.index("score")] = "5"
    assert await table.read_text() == "".join(
        "\t".join(c) + "\n" for c in [HEADER, *lines]
    )
    rows = await table.as_list()
    assert rows[0]["score"] == 5
    rows[1]["counts"] = [1]
    await table.write(rows)
    assert (await table.as_list(raw=True))[1]["counts"] == "1"
    assert (await table.as_list(raw=True))[0]["weight"] == "70.50"


@pytest.mark.anyio
async def test_async_dataframe_dtypes(async_ds):
    pytest.importorskip("pandas")
    df = await (async_ds / "participants.tsv").as_dataframe()
    assert str(df["age"].dtype) == "Int64"
    assert str(df["weight"].dtype) == "float64"
    assert df["code"].tolist() == ["02", "10"]


# -- no quoting --------------------------------------------------------------------

QUOTED = 'id\tnote\tq\nsub-01\ta"b\t"q"\nsub-02\tsaid "hi"\t""\n'


def test_quotes_are_text():
    rows = parse_tsv(QUOTED)
    assert [r["note"] for r in rows] == ['a"b', 'said "hi"']
    assert [r["q"] for r in rows] == ['"q"', '""']
    assert [r["q"] for r in parse_tsv(QUOTED, raw=True)] == ['"q"', '""']
    assert dump_tsv(rows) == QUOTED
    rows[0]["id"] = "sub-09"
    assert dump_tsv(rows) == QUOTED.replace("sub-01", "sub-09")
    rows.append({"id": "sub-03", "note": 'x "y"'})
    assert dump_tsv(rows).splitlines()[-1] == 'sub-03\tx "y"\tn/a'


def test_quoted_file_round_trips(ds):
    table = ds / "quoted.tsv"
    table.write_text(QUOTED)
    with ds.transaction() as tx:
        table["id"] = ["sub-01", "sub-09"]
        assert table.as_list(raw=True)[0]["q"] == '"q"'
    assert tx.written == [table]
    assert table.read_text() == QUOTED.replace("sub-02", "sub-09")
    assert table["q"] == ['"q"', '""']
    pytest.importorskip("pandas")
    assert table.as_dataframe()["q"].tolist() == ['"q"', '""']


@pytest.mark.parametrize("value", ["a\tb", "a\nb", "a\rb"])
def test_tab_or_line_break_is_refused(ds, value):
    table = ds["participants.tsv"]
    with pytest.raises(ValueError, match="tab or a line break"):
        with ds.transaction():
            table["notes"] = [value, 8]
    with pytest.raises(ValueError, match="tab or a line break"):
        table["notes"] = [value, 8]
    assert table.read_text() == TEXT   # nothing written
    with pytest.raises(ValueError, match="column name"):
        dump_tsv(Table([{value: 1}]))


# -- NaN and infinity --------------------------------------------------------------

def test_nan_is_written_as_na():
    nan = float("nan")
    table = Table([{"x": 1.5, "y": nan}, {"x": nan, "y": nan}])
    text = dump_tsv(table)
    assert text == "x\ty\n1.5\tn/a\nn/a\tn/a\n"
    assert [r["x"] for r in parse_tsv(text)] == [1.5, None]
    with pytest.raises(ValueError, match="'x' holds inf"):
        dump_tsv(Table([{"x": float("inf")}]))
    with pytest.raises(ValueError, match="-inf"):
        dump_tsv(Table([{"x": float("-inf")}]))


def test_nan_from_a_dataframe(ds):
    pytest.importorskip("pandas")
    table = ds["participants.tsv"]
    frame = table.as_dataframe()
    rows = frame[["participant_id", "weight"]].to_dict("records")
    rows[1]["weight"] = float("nan")
    with ds.transaction():
        table.write(rows)
    # 70.5 was read from `70.50`: its text is kept
    assert table.read_text() == (
        "participant_id\tweight\nsub-01\t70.50\nsub-02\tn/a\n"
    )
    assert table.as_list()[1]["weight"] is None
    table["weight"] = frame["weight"].tolist()       # a column of a frame
    assert table["weight"] == [70.5, 100.0]


# -- the sidecar's Delimiters, for new columns and new tables ----------------------

def _with_tags(ds):
    ds["participants.json"].write_text(json.dumps(
        {**DESCRIPTIONS, "tags": {"Delimiter": ","}}
    ))
    (ds / "sessions.json").write_text(json.dumps({"tags": {"Delimiter": "|"}}))


def test_new_column_uses_the_sidecar_delimiter(ds):
    _with_tags(ds)
    table = ds["participants.tsv"]
    table["tags"] = [["a", "b"], []]
    assert [r["tags"] for r in table.as_list(raw=True)] == ["a,b", ""]


def test_new_table_uses_the_sidecar_delimiter(ds):
    _with_tags(ds)
    new = ds / "sub-01" / "sub-01_sessions.tsv"
    new.write([{"session_id": "ses-1", "tags": ["a", "b"]}])
    assert new.read_text() == "session_id\ttags\nses-1\ta|b\n"
    # a table written without lists, then given one
    with ds.transaction():
        new.write([{"session_id": "ses-2"}])
        new["tags"] = [["c", "d"]]
    assert new.read_text() == "session_id\ttags\nses-2\tc|d\n"
    other = ds / "sub-02" / "sub-02_sessions.tsv"
    other["session_id"] = ["ses-1"]            # a new table, by column
    other["tags"] = [["e", "f"]]
    assert other.read_text() == "session_id\ttags\nses-1\te|f\n"


# -- a byte-order mark -------------------------------------------------------------

def test_byte_order_mark_is_skipped(ds):
    table, sidecar = ds / "bom.tsv", ds / "bom.json"
    table.write_bytes(b"\xef\xbb\xbfparticipant_id\tage\nsub-01\t30\n")
    sidecar.write_bytes(b'\xef\xbb\xbf{"Level": "bom"}')
    assert table.keys() == ["participant_id", "age"]
    assert table.as_list() == [{"participant_id": "sub-01", "age": 30.0}]
    assert list(table.as_dict(raw=True)) == ["participant_id", "age"]
    assert sidecar["Level"] == "bom"
    pytest.importorskip("pandas")
    assert list(table.as_dataframe().columns) == ["participant_id", "age"]
    with ds.transaction():
        sidecar["Level"] = "edited"
        table["participant_id"] = ["sub-02"]
    assert not sidecar.read_bytes().startswith(b"\xef\xbb\xbf")
    assert table.read_bytes() == b"participant_id\tage\nsub-02\t30\n"


@pytest.mark.anyio
async def test_async_byte_order_mark_is_skipped(async_ds):
    table, sidecar = async_ds / "bom.tsv", async_ds / "bom.json"
    await table.write_bytes(b"\xef\xbb\xbfparticipant_id\nsub-01\n")
    await sidecar.write_bytes(b'\xef\xbb\xbf{"Level": "bom"}')
    assert await table.keys() == ["participant_id"]
    assert await sidecar.get("Level") == "bom"
    async with async_ds.transaction():
        await sidecar.set("Level", "edited")
    assert not (await sidecar.read_bytes()).startswith(b"\xef\xbb\xbf")
    await table.set("participant_id", ["sub-02"])
    assert await table.read_bytes() == b"participant_id\nsub-02\n"


@pytest.mark.anyio
async def test_async_new_column_uses_the_sidecar_delimiter(async_ds, local_ds):
    _with_tags(local_ds)
    table = async_ds / "participants.tsv"
    async with async_ds.transaction():
        await table.set("tags", [["a", "b"], None])
    assert [r["tags"] for r in await table.as_list(raw=True)] == ["a,b", "n/a"]
    new = async_ds / "sub-01" / "sub-01_sessions.tsv"
    await new.write([{"session_id": "ses-1", "tags": ["a", "b"]}])
    assert await new.read_text() == "session_id\ttags\nses-1\ta|b\n"


def test_empty_cell_of_a_one_column_table_is_refused():
    with pytest.raises(ValueError, match="one column"):
        dump_tsv(Table([{"x": "a"}, {"x": ""}]))
    assert dump_tsv(Table([{"x": "a"}, {"x": None}])) == "x\na\nn/a\n"
    assert dump_tsv(Table([{"x": "", "y": ""}])) == "x\ty\n\t\n"
