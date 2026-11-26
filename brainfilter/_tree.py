"""Read-only dataset tree: child access, file contents and sidecar metadata.

These mixins give `BidsPath` and its file classes a dict-like, read-only
surface:

- a directory maps child names to paths: `dataset["sub-01"]["anat"]`;
- a JSON file maps its keys to values: `sidecar["RepetitionTime"]`, and
  `sidecar.read()` returns the whole object as a `dict`;
- a TSV file reads as rows: `table.read()` is a list of `dict`, one per row,
  and `table.read_dataframe()` a `pandas.DataFrame` (pandas is optional);
- any file's effective metadata, `data.metadata`, is a
  `collections.ChainMap` of the JSON sidecars that apply to it, nearest
  first, up to the dataset root.

Writing is not supported here: it will come with transactions.
"""
from __future__ import annotations

import csv
import io
import json
from collections import ChainMap
from collections.abc import ItemsView, Iterator, KeysView, ValuesView
from typing import TYPE_CHECKING, NoReturn

from brainfilter._names import applies_to, parse_name

if TYPE_CHECKING:
    from pandas import DataFrame
    from typing_extensions import Self

__all__ = ["DATASET_DESCRIPTION", "JSONContentMixin", "TSVContentMixin",
           "TreeMixin"]

DATASET_DESCRIPTION = "dataset_description.json"

# Missing-value marker of BIDS tables.
_NA = "n/a"


def _read_only(obj: object) -> TypeError:
    return TypeError(
        f"{type(obj).__name__} is read-only: writing through the dataset "
        "tree is not supported yet (it will come with transactions)"
    )


