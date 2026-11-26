"""Select a subset of a BIDS dataset from its file listing.

A [`Filter`][brainfilter.Filter] works on paths relative to the
dataset root only, so it applies to any listing (OpenNeuro, S3, a local
directory, ...) before anything is downloaded::

    >>> f = Filter(subjects=["01"], datatypes="anat", acq="mprage")
    >>> f.select(listing)                       # relative path strings
    >>> f.walk("s3://openneuro.org/ds000224")   # list a dataset, then select
    >>> await f.awalk("s3://openneuro.org/ds000224")  # ... asynchronously

Selection rules
---------------
The input is a listing of files; see `Filter.select` for directories.

1. *Data files* are files inside `sub-*/` that are not metadata. They are
   kept if they pass every filter: subjects, sessions, datatypes, suffixes,
   tasks, other entities and the `include` patterns. A table that is a
   recording (`*_beh.tsv`, `*_motion.tsv`, `*_blood.tsv`) is a data file,
   and so is a continuous recording (`*_physio.tsv.gz`). A data file that
   is a directory (a CTF MEG `*_meg.ds/`, an OME-Zarr `*.ome.zarr/`) is one
   data item: every file inside it is kept or skipped with it, judged on
   the directory's name and datatype.
2. *Metadata files* (`.json`, `.tsv`, `.bval`, `.bvec`), wherever they are,
   are kept if they apply to at least one kept data file under the BIDS
   inheritance principle. So is a data file that is also a companion of
   another (`*_physio.tsv.gz` of a `*_bold.nii.gz`) and does not pass the
   filters itself.
3. A metadata file that applies to no data file of the listing at all
   (`beh/*_events.tsv` alone, `electrodes.tsv` of a session with no
   recording) is judged on what it names: it is kept if its subject,
   session, datatype, suffix and path pass the filters, and the entity
   filters for the entities it has. An entity filter on an entity it does
   not have passes. So an empty `Filter()` keeps every file that rule 5
   does not skip.
4. Dataset-level files (`dataset_description.json`, `participants.tsv`,
   `README`, `CHANGES`, `.bidsignore`, ...), other top-level files that are
   not sidecars, and `phenotype/` are always kept. Top-level sidecars
   (`T1w.json`, `task-rest_bold.json`) follow rules 2 and 3.
5. `derivatives/`, `sourcedata/`, `code/` and `stimuli/` are skipped unless
   requested with `folders`. Hidden files and folders (`.datalad/`,
   `.gitattributes`, ...) and other top-level folders are always skipped;
   a hidden name inside a data directory (`.zattrs` in `*.ome.zarr/`) is
   part of the data file, and kept with it.
6. Last, the `exclude` patterns remove any kept file but
   `dataset_description.json`.

Matching values
---------------
Each filter takes a plain value (matched exactly), a list of values (any of
them), a glob ([`Glob`][brainfilter.Glob]), a regex (a `re.Pattern` or
[`Regex`][brainfilter.Regex], which must match the whole label:
`re.compile("1")` matches `sub-1` but not `sub-10`; a
`Regex(..., full=False)` is found anywhere in it instead) or any other
condition. Plain labels may keep their `<key>-` prefix (`"sub-01"` is
`"01"`); a pattern is matched against the bare label.

Index entities (`run`, `echo`, `flip`, `inv`, `split`, `chunk`) compare
plain values by number: `run=1`, `run="1"` and `run="01"` all match
`run-1` and `run-01`. A glob or regex on an index entity matches its label
as written in the file name.
Other entities compare strings as exact text, but an `int` by number on any
entity: `subjects=1` matches `sub-1`, `sub-01` and `sub-001` (never `sub-1a`)
where `subjects="1"` matches `sub-1` only.

The `include`/`exclude` patterns are matched against the relative path
instead, and a regex there is found anywhere in it (`re.search`) unless
anchored.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from typing import TypeVar

from brainfilter._family import in_family
from brainfilter._names import (
    COMPANION_SUFFIXES,
    DATATYPES,
    INDEX_ENTITIES,
    OPTIONAL_FOLDERS,
    SORTED_ENTITIES,
    TOP_LEVEL_FILES,
    ParsedPath,
    applies_to,
    data_directory,
    index_value,
    parse_name,
    parse_path,
)
from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.conditions import Condition, Or, Regex, default_full

__all__ = ["Filter"]

T = TypeVar("T")

# Never removed by `exclude`.
_PROTECTED = frozenset({"dataset_description.json"})

# Filter keywords that are entity filters under another name.
_ALIASES = {"subjects": "sub", "sessions": "ses", "tasks": "task"}


def _is_many(value: object) -> bool:
    return isinstance(value, (list, tuple, set, frozenset))


def _as_condition(value: object) -> Condition | None:
    """Return a filter value as a label condition; `None` for a plain value.

    A regex that did not choose (`full=None`) must match the whole label.
    """
    if isinstance(value, Condition):
        return default_full(value, True)
    if isinstance(value, re.Pattern):
        return Regex(value, full=True)
    return None


def _matcher(
    value: object, key: str | None, index: bool = False
) -> Callable[[object], bool] | None:
    """Build `label -> bool` from a filter value; `None` keeps everything.

    A plain value loses its `<key>-` prefix (when `key` is given). An `int`
    (not a `bool`) matches any all-digit label equal to it as a number, on
    any entity. With `index`, a plain string and the label compare by number
    too; otherwise a string compares as exact text. Conditions see the label
    as written; a regex must match all of it.
    """
    if value is None:
        return None
    values = list(value) if _is_many(value) else [value]
    if not values:
        return None
    exact: set[object] = set()
    numbers: set[int] = set()
    conditions: list[Condition] = []
    for item in values:
        cond = _as_condition(item)
        if cond is not None:
            conditions.append(cond)
            continue
        if isinstance(item, int) and not isinstance(item, bool):
            numbers.add(item)
            continue
        item = str(item)
        if key and item.startswith(key + "-"):
            item = item[len(key) + 1:]
        exact.add(index_value(item) if index else item)

    def match(label: object) -> bool:
        if label is None:
            return False
        text = str(label)
        number = index_value(text)
        if isinstance(number, int) and number in numbers:
            return True
        value = number if index else label
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
    entities) match the bare label of each file. An `int` matches by
    number on any entity: `subjects=1` keeps `sub-1`, `sub-01` and
    `sub-001`, `acq=3` keeps `acq-003`, and a label such as `1a` never
    matches it. A string matches exactly (`subjects="01"` does not keep
    `sub-1`), but on an index entity (`run`, `echo`, ...) by number, so
    `run="1"` matches `run-01`. A regex must match the whole label
    (`re.fullmatch`): `subjects=re.compile("1")` keeps `sub-1`, not
    `sub-10`; a `Regex(..., full=False)` is found anywhere in the label. A
    glob or regex on an index entity sees the label as written.

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

    Notes
    -----
    The filtering tutorial walks through the selection rules and the values
    a filter takes; the inheritance page explains which sidecars and
    companion files come along with the data files that are kept.
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
        """Whether a data file passes every filter (path relative to root).

        A file inside a data file that is a directory (`sub-01_meg.ds/x`) is
        judged on that directory's name and datatype.
        """
        return self._passes(parse_path(path))

    def _passes(self, name: ParsedPath, entities: dict | None = None) -> bool:
        """Whether a parsed path passes every filter.

        With `entities` (for a metadata file that applies to no data file),
        the entity filters read them instead, and one on an entity they do
        not have passes.
        """
        partial = entities is not None
        ent = name.entities if entities is None else entities
        for key, match in self.entities.items():
            label = ent.get(key)
            if label is None and partial:
                continue
            if not match(label):
                return False
        if self.exclude_subjects and self.exclude_subjects(ent.get("sub")):
            return False
        if self.datatypes and not self.datatypes(name.datatype):
            return False
        if self.suffixes and not self.suffixes(name.suffix):
            return False
        if self.include and not self.include(name.item):
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

        The paths should be files, as `walk` lists them. A directory cannot
        always be told from a file by its name: the directories BIDS names
        (`sub-01`, `sub-01/ses-1`, `sub-01/anat`, `phenotype`,
        `derivatives`, ...) are skipped, but any other one (a folder inside
        `derivatives/`, say) is treated as a file. So filter the output of
        `root.rglob("*")` on `is_file()` first.

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
        skipped are not listed. An `AsyncBidsPath` or a pure path is listed
        through the `BidsPath` of its string and storage options. The files
        have the mode of `root` (read-only for a string).
        """
        root = in_family(root, BidsPath)
        found: dict[str, BidsPath] = {}
        for dirpath, dirnames, filenames in root.walk():
            parts = PurePosixPath(dirpath.relative_to(root).as_posix()).parts
            dirnames[:] = [d for d in dirnames if self._descend(parts, d)]
            for filename in filenames:
                path = dirpath / filename
                found[path.relative_to(root).as_posix()] = path
        return [found[rel] for rel in self._select(found)]

    async def awalk(self, root: object) -> list[AsyncBidsPath]:
        """List a dataset asynchronously and return the files to keep, sorted.

        The coroutine counterpart of `walk`: `root` is an `AsyncBidsPath`,
        a path object, or a local path or URL string, and the files are
        `AsyncBidsPath` objects. A `BidsPath` or a pure path is listed
        through the `AsyncBidsPath` of its string and storage options, so a
        remote store with a natively async backend is listed on its
        coroutines. The listing goes one level at a time, every directory
        of a level at once, and lists no folder `walk` would not. The files
        have the mode of `root`, as in `walk`.
        """
        root = in_family(root, AsyncBidsPath)
        found: dict[str, AsyncBidsPath] = {}
        level = [root]
        while level:
            listings = await asyncio.gather(*map(_alist, level))
            below: list[AsyncBidsPath] = []
            for directory, children in zip(level, listings):
                rel_dir = directory.relative_to(root).as_posix()
                parts = PurePosixPath(rel_dir).parts
                for child, is_dir, is_link in children:
                    if not is_dir:
                        found[child.relative_to(root).as_posix()] = child
                    elif not is_link and self._descend(parts, child.name):
                        below.append(child)
            level = below
        return [found[rel] for rel in self._select(found)]

    def __call__(self, paths: Iterable[T], root: object = None) -> list[T]:
        """Alias of `select`."""
        return self.select(paths, root)

    # -- engine --------------------------------------------------------------
    def _descend(self, parts: tuple[str, ...], name: str) -> bool:
        """Whether a walk lists directory `name` of the directory `parts`.

        `parts` is the relative path of the directory being listed (`()` at
        the root). Pruning never changes a result.
        """
        if parts and data_directory((*parts, name)) is not None:
            return True  # inside a data directory, every file is kept with it
        if name.startswith("."):
            return False
        if parts:
            return True
        return (
            name.startswith("sub-") or name == "phenotype"
            or name in self.folders
        )

    def _select(self, paths: Iterable[str]) -> list[str]:
        """Select among relative path strings; return them sorted."""
        data: dict[str, ParsedPath] = {}     # data item -> how it parses
        members: dict[str, list[str]] = {}   # data item -> its files
        meta: list[ParsedPath] = []
        kept: set[str] = set()
        for path in paths:
            parts = PurePosixPath(path).parts
            if not parts:
                continue
            if path in TOP_LEVEL_FILES:
                kept.add(path)
                continue
            # Names inside a data directory (`.zattrs`) belong to the data
            boundary = data_directory(parts)
            named = parts if boundary is None else parts[:boundary + 1]
            if any(p.startswith(".") for p in named):
                continue
            if _is_bids_directory(parts):
                continue
            top = parts[0]
            if len(parts) > 1 and top in OPTIONAL_FOLDERS:
                if top in self.folders:
                    kept.add(path)
                continue
            name = parse_path(path)
            if top.startswith("sub-") and len(parts) > 1:
                if name.is_metadata:
                    meta.append(name)
                else:
                    data.setdefault(name.item, name)
                    members.setdefault(name.item, []).append(path)
            elif top == "phenotype":
                kept.add(path)
            elif len(parts) == 1:
                if name.is_metadata and name.suffix:
                    # top-level sidecar: T1w.json, task-rest_bold.json
                    meta.append(name)
                else:
                    kept.add(path)
            # other top-level folders (e.g. "models/") are skipped

        passed = {item for item, d in data.items() if self._passes(d)}
        for item in passed:
            kept.update(members[item])
        kept_data = _by_directory(data[item] for item in passed)
        all_data = _by_directory(data.values())

        # A data file that is also a companion (`physio.tsv.gz` of a run)
        # follows the data it describes, as its metadata does.
        for item, d in data.items():
            if (
                item not in passed and d.suffix in COMPANION_SUFFIXES
                and _applies(d, kept_data)
            ):
                kept.update(members[item])
        for m in meta:
            if _applies(m, kept_data) or (
                not _applies(m, all_data)
                and self._passes(m, _with_directory_entities(m))
            ):
                kept.add(m.path)

        if self.exclude:
            kept = {p for p in kept if p in _PROTECTED or not self.exclude(p)}
        return sorted(kept)


