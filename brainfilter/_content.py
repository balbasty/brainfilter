"""The contents of BIDS JSON and TSV files: parsing, writing, and `Table`.

Everything here is pure (no I/O), so the sync and async families, and the
transactions that buffer their edits, share it.

TSV values are typed when they are read. Each column gets one type, from
the first of these that applies:

1. the column's description in the table's JSON sidecar, if it has a
   `Format` (`participants.json` describes `participants.tsv`);
2. the column's standard definition in BIDS (`STANDARD_COLUMNS`);
3. the values themselves: `int` if every value is an integer written
   canonically, else `float` if every value is a float written as Python
   writes it (`repr`), else `str`.

A declared type (1 or 2) is used only if every value of the column parses
as it; otherwise the next one is tried. A column with `Levels` keeps its
values as text, so they match the keys of `Levels`. A column with a
`Delimiter` holds lists of values of its type. `n/a` is `None`.

A BIDS TSV file has no quoting: a cell is the exact text between two tabs,
quotes included, so a cell cannot hold a tab or a line break. Files are read
as UTF-8, with or without a byte-order mark, and written without one.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Callable, NamedTuple

if TYPE_CHECKING:
    from pandas import DataFrame, Series

__all__ = ["STANDARD_COLUMNS", "Table"]

# Missing-value marker of BIDS tables.
NA = "n/a"

# The byte-order mark some editors write at the start of a UTF-8 file.
BOM = "\ufeff"

# What a TSV cell cannot hold: BIDS tables have no quoting.
_SEPARATORS = re.compile(r"[\t\n\r]")

JSON = "json"
TSV = "tsv"

# The Python types a TSV column can hold.
STR, INT, FLOAT, BOOL, DATE, DATETIME, TIME = (
    "str", "int", "float", "bool", "date", "datetime", "time",
)

# BIDS `Format` values with a Python type other than `str`. Every other
# format (`string`, `label`, `unit`, `uri`, `rrid`, `bids_uri`,
# `dataset_relative`, ...) reads as `str`.
_FORMATS = {
    "number": FLOAT,
    "integer": INT,
    "index": INT,
    "boolean": BOOL,
    "date": DATE,
    "datetime": DATETIME,
    "time": TIME,
}

# The type of each standard TSV column of BIDS 1.11.2, as a BIDS `Format`
# (from `objects.columns` of the official schema: its `type`, or its
# `definition.Format`; `acq_time` has `format: datetime`). `group` is left
# out: BIDS lets it be a string or a number.
STANDARD_COLUMNS: dict[str, str] = {
    # number
    "age": "number", "cardiac": "number", "duration": "number",
    "high_cutoff": "number", "hplc_recovery_fractions": "number",
    "impedance": "number", "interelectrode_distance": "number",
    "low_cutoff": "number", "metabolite_parent_fraction": "number",
    "metabolite_polar_fraction": "number", "onset": "number",
    "plasma_radioactivity": "number", "pupil_size": "number",
    "respiratory": "number", "response_time": "number",
    "sampling_frequency": "number", "size": "number", "template_x": "number",
    "template_y": "number", "template_z": "number", "time": "number",
    "timestamp": "number", "trigger": "number", "wavelength_actual": "number",
    "wavelength_emission_actual": "number", "wavelength_nominal": "number",
    "whole_blood_radioactivity": "number", "x": "number",
    "x_coordinate": "number", "y": "number", "y_coordinate": "number",
    "z": "number",
    # integer
    "index": "integer", "mapping": "integer",
    # boolean
    "short_channel": "boolean",
    # datetime
    "acq_time": "datetime",
    # string
    "HED": "string", "abbreviation": "string", "channel": "string",
    "color": "string", "component": "string", "coordinate_system": "string",
    "derived_from": "string", "desc_id": "string", "description": "string",
    "detector": "string", "detector_type": "string", "dimension": "string",
    "filename": "string", "handedness": "string", "hemisphere": "string",
    "manufacturer": "string", "material": "string", "message": "string",
    "name": "string", "notch": "string", "participant_id": "string",
    "pathology": "string", "placement": "string",
    "placement_description": "string", "placement_scheme": "string",
    "reference": "string", "reference_frame": "string", "sample_id": "string",
    "sample_type": "string", "session_id": "string", "sex": "string",
    "signal_electrode": "string", "software_filters": "string",
    "source": "string", "source_type": "string", "species": "string",
    "status": "string", "status_description": "string", "stim_file": "string",
    "strain": "string", "strain_rrid": "string", "target_muscle": "string",
    "tracked_point": "string", "trial_type": "string", "type": "string",
    "units": "string", "volume_type": "string",

}

_ASCII = re.ASCII
_INT_RE = re.compile(r"[+-]?[0-9]+", _ASCII)
_NUMBER_RE = re.compile(
    r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", _ASCII
)
_DATE_PART = r"([0-9]{4})-([0-9]{2})-([0-9]{2})"
_TIME_PART = r"([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?"
_DATE_RE = re.compile(_DATE_PART, _ASCII)
_TIME_RE = re.compile(_TIME_PART, _ASCII)
_DATETIME_RE = re.compile(
    _DATE_PART + "T" + _TIME_PART + r"(Z|[+-][0-9]{2}:[0-9]{2})?", _ASCII
)


def _match(pattern: re.Pattern, text: str) -> re.Match:
    found = pattern.fullmatch(text)
    if found is None:
        raise ValueError(text)
    return found


def _parse_int(text: str) -> int:
    _match(_INT_RE, text)
    return int(text)


def _parse_float(text: str) -> float:
    _match(_NUMBER_RE, text)
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _parse_bool(text: str) -> bool:
    if text == "true":
        return True
    if text == "false":
        return False
    raise ValueError(text)


def _time_args(hour: str, minute: str, second: str, frac: str | None) -> tuple:
    micro = int((frac or "0").ljust(6, "0"))
    return int(hour), int(minute), int(second), micro


def _parse_date(text: str) -> date:
    return date(*map(int, _match(_DATE_RE, text).groups()))


def _parse_time(text: str) -> time:
    return time(*_time_args(*_match(_TIME_RE, text).groups()))


def _parse_datetime(text: str) -> datetime:
    parts = _match(_DATETIME_RE, text).groups()
    zone = parts[7]
    tzinfo = None
    if zone == "Z":
        tzinfo = timezone.utc
    elif zone:
        minutes = int(zone[1:3]) * 60 + int(zone[4:6])
        tzinfo = timezone(timedelta(minutes=-minutes if zone[0] == "-" else minutes))
    return datetime(
        *map(int, parts[:3]), *_time_args(*parts[3:7]), tzinfo=tzinfo
    )


_PARSERS: dict[str, Callable[[str], object]] = {
    STR: str,
    INT: _parse_int,
    FLOAT: _parse_float,
    BOOL: _parse_bool,
    DATE: _parse_date,
    DATETIME: _parse_datetime,
    TIME: _parse_time,
}


class ColumnSpec(NamedTuple):
    """How the values of one TSV column are typed."""

    kind: str
    """The Python type of a value (or of each item of a list): `STR`, ..."""
    delimiter: str | None = None
    """The `Delimiter` that splits a value into a list, or `None`."""


def _split(text: str, delimiter: str) -> list[str]:
    return [] if text == "" else text.split(delimiter)


def _parses(kind: str, texts: list[str]) -> bool:
    parse = _PARSERS[kind]
    try:
        for text in texts:
            parse(text)
    except ValueError:
        return False
    return True


def _infer(texts: list[str]) -> str:
    """Return the type of an undeclared column: `int`, `float` or `str`.

    Only a type that writes every value back as its exact text is used.
    """
    if not texts:
        return STR
    try:
        if all(str(_parse_int(t)) == t for t in texts):
            return INT
    except ValueError:
        pass
    try:
        if all(repr(_parse_float(t)) == t for t in texts):
            return FLOAT
    except ValueError:
        pass
    return STR


def _description(descriptions: Mapping | None, column: str) -> Mapping:
    if descriptions is None:
        return {}
    found = descriptions.get(column)
    return found if isinstance(found, Mapping) else {}


def column_specs(
    columns: Iterable[str],
    rows: list[Mapping[str, str | None]],
    descriptions: Mapping | None = None,
) -> dict[str, ColumnSpec]:
    """Return the type of each column of rows of text (see the module).

    `descriptions` maps a column name to its description (the table's
    JSON sidecar, or a `ChainMap` of its sidecars).
    """
    specs = {}
    for column in columns:
        description = _description(descriptions, column)
        delimiter = description.get("Delimiter")
        if not (isinstance(delimiter, str) and delimiter):
            delimiter = None
        texts: list[str] = []
        for row in rows:
            text = row.get(column)
            if text is None or text == NA:
                continue
            if delimiter is None:
                texts.append(text)
            else:
                texts.extend(t for t in _split(text, delimiter) if t != NA)
        if "Levels" in description:
            kind = STR
        else:
            declared = [
                _FORMATS.get(fmt, STR)
                for fmt in (description.get("Format"),
                            STANDARD_COLUMNS.get(column))
                if isinstance(fmt, str)
            ]
            kind = next(
                (k for k in declared if _parses(k, texts)), None
            ) or _infer(texts)
        specs[column] = ColumnSpec(kind, delimiter)
    return specs


def _convert(spec: ColumnSpec, text: str | None) -> object:
    """Return the value of one cell; `n/a` (or a missing cell) is `None`."""
    if text is None or text == NA:
        return None
    parse = _PARSERS[spec.kind]
    if spec.delimiter is None:
        return parse(text)
    return [
        None if item == NA else parse(item)
        for item in _split(text, spec.delimiter)
    ]


def format_value(
    value: object, delimiter: str | None = None, column: str | None = None
) -> str:
    """Return the text a TSV cell holding `value` is written with."""
    if value is None:
        return NA
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            # A missing value, as pandas holds it.
            return NA
        if math.isinf(value):
            raise ValueError(
                f"column {column!r} holds {value!r}, which a BIDS table "
                "cannot hold: write a finite number, or None for n/a"
            )
        return repr(float(value))
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        if delimiter is None:
            raise TypeError(
                f"column {column!r} holds a list, but its description has "
                "no Delimiter to join it with; set one in the table's JSON "
                "sidecar, or join the values into a string"
            )
        return delimiter.join(format_value(item, column=column) for item in value)
    return str(value)


# What `Table._match_text` records for a value written as `format_value`
# writes it, and for a value written two ways.
_CANONICAL, _AMBIGUOUS = object(), object()


def _value_key(value: object) -> tuple:
    """Return a hashable key for a cell value, equal where `_same` matches."""
    if isinstance(value, list):
        return ("list", tuple(_value_key(item) for item in value))
    return (type(value).__name__, repr(value))


def _held(value: object) -> object:
    """Return a cell value as the table's text record holds it (a list copied)."""
    return list(value) if isinstance(value, list) else value


