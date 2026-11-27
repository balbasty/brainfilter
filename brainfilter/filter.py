"""Select a subset of a BIDS dataset from its file listing.

A [`BidsFilter`][brainfilter.BidsFilter] works on paths relative to the
dataset root, so it applies to any listing (OpenNeuro, S3, a local
directory, ...) before anything is downloaded::

    >>> f = BidsFilter(subjects=["01"], datatypes="anat", acq="mprage")
    >>> f.select(listing)                       # relative path strings
    >>> f.walk("s3://openneuro.org/ds000224")   # list a dataset, then select
    >>> await f.awalk("s3://openneuro.org/ds000224")  # ... asynchronously

Besides the listing, a walk reads `.bidsignore`, a filter on
`participants.tsv` reads that table, and a filter on sidecar values reads
the sidecars of the data files that pass every other filter, each once.

Selection rules
---------------
The input is a listing of files; see `BidsFilter.select` for directories.

1. *Data files* are the files inside `sub-*/` that are not metadata (rule
   2). They are kept if they pass every filter: subjects, sessions,
   datatypes, suffixes, tasks, other entities, the `include` patterns, the
   participants filter (on the subject's row of `participants.tsv`) and
   the sidecar filters (on the merged sidecar of the file). A file's
   subject and session are those its name gives, else those of the
   `sub-<label>/` and `ses-<label>/` folders it is in. A table that is a
   recording (`*_beh.tsv`, `*_motion.tsv`, `*_blood.tsv`) is a data file,
   and so is a continuous recording (`*_physio.tsv.gz`). A data file that
   is a directory (a CTF MEG `*_meg.ds/`, an OME-Zarr `*.ome.zarr/`) is one
   data item: every file inside it is kept or skipped with it, judged on
   the directory's name, datatype and sidecar. So is every *companion*, a
   file with a suffix of its own that describes the recordings it applies
   to: the `events`, `channels`, `electrodes`, `coordsystem`, `optodes`,
   `aslcontext` and other companion tables and files, the `scans` and
   `sessions` tables, the `physio`, `stim` and `blood` recordings, the
   `*_photo` of a recording's set-up, the `*_headshape` and `*_markers` of
   a MEG session, and the MEG fine-calibration and crosstalk files
   (`*_acq-calibration_meg.dat`, `*_acq-crosstalk_meg.fif`). A filter that
   names one (`suffixes="events"`, `acq="crosstalk"`) selects it, with its
   own JSON sidecars and without the recordings it describes.
2. *Metadata files* (`.json`, `.tsv`, `.bval` and `.bvec` files that are no
   companions: `bold.json`, `events.json`, `dwi.bval`), wherever they are,
   are kept if they apply to at least one kept data file under the BIDS
   inheritance principle. Every companion is also kept with the kept
   recordings it applies to, whether it passes the filters or not; the
   MEG fine-calibration and crosstalk files apply to every MEG recording
   of their subject or session, whatever its `acq`. A recording (a data
   file that is not a companion, or a companion recording such as
   `*_physio.tsv.gz`) brings along the metadata and the companions that
   apply to it; any other data file (`*_events.tsv`, `*_photo.jpg`) its
   JSON sidecars alone. A `photo`, `headshape` or `markers` file with an
   `acq` applies only to the recordings with that `acq` label when one of
   the recordings it would apply to otherwise has it; when none has it,
   the label names what the file shows (`acq-NAS`, the nasion), and is not
   compared. A metadata file applies to a data file from the data file's
   directory up to its dataset root, the nearest directory of the listing
   above it that holds a `dataset_description.json`; without one, only the
   metadata in the data file's own directory applies. These are the files
   `path.sidecars` and `path.companions` find.
3. A metadata file that applies to no data file of the listing at all
   (`beh/*_beh.json` alone, `T1w.json` of a dataset with no `T1w`) is
   judged on what it names, when a `dataset_description.json` of the
   listing is in its folder or above it (without one, it is kept only by
   rule 2): it is kept if its subject, session, datatype, suffix and path
   pass the filters, and the entity filters for the entities it has. An
   entity filter on an entity it does not have passes if it admits a file
   without it: one with `Never` among its values, or one made of values
   only (`acq="mprage"`). One that asks for the entity to be there fails:
   `Any` or `Required`, alone or beside values (`acq={Any, "mprage"}`),
   unless `Never` is there too. A sidecar filter is judged the same way, as
   a filter on a field it does not have, and the participants filter on its
   subject, when it has one. So an empty `BidsFilter()` keeps every file of
   a dataset that rule 5 does not skip. A companion that describes no
   recording (`electrodes.tsv` of a session with no recording) is a data
   file, judged as any other by rule 1.
4. Dataset-level files (`dataset_description.json`, `participants.tsv`,
   `README`, `CHANGES`, `.bidsignore`, ...), other top-level files that are
   not sidecars, and `phenotype/` are always kept. Top-level sidecars
   (`T1w.json`, `task-rest_bold.json`) and companion tables
   (`task-rest_events.tsv`), which are outside every `sub-*/`, are metadata
   files: they follow rules 2 and 3.
5. `derivatives/`, `sourcedata/`, `code/` and `stimuli/` are skipped unless
   requested with `folders`. Hidden files and folders (`.datalad/`,
   `.gitattributes`, ...) and other top-level folders are always skipped;
   a hidden name inside a data directory (`.zattrs` in `*.ome.zarr/`) is
   part of the data file, and kept with it. The dataset's `.bidsignore`
   decides which files are data to select, never which metadata applies.
   A data file it names is never selected, and metadata it names is kept
   only as the metadata of a kept data file (rule 2), never on its own
   (rule 3); a companion it names is kept only with a kept recording it
   applies to. Dataset-level files (rule 4) are kept whether
   it names them or not. So an ignored sidecar still applies to the data
   files it describes, its values count for the sidecar filters, and it
   comes along with them; an ignored `participants.tsv` is still read by the
   participants filters, and kept.
6. Last, the `exclude` patterns remove any kept file but
   `dataset_description.json`.

Matching values
---------------
Each label filter takes a plain value (matched exactly), several values in
a list or a set (any of them), a glob ([`Glob`][brainfilter.Glob]), a regex
(a `re.Pattern` or [`Regex`][brainfilter.Regex], which must match the
whole label: `re.compile("1")` matches `sub-1` but not `sub-10`; a
`Regex(..., full=False)` is found anywhere in it instead), a function of
the label that says whether it matches, or a marker of presence:
`typing.Never` matches a file that does not have the entity, and
`typing.Any` (or `typing.Required`) one that has it, whatever its label. A
list or a set may mix all of these: `acq={Never, "mprage"}`. On an entity
keyword (`acq=None`, `sub=None`, `entities={"acq": None}`), `None` is
`Never`; on `subjects`, `exclude_subjects`, `sessions`, `datatypes`,
`suffixes` and `tasks`, it is no filter, their default.
Plain labels may keep their `<key>-` prefix (`"sub-01"` is `"01"`); a
pattern is matched against the bare label.

Index entities (`run`, `echo`, `flip`, `inv`, `split`, `chunk`) compare
plain values by number: `run=1`, `run="1"` and `run="01"` all match
`run-1` and `run-01`. A glob or regex on an index entity matches its label
as written in the file name.
Other entities compare strings as exact text, but an `int` by number on any
entity: `subjects=1` matches `sub-1`, `sub-01` and `sub-001` (never `sub-1a`)
where `subjects="1"` matches `sub-1` only.

A filter on a sidecar field or a `participants.tsv` column takes the same
forms, on the value the JSON or the table holds, with three differences. A
plain value is compared with `==` (`2` matches `2.0`, a string is exact
text, and `True` is not `1`). A list is one value, compared whole
(`SliceTiming=[0.0, 0.5]`), so several values to choose from go in a set.
And `None` is a value: the JSON `null`, or `n/a` in the table. `Never`
matches a file whose sidecars lack the field (a table without the column),
`Any` one that has it, `null` included. A glob or a regex matches text
only, and a function that raises `TypeError`, `ValueError` or
`AttributeError` on a value (a number compared with a string, say) does
not match it.

The `include`/`exclude` patterns are matched against the relative path
instead, and a regex there is found anywhere in it (`re.search`) unless
anchored.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import typing
from collections.abc import Awaitable, Callable, Iterable, Mapping
from pathlib import PurePosixPath
from typing import TypeVar

import typing_extensions
from bagof.paths import AsyncPath, Path, PurePath

from brainfilter._family import in_family
from brainfilter._names import (
    DATATYPES,
    INDEX_ENTITIES,
    OPTIONAL_FOLDERS,
    SORTED_ENTITIES,
    TOP_LEVEL_FILES,
    ParsedPath,
    acq_required,
    applies_to,
    data_directory,
    index_value,
    is_acq_tagged,
    parse_name,
    parse_path,
    same_label,
)
from brainfilter.bidspath import AsyncBidsPath, BidsPath
from brainfilter.conditions import Condition, Or, Regex, default_full

__all__ = ["BidsFilter"]

T = TypeVar("T")
R = TypeVar("R")

# Never removed by `exclude`.
_PROTECTED = frozenset({"dataset_description.json"})

# Never ignored by `.bidsignore`.
_NEVER_IGNORED = frozenset({"dataset_description.json", ".bidsignore"})

# BidsFilter keywords that are entity filters under another name.
_ALIASES = {"subjects": "sub", "sessions": "ses", "tasks": "task"}

_PARTICIPANTS = "participants.tsv"
_BIDSIGNORE = ".bidsignore"
_DESCRIPTION = "dataset_description.json"

# The markers of presence, from `typing` and `typing_extensions` (distinct
# objects on older Pythons), compared by identity.
_ABSENT_MARKERS = tuple({
    id(m): m for m in (
        typing.NoReturn, getattr(typing, "Never", None),
        typing_extensions.Never, typing_extensions.NoReturn,
    ) if m is not None
}.values())
_PRESENT_MARKERS = tuple({
    id(m): m for m in (
        typing.Any, getattr(typing, "Required", None),
        typing_extensions.Any, typing_extensions.Required,
    ) if m is not None
}.values())

# The exceptions that make a test fail on a value instead of raising: what
# a test of the wrong type of value raises (`None < 0.03`, `(2).lower()`).
_WRONG_VALUE = (TypeError, ValueError, AttributeError)


class _Absent:
    """The value of a sidecar field or a table column that is not there."""

    def __repr__(self) -> str:
        return "<absent>"


_ABSENT: object = _Absent()


def _is_marker(value: object, markers: tuple) -> bool:
    return any(value is marker for marker in markers)


def _is_many(value: object) -> bool:
    return isinstance(value, (list, tuple, set, frozenset))


def _is_test(value: object) -> bool:
    """Whether a value is a function to call on a label or a value."""
    return callable(value) and not isinstance(value, type)


def _guarded(test: Callable[[object], object], value: object) -> bool:
    """Call a test; one that raises on a value of the wrong type fails."""
    try:
        return bool(test(value))
    except _WRONG_VALUE:
        return False


def _as_condition(value: object) -> Condition | None:
    """Return a filter value as a pattern condition; `None` for another value.

    A regex that did not choose (`full=None`) must match the whole value.
    """
    if isinstance(value, Condition):
        return default_full(value, True)
    if isinstance(value, re.Pattern):
        return Regex(value, full=True)
    return None


class _LabelMatch:
    """`label -> bool` for a label filter; a label of `None` is absent.

    A plain value loses its `<key>-` prefix (when `key` is given). An `int`
    (not a `bool`) matches any all-digit label equal to it as a number, on
    any entity. With `index`, a plain string and the label compare by number
    too; otherwise a string compares as exact text. Conditions and tests
    see the label as written; a regex must match all of it.

    `keyword` names the label keyword (`subjects`, ...) the values were
    given to, on which `None` is not a value; without it, `None` is `Never`.
    """

    def __init__(
        self, values: list, key: str | None, index: bool,
        keyword: str | None = None,
    ) -> None:
        self.absent = False      # `Never` (or `None`): no such entity
        self.present = False     # `Any` / `Required`: any label
        self.exact: set[object] = set()
        self.numbers: set[int] = set()
        self.tests: list[Callable[[object], bool]] = []
        self.index = index
        for item in values:
            if item is None and keyword is not None:
                raise TypeError(
                    f"BidsFilter got None among the values of {keyword}=: None "
                    f"is no filter there; use typing.Never for the files "
                    f"that have no such label"
                )
            if item is None or _is_marker(item, _ABSENT_MARKERS):
                self.absent = True
                continue
            if _is_marker(item, _PRESENT_MARKERS):
                self.present = True
                continue
            cond = _as_condition(item)
            if cond is not None:
                self.tests.append(cond)
                continue
            if _is_test(item):
                self.tests.append(item)  # type: ignore[arg-type]
                continue
            if isinstance(item, int) and not isinstance(item, bool):
                self.numbers.add(item)
                continue
            item = str(item)
            if key and item.startswith(key + "-"):
                item = item[len(key) + 1:]
            self.exact.add(index_value(item) if index else item)

    @property
    def lenient(self) -> bool:
        """Whether a file without the entity passes, judged on its own name.

        For selection rule 3: a filter that admits a file without the entity
        (`Never` among its values), or one made of values only. A filter
        that asks for the entity to be there (`Any`, `Required`, with or
        without other values) does not.
        """
        return self.absent or not self.present

    def __call__(self, label: object) -> bool:
        if label is None:
            return self.absent
        if self.present:
            return True
        text = str(label)
        number = index_value(text)
        if isinstance(number, int) and number in self.numbers:
            return True
        value = number if self.index else label
        if value in self.exact:
            return True
        return any(_guarded(test, label) for test in self.tests)


def _matcher(
    value: object, key: str | None, index: bool = False,
    keyword: str | None = None,
) -> _LabelMatch | None:
    """Build the test of a label filter; `None` keeps everything.

    On a label keyword (`keyword`, such as `"subjects"`), a value of `None`
    is no filter; on an entity keyword, it is `Never`.
    """
    if value is None and keyword is not None:
        return None
    values = list(value) if _is_many(value) else [value]
    if not values:
        return None
    return _LabelMatch(values, key, index, keyword)


def _equal(value: object, expected: object) -> bool:
    """Whether a JSON or table value is a plain filter value.

    `==`, but a `bool` is never a number, and a list (or tuple) is compared
    item by item, the same way.
    """
    if isinstance(value, bool) or isinstance(expected, bool):
        return (
            isinstance(value, bool) and isinstance(expected, bool)
            and value == expected
        )
    if isinstance(expected, (list, tuple)):
        return (
            isinstance(value, (list, tuple)) and len(value) == len(expected)
            and all(map(_equal, value, expected))
        )
    if isinstance(expected, Mapping):
        return (
            isinstance(value, Mapping) and set(value) == set(expected)
            and all(_equal(value[k], expected[k]) for k in expected)
        )
    try:
        return bool(value == expected)
    except Exception:  # noqa: BLE001 -- a value that cannot be compared
        return False


def _value_test(item: object) -> Callable[[object], bool]:
    """Build `value -> bool` for one value of a sidecar or table filter."""
    if _is_marker(item, _ABSENT_MARKERS):
        return lambda value: value is _ABSENT
    if _is_marker(item, _PRESENT_MARKERS):
        return lambda value: value is not _ABSENT
    if item is None:
        return lambda value: value is None
    cond = _as_condition(item)
    if cond is not None:
        return lambda value: isinstance(value, str) and cond(value)
    if _is_test(item):
        return lambda value: value is not _ABSENT and _guarded(item, value)
    return lambda value: value is not _ABSENT and _equal(value, item)


class _ValueMatch:
    """`value -> bool` for a sidecar or table filter; `_ABSENT` if not there.

    A set (or frozenset) is any of its members; anything else, a list
    included, is one value.
    """

    def __init__(self, value: object) -> None:
        items = list(value) if isinstance(value, (set, frozenset)) else [value]
        self.tests = [_value_test(item) for item in items]
        # Whether a file without the field passes, for selection rule 3:
        # one with `Never` among its values, or one made of values only.
        self.lenient = any(
            _is_marker(item, _ABSENT_MARKERS) for item in items
        ) or not any(_is_marker(item, _PRESENT_MARKERS) for item in items)

    def __call__(self, value: object) -> bool:
        return any(test(value) for test in self.tests)


def _value_matchers(given: Mapping, what: str) -> dict[str, _ValueMatch]:
    tests = {}
    for key, value in given.items():
        if not isinstance(key, str):
            raise TypeError(f"BidsFilter got a {what} filter on {key!r}: a name "
                            "must be a string")
        if isinstance(value, (set, frozenset)) and not value:
            continue
        tests[key] = _ValueMatch(value)
    return tests


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


# The keywords of `BidsFilter` itself, beside the entities.
_KEYWORDS = (
    "subjects", "exclude_subjects", "sessions", "datatypes", "suffixes",
    "tasks", "include", "exclude", "folders", "entities", "sidecar",
    "participants", "bidsignore",
)


def _meant_keyword(name: str) -> str | None:
    """Return the keyword a capitalised keyword misspells, or `None`.

    `Subjects` is `subjects`, `Acq` is `acq`, and a plural or singular form
    of a keyword or an entity (`Runs`, `Subject`) names it too.
    """
    low = name.lower()
    if low in _KEYWORDS or low in SORTED_ENTITIES:
        return low
    for keyword in _KEYWORDS:
        if low in (keyword[:-1], keyword[:-2]) and keyword.endswith("s"):
            return keyword
    if low.endswith("s") and low[:-1] in SORTED_ENTITIES:
        return low[:-1]
    return None


def _refuse_capitalised_keywords(fields: Mapping[str, object]) -> None:
    """Refuse a sidecar keyword that is a `BidsFilter` keyword with a capital."""
    for name in fields:
        meant = _meant_keyword(name)
        if meant is not None:
            raise TypeError(
                f"BidsFilter got {name}=, which looks like {meant}= with a "
                f"capital letter: write {meant}=, or, to filter on a sidecar "
                f"field named {name!r}, sidecar={{{name!r}: ...}}"
            )


class BidsFilter:
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
    glob or regex on an index entity sees the label as written. A list or
    a set is any of its values, and a function of the label is a test.
    `typing.Never` keeps the files that do not have the entity, and
    `typing.Any` (or `typing.Required`) those that have it:
    `acq={Never, "mprage"}` keeps the files with no `acq` entity and those
    with `acq-mprage`. On an entity keyword (`acq=None`,
    `entities={"acq": None}`), `None` means `Never`; on the label keywords
    below, it is no filter. A file's subject and session are those its
    name gives, else those of its `sub-<label>/` and `ses-<label>/`
    folders.

    Sidecar filters, given as keywords that start with a capital letter
    (`RepetitionTime=2.0`), and the `participants` filters match a value of
    the merged sidecar of a data file, or of its subject's row of
    `participants.tsv`. A plain value is compared with `==` (`2` matches
    `2.0`; `True` is not `1`), and a list is one value, compared whole, so
    several values go in a set: `PhaseEncodingDirection={"j", "j-"}`. A
    function of the value is a test (`EchoTime=lambda t: t < 0.03`), and
    one that raises `TypeError`, `ValueError` or `AttributeError` on a
    value does not match it. `None` is the JSON `null` or the table's
    `n/a`; `Never` matches a field (or column) that is not there, and `Any`
    one that is. A glob or a regex matches text only.

    Path filters (`include`, `exclude`) match the path relative to the
    dataset root. A glob must match the whole path (`fnmatch`); a regex is
    found anywhere in it (`re.search`) unless anchored.

    Parameters
    ----------
    subjects, exclude_subjects, sessions, datatypes, suffixes, tasks
        Keep data files whose subject, session, datatype directory, BIDS
        suffix or task match (`exclude_subjects`: whose subject does not).
        `None`, the default, is no filter.
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
    sidecar
        Filters on the merged sidecar of each data file, `{field: value}`,
        for the fields whose name is not a keyword (or to give them all in
        one mapping).
    participants
        Filters on the columns of `participants.tsv`, `{column: value}`:
        keep the data files of the subjects whose row matches every one.
        A subject without a row is not kept, and a dataset without
        `participants.tsv` is an error (one that `.bidsignore` names is
        still read).
    bidsignore
        Whether to honour the dataset's `.bidsignore`: the data files it
        names are not selected (a companion, such as an events table, still
        comes along with the recordings it describes), and the other files
        it names are kept only as the metadata of a kept data file. It
        never changes which metadata applies to a data file, nor the values
        it reads.
    **kwargs
        Filters on a known BIDS entity (`acq="mprage"`, `run=[1, 2]`,
        `sub=...`, ...), and on a sidecar field for a keyword that starts
        with a capital letter (`RepetitionTime=2.0`). A capitalised keyword
        that is a keyword of `BidsFilter` or an entity (`Subjects=`, `Acq=`) is
        refused as a misspelling; give such a field in `sidecar`.

    Notes
    -----
    The filtering tutorial walks through the selection rules and the values
    a filter takes; the inheritance page explains which sidecars and
    companion files come along with the data files that are kept. A data
    file's sidecars are the ones `path.sidecars` finds, so a listing without
    a `dataset_description.json` inherits nothing from above a data file's
    own directory.
    The filter sees only what it walks or selects: walked from a folder
    inside a dataset, it finds no `dataset_description.json` above it, so
    walk from the dataset root (or a nested dataset with its own
    description) for full inheritance.
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
        entities: Mapping | None = None,
        sidecar: Mapping | None = None,
        participants: Mapping | None = None,
        bidsignore: bool = True,
        **kwargs: object,
    ) -> None:
        fields = {k: v for k, v in kwargs.items() if k[:1].isupper()}
        kwargs = {k: v for k, v in kwargs.items() if k not in fields}
        _refuse_capitalised_keywords(fields)
        unknown = set(kwargs) - set(SORTED_ENTITIES)
        if unknown:
            raise TypeError(
                f"BidsFilter got unknown keywords {', '.join(sorted(unknown))}; "
                "filter on another entity with entities={key: value}, and on "
                "a sidecar field with a keyword that starts with a capital "
                "letter or with sidecar={field: value}"
            )
        given = dict(entities or {})
        for name, value in kwargs.items():
            if name in given:
                raise TypeError(f"BidsFilter got two filters for entity {name!r}")
            given[name] = value
        keywords: dict[str, str] = {}   # entity -> the label keyword given
        for name, key in _ALIASES.items():
            value = {"subjects": subjects, "sessions": sessions,
                     "tasks": tasks}[name]
            if value is None:
                continue
            if key in given:
                raise TypeError(
                    f"BidsFilter got both {name}= and a filter on entity {key!r}"
                )
            given[key] = value
            keywords[key] = name
        on_sidecar = dict(sidecar or {})
        for name, value in fields.items():
            if name in on_sidecar:
                raise TypeError(
                    f"BidsFilter got two filters for sidecar field {name!r}"
                )
            on_sidecar[name] = value

        self.entities: dict[str, _LabelMatch] = {}
        for key, value in given.items():
            match = _matcher(
                value, str(key), str(key) in INDEX_ENTITIES, keywords.get(key)
            )
            if match is not None:
                self.entities[str(key)] = match
        self.exclude_subjects = _matcher(
            exclude_subjects, "sub", keyword="exclude_subjects"
        )
        self.datatypes = _matcher(datatypes, None, keyword="datatypes")
        self.suffixes = _matcher(suffixes, None, keyword="suffixes")
        self.include = _patterns(include)
        self.exclude = _patterns(exclude)
        self.sidecar = _value_matchers(on_sidecar, "sidecar")
        self.participants = _value_matchers(participants or {}, "participants")
        self.bidsignore = bool(bidsignore)
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
        """Whether a data file passes the filters on its path and name.

        `path` is relative to the dataset root. A file inside a data file
        that is a directory (`sub-01_meg.ds/x`) is judged on that
        directory's name and datatype. The subject and session of a file
        are those its name gives, else those of the `sub-<label>/` and
        `ses-<label>/` folders it is in. The sidecar and participants
        filters read files, and are not applied here.
        """
        return self._passes(parse_path(path))

    def _passes(self, name: ParsedPath, partial: bool = False) -> bool:
        """Whether a parsed path passes every filter on its name.

        The name's entities are read with the subject and session of its
        folders when it lacks them (`_with_directory_entities`). With
        `partial` (for a metadata file that applies to no data file), an
        entity filter on an entity it does not have passes if it is lenient.
        """
        ent = _with_directory_entities(name)
        for key, match in self.entities.items():
            label = ent.get(key)
            if label is None and partial:
                if match.lenient:
                    continue
                return False
            if not match(label):
                return False
        if self.exclude_subjects and not (partial and ent.get("sub") is None):
            if self.exclude_subjects(ent.get("sub")):
                return False
        if self.datatypes and not self.datatypes(name.datatype):
            return False
        if self.suffixes and not self.suffixes(name.suffix):
            return False
        if self.include and not self.include(name.item):
            return False
        return True

    def keep_subject(self, label: str) -> bool:
        """Whether a subject (`"01"` or `"sub-01"`) passes the subject filters.

        Only `subjects` and `exclude_subjects` are applied; the participants
        filters read `participants.tsv`, and are not.
        """
        label = str(label)
        if label.startswith("sub-"):
            label = label[4:]
        match = self.entities.get("sub")
        if match and not match(label):
            return False
        return not (self.exclude_subjects and self.exclude_subjects(label))

    def _keep_session(self, label: str) -> bool:
        match = self.entities.get("ses")
        return not match or match(label)

    # -- listings ------------------------------------------------------------
    def select(self, paths: Iterable[T], root: object = None) -> list[T]:
        """Return the subset of `paths` to keep, sorted by relative path.

        The paths should be files, as `walk` lists them. A directory cannot
        always be told from a file by its name: the directories BIDS names
        (`sub-01`, `sub-01/ses-1`, `sub-01/anat`, `phenotype`,
        `derivatives`, ...) are skipped, but any other one (a folder inside
        `derivatives/`, say) is treated as a file. So filter the output of
        `root.rglob("*")` on `is_file()` first.

        Most filters need nothing but the names. The others read files:

        - a `.bidsignore` in the listing is read and honoured, from the path
          object given for it or, for a string, under `root`; with neither,
          it is not read;
        - the participants filters read `participants.tsv` under `root`,
          which they need;
        - the sidecar filters read the JSON sidecars that are in the
          listing, so the listing must hold path objects, and the sidecars
          of the data files.

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

        Raises
        ------
        TypeError
            With sidecar filters, if a path is a string, and with
            participants filters, without `root`.
        FileNotFoundError
            With participants filters, if the dataset has no
            `participants.tsv`.
        """
        items: dict[str, T] = {}
        for path in paths:
            rel = _relative(path, root)
            items.setdefault(rel, path)
        if self.sidecar and not all(map(_readable, items.values())):
            raise TypeError(
                "a sidecar filter reads the sidecars of the listing: pass "
                "path objects that can be read to select(), with the "
                "dataset root=, or list the dataset with walk()"
            )
        base = None
        if isinstance(root, str) or _readable(root):
            base = in_family(root, BidsPath)
        if self.participants and base is None:
            raise TypeError(
                "a participants filter reads participants.tsv: pass the "
                "dataset root= to select(), as a path that can be read, or "
                "list the dataset with walk()"
            )
        ignore = None
        if self.bidsignore and _BIDSIGNORE in items:
            given = items[_BIDSIGNORE]
            source = (
                in_family(given, BidsPath) if _readable(given)
                else None if base is None else base / _BIDSIGNORE
            )
            if source is not None:
                try:
                    text = source.read_text(encoding="utf-8")
                except FileNotFoundError:
                    text = ""
                ignore = _BidsIgnore.parse(text)
        subjects = None
        if self.participants:
            assert base is not None
            subjects = self._subjects_from(self._participants(base, None))
        plan = _Plan(self, items, ignore, subjects)
        contents = {rel: _read_json(items[rel]) for rel in plan.reads}
        return [items[rel] for rel in plan.finish(contents)]

    def walk(self, root: object) -> list[BidsPath]:
        """List a dataset and return the files to keep, sorted.

        `root` is a `BidsPath`, a path object, or a local path or URL
        string. Hidden folders, the top-level folders that would be
        skipped, the folders `.bidsignore` names and the subject and
        session folders the filters on their labels (and on
        `participants.tsv`) leave out are not listed, unless a metadata file
        above one of them may describe nothing but what it holds. An
        `AsyncBidsPath` or a pure path is listed through the `BidsPath` of
        its string and storage options. The files have the mode of `root`
        (read-only for a string).

        A walk keeps what `select` keeps of the whole listing, with one
        exception, for a dataset that is not valid BIDS: a file whose name
        gives another subject or session than its folder
        (`sub-01/anat/sub-02_T1w.nii.gz`) is judged on its name, and is
        missed when the folder's own label leaves the folder out.

        Inheritance reaches no further than `root`: walked from a folder
        inside a dataset (`sub-01/`), the walk finds no
        `dataset_description.json` and inherits nothing from above each
        data file's own folder. Walk from the dataset root, or from a nested
        dataset with its own description, for full inheritance.

        Raises
        ------
        FileNotFoundError
            With participants filters, if the dataset has no
            `participants.tsv`.
        """
        root = in_family(root, BidsPath)
        found: dict[str, BidsPath] = {}
        state = _Walk()
        for dirpath, dirnames, filenames in root.walk():
            parts = PurePosixPath(dirpath.relative_to(root).as_posix()).parts
            if not parts and not state.started:
                state.started = True
                names = set(filenames)
                if self.bidsignore and _BIDSIGNORE in names:
                    state.ignore = _BidsIgnore.parse(
                        (root / _BIDSIGNORE).read_text(encoding="utf-8")
                    )
                if self.participants:
                    state.subjects = self._subjects_from(
                        self._participants(root, _PARTICIPANTS in names)
                    )
            dirnames[:] = [d for d in dirnames if self._descend(parts, d, state)]
            for filename in filenames:
                path = dirpath / filename
                found[path.relative_to(root).as_posix()] = path
        if self.participants and not state.started:
            self._participants(root, False)
        plan = _Plan(self, found, state.ignore, state.subjects)
        unsure = plan.unsure(state.pruned)
        for pruned in sorted(state.pruned):
            if not _above_any(unsure, pruned):
                continue
            for dirpath, dirnames, filenames in (root / pruned).walk():
                parts = PurePosixPath(dirpath.relative_to(root).as_posix()).parts
                dirnames[:] = [
                    d for d in dirnames if self._descend(parts, d, state, False)
                ]
                listed = []
                for filename in filenames:
                    path = dirpath / filename
                    listed.append(rel := path.relative_to(root).as_posix())
                    found[rel] = path
                unsure = plan.settle(unsure, listed)
                if not _above_any(unsure, pruned):
                    break
        if state.pruned and len(found) > len(plan.listed):
            plan = _Plan(self, found, state.ignore, state.subjects)
        contents = {rel: _read_json(found[rel]) for rel in plan.reads}
        return [found[rel] for rel in plan.finish(contents)]

    async def awalk(self, root: object) -> list[AsyncBidsPath]:
        """List a dataset asynchronously and return the files to keep, sorted.

        The coroutine counterpart of `walk`: `root` is an `AsyncBidsPath`,
        a path object, or a local path or URL string, and the files are
        `AsyncBidsPath` objects. A `BidsPath` or a pure path is listed
        through the `AsyncBidsPath` of its string and storage options, so a
        remote store with a natively async backend is listed on its
        coroutines. The listing goes one level at a time, every directory
        of a level at once, and lists no folder `walk` would not; the
        sidecars a sidecar filter reads are read at once too. The files
        have the mode of `root`, as in `walk`.
        """
        root = in_family(root, AsyncBidsPath)
        found: dict[str, AsyncBidsPath] = {}
        state = _Walk()
        await self._alist_below(root, [root], found, state)
        plan = _Plan(self, found, state.ignore, state.subjects)
        unsure = plan.unsure(state.pruned)
        for pruned in sorted(state.pruned):
            if _above_any(unsure, pruned):
                unsure = await self._alist_below(
                    root, [root / pruned], found, state, plan, unsure, pruned
                )
        if state.pruned and len(found) > len(plan.listed):
            plan = _Plan(self, found, state.ignore, state.subjects)
        reads = sorted(plan.reads)
        contents = dict(zip(
            reads, await _gather(_aread_json, [found[r] for r in reads])
        ))
        return [found[rel] for rel in plan.finish(contents)]

    async def _alist_below(
        self,
        root: AsyncBidsPath,
        level: list[AsyncBidsPath],
        found: dict[str, AsyncBidsPath],
        state: _Walk,
        plan: _Plan | None = None,
        unsure: list[ParsedPath] | None = None,
        pruned: str = "",
    ) -> list[ParsedPath]:
        """List the tree below `level`, one level at a time, into `found`.

        Without `plan`, it is the walk of the dataset: the root listing is
        read first, and folders are pruned. With `plan`, it lists the
        pruned folder `pruned` (pruning nothing by label) until no metadata
        file of `unsure` above it is left unsettled, and returns those left.
        """
        while level:
            listings = await _gather(_alist, level)
            if not state.started:
                state.started = True
                await self._aread_root(root, listings[0], state)
            below: list[AsyncBidsPath] = []
            listed = []
            for directory, children in zip(level, listings):
                rel_dir = directory.relative_to(root).as_posix()
                parts = PurePosixPath(rel_dir).parts
                for child, is_dir, is_link in children:
                    if not is_dir:
                        listed.append(rel := child.relative_to(root).as_posix())
                        found[rel] = child
                    elif not is_link and self._descend(
                        parts, child.name, state, plan is None
                    ):
                        below.append(child)
            level = below
            if plan is not None:
                unsure = plan.settle(unsure or [], listed)
                if not _above_any(unsure, pruned):
                    break
        return unsure or []

    def __call__(self, paths: Iterable[T], root: object = None) -> list[T]:
        """Alias of `select`."""
        return self.select(paths, root)

    # -- engine --------------------------------------------------------------
    async def _aread_root(
        self, root: AsyncBidsPath, children: list[tuple], state: _Walk
    ) -> None:
        """Read `.bidsignore` and `participants.tsv` from the root listing."""
        names = {child.name for child, is_dir, _ in children if not is_dir}
        read_ignore = self.bidsignore and _BIDSIGNORE in names
        read_rows = bool(self.participants) and _PARTICIPANTS in names
        text, rows = await asyncio.gather(
            (root / _BIDSIGNORE).read_text(encoding="utf-8")
            if read_ignore else _nothing(),
            (root / _PARTICIPANTS).as_list() if read_rows else _nothing(),
        )
        if read_ignore:
            state.ignore = _BidsIgnore.parse(text)
        if self.participants:
            if not read_rows:
                raise _no_participants(root)
            state.subjects = self._subjects_from(rows)

    def _participants(self, root: BidsPath, listed: bool | None) -> list[dict]:
        """Read the rows of `participants.tsv` for the participants filters.

        `listed` says whether the listing has the table; `None` when it is
        not known, and the table is read if it is there. A table that
        `.bidsignore` names is read all the same.
        """
        if listed is False:
            raise _no_participants(root)
        try:
            return _read_rows(root / _PARTICIPANTS)
        except FileNotFoundError:
            if listed:
                raise
            raise _no_participants(root) from None

    def _subjects_from(self, rows: Iterable[Mapping]) -> set[str]:
        """Return the labels of the subjects whose row passes the filters."""
        subjects: set[str] = set()
        for row in rows:
            if "participant_id" not in row:
                raise ValueError(
                    "participants.tsv has no participant_id column, so a "
                    "participants filter cannot tell its subjects apart"
                )
            pid = row["participant_id"]
            if not isinstance(pid, str):
                continue
            if all(
                test(row.get(column, _ABSENT))
                for column, test in self.participants.items()
            ):
                subjects.add(pid[4:] if pid.startswith("sub-") else pid)
        return subjects

    def _descend(
        self,
        parts: tuple[str, ...],
        name: str,
        state: _Walk | None = None,
        prune: bool = True,
    ) -> bool:
        """Whether a walk lists directory `name` of the directory `parts`.

        `parts` is the relative path of the directory being listed (`()` at
        the root). Pruning never changes a result on a valid dataset. A
        subject or session folder is left out (with `prune`) when its label
        fails a filter that every data file inside it is judged on, since a
        file's subject (session) is its name's, else its folder's, and BIDS
        names every file under `sub-<label>/` with that label; a name that
        contradicts its folder is not valid BIDS, and may be missed. The
        folder is recorded in `state.pruned`: a metadata file above it may
        apply to a data file inside it and to none of those listed, and the
        walk then lists it after all (see `_Plan.unsure`).

        A folder that `.bidsignore` names is left out too (with `prune`),
        and recorded the same way: every file in it is ignored, so none of
        its data files is selected, and its metadata applies to nothing but
        them.
        """
        if not self._lists(parts, name, state, prune):
            return False
        rel = "/".join((*parts, name))
        ignore = None if state is None else state.ignore
        if (
            prune and ignore is not None and rel != "phenotype"
            and ignore.ignores(rel, True)
        ):
            state.pruned.append(rel)  # type: ignore[union-attr]
            return False
        return True

    def _lists(
        self,
        parts: tuple[str, ...],
        name: str,
        state: _Walk | None,
        prune: bool,
    ) -> bool:
        """Whether `_descend` lists a folder, `.bidsignore` aside."""
        if parts and data_directory((*parts, name)) is not None:
            return True  # inside a data directory, every file is kept with it
        if name.startswith("."):
            return False
        key = None
        if not parts:
            if not name.startswith("sub-"):
                return name == "phenotype" or name in self.folders
            key = "sub"
        elif len(parts) == 1 and _is_entity_directory(parts[0], "sub"):
            key = "ses"
        if key is None or not prune or self._may_hold(name, key, state):
            return True
        if state is not None:
            state.pruned.append("/".join((*parts, name)))
        return False

    def _may_hold(self, name: str, key: str, state: _Walk | None) -> bool:
        """Whether a `sub-`/`ses-` folder may hold a file the filters keep."""
        if not _is_entity_directory(name, key):
            return True
        label = parse_name(name).entities[key]
        if key == "ses":
            return self._keep_session(label)
        if not self.keep_subject(label):
            return False
        subjects = None if state is None else state.subjects
        return subjects is None or label in subjects


class _Walk:
    """What a walk learns from the root listing, for the levels below it."""

    def __init__(self) -> None:
        self.started = False
        self.ignore: _BidsIgnore | None = None
        self.subjects: set[str] | None = None
        self.pruned: list[str] = []      # the folders left out: label, ignore


def _above_any(metadata: list[ParsedPath], directory: str) -> bool:
    """Whether a metadata file is in an ancestor of `directory`."""
    parents = PurePosixPath(directory).parents
    return any(m.directory in parents for m in metadata)


class _Plan:
    """One selection among relative path strings.

    Built from the listing, it sorts the files into data, metadata and the
    rest, and applies the filters on names and on `participants.tsv`.
    `reads` is then the sidecars to read for the sidecar filters, and
    `finish` takes their contents and returns the kept paths, sorted.

    A file `.bidsignore` names is still sorted: an ignored data file is
    never selected, but metadata still applies to it; ignored metadata (or
    an ignored companion) still applies to the data files it describes,
    and comes along with them, but is never kept on its own.
    """

    def __init__(
        self,
        f: BidsFilter,
        paths: Iterable[str],
        ignore: _BidsIgnore | None = None,
        subjects: set[str] | None = None,
    ) -> None:
        self.filter = f
        self.subjects = subjects
        self.data: dict[str, ParsedPath] = {}     # data item -> how it parses
        self.members: dict[str, list[str]] = {}   # data item -> its files
        self.ignored: dict[str, list[str]] = {}   # ... and its ignored files
        self.meta: list[ParsedPath] = []
        self.ignored_meta: set[str] = set()
        self.kept: set[str] = set()
        self.ignore = ignore
        self.scopes = _Scopes()
        self.required: dict[str, bool] = {}       # see `_required`
        self.tagged: set[str] = set()             # see `unsure`
        self.listed = list(paths)
        for path in self.listed:
            self._sort(path)
        self.passed = {
            item for item, d in self.data.items()
            if self.members.get(item) and f._passes(d) and self._has_subject(d)
        }
        self.chains: dict[str, tuple[str, ...]] = {}
        if f.sidecar:
            self.chains = _sidecar_chains(
                [self.data[item] for item in self.passed],
                [*self.meta, *self.data.values()], self.scopes,
            )
        self.reads = {rel for chain in self.chains.values() for rel in chain}

    def _sort(self, path: str) -> None:
        self.scopes.note(path)
        kind, name = _classify(path, self.filter.folders)
        ignored = self.ignore is not None and self.ignore.ignores(path)
        if kind == "keep" and (not ignored or _dataset_level(path)):
            # `.bidsignore` never removes a dataset-level file (rule 4).
            self.kept.add(path)
        elif kind == "meta":
            self.meta.append(name)  # type: ignore[arg-type]
            if ignored:
                self.ignored_meta.add(path)
        elif kind == "data":
            self.data.setdefault(name.item, name)  # type: ignore[union-attr]
            files = self.ignored if ignored else self.members
            files.setdefault(name.item, []).append(path)  # type: ignore

    def _kept_alone(self, m: ParsedPath) -> bool:
        """Whether a metadata file that applies to no data file is kept."""
        f = self.filter
        if m.path in self.ignored_meta:
            return False
        if self.scopes.scope(m.directory)[1] is None:
            # Outside every dataset root, a metadata file reaches only its
            # own folder's data files, so it is never kept on its own.
            return False
        if not all(test.lenient for test in f.sidecar.values()):
            return False
        return f._passes(m, partial=True) and self._has_subject(m, partial=True)

    def _required(self, x: ParsedPath, all_data: dict) -> bool:
        """Whether `x` applies only to recordings with its `acq` label.

        See `acq_required`: `x` is a `photo`, `headshape` or `markers` file
        (or its JSON), and `all_data` the index of every data item, of
        which the recordings it may apply to are those it reaches.
        """
        if x.path not in self.required:
            self.required[x.path] = acq_required(
                x, all_data.get(x.directory, ()), self.scopes.applies_to
            )
        return self.required[x.path]

    def _relates(
        self, x: ParsedPath, d: ParsedPath, all_data: dict | None = None
    ) -> bool:
        """Whether file `x` comes along with data item `d`, when `d` is kept.

        A recording (see `ParsedPath.has_companions`) brings the metadata
        and the companions that apply to it (`applies_to`); any other data
        item (`events.tsv`, `photo.jpg`) its JSON sidecars alone. An
        `acq`-tagged `photo`, `headshape` or `markers` file needs its `acq`
        matched only when `_required` says so, given `all_data`; without
        `all_data`, its `acq` is not compared, which tells as well whether
        it comes along with any recording at all.
        """
        if x.item == d.item:
            return False
        scopes = self.scopes
        if not d.has_companions:
            return (
                x.extension == ".json" and x.suffix is not None
                and scopes.applies_to(x, d, companions=False)
            )
        if is_acq_tagged(x) and (
            all_data is None or not self._required(x, all_data)
        ):
            return scopes.applies_to(x, d, acq=False)
        return scopes.applies_to(x, d)

    def unsure(self, pruned: list[str]) -> list[ParsedPath]:
        """Return the files whose fate depends on pruned folders.

        Those above a folder in `pruned` that are either metadata that
        applies to no data file listed and would be kept for that (rule
        3), or an `acq`-tagged companion (see `_required`) that would come
        along with a recording without its `acq` label, since no recording
        listed has it: if a data file inside the folder is one it applies
        to (has that label), it is not kept after all (it is not brought
        along).
        """
        if not pruned:
            return []
        scopes = self.scopes
        all_data = scopes.index(self.data.values())
        candidates = [
            m for m in self.meta
            if not scopes.applies(m, all_data, self._relates)
            and self._kept_alone(m)
        ]
        passed = scopes.index(self.data[item] for item in self.passed)
        companions = [d for d in self.data.values() if d.is_companion]
        for x in (*self.meta, *companions):
            if (
                x.item in self.passed or not is_acq_tagged(x)
                or self._required(x, all_data)
            ):
                continue
            if any(
                d.has_companions and not _same_acq(x, d)
                and scopes.applies_to(x, d, acq=False)
                for d in passed.get(x.directory, ())
            ):
                candidates.append(x)
                self.tagged.add(x.path)
        return [m for m in candidates
                if any(_above_any([m], p) for p in pruned)]

    def settle(
        self, unsure: list[ParsedPath], paths: Iterable[str]
    ) -> list[ParsedPath]:
        """Return the files of `unsure` that no data file of `paths` settles.

        `paths` are the files of one more directory (or level) of the walk,
        listed after every directory above them. A data file settles a
        metadata file it applies to, and an `acq`-tagged companion that it
        is a recording with the same `acq` of.
        """
        paths = list(paths)
        for path in paths:
            self.scopes.note(path)
        for path in paths:
            if not unsure:
                break
            kind, d = _classify(path, self.filter.folders)
            if kind == "data":
                unsure = [
                    m for m in unsure
                    if not self._settles(m, d)  # type: ignore[arg-type]
                ]
        return unsure

    def _settles(self, m: ParsedPath, d: ParsedPath) -> bool:
        """Whether data file `d` settles the fate of `m` (see `settle`)."""
        if m.path in self.tagged:
            return (
                d.has_companions and _same_acq(m, d)
                and self.scopes.applies_to(m, d, acq=False)
            )
        return self._relates(m, d)

    def _has_subject(self, name: ParsedPath, partial: bool = False) -> bool:
        """Whether a file's subject passes the participants filters.

        The subject is the name's, else its folder's. With `partial` (a
        metadata file judged on its own name), a file without one passes.
        """
        if self.subjects is None:
            return True
        label = _with_directory_entities(name).get("sub")
        if label is None:
            return partial
        return label in self.subjects

    def finish(self, contents: Mapping[str, object]) -> list[str]:
        """Return the kept paths, sorted, given the sidecars in `reads`."""
        f, kept = self.filter, set(self.kept)
        passed = self.passed
        if f.sidecar:
            passed = {
                item for item in passed
                if _sidecar_passes(f, [contents[r] for r in self.chains[item]])
            }
        for item in passed:
            kept.update(self.members[item])
        scopes = self.scopes
        kept_data = scopes.index(self.data[item] for item in passed)
        all_data = scopes.index(self.data.values())
        self.required.clear()

        def brought(x: ParsedPath) -> bool:
            return scopes.applies(
                x, kept_data, lambda x, d: self._relates(x, d, all_data)
            )

        # A companion (`events.tsv`, `physio.tsv.gz`, `photo.jpg`) follows
        # the recordings it describes, as their metadata does, even when it
        # does not pass the filters or `.bidsignore` names it.
        for item, d in self.data.items():
            if item not in passed and d.is_companion and brought(d):
                kept.update(self.members.get(item, ()))
                kept.update(self.ignored.get(item, ()))
        for m in self.meta:
            if brought(m) or (
                not scopes.applies(m, all_data, self._relates)
                and self._kept_alone(m)
            ):
                kept.add(m.path)

        if f.exclude:
            kept = {p for p in kept if p in _PROTECTED or not f.exclude(p)}
        return sorted(kept)


def _same_acq(x: ParsedPath, d: ParsedPath) -> bool:
    """Whether `d` has the `acq` label of `x`."""
    label, other = x.entities.get("acq"), d.entities.get("acq")
    return None not in (label, other) and same_label("acq", label, other)


def _dataset_level(path: str) -> bool:
    """Whether a file `_classify` keeps is a dataset-level file (rule 4)."""
    parts = PurePosixPath(path).parts
    return len(parts) == 1 or parts[0] == "phenotype"


def _classify(
    path: str, folders: frozenset[str]
) -> tuple[str, ParsedPath | None]:
    """Sort a relative path into what the selection makes of it.

    `("data", parsed)` or `("meta", parsed)`; `("keep", None)` for a file
    kept whatever the filters, `("skip", None)` for one never kept. Whether
    `.bidsignore` names the file is not asked here.
    """
    parts = PurePosixPath(path).parts
    if not parts:
        return "skip", None
    if path in TOP_LEVEL_FILES:
        return "keep", None
    # Names inside a data directory (`.zattrs`) belong to the data
    boundary = data_directory(parts)
    named = parts if boundary is None else parts[:boundary + 1]
    if any(p.startswith(".") for p in named) or _is_bids_directory(parts):
        return "skip", None
    top = parts[0]
    if len(parts) > 1 and top in OPTIONAL_FOLDERS:
        return ("keep" if top in folders else "skip"), None
    name = parse_path(path)
    if top.startswith("sub-") and len(parts) > 1:
        # A companion (`events.tsv`, `photo.jpg`, a MEG crosstalk file) is
        # a data file too; its JSON sidecar (`events.json`) is metadata.
        meta = name.is_metadata and not name.is_companion
        return ("meta" if meta else "data"), name
    if top == "phenotype":
        return "keep", None
    if len(parts) == 1:
        if name.is_metadata and name.suffix:
            # top-level sidecar: T1w.json, task-rest_bold.json
            return "meta", name
        return "keep", None
    # other top-level folders (e.g. "models/") are skipped
    return "skip", None


class _Scopes:
    """Where BIDS inheritance reaches, from the `dataset_description.json`s.

    A metadata file applies to a data file only from the data file's own
    directory up to its dataset root: the nearest of those directories that
    holds a `dataset_description.json`. Without one, only the data file's
    own directory counts. This is the search `path.sidecars` makes, on the
    listing instead of the store.
    """

    def __init__(self) -> None:
        self.roots: set[PurePosixPath] = set()
        self._cache: dict[PurePosixPath, tuple] = {}

    def note(self, path: str) -> None:
        """Record a listed file, if it is a `dataset_description.json`."""
        if path.rpartition("/")[2] == _DESCRIPTION:
            self.roots.add(PurePosixPath(path).parent)
            self._cache.clear()

    def scope(
        self, directory: PurePosixPath
    ) -> tuple[tuple[PurePosixPath, ...], PurePosixPath | None]:
        """Return the directories inheritance reaches from `directory`.

        Nearest first, with the dataset root they end at (`None` without
        one).
        """
        if directory not in self._cache:
            reached = []
            found = None
            for parent in (directory, *directory.parents):
                reached.append(parent)
                if parent in self.roots:
                    found = parent
                    break
            self._cache[directory] = (
                (tuple(reached), found) if found is not None
                else ((directory,), None)
            )
        return self._cache[directory]

    def applies_to(
        self, meta: ParsedPath, data: ParsedPath, companions: bool = True,
        acq: bool = True,
    ) -> bool:
        """Whether `meta` applies to `data` within the data file's dataset."""
        dirs, root = self.scope(data.directory)
        if meta.directory not in dirs:
            return False
        if root is not None and root.parts:
            # Judged relative to the dataset root, as `path.sidecars` does.
            meta, data = _rerooted(meta, root), _rerooted(data, root)
        return applies_to(meta, data, companions=companions, acq=acq)

    def index(self, data: Iterable[ParsedPath]) -> dict:
        """Index data items by every directory inheritance reaches them from."""
        by_dir: dict[PurePosixPath, list[ParsedPath]] = {}
        for d in data:
            for parent in self.scope(d.directory)[0]:
                by_dir.setdefault(parent, []).append(d)
        return by_dir

    def applies(
        self, meta: ParsedPath, by_dir: dict,
        relation: Callable[[ParsedPath, ParsedPath], bool],
    ) -> bool:
        """Whether `relation(meta, d)` holds for a data item `d` of an `index`."""
        return any(relation(meta, d) for d in by_dir.get(meta.directory, ()))


