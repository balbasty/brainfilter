"""The files that belong with a data file: sidecars, companions, fieldmaps.

Each search here does no I/O itself. It is a generator that yields what it
needs, `("list", directory)` for the set of a directory's child names or
`("read", file)` for the content of a JSON file, and is sent the answer
back, so that one search serves the sync and the async surfaces (see
`TreeMixin` and `AsyncTreeMixin`, which answer the requests).

- `search_sidecars`: the JSON sidecars of a file, nearest first (BIDS
  inheritance, up to the dataset root).
- `search_companions`: the other files that come along with a recording
  under the same inheritance rules, as `BidsFilter` keeps them: its
  companion metadata (`events.tsv`, `channels.tsv`, `scans.tsv`, a `.bval`,
  ...), the companion recordings that apply to it (`physio.tsv.gz`,
  `blood.tsv`) and the companion files (`photo.jpg`, `headshape.pos`, a
  MEG crosstalk file). A `photo`, `headshape` or `markers` file with an
  `acq` label applies to it by that label only when a recording it may
  apply to has it (see `acq_required`).
- `search_companion`: one of them by name (`events`, `bval`,
  `crosstalk`), or an image paired with the data file (`sbref`, `m0scan`,
  `mrsref`).
- `search_fieldmaps`: the fieldmaps of the subject that name a data file,
  through `IntendedFor` or `B0FieldIdentifier`/`B0FieldSource`.
"""
from __future__ import annotations

import posixpath
from collections.abc import Generator, Iterable
from typing import Any, TypeVar

from brainfilter._names import (
    COMPANION_SUFFIXES,
    IMAGE_EXTENSIONS,
    JSON_COMPANIONS,
    MEG_SYSTEM_FILES,
    METADATA_EXTENSIONS,
    PAIRED_IMAGES,
    acq_required,
    applies_to,
    check_entity,
    data_directory,
    has_companions,
    is_acq_tagged,
    is_companion_file,
    is_companion_recording,
    is_metadata,
    meg_system_file,
    parse_name,
    parse_path,
    same_label,
)

__all__ = ["DATASET_DESCRIPTION", "check_companion", "companion_names",
           "search_companion", "search_companions", "search_fieldmaps",
           "search_paired", "search_sidecars"]

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
    """Whether `path` is named like a recording: a data file with companions.

    A BIDS file name (a suffix, and entities or an extension) that is not a
    metadata file (`events.tsv`), nor a companion file (`photo.jpg`, a MEG
    crosstalk file; see `has_companions`), and not a file inside a data
    file that is a directory (`sub-01_meg.ds/`). A filter selects those as
    data files too, but they have no companions. Nothing is read.
    """
    parsed = parse_name(path.name)
    if not has_companions(parsed.suffix, parsed.extension, parsed.entities):
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
    a metadata file that is not one of its JSON sidecars, a recording with
    a companion suffix (`physio.tsv.gz`, `blood.tsv`), or a companion file
    (`photo.jpg`, `headshape.pos`, a MEG crosstalk file): the files
    `BidsFilter` keeps along with `path`, but its sidecars. Nearer
    directories first, by name within one.
    """
    levels = yield from _companion_levels(path)
    return tuple(file for level in levels for file in level)


def _companion_levels(path: _P) -> _Search:
    """Return the companions of `path` per directory, nearest first.

    A list of lists, one per directory the inheritance reaches that holds
    a companion, each sorted by name (see `search_companions`).
    """
    if not _is_data_file(path):
        return []
    levels, data_rel, rooted = yield from _levels(path)
    cache = {str(directory): names for directory, names, _ in levels}
    # A dataset root in a subject folder is no top level: the files of its
    # folder are those of the subject.
    top = rooted and not any(
        _is_entity_directory(p.name, "sub")
        for p in (levels[-1][0], *levels[-1][0].parents)
    )
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
            elif not (
                is_companion_recording(parsed.suffix, parsed.extension)
                or is_companion_file(
                    parsed.suffix, parsed.extension, parsed.entities
                )
            ):
                continue
            meta_rel = f"{rel_dir}/{name}".lstrip("/")
            if applies_to(meta_rel, data_rel) or (
                is_acq_tagged(meta_rel)
                and applies_to(meta_rel, data_rel, acq=False)
                and not acq_required(meta_rel, (yield from _recordings(
                    directory, names, rel_dir, top,
                    rooted and parse_path(meta_rel).datatype is None, cache,
                )))
            ):
                level.append(name)
        if level:
            found.append([directory / name for name in sorted(level)])
    return found


def _recordings(
    directory: _P, names: set[str], rel_dir: str, top: bool, below: bool,
    cache: dict[str, set[str]],
) -> _Search:
    """Return the recordings a file of `directory` may apply to.

    Their paths relative to the dataset root (`rel_dir` is that of
    `directory`): the names of `directory` that are recordings (see
    `has_companions`). At the top level of a dataset (`top` and an empty
    `rel_dir`), the recordings are in its `sub-<label>/` folders, and none
    is the dataset's own. With `below` (for a file outside a datatype
    directory, in a dataset with a root), the recordings in the folders
    below `directory` count too, but in hidden folders, in folders named
    with an extension (a data file that is a directory is a recording of
    its own) and in nested datasets (a folder with its own
    `dataset_description.json`), whose files inherit nothing from above.
    """
    found = []
    pending = [(directory, names, rel_dir)]
    while pending:
        parent, children, rel = pending.pop()
        at_top = top and not rel
        for name in sorted(children):
            child_rel = f"{rel}/{name}".lstrip("/")
            parsed = parse_name(name)
            if not at_top and has_companions(
                parsed.suffix, parsed.extension, parsed.entities
            ):
                found.append(child_rel)
            if (
                not below or name.startswith(".") or parsed.extension
                or (at_top and not name.startswith("sub-"))
                or data_directory((*child_rel.split("/"), "")) is not None
            ):
                continue
            listed = yield from _listing(parent / name, cache)
            if listed and DATASET_DESCRIPTION not in listed:
                pending.append((parent / name, listed, child_rel))
    return found


# -- one companion -------------------------------------------------------------

def companion_names() -> list[str]:
    """Return every name `companion` takes, sorted."""
    extensions = {e[1:] for e in METADATA_EXTENSIONS} - {"json", "tsv"}
    return sorted(
        COMPANION_SUFFIXES | extensions | set(PAIRED_IMAGES)
        | set(MEG_SYSTEM_FILES)
    )


def check_companion(name: object, entities: dict) -> dict[str, str | None]:
    """Check a `companion` request; return its entities as strings.

    `name` must be one of `companion_names()`, and each entity a valid
    `key-label` (a label of `None` asks for a file without that entity).
    """
    names = companion_names()
    if name not in names:
        raise ValueError(
            f"unknown companion {name!r}: name one of {', '.join(names)}"
        )
    checked: dict[str, str | None] = {}
    for key, label in entities.items():
        if label is None:
            checked[str(key)] = None
        else:
            key, label = check_entity(key, label)
            checked[key] = label
    return checked


def _wanted(name: str, path: Any, entities: dict) -> Any:  # noqa: ANN401
    """Return a test of whether a file name is the `name` companion of `path`."""
    extension = f".{name}"

    def test(file: str) -> bool:
        parsed = parse_name(file)
        if name in MEG_SYSTEM_FILES:
            system = meg_system_file(
                parsed.entities, parsed.suffix, parsed.extension
            )
            if system != name:
                return False
        elif name in COMPANION_SUFFIXES:
            if parsed.suffix != name:
                return False
            is_json = parsed.extension == ".json"
            if is_json != (name in JSON_COMPANIONS):
                return False
        elif parsed.suffix != path.suffix or parsed.extension != extension:
            return False
        return _has_entities(parsed.entities, entities)

    return test


def _has_entities(have: dict, entities: dict) -> bool:
    """Whether a name's entities have these labels (`None`: not the entity)."""
    for key, label in entities.items():
        other = have.get(key)
        if label is None:
            if other is not None:
                return False
        elif other is None or not same_label(key, other, label):
            return False
    return True


