"""The files that belong with a data file: sidecars, companions, fieldmaps.

Each search here does no I/O itself. It is a generator that yields what it
needs, `("list", directory)` for the set of a directory's child names or
`("read", file)` for the content of a JSON file, and is sent the answer
back, so that one search serves the sync and the async surfaces (see
`TreeMixin` and `AsyncTreeMixin`, which answer the requests).

- `search_sidecars`: the JSON sidecars of a file, nearest first (BIDS
  inheritance, up to the dataset root).
- `search_companions`: the other files that come along with a data file
  under the same inheritance rules, as `BidsFilter` keeps them: its
  companion metadata (`events.tsv`, `channels.tsv`, `scans.tsv`, a `.bval`,
  ...) and the companion recordings that apply to it (`physio.tsv.gz`).
- `search_fieldmaps`: the fieldmaps of the subject that name a data file,
  through `IntendedFor` or `B0FieldIdentifier`/`B0FieldSource`.
"""
from __future__ import annotations

import posixpath
from collections.abc import Generator, Iterable
from typing import Any, TypeVar

from brainfilter._names import (
    applies_to,
    data_directory,
    is_companion_recording,
    is_metadata,
    parse_name,
)

__all__ = ["DATASET_DESCRIPTION", "search_companions", "search_fieldmaps",
           "search_sidecars"]

DATASET_DESCRIPTION = "dataset_description.json"

# The datatype directory of fieldmaps.
_FMAP = "fmap"

# A path of either family (sync or async).
_P = TypeVar("_P")

# A search: yields `(kind, path)` requests, is sent their answers.
_Search = Generator[tuple[str, Any], Any, Any]


def _list(directory: _P) -> _Search:
    """Ask for the child names of `directory`."""
    return (yield ("list", directory))


def _levels(path: _P) -> _Search:
    """List the directories BIDS inheritance reaches from `path`, once each.

    Returns `(levels, data_rel, rooted)`: `levels` holds `(directory,
    names, rel_dir)` from the file's own directory up to its dataset root,
    the nearest that holds a `dataset_description.json` (`rooted`), or the
    file's own directory alone when there is none; `rel_dir` and `data_rel`
    are the directory and the file relative to the root (to the file's own
    directory without one), as `applies_to` expects.
    """
    listed: list[tuple[Any, set[str]]] = []
    rooted = False
    for directory in path.parents:
        names = yield from _list(directory)
        listed.append((directory, names))
        if DATASET_DESCRIPTION in names:
            rooted = True
            break
    else:
        # No dataset root: only the file's own directory counts. Its
        # listing is the first one, so this costs no more I/O.
        listed = listed[:1]
    dirs = [d.name for d, _ in listed[:-1]]
    rel_dirs = ["/".join(reversed(dirs[i:])) for i in range(len(dirs))]
    rel_dirs.append("")
    data_rel = f"{rel_dirs[0]}/{path.name}".lstrip("/")
    levels = [(d, names, rel) for (d, names), rel in zip(listed, rel_dirs)]
    return levels, data_rel, rooted


def _is_data_file(path: Any) -> bool:  # noqa: ANN401
    """Whether `path` is named like a data file: neither metadata nor inside one.

    A BIDS file name (a suffix, and entities or an extension) that is not a
    metadata file, and not a file inside a data file that is a directory
    (`sub-01_meg.ds/`). Nothing is read.
    """
    parsed = parse_name(path.name)
    if not parsed.is_file_name or is_metadata(parsed.suffix, parsed.extension):
        return False
    return data_directory(path.parts) is None


def search_sidecars(path: _P) -> _Search:
    """Find the sidecars of `path`, nearest first (see `TreeMixin.sidecars`)."""
    if path.suffix is None:
        return ()
    levels, data_rel, _ = yield from _levels(path)
    found = []
    for directory, names, rel_dir in levels:
        level = []
        for name in names:
            parsed = parse_name(name)
            if parsed.extension != ".json" or parsed.suffix is None:
                continue
            if directory == path.parent and name == path.name:
                continue
            meta_rel = f"{rel_dir}/{name}".lstrip("/")
            if applies_to(meta_rel, data_rel, companions=False):
                level.append((-len(parsed.entities), name))
        found.extend(directory / name for _, name in sorted(level))
    return tuple(found)


def search_companions(path: _P) -> _Search:
    """Find the companions of a data file, nearest first (`TreeMixin.companions`).

    A file of a directory the inheritance reaches (see `_levels`) is one
    when it applies to `path` (`applies_to`, companions included) and is
    either a metadata file that is not one of its JSON sidecars, or a
    recording with a companion suffix (`physio.tsv.gz`): the files
    `BidsFilter` keeps along with `path`, but its sidecars. Nearer
    directories first, by name within one.
    """
    if not _is_data_file(path):
        return ()
    levels, data_rel, _ = yield from _levels(path)
    found = []
    for directory, names, rel_dir in levels:
        level = []
        for name in names:
            if directory == path.parent and name == path.name:
                continue
            parsed = parse_name(name)
            if parsed.suffix is None:
                continue
            if is_metadata(parsed.suffix, parsed.extension):
                if parsed.extension == ".json" and parsed.suffix == path.suffix:
                    continue        # a sidecar, which `sidecars` finds
            elif not is_companion_recording(parsed.suffix, parsed.extension):
                continue
            meta_rel = f"{rel_dir}/{name}".lstrip("/")
            if applies_to(meta_rel, data_rel):
                level.append(name)
        found.extend(directory / name for name in sorted(level))
    return tuple(found)