def _rerooted(name: ParsedPath, root: PurePosixPath) -> ParsedPath:
    """Parse a path again, relative to a dataset root below the listing's."""
    return parse_path(PurePosixPath(name.path).relative_to(root).as_posix())


def _sidecar_chains(
    data: Iterable[ParsedPath], meta: Iterable[ParsedPath], scopes: _Scopes
) -> dict[str, tuple[str, ...]]:
    """Return the JSON sidecars of each data item, nearest first.

    The sidecars that apply to it (a `.json` with its suffix and a subset
    of its entities, in its directory or above, up to its dataset root, but
    the data item itself), as `path.sidecars` finds them: nearer
    directories first, and within one directory the sidecars with more
    entities. `meta` may hold data items too: a `coordsystem.json` is the
    sidecar of the one below it.
    """
    by_dir: dict[PurePosixPath, list[ParsedPath]] = {}
    for m in meta:
        if m.extension == ".json" and m.suffix is not None:
            by_dir.setdefault(m.directory, []).append(m)
    for sidecars in by_dir.values():
        sidecars.sort(key=lambda m: (-len(m.entities), PurePosixPath(m.path).name))
    chains = {}
    for d in data:
        chain = []
        for directory in scopes.scope(d.directory)[0]:
            chain.extend(
                m.path for m in by_dir.get(directory, ())
                if m.item != d.item
                and scopes.applies_to(m, d, companions=False)
            )
        chains[d.item] = tuple(chain)
    return chains


