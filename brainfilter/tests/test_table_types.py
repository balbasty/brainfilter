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
    top = BidsPath(str(tmp_path / "ds"))
    top.mkdir()
    return _write_ds(top)


@pytest.fixture
def memory_ds():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    top = BidsPath("memory://ds")
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
    rows = table.read()
    assert rows == TYPED
    for got, want in zip(rows, TYPED):
        assert [type(v) for v in got.values()] == [type(v) for v in want.values()]
    assert list(table) == rows


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
    table = ds["participants.tsv"].read(raw=True)
    assert table.columns == HEADER
    assert [list(row.values()) for row in table] == LINES
    assert dump_tsv(table) == TEXT


# -- writing back ------------------------------------------------------------------

def test_unchanged_table_is_not_written(ds):
    with ds.transaction() as tx:
        assert ds["participants.tsv"].read() == TYPED
    assert tx.written == []
    assert dump_tsv(parse_tsv(TEXT, DESCRIPTIONS)) == TEXT


def test_edit_one_cell_keeps_the_others(ds):
    table = ds["participants.tsv"]
    with ds.transaction() as tx:
        rows = table.read()
        rows[1]["weight"] = 101.0
    assert tx.written == [table]
    lines = [cells[:] for cells in LINES]
    lines[1][HEADER.index("weight")] = "101.0"
    want = "".join("\t".join(c) + "\n" for c in [HEADER, *lines])
    assert table.read_text() == want   # `70.50`, `1e2`, `n/a`, `` kept


def test_changed_and_new_cells_are_formatted(ds):
    table = ds["participants.tsv"]
    with ds.transaction():
        rows = table.read()
        rows[0]["channels"].append("Cz")          # a list changed in place
        rows[0]["weight"] = 70.5                  # equal value: text kept
        rows[0]["age"] = 30.0                     # equal, another type
        rows[0]["flag"] = False
        rows.append({
            "participant_id": "sub-03", "age": 41, "weight": 1e-7,
            "flag": True, "channels": ["C3"], "counts": [3, None],
            "when": date(2025, 2, 1), "onset": 0.1, "notes": "x y",
        })
    out = table.read(raw=True)
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
        with ds.transaction():
            table.read()[0]["notes"] = [1, 2]
    assert table.read_text() == TEXT   # nothing written


def test_copied_table_keeps_the_text():
    table = parse_tsv(TEXT, DESCRIPTIONS)
    assert dump_tsv(Table(table)) == TEXT
    del table[0]
    assert dump_tsv(Table(table)) == "".join(
        "\t".join(c) + "\n" for c in [HEADER, LINES[1]]
    )


@pytest.mark.parametrize("copy, kept", [
    (lambda rows: rows[::-1], True),             # its own rows, reordered
    (lambda rows: [dict(r) for r in rows[::-1]], False),   # new rows
    (lambda rows: Table(rows)[::-1], False),     # rows of another table
])
def test_rewritten_table_keeps_the_text(ds, copy, kept):
    table = ds["participants.tsv"]
    with ds.transaction():
        table.write(copy(table.read()))
    lines = table.read_text().splitlines()
    assert lines[1].split("\t")[0] == "sub-02"
    if kept:
        assert lines[1:] == ["\t".join(c) for c in LINES[::-1]]
    else:
        # formatted from the values; lists join with the sidecar's Delimiter
        assert lines[2].split("\t")[1:3] == ["30", "70.5"]
        assert lines[2].split("\t")[8:10] == ["C3,C4", "1|2"]


def test_new_table_lists_use_the_sidecar_delimiter(ds):
    with ds.transaction():
        ds["participants.tsv"].write([{"participant_id": "sub-9",
                                       "channels": ["a", "b"]}])
    assert ds["participants.tsv"].read_text() == (
        "participant_id\tchannels\nsub-9\ta,b\n"
    )


def test_raw_read_in_a_transaction_is_a_copy(ds):
    table = ds["participants.tsv"]
    with ds.transaction() as tx:
        table.read()[0]["score"] = 5
        raw = table.read(raw=True)
        assert raw[0]["score"] == "5" and raw[0]["weight"] == "70.50"
        raw[0]["score"] = "6"                    # not an edit
    assert tx.written == [table]
    assert table.read()[0]["score"] == 5


# -- pandas ------------------------------------------------------------------------

def test_dataframe_dtypes(ds):
    pytest.importorskip("pandas")
    df = ds["participants.tsv"].read_dataframe()
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
    df = ds["participants.tsv"].read_dataframe(dtype={"code": int})
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
    return AsyncBidsPath(str(local_ds))


@pytest.mark.anyio
async def test_async_typed_read(async_ds):
    table = async_ds / "participants.tsv"
    assert await table.read() == TYPED
    assert [row async for row in table] == TYPED
    raw = await table.read(raw=True)
    assert [list(row.values()) for row in raw] == LINES


@pytest.mark.anyio
async def test_async_edit_one_cell_keeps_the_others(async_ds):
    table = async_ds / "participants.tsv"
    async with async_ds.transaction() as tx:
        rows = await table.read()
        rows[0]["score"] = 5
        assert (await table.read(raw=True))[0]["score"] == "5"
    assert tx.written == [table]
    lines = [cells[:] for cells in LINES]
    lines[0][HEADER.index("score")] = "5"
    assert await table.read_text() == "".join(
        "\t".join(c) + "\n" for c in [HEADER, *lines]
    )
    async with table.edit() as rows:
        assert rows[0]["score"] == 5
        rows[1]["counts"] = [1]
    assert (await table.read(raw=True))[1]["counts"] == "1"