def _same(value: object, original: object) -> bool:
    """Whether a cell still holds the value it was read with."""
    if type(value) is not type(original):
        return False
    if isinstance(value, list):
        return len(value) == len(original) and all(map(_same, value, original))
    return value == original


class Table(list):
    """A TSV table: a list of rows, each a `dict` of `column -> value`.

    It is a plain `list` of rows, plus the order of its columns, and is what
    a TSV file holds. Pass one to a TSV file's `write()` to give the order
    of the columns along with the rows.

    Edit it as a list (`append`, `del table[i]`, `table[i]["age"] = 31`)
    and with `add_column` and `drop_column`. A key that a row has and
    `columns` does not becomes a new, last column. When a table is written,
    a value read from the file and left unchanged keeps its exact text. Any
    other value is written from its type: `None`, a missing key or a float
    NaN as `n/a`, a `bool` as `true`/`false`, a `float` in its shortest
    `repr` form, a date or time in ISO 8601, a list joined with the
    column's `Delimiter` (from the table's JSON sidecar), and anything else
    as `str(value)`. A value whose text holds a tab or a line break, and an
    infinite float, cannot be written (`ValueError`).
    """

    def __init__(
        self,
        rows: Iterable[Mapping[str, object]] = (),
        columns: Iterable[str] | None = None,
        *,
        _origin: Table | None = None,
    ) -> None:
        if not isinstance(rows, Table):
            rows = list(rows)
        super().__init__(dict(row) for row in rows)
        if columns is None and isinstance(rows, Table):
            columns = rows.columns
        self._columns = list(columns or ())
        # `id(row) -> (row, {column: (value, text)})`: the text of the cells
        # read from a file that `format_value` would write differently, so
        # an unchanged cell is written back as it was. The row is kept, so
        # its id is not reused.
        self._text: dict[int, tuple[dict, dict[str, tuple[object, str]]]] = {}
        # `column -> Delimiter`, to join a list value.
        self._delimiters: dict[str, str] = {}
        # A copy keeps what its rows were read with: from the table they
        # are copied from, or the `_origin` table they were taken out of.
        sources = [t for t in (_origin, rows) if isinstance(t, Table)]
        for source in sources:
            self._delimiters.update(source._delimiters)
        for old, new in zip(rows, self):
            for source in sources:
                kept = source._original_text(old)
                if kept:
                    self._text[id(new)] = (new, dict(kept))
        if _origin is not None:
            self._match_text(_origin)

    def _match_text(self, origin: Table) -> None:
        """Keep the text of cells equal to the cells `origin` was read with.

        A row that is not one of `origin`'s own (a copy of it, say) has no
        text of its own. Each of its cells takes the text of the cell in the
        same place in `origin`, if that holds the same value, else the text
        every cell of the column that holds the value has in `origin`, if
        they all have the same.
        """
        texts: dict[str, dict[tuple, object]] = {}
        for row in origin:
            kept = origin._original_text(row)
            for column, value in row.items():
                text: object = _CANONICAL
                if column in kept and _same(value, kept[column][0]):
                    text = kept[column][1]
                seen = texts.setdefault(column, {})
                key = _value_key(value)
                seen[key] = text if seen.get(key, text) == text else _AMBIGUOUS
        for index, row in enumerate(self):
            kept = dict(self._original_text(row))
            place = (
                origin._original_text(origin[index])
                if index < len(origin) else {}
            )
            for column, value in row.items():
                if column in kept:
                    continue
                found = place.get(column)
                if found is not None and _same(value, found[0]):
                    kept[column] = found
                    continue
                text = texts.get(column, {}).get(_value_key(value))
                if isinstance(text, str):
                    kept[column] = (_held(value), text)
            if kept:
                self._text[id(row)] = (row, kept)

    def _original_text(self, row: dict) -> dict[str, tuple[object, str]]:
        kept = self._text.get(id(row))
        return kept[1] if kept is not None and kept[0] is row else {}

    @property
    def columns(self) -> list[str]:
        """The column names, in order (the header of the file)."""
        names = dict.fromkeys(self._columns)
        for row in self:
            for name in row:
                names.setdefault(name)
        return [name for name in names if name is not None]

    def add_column(
        self, name: str, values: Iterable[object] | None = None
    ) -> None:
        """Add a last column; `values` gives one value per row (else `n/a`).

        Raises
        ------
        ValueError
            If the column exists, or `values` has not one value per row.
        """
        if name in self.columns:
            raise ValueError(f"the table already has a column {name!r}")
        values = [None] * len(self) if values is None else list(values)
        if len(values) != len(self):
            raise ValueError(
                f"{len(values)} values for a column of {len(self)} rows"
            )
        self._columns = [*self.columns, name]
        for row, value in zip(self, values):
            row[name] = value

    def drop_column(self, name: str) -> None:
        """Remove a column from the header and from every row.

        Raises
        ------
        KeyError
            If the table has no such column.
        """
        if name not in self.columns:
            raise KeyError(name)
        self._columns = [c for c in self.columns if c != name]
        for row in self:
            row.pop(name, None)

    def _set_column(self, name: str, values: list) -> None:
        """Set the values of a column, adding it last if it is new.

        A table with no column yet gets one row per value.

        Raises
        ------
        ValueError
            If `values` has not one value per row.
        """
        if not self and not self.columns:
            self.extend({} for _ in values)
        if len(values) != len(self):
            raise ValueError(
                f"column {name!r} is given {len(values)} values, but the "
                f"table has {len(self)} rows: give one value per row"
            )
        if name not in self.columns:
            self._columns = [*self.columns, name]
        for row, value in zip(self, values):
            row[name] = value

    def __repr__(self) -> str:
        return f"Table({list(self)!r}, columns={self.columns!r})"

    def _snapshot(self) -> Callable[[], None]:
        """Return a function that puts this table back as it is now, in place.

        Its rows are the same objects again, with their values as now.
        """
        rows = [(row, copy.deepcopy(dict(row))) for row in self]
        columns = list(self._columns)
        text = {key: (row, dict(kept)) for key, (row, kept) in self._text.items()}
        delimiters = dict(self._delimiters)

        def restore() -> None:
            for row, values in rows:
                row.clear()
                row.update(values)
            self[:] = [row for row, _ in rows]
            self._columns = columns
            self._text = text
            self._delimiters = delimiters

        return restore