def _sidecar_passes(f: BidsFilter, contents: list[Mapping]) -> bool:
    """Whether the merged content of a chain of sidecars passes `f`."""
    for key, test in f.sidecar.items():
        value = _ABSENT
        for content in contents:
            if key in content:
                value = content[key]
                break
        if not test(value):
            return False
    return True


def _read_json(path: object) -> dict:
    """Read a JSON sidecar of a listing (inside a transaction, as it holds it).

    One that is not a JSON object raises `TypeError`, and one that is not
    valid JSON `json.JSONDecodeError`, both naming the file.
    """
    path = in_family(path, BidsPath)
    try:
        return path.as_dict()
    except json.JSONDecodeError as e:
        raise _not_json(path, e) from e


async def _aread_json(path: object) -> dict:
    """Read a JSON sidecar of a listing, as a coroutine."""
    path = in_family(path, AsyncBidsPath)
    try:
        return await path.as_dict()
    except json.JSONDecodeError as e:
        raise _not_json(path, e) from e


def _not_json(path: object, error: json.JSONDecodeError) -> json.JSONDecodeError:
    return json.JSONDecodeError(
        f"the sidecar {path} that a sidecar filter reads is not valid JSON "
        f"({error.msg})", error.doc, error.pos,
    )


def _read_rows(path: BidsPath) -> list[dict]:
    """Read the typed rows of a table."""
    return path.as_list()  # type: ignore[attr-defined]


