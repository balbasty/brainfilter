import json
import re
import warnings
from fnmatch import fnmatch
from typing import Union
from io import IOBase

from brainfilter.fancypath import (
    FancyDirectory, FancyFile, FancyJSONFile, FancyPath,
    StrOrBytesOrPath, TextFileLike
)
from brainfilter.hdict import HDict, TrackedHDict
from brainfilter.tracking import TrackedDict, tracks


REGISTERED_PATH_TYPES = {}


class BidsEntities(dict):
    """Container for BIDS entities."""

    SORTED_ENTITIES = [
        "sub",                  # ()            Subject
        "ses",                  # ()            Session
        "sample",               # (MICR)        Sample
        "task",                 # ()            Task
        "tracksys",             # (MOTION)      Tracking system
        "acq",                  # ()            Acquisition
        "ce",                   # (MRI)         Contrast enhancement
        "trc",                  # (PET)         Tracer
        "stain",                # (MICR)        Stain
        "nuc",                  # (RMS)         Nucleus
        "voi",                  # (RMS)         Volume of Interest
        "rec",                  # (MRI/PET)     Reconstruction
        "dir",                  # (MRI-EPI)     PE-Direction
        "run",                  # ()            Run
        "proc",                 # (EEG/MEG)     Processing
        "mod",                  # ()            Modality (derives from suffix)
        "echo",                 # (MRI)         Echo
        "flip",                 # (MRI)         Flip angle
        "inv",                  # (MRI)         Inversion time
        "mt",                   # (MRI)         Magnetization transfer
        "part",                 # ()            Part Magnitude/Phase/Real/Imag
        "chunk",                # (MRI/MICR)    Chunk index
        "split",                # (MEG)         Split file index
        "hemi",                 # (DRV/SURF)    Hemisphere
        "space",                # ()            Coordinates space
        "seg",                  # (DRV)         Segmentation
        "res",                  # (DRV/IMG)     Resolution
        "den",                  # (DRV/SURF)    Density
        "label",                # (DRV/MSK)     Segmentation label
        "desc",                 # (DRV)         Description
        "recording",            # (Phys)        Recording
    ]

    def __lt__(self, other: dict) -> bool:
        """Check whether this file inherits (strictly) from the other file."""
        if not isinstance(other, dict):
            return NotImplemented

        # If exactly the same, return False
        if set(self.keys()) == set(other.keys()):
            return False

        # Subset of self that are also in other
        common = {k: v for k, v in self.items() if k in other}

        # Check if the subset matches the inherited dict
        return common == other

    def __le__(self, other: dict) -> bool:
        """Check whether this file inherits from the other file."""
        return self < other or self == other

    def __gt__(self, other: dict) -> bool:
        """Check whether the other file inherits (stricly) from this file."""
        if not isinstance(other, dict):
            return NotImplemented

        # If exactly the same, return False
        if set(self.keys()) == set(other.keys()):
            return False

        # Subset of self that are also in other
        common = {k: v for k, v in other.items() if k in self}

        # Check if the subset matches the inherited dict
        return common == self

    def __ge__(self, other: dict) -> bool:
        """Check whether the other file inherits from this file."""
        return self > other or self == other


class JSONContent(dict):
    """Container for JSON file content."""

    def write_to(self, file: TextFileLike) -> None:
        """Write content to a JSON file."""
        if not isinstance(file, IOBase):
            file = FancyPath(file)
            with file.open("w", encoding="utf-8") as f:
                return self.write_to(f)
        json.dump(self, file, indent=4)

    @classmethod
    def load_from(cls, file: TextFileLike) -> "JSONContent":
        """Load content from a JSON file."""
        if not isinstance(file, IOBase):
            file = FancyPath(file)
            with file.open("r", encoding="utf-8") as f:
                return cls.load_from(f)
        return cls(json.load(file))