# -- JSON --------------------------------------------------------------------------

def _without_bom(text: str) -> str:
    return text[1:] if text.startswith(BOM) else text


def parse_json(text: str) -> object:
    """Parse the text of a JSON file (a leading byte-order mark is skipped)."""
    return json.loads(_without_bom(text))


def dump_json(content: object) -> str:
    """Return the text a JSON file is written with (4-space indent)."""
    return json.dumps(content, indent=4, ensure_ascii=False) + "\n"


def json_object(path: object, content: object) -> dict:
    """Return `content`, checked to be a JSON object."""
    if not isinstance(content, dict):
        raise TypeError(f"{path!s} does not hold a JSON object")
    return content


def copy_json(content: object) -> object:
    """Return a deep copy of `content`, which must be JSON-serializable."""
    return json.loads(json.dumps(content))


# -- TSV ---------------------------------------------------------------------------

def delimiters(descriptions: Mapping | None) -> dict[str, str]:
    """Return the `Delimiter` of each column that `descriptions` gives one."""
    found = {}
    for column, description in (descriptions or {}).items():
        if isinstance(description, Mapping):
            delimiter = description.get("Delimiter")
            if isinstance(delimiter, str) and delimiter:
                found[column] = delimiter
    return found


def _text_rows(text: str) -> tuple[list[dict[str, str | None]], list[str]]:
    # BIDS tables have no quoting: a quote is a character of its cell.
    reader = csv.DictReader(
        io.StringIO(_without_bom(text)), delimiter="\t",
        quoting=csv.QUOTE_NONE,
    )
    rows = list(reader)
    return rows, list(reader.fieldnames or ())