def _no_participants(root: object) -> FileNotFoundError:
    return FileNotFoundError(
        f"a participants filter reads participants.tsv, and the dataset "
        f"{root} has none"
    )


def _readable(path: object) -> bool:
    """Whether a listing item is a path whose file can be read.

    A string, and a pure path (`PureBidsPath`, `pathlib.PurePath`), cannot.
    """
    if path is None or isinstance(path, (str, bytes)):
        return False
    if isinstance(path, (Path, AsyncPath, pathlib.Path)):
        return True
    return not isinstance(path, (PurePath, pathlib.PurePath))


async def _nothing() -> None:
    return None


# The most reads (or listings) an asynchronous walk has under way at once.
_CONCURRENCY = 32


async def _gather(
    call: Callable[[T], Awaitable[R]], items: Iterable[T]
) -> list[R]:
    """`await call(item)` for every item, `_CONCURRENCY` at a time at most.

    The results are in the order of `items`.
    """
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def one(item: T) -> R:
        async with semaphore:
            return await call(item)

    return list(await asyncio.gather(*map(one, items)))


def _with_directory_entities(name: ParsedPath) -> dict:
    """Return a name's entities, with `sub`/`ses` from its folders if absent.

    The folders are the top-level `sub-<label>/` and the `ses-<label>/`
    directly in it, the ones a walk prunes by label. Where the name has the
    entity, the name wins.
    """
    entities = dict(name.entities)
    parts = PurePosixPath(name.path).parts[:-1]
    if parts and _is_entity_directory(parts[0], "sub"):
        entities.setdefault("sub", parse_name(parts[0]).entities["sub"])
        if len(parts) > 1 and _is_entity_directory(parts[1], "ses"):
            entities.setdefault("ses", parse_name(parts[1]).entities["ses"])
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