class BidsSidecarContent(HDict):
    """Container for BIDS sidecar file content."""

    @classmethod
    def load_from(cls, file: StrOrBytesOrPath) -> "BidsSidecarContent":
        """Load content from a JSON file."""
        path = BidsPath(file)

        # Load content that exactly matches the file
        if path.exists():
            leaf = JSONContent.load_from(file)
        else:
            leaf = JSONContent()
        leaf._parent = path

        # Load inherited content from sibling files
        dir = path.parent
        inherited = []
        while True:
            for sibling in dir.iterdir():
                if (
                    path.extension == sibling.extension
                    and path.suffix == sibling.suffix
                    and path.entities < sibling.entities
                ):
                    inherited.append(JSONContent.load_from(sibling))

            if (dir / "dataset_description.json").exists():
                break
            if dir.resolve() == FancyPath("/"):
                break
            dir = dir.parent

        return cls(leaf, *inherited)

    def write_to(self, file: StrOrBytesOrPath) -> None:
        """Write content to a JSON file."""
        if self._leaf or FancyPath(file).exists():
            self._leaf.write_to(file)


class BidsDatasetDescriptionContent(dict):
    """Container for BIDS dataset_description.json content."""
    ...


@tracks(JSONContent)
class TrackedJSONContent(TrackedDict, JSONContent):
    """A tracked JSON content dictionary."""
    ...


@tracks(BidsSidecarContent)
class TrackedBidsSidecarContent(TrackedHDict, BidsSidecarContent):
    """A tracked BIDS sidecar content dictionary."""
    ...


@tracks(BidsDatasetDescriptionContent)
class TrackedBidsDatasetDescriptionContent(
    TrackedDict, BidsDatasetDescriptionContent
):
    """A tracked BIDS dataset_description.json content dictionary."""
    ...


class BidsPath(FancyPath):
    """Base class for BIDS paths (files or directories)."""

    def __new__(cls, *args, **kwargs):
        cls0 = cls
        path = FancyPath._make_pure(*args, **kwargs)
        for pattern, path_type in REGISTERED_PATH_TYPES.items():
            if (
                (isinstance(pattern, re.Pattern) and pattern.match(path.name))
                or
                (isinstance(pattern, str) and fnmatch(path.name, pattern))
                or
                (callable(pattern) and pattern(path))
            ):
                cls = path_type
                break
        obj = super().__new__(cls, *args, **kwargs)
        if not issubclass(cls, cls0):
            obj.__init__(*args, **kwargs)
        return obj

    @property
    def extension(self) -> str:
        """Return the file extension, including .nii.gz for NIfTI files."""
        if "." in self.name:
            return ".".join(self.name.split(".")[1:])
        else:
            return ""

    def with_extension(self, extension: str) -> "BidsPath":
        """Return a new BidsPath with the given file extension."""
        return type(self)(self.parent / (self.basename + extension))

    @property
    def basename(self) -> str:
        """Return the file name without extensions."""
        return self.name.split(".")[0]

    def with_basename(self, basename: str) -> "BidsPath":
        """Return a new BidsPath with the given file extension."""
        return type(self)(self.parent / (basename + self.extension))

    @property
    def entities(self) -> BidsEntities:
        """Return BIDS entities as a dictionary."""
        parts = self.basename.split("_")
        entities = BidsEntities()
        for part in parts:
            if "-" in part:
                key, *value = part.split("-")
                entities[key] = "-".join(value)
        return entities

    def with_entities(
        self,
        entities: dict | None = None,
        keep_existing: bool = False,
        sort: bool | None = None,
        **extra_entities,
    ) -> "BidsPath":
        """Return a new BidsPath with the given file extension."""
        if sort is None:
            sort = keep_existing

        new_entities = self.entities if keep_existing else BidsEntities()
        new_entities.update(entities or {})
        new_entities.update(extra_entities)

        if sort:
            new_entities = {
                key: new_entities[key]
                for key in BidsEntities.SORTED_ENTITIES
                if key in new_entities
            } | {
                key: value
                for key, value in new_entities.items()
                if key not in BidsEntities.SORTED_ENTITIES
            }

        basename = "_".join(
            f"{key}-{value}" for key, value in new_entities.items()
        )
        if self.suffix:
            basename += f"_{self.suffix}"

        return type(self)(self.parent / (basename + self.extension))

    @property
    def subject(self) -> str | None:
        """Return the subject ID."""
        return self.entities.get("sub", None)

    def with_subject(self, subject: str) -> "BidsPath":
        """Return a new BidsPath with the given subject ID."""
        prev_name = f"sub-{self.subject}"
        new_name = f"sub-{subject}"
        parts = list(self.parts)
        if prev_name in parts:
            parts[parts.index(prev_name)] = new_name
            return type(self)(FancyPath(*parts)).with_subject(subject)

        return self.with_entities(keep_existing=True, sub=subject)

    @property
    def session(self) -> str | None:
        """Return the session ID."""
        return self.entities.get("ses", None)

    def with_session(self, session: str) -> "BidsPath":
        """Return a new BidsPath with the given session ID."""
        prev_name = f"ses-{self.session}"
        new_name = f"ses-{session}"
        parts = list(self.parts)
        if prev_name in parts:
            parts[parts.index(prev_name)] = new_name
            return type(self)(FancyPath(*parts)).with_session(session)

        return self.with_entities(keep_existing=True, ses=session)

    @property
    def suffix(self) -> str | None:
        """
        Return the BIDS suffix.

        !!! warning "This is different from the file extension"
        """
        if "_" in self.name:
            return self.basename.split("_")[-1]
        return None

    def with_suffix(self, suffix: str) -> "BidsPath":
        """Return a new BidsPath with the given BIDS suffix."""
        basename = self.basename.split("_")
        if "-" not in basename[-1]:
            basename = basename[:-1]
        basename.append(suffix)
        basename = "_".join(basename)
        return type(self)(self.parent / (basename + self.extension))

    @property
    def dataset(self) -> Union["BidsPath", None]:
        """Return the root dataset directory."""
        path = self
        while not (path / "dataset_description.json").exists():
            if path.resolve() == FancyPath("/"):
                return None
            path = path.parent
        return BidsPath(path)


