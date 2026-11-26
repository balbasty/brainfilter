"""Lexical BIDS name rules: parsing, validation and file-type dispatch.

Everything here works on name strings only and never touches a filesystem,
so it applies equally to local paths, remote paths, pure paths and paths
that do not exist yet.
"""
from __future__ import annotations

from typing import NamedTuple

# Datatype directories (`sub-<label>[/ses-<label>]/<datatype>/`).
DATATYPES = frozenset({
    "anat", "func", "dwi", "fmap", "perf", "beh", "eeg", "meg", "ieeg",
    "pet", "micr", "nirs", "motion", "mrs",
})

# Extensions of metadata files (sidecars, tables, gradient tables).
METADATA_EXTENSIONS = frozenset({".json", ".tsv", ".bval", ".bvec"})

# Entity keys in the order BIDS 1.11.2 puts them in a file name
# (`rules/entities.yaml` of the official schema).
SORTED_ENTITIES = (
    "sub",          # subject
    "tpl",          # template
    "ses",          # session
    "cohort",       # cohort
    "sample",       # sample
    "task",         # task
    "tracksys",     # tracking system
    "acq",          # acquisition
    "nuc",          # nucleus
    "voi",          # volume of interest
    "ce",           # contrast enhancement
    "trc",          # tracer
    "stain",        # stain
    "rec",          # reconstruction
    "dir",          # phase-encoding direction
    "run",          # run
    "mod",          # corresponding modality
    "echo",         # echo
    "flip",         # flip angle
    "inv",          # inversion time
    "mt",           # magnetization transfer
    "part",         # magnitude/phase/real/imaginary
    "proc",         # processed (on device)
    "hemi",         # hemisphere
    "space",        # coordinate space
    "split",        # split file index
    "recording",    # recording
    "chunk",        # chunk index
    "atlas",        # atlas
    "seg",          # segmentation
    "scale",        # scale
    "res",          # resolution
    "den",          # density
    "label",        # label
    "desc",         # description (kept last by convention)
)

# Characters that would change how a name splits back into its parts.
_RESERVED = frozenset("_-./")

# Tables (and their JSON sidecars) recognised by their BIDS suffix.
_TABLE_SUFFIXES = frozenset({"participants", "sessions", "samples", "scans"})


class ParsedName(NamedTuple):
    """The BIDS components of one file or directory name."""

    basename: str
    """The name without its extension."""
    extension: str
    """Everything from the first dot of the name (`.nii.gz`), or `""`."""
    entities: dict
    """`key -> label` pairs in file-name order; empty for a non-BIDS name."""
    suffix: str | None
    """The BIDS suffix (`T1w`, `bold`); `None` when there is none."""

    @property
    def is_bids(self) -> bool:
        """Whether the name is shaped like a BIDS name."""
        return bool(self.entities) or self.suffix is not None


def parse_name(name: str) -> ParsedName:
    """Split a name into basename, extension, entities and suffix.

    The basename is cut at the first dot, so `.nii.gz` is one extension.
    It is then split on `_`: every part but the last must be a `key-label`
    entity, and the last is either an entity or the suffix. A name that does
    not have this shape (`dataset_description.json`, a doubled `_`, a part
    with an empty key or label, a repeated entity, a hidden name) is not a
    BIDS name: it has no entities and no suffix. Parsing never raises.
    """
    lead = len(name) - len(name.lstrip("."))
    stem, dot, ext = name[lead:].partition(".")
    basename, extension = name[:lead] + stem, dot + ext
    not_bids = ParsedName(basename, extension, {}, None)
    if lead or not stem:
        return not_bids
    entities: dict[str, str] = {}
    suffix = None
    parts = stem.split("_")
    for i, part in enumerate(parts):
        key, dash, value = part.partition("-")
        if dash:
            if not key or not value or key in entities:
                return not_bids
            entities[key] = value
        elif part and i == len(parts) - 1:
            suffix = part
        else:
            return not_bids
    return ParsedName(basename, extension, entities, suffix)


def sort_entities(entities: dict) -> dict:
    """Entities in canonical order; unknown keys follow in their own order."""
    known = {k: entities[k] for k in SORTED_ENTITIES if k in entities}
    return known | {k: v for k, v in entities.items() if k not in known}


def format_name(entities: dict, suffix: str | None, extension: str) -> str:
    """Join entities, suffix and extension back into a name."""
    parts = [f"{key}-{value}" for key, value in entities.items()]
    if suffix:
        parts.append(suffix)
    return "_".join(parts) + extension


def check_entity(key: object, value: object) -> tuple[str, str]:
    """Validate one new entity, returning it as strings."""
    key, value = str(key), str(value)
    # The name splits at a key's first dash, so a label may hold one.
    if not key or _RESERVED & set(key):
        raise ValueError(
            f"invalid BIDS entity {key}-{value}: its key must be non-empty "
            "and contain none of '_', '-', '.', '/'"
        )
    if not value or (_RESERVED - {"-"}) & set(value):
        raise ValueError(
            f"invalid BIDS entity {key}-{value}: its label must be non-empty "
            "and contain none of '_', '.', '/'"
        )
    return key, value


def check_suffix(suffix: str) -> str:
    """Validate a new BIDS suffix."""
    if suffix.startswith("."):
        raise ValueError(
            f"{suffix!r} looks like a file extension; with_suffix sets the "
            "BIDS suffix (T1w, bold, ...), use with_extension for '.nii.gz'"
        )
    if not suffix or _RESERVED & set(suffix):
        raise ValueError(
            f"invalid BIDS suffix {suffix!r}: it must be non-empty and "
            "contain none of '_', '-', '.', '/'"
        )
    return suffix


def check_extension(extension: str) -> str:
    """Validate a new extension: empty, or a dot then no `/`."""
    if extension and (
        not extension.startswith(".") or extension == "." or "/" in extension
    ):
        raise ValueError(
            f"invalid extension {extension!r}: it must be empty or start "
            "with a dot, as in '.nii.gz'"
        )
    return extension


def role_of(name: str, parent_name: str) -> str | None:
    """Tell the kind of BIDS file a name denotes, from the names alone.

    Returns `None` for a name with no special role. The rules read the name
    and its parent's name only, never the filesystem.
    """
    if name == "dataset_description.json":
        return "dataset_description"
    parsed = parse_name(name)
    ext = parsed.extension
    if parent_name == "phenotype" and ext in (".tsv", ".json"):
        return "phenotype" + ("_sidecar" if ext == ".json" else "")
    if parsed.suffix in _TABLE_SUFFIXES and ext in (".tsv", ".json"):
        return parsed.suffix + ("_sidecar" if ext == ".json" else "")
    if name == "code":
        return "code"
    if ext == ".json":
        return "sidecar"
    if ext == ".tsv":
        return "table"
    return None