# -- .bidsignore -----------------------------------------------------------------

class _BidsIgnore:
    r"""The patterns of a `.bidsignore`, with the rules of `.gitignore`.

    One pattern per line; blank lines and lines starting with `#` are
    skipped, trailing spaces are dropped unless escaped with a backslash
    (`trail\ `), and a backslash makes the next character part of the
    pattern (`\#`, `\!`, `\*`). `!` re-includes what an earlier pattern
    ignored, and the last pattern that matches a path decides; a file
    inside an ignored directory cannot be re-included. A pattern ending in
    `/` matches directories only. A pattern with a `/` at its start or in
    its middle is matched against the path from the dataset root; any other
    against a name at any depth. `*` and `?` match within one name, and
    `**` matches any number of directories (`**/x`, `a/**/x`, `a/**`).
    `[...]` is a class of characters as in git: ranges, `!` or `^` to
    negate it, a backslash to escape, and the POSIX classes
    (`[[:digit:]]`); it never matches `/`. As in git, a reversed range
    (`[z-a]`) matches its first character only, and a pattern git cannot
    match (an unterminated class, an unknown POSIX class, a trailing
    backslash) matches nothing.
    """

    def __init__(self, rules: list[tuple[re.Pattern, bool, bool]]) -> None:
        self.rules = rules          # (regex, negated, directories only)
        self._dirs: dict[str, bool] = {}

    @classmethod
    def parse(cls, text: str) -> _BidsIgnore | None:
        """Parse the text of a `.bidsignore`; `None` when it has no pattern."""
        rules = []
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            line = _trim_trailing_spaces(line)
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            dir_only = line.endswith("/")
            if dir_only:
                line = line[:-1]
            if not line:
                continue
            anchored = "/" in line
            regex = _ignore_regex(line.lstrip("/"), anchored)
            if regex is not None:
                rules.append((regex, negated, dir_only))
        return cls(rules) if rules else None

    def _decide(self, rel: str, is_dir: bool) -> bool:
        ignored = False
        for regex, negated, dir_only in self.rules:
            if dir_only and not is_dir:
                continue
            if regex.match(rel):
                ignored = not negated
        return ignored

    def ignores(self, rel: str, is_dir: bool = False) -> bool:
        """Whether the path `rel` (relative to the root) is ignored.

        It is when the patterns ignore it or one of its directories.
        """
        if rel in _NEVER_IGNORED:
            return False
        parts = rel.split("/")
        for i in range(1, len(parts)):
            directory = "/".join(parts[:i])
            if directory not in self._dirs:
                self._dirs[directory] = self._decide(directory, True)
            if self._dirs[directory]:
                return True
        return self._decide(rel, is_dir)