class BidsDirectory(BidsPath, FancyDirectory):
    """Class for BIDS directories."""
    ...


class BidsDataset(BidsDirectory):
    """Class for BIDS datasets."""

    def __init__(self, *args, **kwargs):
        if_missing: str = kwargs.get("if_missing", "ignore")
        super().__init__(*args, **kwargs)
        self._post_init(if_missing=if_missing)

    def _post_init(self, if_missing: str = "ignore") -> None:
        if not (self / "dataset_description.json").exists():
            msg = (
                f"{self} is not a BIDS dataset: "
                f"missing dataset_description.json"
            )
            if if_missing == "raise":
                raise FileNotFoundError(msg)
            elif if_missing == "warn":
                warnings.warn(msg, UserWarning)
            elif if_missing == "create":
                (self / "dataset_description.json").touch()


class BidsFile(BidsPath, FancyFile):
    """Class for BIDS files."""
    ...


class BidsJSONFile(BidsFile, FancyJSONFile):
    """
    A BIDS JSON file.

    Examples
    --------
    >>> sidecar = BidsJSONFile("sub-01_task-rest_bold.json")
    ...
    ... # Read into a variable then write back
    >>> content = sidecar.read()             # read content into var
    >>> content["RepetitionTime"] = 2.0      # modify content in var
    >>> content["EchoTime"] = 0.1            # ...
    >>> sidecar.write(content)               # write content back to file
    ...
    ... # Load into the object then dump back
    >>> sidecar.load()                       # load content into object
    >>> sidecar["RepetitionTime"] = 2.0      # modify content in memory
    >>> sidecar["EchoTime"] = 0.1            # ...
    >>> sidecar.dump()                       # write changes back to file
    ...
    ... # Use as a context manager
    >>> with sidecar as content:             # enter: load content into obj
    ...     content["RepetitionTime"] = 2.0  # modify content in memory
    ...     content["EchoTime"] = 0.1        # ...
    ...                                      # exit: write changes back to file
    ...
    ... # Implicit read-modify-write
    >>> TR = sidecar["RepetitionTime"]       # read content from disk
    >>> sidecar["RepetitionTime"] = 2.0      # modify content on disk
    """

    def _read_json(self) -> JSONContent:
        return JSONContent.load_from(self)


