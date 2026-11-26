"""The contents of BIDS JSON and TSV files: parsing, writing, and `Table`.

Everything here is pure (no I/O), so the sync and async families, and the
transactions that buffer their edits, share it.
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandas import DataFrame

__all__ = ["Table"]

# Missing-value marker of BIDS tables.
NA = "n/a"

JSON = "json"
TSV = "tsv"


class Table(list):
    """A TSV table: a list of rows, each a `dict` of `column -> value`.

    It is a plain `list` of rows, plus the order of its columns. Values read
    from a file are strings, and the BIDS missing value `n/a` is `None`.

    Edit it as a list (`append`, `del table[i]`, `table[i]["age"] = "31"`)
    and with `add_column` and `drop_column`. A key that a row has and
    `columns` does not becomes a new, last column. When the table is
    written, a value of `None` or a missing key becomes `n/a`, and any other
    value is written as `str(value)`.
    """

    def __init__(
        self,
        rows: Iterable[Mapping[str, object]] = (),
        columns: Iterable[str] | None = None,
    ) -> None:
        super().__init__(dict(row) for row in rows)
        if columns is None and isinstance(rows, Table):
            columns = rows.columns
        self._columns = list(columns or ())

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

    def __repr__(self) -> str:
        return f"Table({list(self)!r}, columns={self.columns!r})"


# -- JSON --------------------------------------------------------------------------

def parse_json(text: str) -> object:
    """Parse the text of a JSON file."""
    return json.loads(text)


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

def parse_tsv(text: str) -> Table:
    """Parse the text of a TSV file; `n/a` reads as `None`."""
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows = [
        {k: (None if v == NA else v) for k, v in row.items()}
        for row in reader
    ]
    return Table(rows, columns=reader.fieldnames or ())


def dump_tsv(table: Table) -> str:
    """Return the text a TSV file is written with (`None` as `n/a`)."""
    columns = table.columns
    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(columns)
    for row in table:
        writer.writerow(
            NA if row.get(c) is None else str(row[c]) for c in columns
        )
    return out.getvalue()


def tsv_dataframe(text: str, kwargs: dict) -> DataFrame:
    """Read the text of a TSV file as a `pandas.DataFrame`."""
    try:
        import pandas
    except ImportError:
        raise ImportError(
            "read_dataframe needs pandas; install it, or use read() "
            "for a list of rows"
        ) from None
    options = {"sep": "\t", "na_values": [NA], "keep_default_na": False}
    options.update(kwargs)
    return pandas.read_csv(io.StringIO(text), **options)


# -- by kind -----------------------------------------------------------------------

def parse(kind: str, text: str | None) -> object:
    """Parse a file of `kind`; `None` (no file yet) is empty content."""
    if kind == JSON:
        return {} if text is None else parse_json(text)
    return Table() if text is None else parse_tsv(text)


def dump(kind: str, content: object) -> str:
    """Return the text a file of `kind` is written with."""
    return dump_json(content) if kind == JSON else dump_tsv(content)