def _trim_trailing_spaces(line: str) -> str:
    """Drop the trailing spaces of a line, but those escaped (as git does)."""
    end = len(line)
    while end and line[end - 1] == " ":
        backslashes = len(line[:end - 1]) - len(line[:end - 1].rstrip("\\"))
        if backslashes % 2:
            break
        end -= 1
    return line[:end]


def _ignore_regex(pattern: str, anchored: bool) -> re.Pattern | None:
    """Translate one `.gitignore` pattern (no `!`, no trailing `/`).

    `None` for a pattern that git can never match.
    """
    segments = _ignore_segments(pattern)
    if segments is None:
        return None
    out = ["" if anchored else "(?:.*/)?"]
    for i, segment in enumerate(segments):
        last = i == len(segments) - 1
        if segment == "**":
            out.append(".*" if last else "(?:.*/)?")
            continue
        translated = _ignore_segment(segment)
        if translated is None:
            return None
        out.append(translated + ("" if last else "/"))
    return re.compile("".join(out) + r"\Z")


def _ignore_segments(pattern: str) -> list[str] | None:
    """Split a pattern on the `/` that are not in a class or escaped.

    `None` for a pattern git can never match.
    """
    segments, start, i, n = [], 0, 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            translated, i = _ignore_class(pattern, i)
            if translated is None:
                return None
            continue
        if c == "/":
            segments.append(pattern[start:i])
            start = i + 1
        i += 1
    segments.append(pattern[start:])
    return segments