class BidsTSVFile(BidsFile):
    """A BIDS TSV file.

    Examples
    --------
    >>> tsv = BidsTSVFile("participants.tsv")
    >>>
    >>> print(tsv.content)                   # load content
    >>> tsv.content['sub-0001', 'age'] = 70  # modify content in memory
    >>> tsv.write_content()                  # write changes back to file
    >>>
    >>> # Or use as a context manager (changes are saved on exit)
    >>> with BidsTSVFile("participants.tsv") as content:
    ...     content['sub-0001', 'age'] = 70
    """
    ...


class BidsDatasetDescriptionFile(BidsJSONFile):
    """A BIDS dataset_description.json file."""

    def _read_json(self) -> BidsDatasetDescriptionContent:
        return BidsDatasetDescriptionContent.load_from(self)


class BidsSidecarFile(BidsJSONFile):
    """A BIDS sidecar JSON file."""

    def _read_json(self) -> BidsSidecarContent:
        return BidsSidecarContent.load_from(self)


class BidsTableSidecarFile(BidsSidecarFile):
    """A BIDS sidecar JSON file for a TSV file."""
    ...


class BidsParticipantsFile(BidsTSVFile):
    """A BIDS participants.tsv file."""
    ...


class BidsParticipantsSidecarFile(BidsTableSidecarFile):
    """A BIDS participants.json file."""
    ...


class BidsSessionsFile(BidsTSVFile):
    """A BIDS sessions.tsv file."""
    ...


class BidsSessionsSidecarFile(BidsTableSidecarFile):
    """A BIDS sessions.json file."""
    ...


class BidsSamplesFile(BidsTSVFile):
    """A BIDS samples.tsv file."""
    ...


class BidsSamplesSidecarFile(BidsTableSidecarFile):
    """A BIDS samples.json file."""
    ...


class BidsScansFile(BidsTSVFile):
    """A BIDS scans.tsv file."""
    ...


class BidsScansSidecarFile(BidsTableSidecarFile):
    """A BIDS scans.json file."""
    ...


class BidsPhenotypeFile(BidsTSVFile):
    """A BIDS <phenotype>.tsv file."""
    ...


class BidsPhenotypeSidecarFile(BidsTableSidecarFile):
    """A BIDS <phenotype>.json file."""
    ...


class BidsCodeDirectory(BidsDirectory):
    """A BIDS code/ directory."""
    ...


REGISTERED_PATH_TYPES.update({
    "dataset_description.json":
        BidsDatasetDescriptionFile,
    "participants.json":
        BidsParticipantsSidecarFile,
    "participants.tsv":
        BidsParticipantsFile,
    "sessions.json":
        BidsSessionsSidecarFile,
    "sessions.tsv":
        BidsSessionsFile,
    "*_sessions.tsv":
        BidsSessionsFile,
    "samples.json":
        BidsSamplesSidecarFile,
    "samples.tsv":
        BidsSamplesFile,
    "scans.json":
        BidsScansSidecarFile,
    "*_scans.json":
        BidsScansSidecarFile,
    "scans.tsv":
        BidsScansFile,
    "*_scans.tsv":
        BidsScansFile,
    (lambda x: x.parent.name == "phenotype" and x.suffix == ".json"):
        BidsPhenotypeSidecarFile,
    (lambda x: x.parent.name == "phenotype" and x.suffix == ".tsv"):
        BidsPhenotypeFile,
    (lambda x: x.name == "code"):
        BidsCodeDirectory,
    "*.json":
        BidsSidecarFile,
    "*.tsv":
        BidsTSVFile,
    (lambda x: x.is_dir()):
        BidsDirectory,
    (lambda x: x.is_file()):
        BidsFile,
})