def new_table(
    descriptions: Mapping | None = None, columns: Iterable[str] = ()
) -> Table:
    """Return an empty `Table` that knows the `Delimiter`s `descriptions` give.

    Every column the descriptions give a `Delimiter` is known, whether the
    table has it yet or not, so a list added later can be written.
    """
    table = Table(columns=columns)
    table._delimiters = delimiters(descriptions)
    return table


def parse_tsv(
    text: str, descriptions: Mapping | None = None, *, raw: bool = False
) -> Table:
    """Parse the text of a TSV file into a `Table` of typed values.

    `descriptions` maps a column to its description (the table's JSON
    sidecar); see the module for how a column is typed. With `raw`, every
    value is its exact text, `n/a` included.
    """
    rows, columns = _text_rows(text)
    if raw:
        return Table(rows, columns=columns)
    specs = column_specs(columns, rows, descriptions)
    table = new_table(descriptions, columns)
    for cells in rows:
        row: dict = {}
        kept = {}
        for key, cell in cells.items():
            spec = specs.get(key)
            if spec is None:
                # The cells past the header of a too-long row.
                row[key] = cell
                continue
            value = row[key] = _convert(spec, cell)
            if cell is not None and format_value(value, spec.delimiter) != cell:
                kept[key] = (_held(value), cell)
        table.append(row)
        if kept:
            table._text[id(row)] = (row, kept)
    return table