def _ignore_segment(segment: str) -> str | None:
    """Translate the glob of one path segment to a regex.

    `None` for a segment git can never match.
    """
    out = []
    i, n = 0, len(segment)
    while i < n:
        c = segment[i]
        if c == "\\":
            if i + 1 == n:
                return None     # a trailing backslash escapes nothing
            out.append(re.escape(segment[i + 1]))
            i += 2
            continue
        if c == "[":
            translated, i = _ignore_class(segment, i)
            if translated is None:
                return None
            out.append(translated)
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


# The POSIX classes git knows, `[[:name:]]`, in ASCII.
_POSIX_CLASSES = {
    "alnum": "a-zA-Z0-9", "alpha": "a-zA-Z", "blank": " \\t",
    "cntrl": "\\x00-\\x1f\\x7f", "digit": "0-9", "graph": "\\x21-\\x7e",
    "lower": "a-z", "print": "\\x20-\\x7e",
    "punct": "!-/:-@\\[-`{-~", "space": " \\t\\n\\r\\f\\v", "upper": "A-Z",
    "xdigit": "0-9A-Fa-f",
}


def _ignore_class(segment: str, i: int) -> tuple[str | None, int]:
    """Translate the class that starts at `segment[i]` (a `[`), as git does.

    Return the regex and the index after the class; the regex is `None`
    when git can never match the pattern (an unterminated class, an unknown
    POSIX class). A `]` first in the class is a character of it, a
    backslash escapes the next character, a reversed range matches no
    character, and a negated class never matches `/`.
    """
    n = len(segment)
    j = i + 1
    negated = j < n and segment[j] in "!^"
    if negated:
        j += 1
    items: list[str] = []
    previous: str | None = None     # the character a `-` starts a range from
    first = True
    while True:
        if j >= n:
            return None, n
        c = segment[j]
        if c == "]" and not first:
            break
        first = False
        if c == "\\":
            j += 1
            if j >= n:
                return None, n
            previous = segment[j]
            items.append(re.escape(previous))
        elif (
            c == "-" and previous is not None and j + 1 < n
            and segment[j + 1] != "]"
        ):
            j += 1
            high = segment[j]
            if high == "\\":
                j += 1
                if j >= n:
                    return None, n
                high = segment[j]
            if previous <= high:
                items[-1] = re.escape(previous) + "-" + re.escape(high)
            # else git matches the start of a reversed range, and no more
            previous = None
        elif c == "[" and segment[j + 1:j + 2] == ":":
            end = segment.find("]", j + 2)
            if end == -1:
                return None, n
            if end == j + 2 or segment[end - 1] != ":":
                previous = "["      # not a POSIX class: `[` is a character
                items.append(re.escape(previous))
            else:
                posix = _POSIX_CLASSES.get(segment[j + 2:end - 1])
                if posix is None:
                    return None, n
                items.append(posix)
                previous = None
                j = end
        else:
            previous = c
            items.append(re.escape(c))
        j += 1
    body = "".join(items)
    if negated:
        return "[^" + body + "/]", j + 1
    if re.fullmatch("[" + body + "]", "/"):
        return "(?!/)[" + body + "]", j + 1    # a class never matches `/`
    return "[" + body + "]", j + 1


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