# -- fieldmaps ---------------------------------------------------------------------

def _listing(directory: _P, cache: dict[str, set[str]]) -> _Search:
    """Ask for the child names of `directory`, once per search."""
    key = str(directory)
    if key not in cache:
        cache[key] = yield from _list(directory)
    return cache[key]


def _cached(search: _Search, cache: dict[str, set[str]]) -> _Search:
    """Run a search, answering each directory it lists from `cache`."""
    try:
        kind, target = next(search)
        while True:
            assert kind == "list"
            names = yield from _listing(target, cache)
            kind, target = search.send(names)
    except StopIteration as done:
        return done.value


def _merged_sidecar(
    path: _P, listings: dict[str, set[str]], contents: dict[str, dict]
) -> _Search:
    """Return the merged content of the sidecars of `path`, as a `dict`.

    The nearest sidecar that has a key gives its value, as in
    `path.sidecar`; each sidecar is read once per search.
    """
    sidecars = yield from _cached(search_sidecars(path), listings)
    merged: dict = {}
    for sidecar in reversed(sidecars):
        key = str(sidecar)
        if key not in contents:
            contents[key] = yield ("read", sidecar)
        merged.update(contents[key])
    return merged


def _strings(value: object) -> list[str]:
    """Return the strings of a metadata value: a string, or a list of them."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _is_entity_directory(name: str, key: str) -> bool:
    """Whether `name` is a `<key>-<label>` directory (`sub-01`, `ses-1`)."""
    parsed = parse_name(name)
    return (
        parsed.suffix is None and not parsed.extension
        and list(parsed.entities) == [key]
    )


def _relative(target: str) -> str | None:
    """Normalise a relative `/` path; `None` for one that leaves its base."""
    if not target or target.startswith("/"):
        return None
    target = posixpath.normpath(target)
    if target == ".." or target.startswith("../"):
        return None
    return target


def _intended(
    entries: Iterable[str], subject_rel: str, dataset_rel: str | None
) -> bool:
    """Whether an `IntendedFor` names the file at these relative paths.

    A `bids::` URI is relative to the dataset root (`dataset_rel`, `None`
    without a root, where it cannot be resolved); a URI naming another
    dataset (`bids:<name>:`) never names this file. Any other entry is
    relative to the subject directory (`subject_rel`).
    """
    for entry in entries:
        if entry.startswith("bids:"):
            name, colon, target = entry[len("bids:"):].partition(":")
            if not colon or name or dataset_rel is None:
                continue
            if _relative(target) == dataset_rel:
                return True
        elif _relative(entry) == subject_rel:
            return True
    return False


def search_fieldmaps(path: _P) -> _Search:
    """Find the fieldmaps of a data file, sorted (see `TreeMixin.fieldmaps`).

    The candidates are the data files of the `fmap/` directories of the
    file's subject (`sub-<label>/fmap/`, `sub-<label>/ses-<label>/fmap/`),
    the subject directory being the nearest `sub-<label>` folder above the
    file, within its dataset. One is a fieldmap of `path` when its merged
    sidecar's `IntendedFor` names `path`, or its `B0FieldIdentifier` is one
    of the `B0FieldSource` of the merged sidecar of `path`. Each directory
    is listed, and each sidecar read, once.
    """
    if not _is_data_file(path):
        return ()
    listings: dict[str, set[str]] = {}
    contents: dict[str, dict] = {}
    levels, _, rooted = yield from _cached(_levels(path), listings)
    root = levels[-1][0] if rooted and levels else None

    # The path of `path` relative to each of its parents, nearest first,
    # up to the dataset root; the subject directory is one of them.
    below: dict[str, str] = {}
    subject = None
    names = [path.name]
    for parent in path.parents:
        below[str(parent)] = "/".join(reversed(names))
        if subject is None and _is_entity_directory(parent.name, "sub"):
            subject = parent
        if root is not None and str(parent) == str(root):
            break
        names.append(parent.name)
    if subject is None:
        return ()
    subject_rel = below[str(subject)]
    dataset_rel = None if root is None else below[str(root)]

    fmaps = []
    top = yield from _listing(subject, listings)
    if _FMAP in top:
        fmaps.append(subject / _FMAP)
    for name in sorted(top):
        if _is_entity_directory(name, "ses"):
            session = subject / name
            if _FMAP in (yield from _listing(session, listings)):
                fmaps.append(session / _FMAP)

    sources: set[str] | None = None
    found = []
    for fmap in fmaps:
        for name in sorted((yield from _listing(fmap, listings))):
            candidate = fmap / name
            if name == path.name and fmap == path.parent:
                continue
            if not _is_data_file(candidate):
                continue
            meta = yield from _merged_sidecar(candidate, listings, contents)
            if _intended(
                _strings(meta.get("IntendedFor")), subject_rel, dataset_rel
            ):
                found.append(candidate)
                continue
            identifiers = _strings(meta.get("B0FieldIdentifier"))
            if not identifiers:
                continue
            if sources is None:
                own = yield from _merged_sidecar(path, listings, contents)
                sources = set(_strings(own.get("B0FieldSource")))
            if sources.intersection(identifiers):
                found.append(candidate)
    return tuple(found)