def _by_directory(data: Iterable[ParsedPath]) -> dict:
    """Index data items by every directory they are in, at any depth."""
    by_dir: dict[PurePosixPath, list[ParsedPath]] = {}
    for d in data:
        for parent in (d.directory, *d.directory.parents):
            by_dir.setdefault(parent, []).append(d)
    return by_dir


def _applies(meta: ParsedPath, by_dir: dict) -> bool:
    """Whether `meta` applies to a data item of an index of `_by_directory`."""
    return any(applies_to(meta, d) for d in by_dir.get(meta.directory, ()))


def _with_directory_entities(name: ParsedPath) -> dict:
    """Return a name's entities, with `sub`/`ses` from its directories if absent."""
    entities = dict(name.entities)
    for part in PurePosixPath(name.path).parts[:-1]:
        for key in ("sub", "ses"):
            if _is_entity_directory(part, key):
                entities.setdefault(key, parse_name(part).entities[key])
    return entities


def _is_entity_directory(name: str, key: str) -> bool:
    """Whether `name` is a `<key>-<label>` directory (`sub-01`, `ses-1`)."""
    parsed = parse_name(name)
    return (
        parsed.suffix is None and not parsed.extension
        and list(parsed.entities) == [key]
    )


def _is_bids_directory(parts: tuple[str, ...]) -> bool:
    """Whether a relative path names a directory BIDS defines, not a file.

    These are the top-level `sub-<label>`, `phenotype` and optional folders,
    and `sub-<label>/ses-<label>` and the datatype directories below them.
    """
    subject = _is_entity_directory(parts[0], "sub")
    if len(parts) == 1:
        return (
            subject or parts[0] == "phenotype" or parts[0] in OPTIONAL_FOLDERS
        )
    if not subject or len(parts) > 3:
        return False
    session = _is_entity_directory(parts[1], "ses")
    if len(parts) == 2:
        return session or parts[1] in DATATYPES
    return session and parts[2] in DATATYPES


async def _alist(directory: AsyncBidsPath) -> list[tuple]:
    """List a directory: `(child, is_dir, is_symlink)` for each child.

    Both answers come from the listing; a symbolic link to a directory is
    not descended into, as in `walk`.
    """
    children = []
    async for child in directory.iterdir():
        is_link = await child.pathinfo.is_symlink()
        children.append((child, await child.pathinfo.is_dir(), is_link))
    return children


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