def dump_tsv(table: Table) -> str:
    """Return the text a TSV file is written with.

    An unchanged cell read from a file keeps its text; any other value is
    written from its type (see `Table`).
    """
    if not isinstance(table, Table):
        table = Table(table)
    columns = table.columns
    lines = ["\t".join(
        _check_cell(str(column), column, None) for column in columns
    )]
    for index, row in enumerate(table):
        kept = table._original_text(row)
        cells = []
        for column in columns:
            value = row.get(column)
            original = kept.get(column)
            if original is not None and _same(value, original[0]):
                cells.append(original[1])
            else:
                cells.append(_check_cell(format_value(
                    value, table._delimiters.get(column), column
                ), column, index))
        if cells == [""]:
            # A blank line, which a reader skips: the row would be lost.
            raise ValueError(
                f"row {index} of column {columns[0]!r} is an empty string, "
                "which a table of one column cannot hold (its line would be "
                "blank); write None for n/a"
            )
        lines.append("\t".join(cells))
    return "\n".join(lines) + "\n"


def _check_cell(text: str, column: object, row: int | None) -> str:
    """Return `text`, checked to fit in one cell of a BIDS table."""
    if _SEPARATORS.search(text):
        where = "the column name" if row is None else (
            f"row {row} of column {column!r}"
        )
        raise ValueError(
            f"{where} holds a tab or a line break ({text!r}), which a BIDS "
            "table cannot hold: it has no quoting; replace them, e.g. with "
            "spaces"
        )
    return text