@pytest.mark.anyio
async def test_async_dataframe_dtypes(async_ds):
    pytest.importorskip("pandas")
    df = await (async_ds / "participants.tsv").read_dataframe()
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
        table.read()[1]["id"] = "sub-09"
        assert table.read(raw=True)[0]["q"] == '"q"'
    assert tx.written == [table]
    assert table.read_text() == QUOTED.replace("sub-02", "sub-09")
    pytest.importorskip("pandas")
    assert table.read_dataframe()["q"].tolist() == ['"q"', '""']


@pytest.mark.parametrize("value", ["a\tb", "a\nb", "a\rb"])
def test_tab_or_line_break_is_refused(ds, value):
    table = ds["participants.tsv"]
    with pytest.raises(ValueError, match="tab or a line break"):
        with ds.transaction():
            table.read()[0]["notes"] = value
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
    frame = table.read_dataframe()
    rows = frame[["participant_id", "weight"]].to_dict("records")
    rows[1]["weight"] = float("nan")
    with ds.transaction():
        table.write(rows)
    assert table.read_text() == "participant_id\tweight\nsub-01\t70.5\nsub-02\tn/a\n"
    assert table.read()[1]["weight"] is None


# -- the sidecar's Delimiters, for new columns and new tables ----------------------

def _with_tags(ds):
    ds["participants.json"].write_text(json.dumps(
        {**DESCRIPTIONS, "tags": {"Delimiter": ","}}
    ))
    (ds / "sessions.json").write_text(json.dumps({"tags": {"Delimiter": "|"}}))


def test_new_column_uses_the_sidecar_delimiter(ds):
    _with_tags(ds)
    table = ds["participants.tsv"]
    with ds.transaction():
        rows = table.read()
        rows.add_column("tags", [["a", "b"], []])
    assert [r["tags"] for r in table.read(raw=True)] == ["a,b", ""]


def test_new_table_uses_the_sidecar_delimiter(ds):
    _with_tags(ds)
    new = ds / "sub-01" / "sub-01_sessions.tsv"
    with new.edit() as rows:
        rows.append({"session_id": "ses-1", "tags": ["a", "b"]})
    assert new.read_text() == "session_id\ttags\nses-1\ta|b\n"
    # a table written without lists, then given one
    with ds.transaction():
        new.write([{"session_id": "ses-2"}])
        new.read()[0]["tags"] = ["c", "d"]
    assert new.read_text() == "session_id\ttags\nses-2\tc|d\n"


# -- a byte-order mark -------------------------------------------------------------

def test_byte_order_mark_is_skipped(ds):
    table, sidecar = ds / "bom.tsv", ds / "bom.json"
    table.write_bytes(b"\xef\xbb\xbfparticipant_id\tage\nsub-01\t30\n")
    sidecar.write_bytes(b'\xef\xbb\xbf{"Level": "bom"}')
    assert table.read().columns == ["participant_id", "age"]
    assert table.read() == [{"participant_id": "sub-01", "age": 30.0}]
    assert table.read(raw=True).columns == ["participant_id", "age"]
    assert sidecar["Level"] == "bom"
    pytest.importorskip("pandas")
    assert list(table.read_dataframe().columns) == ["participant_id", "age"]
    with ds.transaction():
        sidecar["Level"] = "edited"
        table.read()[0]["participant_id"] = "sub-02"
    assert not sidecar.read_bytes().startswith(b"\xef\xbb\xbf")
    assert table.read_bytes() == b"participant_id\tage\nsub-02\t30\n"


@pytest.mark.anyio
async def test_async_byte_order_mark_is_skipped(async_ds):
    table, sidecar = async_ds / "bom.tsv", async_ds / "bom.json"
    await table.write_bytes(b"\xef\xbb\xbfparticipant_id\nsub-01\n")
    await sidecar.write_bytes(b'\xef\xbb\xbf{"Level": "bom"}')
    assert (await table.read()).columns == ["participant_id"]
    assert await sidecar.get("Level") == "bom"
    async with async_ds.transaction():
        await sidecar.set("Level", "edited")
    assert not (await sidecar.read_bytes()).startswith(b"\xef\xbb\xbf")


@pytest.mark.anyio
async def test_async_new_column_uses_the_sidecar_delimiter(async_ds, local_ds):
    _with_tags(local_ds)
    table = async_ds / "participants.tsv"
    async with async_ds.transaction():
        (await table.read()).add_column("tags", [["a", "b"], None])
    assert [r["tags"] for r in await table.read(raw=True)] == ["a,b", "n/a"]
    new = async_ds / "sub-01" / "sub-01_sessions.tsv"
    async with new.edit() as rows:
        rows.append({"session_id": "ses-1", "tags": ["a", "b"]})
    assert await new.read_text() == "session_id\ttags\nses-1\ta|b\n"


def test_empty_cell_of_a_one_column_table_is_refused():
    with pytest.raises(ValueError, match="one column"):
        dump_tsv(Table([{"x": "a"}, {"x": ""}]))
    assert dump_tsv(Table([{"x": "a"}, {"x": None}])) == "x\na\nn/a\n"
    assert dump_tsv(Table([{"x": "", "y": ""}])) == "x\ty\n\t\n"