def _ambiguous(path: Any, name: str, files: list) -> ValueError:  # noqa: ANN401
    """Build the error for several `name` companions in one directory."""
    parsed = [parse_name(file.name).entities for file in files]
    keys = sorted({key for entities in parsed for key in entities})
    hint = "they differ only in their extension"
    for key in keys:
        labels = [entities.get(key) for entities in parsed]
        if len(set(labels)) > 1:
            label = next(label for label in labels if label is not None)
            hint = (
                "name the one you want by an entity, e.g. "
                f"companion({name!r}, {key}={label!r})"
            )
            break
    listed = ", ".join(file.name for file in files)
    return ValueError(
        f"{path.name} has {len(files)} {name!r} companions in "
        f"{str(files[0].parent)!r}: {listed}; {hint}"
    )


def search_companion(path: _P, name: str, entities: dict) -> _Search:
    """Find one companion of a data file (`TreeMixin.companion`), or `None`.

    `name` and `entities` are checked by `check_companion`. A paired image
    (`sbref`, `m0scan`, `mrsref`) is looked for by `search_paired`; any
    other name in `companions`: the files of the nearest directory that
    holds one, which must hold only one.
    """
    if name in PAIRED_IMAGES:
        found = yield from search_paired(path, name, entities)
    else:
        test = _wanted(name, path, entities)
        found = []
        for level in (yield from _companion_levels(path)):
            found = [file for file in level if test(file.name)]
            if found:
                break
    if len(found) > 1:
        raise _ambiguous(path, name, found)
    return found[0] if found else None


def search_paired(path: _P, name: str, entities: dict) -> _Search:
    """Find the `name` images paired with a data file (`sbref`, `mrsref`, ...).

    Those in its own directory with the same entities (index entities
    compared by number) and an image extension, sorted by name; none when
    the schema pairs no `name` image with this file's suffix.
    """
    if path.suffix not in PAIRED_IMAGES[name] or not _is_data_file(path):
        return []
    own = parse_name(path.name).entities
    found = []
    for file in sorted((yield from _list(path.parent))):
        parsed = parse_name(file)
        if (
            parsed.suffix == name and parsed.extension in IMAGE_EXTENSIONS
            and set(parsed.entities) == set(own)
            and _has_entities(parsed.entities, own)
            and _has_entities(parsed.entities, entities)
        ):
            found.append(path.parent / file)
    return found


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