def _typed_series(series: Series, spec: ColumnSpec) -> Series:
    """Return a column of text read by pandas, typed as `spec` says."""
    import pandas

    values = [
        _convert(spec, v) if isinstance(v, str) else None for v in series
    ]
    missing = any(v is None for v in values)
    dtypes = {
        INT: "Int64" if missing else "int64",
        FLOAT: "float64",
        BOOL: "boolean" if missing else "bool",
    }
    dtype = None if spec.delimiter else dtypes.get(spec.kind)
    try:
        if dtype is not None:
            return pandas.Series(values, index=series.index, dtype=dtype,
                                 name=series.name)
        typed = pandas.Series(values, index=series.index, dtype=object,
                              name=series.name)
        if spec.kind == DATETIME and not spec.delimiter:
            return pandas.to_datetime(typed)
        return typed
    except (TypeError, ValueError, OverflowError):
        # Out of range for the dtype, or mixed time zones.
        return pandas.Series(values, index=series.index, dtype=object,
                             name=series.name)


def tsv_dataframe(
    text: str, kwargs: dict, descriptions: Mapping | None = None
) -> DataFrame:
    """Read the text of a TSV file as a `pandas.DataFrame`.

    The columns are typed as `parse_tsv` types them, unless `kwargs` sets
    `dtype` or `converters` (then pandas types them as asked).
    """
    try:
        import pandas
    except ImportError:
        raise ImportError(
            "as_dataframe() needs pandas; install it, or use as_list() "
            "for a list of rows"
        ) from None
    text = _without_bom(text)
    options: dict = {
        "sep": "\t", "na_values": [NA], "keep_default_na": False,
        "quoting": csv.QUOTE_NONE,
    }
    typed = "dtype" not in kwargs and "converters" not in kwargs
    if typed:
        options["dtype"] = str
    options.update(kwargs)
    frame = pandas.read_csv(io.StringIO(text), **options)
    if typed:
        rows, columns = _text_rows(text)
        specs = column_specs(columns, rows, descriptions)
        for column in frame.columns:
            spec = specs.get(column)
            if spec is not None and (spec.kind != STR or spec.delimiter):
                frame[column] = _typed_series(frame[column], spec)
    return frame


# -- by kind -----------------------------------------------------------------------

def parse(
    kind: str, text: str | None, descriptions: Mapping | None = None
) -> object:
    """Parse a file of `kind`; `None` (no file yet) is empty content.

    `descriptions` types the columns of a TSV file (see `parse_tsv`).
    """
    if kind == JSON:
        return {} if text is None else parse_json(text)
    if text is None:
        return new_table(descriptions)
    return parse_tsv(text, descriptions)


def dump(kind: str, content: object) -> str:
    """Return the text a file of `kind` is written with."""
    return dump_json(content) if kind == JSON else dump_tsv(content)