class TreeMixin:
    """A directory as a read-only mapping `child name -> path`.

    Indexing, `in`, `keys()`, `values()`, `items()` and iteration list the
    directory each time they are called; nothing is cached.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        name: str
        parent: Self
        parents: tuple[Self, ...]
        suffix: str | None

        def iterdir(self) -> Iterator[Self]: ...  # noqa: D102
        def exists(self) -> bool: ...  # noqa: D102
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102
        def __truediv__(self, other: object) -> Self: ...  # noqa: D105

    # -- mapping of children -------------------------------------------------
    def __getitem__(self, name: str) -> Self:
        """Return the child called `name`; `KeyError` if there is none."""
        if not isinstance(name, str) or not name or "/" in name:
            raise KeyError(name)
        child = self / name
        if not child.exists():
            raise KeyError(name)
        return child

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.keys()

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def keys(self) -> list[str]:
        """Return the names of the children, sorted."""
        return sorted(child.name for child in self.iterdir())

    def values(self) -> list[Self]:
        """Return the children, sorted by name."""
        return sorted(self.iterdir(), key=lambda child: child.name)

    def items(self) -> list[tuple[str, Self]]:
        """Return `(name, child)` pairs, sorted by name."""
        return [(child.name, child) for child in self.values()]

    def get(self, name: str, default: object = None) -> object:
        """Return the child called `name`, or `default`."""
        try:
            return self[name]
        except KeyError:
            return default

    def __setitem__(self, name: str, value: object) -> None:
        raise _read_only(self)

    def __delitem__(self, name: str) -> None:
        raise _read_only(self)

    # -- sidecar inheritance -------------------------------------------------
    @property
    def metadata(self) -> ChainMap:
        """The effective metadata of this file; see `read_metadata`."""
        return self.read_metadata()

    def sidecars(self, root: object = None) -> list[Self]:
        """Return the JSON sidecars that apply to this file, nearest first.

        A sidecar applies when it is a `.json` file with the same BIDS
        suffix, its entities are a subset of this file's (same labels), and
        it is in this file's directory or an ancestor up to the dataset
        root (BIDS inheritance). Within one directory, a sidecar with more
        entities comes first.

        Parameters
        ----------
        root
            The dataset root. By default, the nearest ancestor that holds a
            `dataset_description.json`.

        Raises
        ------
        ValueError
            If no dataset root is found, or `root` is not an ancestor.
        """
        if self.suffix is None:
            return []
        root_path = None if root is None else self._as_root(root)
        # Each directory is listed once; `levels` runs from the file's own
        # directory up to the root.
        levels: list[tuple[Self, set[str]]] = []
        for directory in self.parents:
            names = self._list_names(directory)
            levels.append((directory, names))
            if directory == root_path if root_path is not None else (
                DATASET_DESCRIPTION in names
            ):
                break
        else:
            if root_path is not None:
                raise ValueError(f"{root!s} is not an ancestor of {self!s}")
            raise ValueError(
                f"no dataset root above {self!s}: no ancestor holds a "
                f"{DATASET_DESCRIPTION}; pass root= explicitly"
            )

        # Paths relative to the root, as `applies_to` expects.
        dirs = [d.name for d, _ in levels[:-1]]
        rel_dirs = ["/".join(reversed(dirs[i:])) for i in range(len(dirs))]
        rel_dirs.append("")
        data_rel = f"{rel_dirs[0]}/{self.name}".lstrip("/")

        found = []
        for (directory, names), rel_dir in zip(levels, rel_dirs):
            level = []
            for name in names:
                parsed = parse_name(name)
                if parsed.extension != ".json" or parsed.suffix is None:
                    continue
                if directory == self.parent and name == self.name:
                    continue
                meta_rel = f"{rel_dir}/{name}".lstrip("/")
                if applies_to(meta_rel, data_rel, companions=False):
                    level.append((-len(parsed.entities), name))
            found.extend(directory / name for _, name in sorted(level))
        return found

    def read_metadata(self, root: object = None) -> ChainMap:
        """Read the effective metadata of this file, as a `ChainMap`.

        Its maps are the contents of `sidecars(root)`, nearest first, so a
        key is looked up in the nearest sidecar that has it. The maps are
        read when this is called; they are not kept in sync with the files.
        """
        return ChainMap(*(sidecar.read() for sidecar in self.sidecars(root)))

    def _as_root(self, root: object) -> Self:
        return self._root(root)  # type: ignore[attr-defined]

    @staticmethod
    def _list_names(directory: TreeMixin) -> set[str]:
        try:
            return {child.name for child in directory.iterdir()}
        except OSError:
            return set()


class JSONContentMixin:
    """A JSON file as a read-only mapping of its top-level keys.

    Every lookup reads the file again; call `read()` once to work on the
    content as a plain `dict`.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    def read(self) -> object:
        """Read and parse the file (a `dict` for a BIDS JSON file)."""
        return json.loads(self.read_text(encoding="utf-8"))

    def _mapping(self) -> dict:
        content = self.read()
        if not isinstance(content, dict):
            raise TypeError(f"{self!s} does not hold a JSON object")
        return content

    def __getitem__(self, key: str) -> object:
        return self._mapping()[key]

    def __contains__(self, key: object) -> bool:
        return key in self._mapping()

    def __iter__(self) -> Iterator[str]:
        return iter(self._mapping())

    def keys(self) -> KeysView[str]:
        """Return the keys of the JSON object."""
        return self._mapping().keys()

    def values(self) -> ValuesView[object]:
        """Return the values of the JSON object."""
        return self._mapping().values()

    def items(self) -> ItemsView[str, object]:
        """Return the `(key, value)` pairs of the JSON object."""
        return self._mapping().items()

    def get(self, key: str, default: object = None) -> object:
        """Return the value of `key`, or `default`."""
        return self._mapping().get(key, default)


class TSVContentMixin:
    """A TSV table, read as rows."""

    __slots__ = ()

    if TYPE_CHECKING:
        def read_text(self, encoding: str | None = None) -> str: ...  # noqa: D102

    def read(self) -> list[dict[str, str | None]]:
        """Read the table as a list of rows, `column -> value`.

        Values are strings, and the BIDS missing value `n/a` reads as
        `None`.
        """
        text = self.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        return [
            {k: (None if v == _NA else v) for k, v in row.items()}
            for row in reader
        ]

    def read_dataframe(self, **kwargs: object) -> DataFrame:
        """Read the table as a `pandas.DataFrame` (needs pandas).

        `n/a` reads as a missing value. Keywords go to `pandas.read_csv`.
        """
        try:
            import pandas
        except ImportError:
            raise ImportError(
                "read_dataframe needs pandas; install it, or use read() "
                "for a list of rows"
            ) from None
        options = {"sep": "\t", "na_values": [_NA], "keep_default_na": False}
        options.update(kwargs)
        return pandas.read_csv(io.StringIO(self.read_text(encoding="utf-8")),
                               **options)

    def __getitem__(self, key: object) -> NoReturn:
        raise TypeError(
            f"{type(self).__name__} is a table: use read() for its rows"
        )

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        return iter(self.read())
