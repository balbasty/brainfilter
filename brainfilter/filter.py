"""Select a subset of a BIDS dataset from its file listing.

A [`Filter`][brainfilter.filter.Filter] works on paths relative to the
dataset root only, so it applies to any listing (OpenNeuro, S3, a local
directory, ...) before anything is downloaded::

    >>> f = Filter(subjects=["01"], datatypes="anat", acq="mprage")
    >>> f.select(listing)                       # relative path strings
    >>> f.walk("s3://openneuro.org/ds000224")   # list a dataset, then select
    >>> await f.awalk("s3://openneuro.org/ds000224")  # ... asynchronously

Selection rules
---------------
1. *Data files* are files inside `sub-*/` that are not metadata (see
   `METADATA_EXTENSIONS`). They are kept if they pass every filter:
   subjects, sessions, datatypes, suffixes, tasks, other entities and the
   `include` patterns.
2. *Metadata files* (`.json`, `.tsv`, `.bval`, `.bvec`), wherever they are,
   are kept if they apply to at least one kept data file under the BIDS
   inheritance principle (see `brainfilter._names.applies_to`).
3. Dataset-level files (`dataset_description.json`, `participants.tsv`,
   `README`, `CHANGES`, `.bidsignore`, ...), other top-level files that are
   not sidecars, and `phenotype/` are always kept. Top-level sidecars
   (`T1w.json`, `task-rest_bold.json`) follow rule 2.
4. `derivatives/`, `sourcedata/`, `code/` and `stimuli/` are skipped unless
   requested with `folders`. Hidden files and folders (`.datalad/`,
   `.gitattributes`, ...) and other top-level folders are always skipped.
5. Last, the `exclude` patterns remove any kept file but
   `dataset_description.json`.

Matching values
---------------
Each filter takes a plain value (matched exactly), a list of values (any of
them), a glob ([`Glob`][brainfilter.conditions.Glob]), a regex (a
`re.Pattern` or [`Regex`][brainfilter.conditions.Regex], which must match
the whole label: `re.compile("1")` matches `sub-1` but not `sub-10`) or any
other [`Condition`][brainfilter.conditions.Condition]. Plain labels may keep
their `<key>-` prefix (`"sub-01"` is `"01"`); a pattern is matched against
the bare label.

Index entities (`run`, `echo`, `flip`, `inv`, `split`, `chunk`; see
`brainfilter._names.INDEX_ENTITIES`) compare plain values by number:
`run=1`, `run="1"` and `run="01"` all match `run-1` and `run-01`. A glob or
regex on an index entity matches its label as written in the file name.
Other entities compare plain values as exact strings.

The `include`/`exclude` patterns are matched against the relative path
instead, and a regex there is found anywhere in it (`re.search`) unless
anchored.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from typing import TypeVar

from brainfilter._names import (
    INDEX_ENTITIES,
    OPTIONAL_FOLDERS,
    SORTED_ENTITIES,
    TOP_LEVEL_FILES,
    ParsedPath,
    applies_to,
    parse_path,
)
from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.conditions import And, Condition, Or, Regex

__all__ = ["Filter"]

T = TypeVar("T")

# Never removed by `exclude`.
_PROTECTED = frozenset({"dataset_description.json"})

# Filter keywords that are entity filters under another name.
_ALIASES = {"subjects": "sub", "sessions": "ses", "tasks": "task"}


def _is_many(value: object) -> bool:
    return isinstance(value, (list, tuple, set, frozenset))


def _whole_label(cond: Condition) -> Condition:
    """Make the regexes in `cond` match a whole label (`re.fullmatch`)."""
    if isinstance(cond, Regex):
        return cond if cond.full else Regex(cond.pattern, full=True)
    if type(cond) in (And, Or):
        return type(cond)(*map(_whole_label, cond.cond))
    return cond


def _as_condition(value: object) -> Condition | None:
    if isinstance(value, Condition):
        return _whole_label(value)
    if isinstance(value, re.Pattern):
        return Regex(value, full=True)
    return None


def _index(value: str) -> int | str:
    """Return the value of an index label (`"01"` is `1`); others as is."""
    return int(value) if value.isascii() and value.isdigit() else value


def _matcher(
    value: object, key: str | None, index: bool = False
) -> Callable[[object], bool] | None:
    """Build `label -> bool` from a filter value; `None` keeps everything.

    A plain value loses its `<key>-` prefix (when `key` is given). With
    `index`, plain values and labels compare by number. Conditions see the
    label as written; a regex must match all of it.
    """
    if value is None:
        return None
    values = list(value) if _is_many(value) else [value]
    if not values:
        return None
    exact: set[str] = set()
    conditions: list[Condition] = []
    for item in values:
        cond = _as_condition(item)
        if cond is not None:
            conditions.append(cond)
            continue
        item = str(item)
        if key and item.startswith(key + "-"):
            item = item[len(key) + 1:]
        exact.add(_index(item) if index else item)

    def match(label: object) -> bool:
        if label is None:
            return False
        value = _index(str(label)) if index else label
        return value in exact or any(cond(label) for cond in conditions)

    return match


def _patterns(value: object) -> Condition | None:
    """Coerce include/exclude patterns to one any-of condition.

    A string is a glob, a `re.Pattern` a regex.
    """
    if value is None:
        return None
    values = list(value) if _is_many(value) else [value]
    if not values:
        return None
    return Or(*values)


class Filter:
    """Filters applied to a BIDS listing. Empty filters select everything.

    Label filters (subjects, sessions, tasks, datatypes, suffixes, other
    entities) match the bare label of each file. A plain value matches
    exactly, and on an index entity (`run`, `echo`, ...) by number, so
    `run=1` matches `run-01`. A regex must match the whole label
    (`re.fullmatch`): `subjects=re.compile("1")` keeps `sub-1`, not
    `sub-10`. A glob or regex on an index entity sees the label as written.

    Path filters (`include`, `exclude`) match the path relative to the
    dataset root. A glob must match the whole path (`fnmatch`); a regex is
    found anywhere in it (`re.search`) unless anchored.

    Parameters
    ----------
    subjects, exclude_subjects, sessions, datatypes, suffixes, tasks
        Keep data files whose subject, session, datatype directory, BIDS
        suffix or task match (`exclude_subjects`: whose subject does not).
    include, exclude
        Patterns matched against the path relative to the dataset root
        (a string is a glob, a `re.Pattern` a regex; a list is any-of).
        `include` selects data files; `exclude` removes any kept file but
        `dataset_description.json`.
    folders
        Optional top-level folders to keep, among `derivatives`,
        `sourcedata`, `code` and `stimuli`. They are kept whole.
    entities
        Filters on any other entity, `{key: value}`.
    **kwargs
        Filters on a known BIDS entity (`acq="mprage"`, `run=[1, 2]`,
        `sub=...`, ...).

    See the module documentation for the selection rules and the values a
    filter takes.
    """

    def __init__(
        self,
        *,
        subjects: object = None,
        exclude_subjects: object = None,
        sessions: object = None,
        datatypes: object = None,
        suffixes: object = None,
        tasks: object = None,
        include: object = None,
        exclude: object = None,
        folders: Iterable[str] = (),
        entities: dict | None = None,
        **kwargs: object,
    ) -> None:
        unknown = set(kwargs) - set(SORTED_ENTITIES)
        if unknown:
            raise TypeError(
                f"Filter got unknown keywords {', '.join(sorted(unknown))}; "
                "filter on another entity with entities={key: value}"
            )
        given = dict(entities or {})
        for name, value in kwargs.items():
            if name in given:
                raise TypeError(f"Filter got two filters for entity {name!r}")
            given[name] = value
        for name, key in _ALIASES.items():
            value = {"subjects": subjects, "sessions": sessions,
                     "tasks": tasks}[name]
            if value is None:
                continue
            if key in given:
                raise TypeError(
                    f"Filter got both {name}= and a filter on entity {key!r}"
                )
            given[key] = value

        self.entities: dict[str, Callable[[object], bool]] = {}
        for key, value in given.items():
            match = _matcher(value, str(key), str(key) in INDEX_ENTITIES)
            if match is not None:
                self.entities[str(key)] = match
        self.exclude_subjects = _matcher(exclude_subjects, "sub")
        self.datatypes = _matcher(datatypes, None)
        self.suffixes = _matcher(suffixes, None)
        self.include = _patterns(include)
        self.exclude = _patterns(exclude)
        if isinstance(folders, str):
            folders = [folders]
        self.folders = frozenset(folders)
        unknown = self.folders - set(OPTIONAL_FOLDERS)
        if unknown:
            raise ValueError(
                f"Unknown optional folders: {', '.join(sorted(unknown))}; "
                f"expected some of {', '.join(OPTIONAL_FOLDERS)}"
            )

    # -- single files --------------------------------------------------------
    def keep_data(self, path: object) -> bool:
        """Whether a data file passes every filter (path relative to root)."""
        name = parse_path(path)
        ent = name.entities
        for key, match in self.entities.items():
            if not match(ent.get(key)):
                return False
        if self.exclude_subjects and self.exclude_subjects(ent.get("sub")):
            return False
        if self.datatypes and not self.datatypes(name.datatype):
            return False
        if self.suffixes and not self.suffixes(name.suffix):
            return False
        if self.include and not self.include(name.path):
            return False
        return True

    def keep_subject(self, label: str) -> bool:
        """Whether a subject (`"01"` or `"sub-01"`) passes the subject filters."""
        label = str(label)
        if label.startswith("sub-"):
            label = label[4:]
        match = self.entities.get("sub")
        if match and not match(label):
            return False
        return not (self.exclude_subjects and self.exclude_subjects(label))

    # -- listings ------------------------------------------------------------
    def select(self, paths: Iterable[T], root: object = None) -> list[T]:
        """Return the subset of `paths` to keep, sorted by relative path.

        Parameters
        ----------
        paths
            Paths relative to the dataset root (`/`-separated strings), or
            path objects (`BidsPath`, `PureBidsPath`, ...). With `root`,
            path objects are made relative to it first.
        root
            The dataset root the path objects are under.

        Returns
        -------
        list
            The kept items of `paths`, as given, without duplicates.
        """
        items: dict[str, T] = {}
        for path in paths:
            rel = _relative(path, root)
            items.setdefault(rel, path)
        return [items[rel] for rel in self._select(items)]

    def walk(self, root: object) -> list[BidsPath]:
        """List a dataset and return the files to keep, sorted.

        `root` is a `BidsPath`, a path object, or a local path or URL
        string. Hidden folders and the top-level folders that would be
        skipped are not listed.
        """
        root = root if isinstance(root, BidsPath) else BidsPath(root)
        found: dict[str, BidsPath] = {}
        for dirpath, dirnames, filenames in root.walk():
            self._visit(root, found, dirpath, dirnames, filenames)
        return [found[rel] for rel in self._select(found)]

    async def awalk(self, root: object) -> list[AsyncBidsPath]:
        """List a dataset asynchronously and return the files to keep, sorted.

        The coroutine counterpart of `walk`: `root` is an `AsyncBidsPath`,
        a path object, or a local path or URL string, and the files are
        `AsyncBidsPath` objects. On a remote store with a natively async
        backend the listing runs on its coroutines; there, folders that
        would be skipped may still be listed, but are never kept.
        """
        root = root if isinstance(root, AsyncBidsPath) else AsyncBidsPath(root)
        found: dict[str, AsyncBidsPath] = {}
        async for dirpath, dirnames, filenames in root.walk():
            self._visit(root, found, dirpath, dirnames, filenames)
        return [found[rel] for rel in self._select(found)]

    def __call__(self, paths: Iterable[T], root: object = None) -> list[T]:
        """Alias of `select`."""
        return self.select(paths, root)

    # -- engine --------------------------------------------------------------
    def _visit(
        self,
        root: T,
        found: dict[str, T],
        dirpath: T,
        dirnames: list[str],
        filenames: list[str],
    ) -> None:
        """Record one directory of a walk in `found`; prune `dirnames`."""
        # From the parts: a remote async path spells a relative path as a URL
        rel = dirpath.relative_to(root)  # type: ignore[attr-defined]
        rel_dir = PurePosixPath(*rel.parts)
        top = rel_dir == PurePosixPath(".")
        dirnames[:] = [d for d in dirnames if self._descend(d, top)]
        for filename in filenames:
            rel = (rel_dir / filename).as_posix()
            found[rel] = dirpath / filename  # type: ignore[operator]

    def _descend(self, name: str, top: bool) -> bool:
        """Whether `walk` lists a directory (pruning never changes a result)."""
        if name.startswith("."):
            return False
        if not top:
            return True
        return (
            name.startswith("sub-") or name == "phenotype"
            or name in self.folders
        )

    def _select(self, paths: Iterable[str]) -> list[str]:
        """Select among relative path strings; return them sorted."""
        data: list[ParsedPath] = []
        meta: list[ParsedPath] = []
        kept: set[str] = set()
        for path in paths:
            parts = PurePosixPath(path).parts
            if not parts:
                continue
            if path in TOP_LEVEL_FILES:
                kept.add(path)
                continue
            if any(p.startswith(".") for p in parts):
                continue
            top = parts[0]
            if len(parts) > 1 and top in OPTIONAL_FOLDERS:
                if top in self.folders:
                    kept.add(path)
                continue
            name = parse_path(path)
            if top.startswith("sub-") and len(parts) > 1:
                (meta if name.is_metadata else data).append(name)
            elif top == "phenotype":
                kept.add(path)
            elif len(parts) == 1:
                if name.is_metadata and name.suffix:
                    # top-level sidecar: T1w.json, task-rest_bold.json
                    meta.append(name)
                else:
                    kept.add(path)
            # other top-level folders (e.g. "models/") are skipped

        kept_data = [d for d in data if self.keep_data(d)]
        kept.update(d.path for d in kept_data)

        # Inheritance closure: index kept data by directory ancestors
        by_dir: dict[PurePosixPath, list[ParsedPath]] = {}
        for d in kept_data:
            for parent in (d.directory, *d.directory.parents):
                by_dir.setdefault(parent, []).append(d)
        for m in meta:
            if any(applies_to(m, d) for d in by_dir.get(m.directory, ())):
                kept.add(m.path)

        if self.exclude:
            kept = {p for p in kept if p in _PROTECTED or not self.exclude(p)}
        return sorted(kept)


def _relative(path: object, root: object) -> str:
    """Return `path` relative to `root` (if given), `/`-separated."""
    if isinstance(path, str) and root is None:
        return PurePosixPath(path).as_posix()
    if root is not None:
        if isinstance(root, str):
            root = BidsPath(root)
        if isinstance(path, str):
            path = BidsPath(path)
        path = path.relative_to(root)  # type: ignore[attr-defined]
    as_posix = getattr(path, "as_posix", None)
    return PurePosixPath(as_posix() if as_posix else str(path)).as_posix()
