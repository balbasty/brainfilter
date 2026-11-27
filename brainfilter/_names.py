"""Lexical BIDS name rules: parsing, validation and file-type dispatch.

Everything here works on name strings only and never touches a filesystem,
so it applies equally to local paths, remote paths, pure paths and paths
that do not exist yet.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import PurePath, PurePosixPath
from typing import NamedTuple

# Datatype directories (`sub-<label>[/ses-<label>]/<datatype>/`): the
# `objects.datatypes` of the official BIDS 1.11.2 schema, but `phenotype`,
# which is a dataset-level directory.
DATATYPES = frozenset({
    "anat", "func", "dwi", "fmap", "perf", "beh", "eeg", "emg", "meg",
    "ieeg", "pet", "micr", "nirs", "motion", "mrs",
})

# The datatype directories each data and metadata suffix may be in: every
# `suffixes`/`datatypes` pair of `rules.files.raw` in the official BIDS 1.11.2
# schema (`schema.json` of bidsschematools 2.0.1), merged per suffix. A suffix
# with several datatypes (`events`, `physio`, `channels`, ...) cannot be
# placed from the name alone. The subject and session tables (`sessions`,
# `scans`) are in no datatype directory; see `TABLE_LEVELS`.
SUFFIX_DATATYPES: dict[str, frozenset[str]] = {
    "2PE": frozenset({"micr"}),
    "ADC": frozenset({"dwi"}),
    "angio": frozenset({"anat"}),
    "asl": frozenset({"perf"}),
    "aslcontext": frozenset({"perf"}),
    "asllabeling": frozenset({"perf"}),
    "beh": frozenset({"beh"}),
    "BF": frozenset({"micr"}),
    "blood": frozenset({"pet"}),
    "bold": frozenset({"func"}),
    "CARS": frozenset({"micr"}),
    "cbv": frozenset({"func"}),
    "channels": frozenset({"eeg", "emg", "ieeg", "meg", "motion", "nirs"}),
    "Chimap": frozenset({"anat"}),
    "colFA": frozenset({"dwi"}),
    "CONF": frozenset({"micr"}),
    "coordsystem": frozenset({"eeg", "emg", "ieeg", "meg", "nirs"}),
    "defacemask": frozenset({"anat"}),
    "DF": frozenset({"micr"}),
    "DIC": frozenset({"micr"}),
    "dwi": frozenset({"dwi"}),
    "eeg": frozenset({"eeg"}),
    "electrodes": frozenset({"eeg", "emg", "ieeg", "meg"}),
    "emg": frozenset({"emg"}),
    "epi": frozenset({"fmap"}),
    "events": frozenset({
        "beh", "eeg", "emg", "func", "ieeg", "meg", "motion", "mrs", "nirs", "pet",
    }),
    "expADC": frozenset({"dwi"}),
    "FA": frozenset({"dwi"}),
    "fieldmap": frozenset({"fmap"}),
    "FLAIR": frozenset({"anat"}),
    "FLASH": frozenset({"anat"}),
    "FLUO": frozenset({"micr"}),
    "headshape": frozenset({"meg"}),
    "ieeg": frozenset({"ieeg"}),
    "inplaneT1": frozenset({"anat"}),
    "inplaneT2": frozenset({"anat"}),
    "IRT1": frozenset({"anat"}),
    "M0map": frozenset({"anat"}),
    "m0scan": frozenset({"fmap", "perf"}),
    "magnitude": frozenset({"fmap"}),
    "magnitude1": frozenset({"fmap"}),
    "magnitude2": frozenset({"fmap"}),
    "markers": frozenset({"meg"}),
    "meg": frozenset({"meg"}),
    "MEGRE": frozenset({"anat"}),
    "MESE": frozenset({"anat"}),
    "motion": frozenset({"motion"}),
    "MP2RAGE": frozenset({"anat"}),
    "MPE": frozenset({"micr"}),
    "MPM": frozenset({"anat"}),
    "mrsi": frozenset({"mrs"}),
    "mrsref": frozenset({"mrs"}),
    "MTR": frozenset({"anat"}),
    "MTRmap": frozenset({"anat"}),
    "MTS": frozenset({"anat"}),
    "MTsat": frozenset({"anat"}),
    "MTVmap": frozenset({"anat"}),
    "MWFmap": frozenset({"anat"}),
    "nirs": frozenset({"nirs"}),
    "NLO": frozenset({"micr"}),
    "noRF": frozenset({"func", "perf"}),
    "OCT": frozenset({"micr"}),
    "optodes": frozenset({"nirs"}),
    "PC": frozenset({"micr"}),
    "PD": frozenset({"anat"}),
    "PDmap": frozenset({"anat"}),
    "PDT2": frozenset({"anat"}),
    "PDw": frozenset({"anat"}),
    "pet": frozenset({"pet"}),
    "phase": frozenset({"func"}),
    "phase1": frozenset({"fmap"}),
    "phase2": frozenset({"fmap"}),
    "phasediff": frozenset({"fmap"}),
    "photo": frozenset({"eeg", "emg", "ieeg", "meg", "micr", "nirs"}),
    "physio": frozenset({
        "anat", "beh", "dwi", "eeg", "emg", "func", "ieeg", "meg", "motion",
        "nirs", "perf", "pet",
    }),
    "physioevents": frozenset({
        "anat", "beh", "dwi", "eeg", "emg", "func", "ieeg", "meg", "motion",
        "nirs", "perf", "pet",
    }),
    "PLI": frozenset({"micr"}),
    "R1map": frozenset({"anat"}),
    "R2map": frozenset({"anat"}),
    "R2starmap": frozenset({"anat"}),
    "RB1COR": frozenset({"fmap"}),
    "RB1map": frozenset({"fmap"}),
    "S0map": frozenset({"anat", "dwi"}),
    "sbref": frozenset({"dwi", "func"}),
    "SEM": frozenset({"micr"}),
    "SPIM": frozenset({"micr"}),
    "SR": frozenset({"micr"}),
    "stim": frozenset({
        "anat", "beh", "dwi", "eeg", "emg", "func", "ieeg", "meg", "motion",
        "nirs", "perf", "pet",
    }),
    "svs": frozenset({"mrs"}),
    "T1map": frozenset({"anat"}),
    "T1rho": frozenset({"anat"}),
    "T1w": frozenset({"anat"}),
    "T2map": frozenset({"anat"}),
    "T2star": frozenset({"anat"}),
    "T2starmap": frozenset({"anat"}),
    "T2starw": frozenset({"anat"}),
    "T2w": frozenset({"anat"}),
    "TB1AFI": frozenset({"fmap"}),
    "TB1DAM": frozenset({"fmap"}),
    "TB1EPI": frozenset({"fmap"}),
    "TB1map": frozenset({"fmap"}),
    "TB1RFM": frozenset({"fmap"}),
    "TB1SRGE": frozenset({"fmap"}),
    "TB1TFL": frozenset({"fmap"}),
    "TEM": frozenset({"micr"}),
    "trace": frozenset({"dwi"}),
    "uCT": frozenset({"micr"}),
    "UNIT1": frozenset({"anat"}),
    "unloc": frozenset({"mrs"}),
    "VFA": frozenset({"anat"}),
    "XPCT": frozenset({"micr"}),
}

# The level of the subject and session tables (`rules.files.common.tables`
# of the official BIDS 1.11.2 schema): `sub-<label>_sessions.tsv` in the
# subject directory, `sub-<label>[_ses-<label>]_scans.tsv` in the session
# directory (the subject directory when there are no sessions).
TABLE_LEVELS = {"sessions": "sub", "scans": "ses"}

# Extensions of metadata files (sidecars, tables, gradient tables).
METADATA_EXTENSIONS = frozenset({".json", ".tsv", ".bval", ".bvec"})

# Suffixes of `.tsv` files that are data, not metadata: in `rules.files.raw`
# of the official BIDS 1.11.2 schema, the tabular files that are a datatype's
# recording (`beh.noncontinuous`, `motion.motion`, `pet.blood`). Every other
# `.tsv` there (`channels`, `electrodes`, `optodes`, `events`, `aslcontext`,
# `scans`, `sessions`) describes another file's recording. Continuous
# recordings (`physio`, `stim`, ...) are `.tsv.gz`, which is not a metadata
# extension, so they are data already. A `blood` recording is also a
# companion of the PET images it was sampled with (see `COMPANION_SUFFIXES`).
TABULAR_DATA_SUFFIXES = frozenset({"beh", "motion", "blood"})

# Suffixes of the files that apply to data files with another suffix
# (`sub-01_task-x_events.tsv` describes `sub-01_task-x_bold.nii.gz`): the
# suffixes of the `channels`, `events` and `task` groups, `perf.aslcontext`,
# `perf.asllabeling`, `pet.blood`, the `photo` group, `meg.headshape`,
# `meg.markers` and the `scans`/`sessions` tables, in `rules.files` of the
# official BIDS 1.11.2 schema.
COMPANION_SUFFIXES = frozenset({
    "scans", "sessions", "events", "physio", "physioevents", "stim",
    "channels", "electrodes", "coordsystem", "optodes", "aslcontext",
    "asllabeling", "blood", "photo", "headshape", "markers",
})

# Companion suffixes whose files are neither metadata nor recordings: in
# `rules.files.raw` of the official BIDS 1.11.2 schema, the `photo` of a
# recording's set-up (`.jpg`, `.png`, `.tif`; eeg, emg, ieeg, meg, micr,
# nirs), and the `headshape` (`.pos`, or any extension) and `markers`
# (`.sqd`, `.mrk`) of a MEG session. Their extensions are no metadata
# extensions, but they describe recordings and hold none. A `.json` among
# them (the `photo` of a `micr` sample may have one) is metadata already.
COMPANION_FILES = frozenset({"photo", "headshape", "markers"})

# Companions whose `acq` may name what the file itself shows rather than an
# acquisition of the recordings: on a `photo` the landmark (`acq-NAS`), on a
# `headshape` the kind of digitization (`acq-HEAD`), in the text of the
# official BIDS 1.11.2 specification; on `markers`, before or after the
# recording (`acq-pre`, `acq-post`), as MNE-BIDS writes them. Such a file
# applies only to the recordings with its `acq` label when one of the
# recordings it may apply to has it, and its `acq` is not compared
# otherwise (see `acq_required`).
ACQ_TAGGED = frozenset({"photo", "headshape", "markers"})

# MEG files named like a recording that describe every MEG recording of
# their subject or session: in `rules.files.raw.meg` of the official BIDS
# 1.11.2 schema, the fine-calibration file (`calibration`:
# `sub-<label>[_ses-<label>]_acq-calibration_meg.dat`) and the crosstalk
# file (`crosstalk`: `..._acq-crosstalk_meg.fif`), whose `acquisition` is
# fixed by an enum, with this extension each. They have no `task`, which
# every MEG recording has. Each is a companion of those recordings, named
# by its `acq` label.
MEG_SYSTEM_FILES = {"calibration": ".dat", "crosstalk": ".fif"}

# Entities a companion file may have that the data file it describes cannot:
# in `rules.files.raw` of the official BIDS 1.11.2 schema, `space` on
# `electrodes`/`coordsystem`/`markers` (EEG, iEEG, EMG and MEG recordings
# have none) and `recording` on `physio`/`physioevents`/`stim`/`blood` and
# an EMG `photo` (MRI, MEG, motion and PET recordings have none). They name
# the companion's own coordinate space or recording, so a data file that
# lacks one is still described by it. The `acq` of a MEG system file (see
# `MEG_SYSTEM_FILES`) is one too, and is never compared with the
# recording's.
COMPANION_ONLY_ENTITIES = frozenset({"space", "recording"})

# Companion suffixes whose file is the JSON itself (`*_coordsystem.json`).
# Every other companion is a table or a recording, and its `.json` describes
# that file: `*_events.json` documents the columns of `*_events.tsv`.
JSON_COMPANIONS = frozenset({"coordsystem"})

# Images acquired with a data image and paired with it by name: the same
# directory, the same entities, another suffix. In `rules.files.raw` of the
# official BIDS 1.11.2 schema, `sbref` sits with the `func` images (`bold`,
# `cbv`, `phase`) and with `dwi`, `m0scan` with `asl` in `perf`, and the
# reference scan `mrsref` with the `mrs` spectroscopy scans (`svs`, `mrsi`;
# not with the localiser, `unloc`). Each is a data file of its own, so it
# is not one of the image's companions.
PAIRED_IMAGES: dict[str, frozenset[str]] = {
    "sbref": frozenset({"bold", "cbv", "phase", "dwi"}),
    "m0scan": frozenset({"asl"}),
    "mrsref": frozenset({"svs", "mrsi"}),
}

# Extensions of the paired images (`objects.extensions` of the schema).
IMAGE_EXTENSIONS = (".nii.gz", ".nii")

# Data suffixes whose files have a class of their own, with shortcuts to
# their companions (`dwi.bval`, `bold.events`, `asl.m0scan`).
DATA_ROLES = frozenset({"dwi", "bold", "asl"})

# Extensions of data "files" that are directories (`sub-01_meg.ds/`): those
# ending in `/` in `objects.extensions` of the official BIDS 1.11.2 schema.
# The schema's bare `/` (a MEG directory without an extension) is recognised
# by its place instead; see `data_directory`.
DIRECTORY_EXTENSIONS = frozenset({".ds", ".mefd", ".ome.zarr"})

# Top-level folders that are not part of the raw data.
OPTIONAL_FOLDERS = ("derivatives", "sourcedata", "code", "stimuli")

# Dataset-level files.
TOP_LEVEL_FILES = frozenset({
    "dataset_description.json", "participants.tsv", "participants.json",
    "samples.tsv", "samples.json", "genetic_info.json",
    "README", "README.md", "README.txt", "README.rst",
    "CHANGES", "LICENSE", "CITATION.cff", ".bidsignore",
})

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

# Index entities: their value is a non-negative integer, so `run-1` and
# `run-01` are the same run. The entities whose `format` is `index` in
# `objects.entities` of the official BIDS 1.11.2 schema.
INDEX_ENTITIES = frozenset({
    "chunk", "echo", "flip", "inv", "run", "split",
})

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

    @property
    def is_file_name(self) -> bool:
        """Whether the name is shaped like the name of a BIDS file.

        It has a suffix, and entities or an extension (`sub-01_T1w.nii.gz`,
        `T1w.json`). A bare word (`anat`, `README`) and a name with entities
        only (`sub-01`) are not: entities cannot be added to them.
        """
        return self.suffix is not None and bool(self.entities or self.extension)


def index_value(label: str) -> int | str:
    """Return the value of an index label (`"01"` is `1`); others as is."""
    return int(label) if label.isascii() and label.isdigit() else label


def same_label(key: str, a: str, b: str) -> bool:
    """Whether two labels of entity `key` are the same.

    Index entities (`run`, `echo`, ...; see `INDEX_ENTITIES`) compare by
    number, so `run-1` and `run-01` are the same run; others as strings.
    """
    if key in INDEX_ENTITIES:
        return index_value(a) == index_value(b)
    return a == b


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
    if (
        parsed.suffix in DATA_ROLES and parsed.extension
        and not is_metadata(parsed.suffix, ext)
        and ext not in DIRECTORY_EXTENSIONS
    ):
        return parsed.suffix    # a data file: `sub-01_dwi.nii.gz`
    return None


def data_directory(parts: Sequence[str]) -> int | None:
    """Return the index of the part that is a directory-shaped data file.

    Some BIDS data files are directories (a CTF MEG `sub-01_meg.ds/`, an
    OME-Zarr `sub-01_BF.ome.zarr/`): every file inside belongs to that one
    data file. It is the first part above the last whose name is a BIDS
    file name with an extension in `DIRECTORY_EXTENSIONS`, or with no
    extension at all directly in a datatype directory (a MEG directory such
    as `sub-01_task-x_meg/`). `None` when no part is one.
    """
    for i, part in enumerate(parts[:-1]):
        parsed = parse_name(part)
        if not parsed.is_file_name:
            continue
        if parsed.extension in DIRECTORY_EXTENSIONS:
            return i
        if not parsed.extension and i and parts[i - 1] in DATATYPES:
            return i
    return None


def datatype_of(parts: Sequence[str]) -> str | None:
    """Return the datatype directory a path is in, from its parts, or `None`.

    A file inside a directory-shaped data file (see `data_directory`) is in
    the datatype directory of that data file.
    """
    i = data_directory(parts)
    parent = (len(parts) if i is None else i + 1) - 2
    if parent >= 0 and parts[parent] in DATATYPES:
        return parts[parent]
    return None


class ParsedPath(NamedTuple):
    """The BIDS components of a path, relative to its dataset root.

    For a file inside a directory-shaped data file (`sub-01_meg.ds/x`, see
    `data_directory`), every component but `path` is that data file's.
    """

    path: str
    """The path, `/`-separated."""
    directory: PurePosixPath
    """The directory the data item is in (`.` at the dataset root)."""
    entities: dict
    """The entities of the name; empty for a non-BIDS name."""
    suffix: str | None
    """The BIDS suffix of the name, or `None`."""
    extension: str
    """Everything from the first dot of the name, or `""`."""
    datatype: str | None
    """The datatype directory the path is in (`anat`), or `None`."""
    item: str
    """The data item the path belongs to: `path`, or the data directory."""

    @property
    def is_metadata(self) -> bool:
        """Whether the name is a metadata file (`.json`, `.tsv`, ...).

        A `.tsv` file whose suffix is a data suffix (`beh`, `motion`,
        `blood`; see `TABULAR_DATA_SUFFIXES`) is data, not metadata, and so
        is every file inside a directory-shaped data file.
        """
        return is_metadata(self.suffix, self.extension)

    @property
    def is_companion_file(self) -> bool:
        """Whether the name is a companion file (`photo.jpg`, ...).

        A file that is not metadata but describes recordings without being
        one; see `is_companion_file`. Never a file inside a directory-shaped
        data file.
        """
        if self.item != self.path:
            return False
        return is_companion_file(self.suffix, self.extension, self.entities)

    @property
    def is_companion(self) -> bool:
        """Whether the data item is a companion (`events.tsv`, `photo.jpg`).

        See `is_companion`. Never a file inside a directory-shaped data
        file.
        """
        if self.item != self.path:
            return False
        return is_companion(self.suffix, self.extension, self.entities)

    @property
    def has_companions(self) -> bool:
        """Whether the data item is a recording, which has companions.

        See `has_companions`; a directory-shaped data file is one.
        """
        return has_companions(self.suffix, self.extension, self.entities)


def is_metadata(suffix: str | None, extension: str) -> bool:
    """Whether a name with this suffix and extension is a metadata file."""
    if extension == ".tsv" and suffix in TABULAR_DATA_SUFFIXES:
        return False
    return extension in METADATA_EXTENSIONS


def is_companion_recording(suffix: str | None, extension: str) -> bool:
    """Whether a file with this suffix and extension is a companion recording.

    A file that is not metadata, whose suffix is a companion suffix
    (`*_physio.tsv.gz`, `*_stim.tsv.gz`, `*_blood.tsv`, `*_asllabeling.jpg`;
    see `COMPANION_SUFFIXES`) but not that of a companion file (see
    `is_companion_file`): a recording of its own, which has companions
    too, and a companion of the recordings it applies to.
    """
    return (
        suffix in COMPANION_SUFFIXES and suffix not in COMPANION_FILES
        and not is_metadata(suffix, extension)
    )


def meg_system_file(
    entities: dict, suffix: str | None, extension: str
) -> str | None:
    """Return `"calibration"` or `"crosstalk"` for a MEG system file, else `None`.

    A name with the `meg` suffix, an `acq` label of `MEG_SYSTEM_FILES`
    with the extension the schema gives it, and no `task`:
    `sub-01_acq-crosstalk_meg.fif`, not `sub-01_task-x_acq-crosstalk_meg.fif`.
    """
    if suffix != "meg" or "task" in entities:
        return None
    acq = entities.get("acq")
    if acq in MEG_SYSTEM_FILES and MEG_SYSTEM_FILES[acq] == extension:
        return acq
    return None


def is_companion_file(
    suffix: str | None, extension: str, entities: dict
) -> bool:
    """Whether a file that is not metadata describes recordings without being one.

    A `photo`, `headshape` or `markers` file that is not metadata (see
    `COMPANION_FILES`), or a MEG system file (see `meg_system_file`). It
    comes along with the recordings it applies to, and has no companions
    of its own.
    """
    if is_metadata(suffix, extension):
        return False
    return suffix in COMPANION_FILES or (
        meg_system_file(entities, suffix, extension) is not None
    )


def is_companion(suffix: str | None, extension: str, entities: dict) -> bool:
    """Whether a file is a companion: a file of its own that describes others.

    A file whose suffix is a companion suffix (see `COMPANION_SUFFIXES`),
    but not the JSON sidecar of one (`events.json`, `photo.json`) nor a
    gradient table, or a MEG system file (see `meg_system_file`). A
    `coordsystem` is the JSON itself (see `JSON_COMPANIONS`). The
    selection treats every companion as a data file, which a filter can
    select; it also comes along with the recordings it applies to.
    """
    if meg_system_file(entities, suffix, extension) is not None:
        return True
    if suffix not in COMPANION_SUFFIXES:
        return False
    if extension == ".json":
        return suffix in JSON_COMPANIONS
    return extension not in (".bval", ".bvec")


def has_companions(suffix: str | None, extension: str, entities: dict) -> bool:
    """Whether a data file of this name has companions: it is a recording.

    A BIDS file name (a suffix, and entities or an extension) that is
    neither metadata (`events.tsv`, `coordsystem.json`) nor a companion
    file (`photo.jpg`, a MEG crosstalk file; see `is_companion_file`). A
    companion recording (`physio.tsv.gz`) has companions too. Every other
    data file has its JSON sidecars alone.
    """
    if suffix is None or not (entities or extension):
        return False
    if is_metadata(suffix, extension):
        return False
    return not is_companion_file(suffix, extension, entities)


def parse_path(path: object) -> ParsedPath:
    """Parse a path's name and its datatype directory, lexically.

    `path` is a `/`-separated string or a path object; a `ParsedPath` is
    returned unchanged. Parsing never raises.
    """
    if isinstance(path, ParsedPath):
        return path
    if isinstance(path, PurePath):
        path = path.as_posix()
    p = PurePosixPath(str(path))
    parts = p.parts
    i = data_directory(parts)
    item = p if i is None else PurePosixPath(*parts[:i + 1])
    parsed = parse_name(item.name)
    return ParsedPath(
        p.as_posix(), item.parent, parsed.entities, parsed.suffix,
        parsed.extension, datatype_of(parts), item.as_posix(),
    )


def applies_to(
    meta: object, data: object, *, companions: bool = True, acq: bool = True
) -> bool:
    """Whether a metadata file applies to a data file (BIDS inheritance).

    It does when all of these hold:

    - its directory is the data file's directory or one of its ancestors;
    - every entity of its name is in the data file's name, with the same
      label (index entities, such as `run`, compare by number: `run-1` is
      `run-01`);
    - its suffix is the data file's suffix, or (when `companions` is true)
      a companion suffix (`events`, `scans`, `sessions`, `physio`, ...; see
      `COMPANION_SUFFIXES`);
    - if it is in a datatype directory, the data file is in one of the
      same datatype.

    A companion may also have an entity that the data file lacks, when that
    entity names the companion's own space or recording (`space`,
    `recording`; see `COMPANION_ONLY_ENTITIES`): `sub-01_space-CapTrak_
    electrodes.tsv` describes `sub-01_task-x_eeg.edf`.

    A MEG system file (`sub-01_acq-crosstalk_meg.fif`; see
    `meg_system_file`) is a companion of the MEG recordings (suffix `meg`,
    none a system file itself), and its `acq` is not compared with theirs.
    With `acq` false, a companion's `acq` is not compared either (for a
    `photo`, `headshape` or `markers` file; see `acq_required`).

    Pass `companions=False` for a JSON sidecar's metadata: a companion's
    sidecar (`events.json`) describes the companion file, not the data.

    Both paths are `/`-separated strings, path objects or `ParsedPath`,
    relative to the same root. Whether `meta` is a metadata file at all is
    not checked.
    """
    meta, data = parse_path(meta), parse_path(data)
    if meta.directory != data.directory and (
        meta.directory not in data.directory.parents
    ):
        return False
    system = meg_system_file(meta.entities, meta.suffix, meta.extension)
    if system is not None:
        if not companions or data.suffix != meta.suffix or meg_system_file(
            data.entities, data.suffix, data.extension
        ) is not None:
            return False
        companion = True
    else:
        companion = meta.suffix != data.suffix
        if companion and (
            not companions or meta.suffix not in COMPANION_SUFFIXES
        ):
            return False
    if meta.datatype and meta.datatype != data.datatype:
        return False
    skip_acq = system is not None or (companion and not acq)
    for key, label in meta.entities.items():
        if skip_acq and key == "acq":
            continue
        other = data.entities.get(key)
        if other is None:
            if not (companion and key in COMPANION_ONLY_ENTITIES):
                return False
        elif not same_label(key, label, other):
            return False
    return True


def is_acq_tagged(meta: object) -> bool:
    """Whether a file is a `photo`, `headshape` or `markers` with an `acq`.

    See `ACQ_TAGGED`; its JSON sidecar is one too.
    """
    meta = parse_path(meta)
    return meta.suffix in ACQ_TAGGED and "acq" in meta.entities


def acq_required(
    meta: object,
    recordings: Iterable[object],
    applies: Callable[..., bool] = applies_to,
) -> bool:
    """Whether a `photo`, `headshape` or `markers` file needs its `acq` matched.

    The `acq` of such a file may name what it shows (`acq-NAS`, the
    nasion) instead of the acquisition of a recording. So it applies only
    to the recordings with its `acq` label (index-aware) when one of the
    recordings it would apply to without comparing `acq` has that label,
    and to all of those recordings otherwise. This says which: `recordings`
    are the recordings (see `has_companions`) it may apply to, and
    `applies(meta, data, acq=False)` tells whether it applies to one. A
    file that is not `acq`-tagged (see `is_acq_tagged`) needs it.
    """
    meta = parse_path(meta)
    label = meta.entities.get("acq")
    if label is None or meta.suffix not in ACQ_TAGGED:
        return True
    for data in recordings:
        data = parse_path(data)
        other = data.entities.get("acq")
        if (
            other is not None and same_label("acq", label, other)
            and data.has_companions and applies(meta, data, acq=False)
        ):
            return True
    return False
