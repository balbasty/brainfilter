"""BIDS paths: name parsing, entity editing and file-type dispatch.

A [`BidsPath`][brainfilter.bidspath.BidsPath] is a `bagof.paths.Path` that
also reads its name as a BIDS name::

    >>> p = BidsPath("ds/sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz")
    >>> p.entities, p.suffix, p.extension, p.datatype
    ({'sub': '01', 'ses': '1'}, 'T1w', '.nii.gz', 'anat')
    >>> p.with_subject("02")
    BidsPath('ds/sub-02/ses-1/anat/sub-02_ses-1_T1w.nii.gz')

A [`PureBidsPath`][brainfilter.bidspath.PureBidsPath] has the same BIDS
surface over a `bagof.paths.PurePath`, with no I/O at all, and an
[`AsyncBidsPath`][brainfilter.bidspath.AsyncBidsPath] over a
`bagof.paths.AsyncPath`, whose I/O members are coroutines (on a remote store
with a natively async fsspec backend, bagof-paths' native async driver).

Every BIDS component is computed from the name when asked for, never
stored, so a derived path (`/`, `parent`, `with_name`, ...) re-parses its
own name. The class of a path is picked from its name and its parent's name
as well (`participants.tsv` is a `BidsParticipantsFile`, a `.json` file a
`BidsSidecarFile`, ...), without touching the filesystem, so a remote path
or one that does not exist yet gets the same class as a local one.

!!! warning "`suffix` is the BIDS suffix"
    On these paths `suffix` is the BIDS suffix (`T1w`) and `with_suffix`
    replaces it. The file extension is `extension` (`.nii.gz`) and is
    replaced with `with_extension`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from bagof.paths import AsyncPath, Path, PurePath

from brainfilter._names import (
    DATATYPES,
    METADATA_EXTENSIONS,
    SORTED_ENTITIES,
    ParsedName,
    check_entity,
    check_extension,
    check_suffix,
    data_directory,
    datatype_of,
    format_name,
    is_metadata,
    parse_name,
    role_of,
    sort_entities,
)
from brainfilter._tree import (
    AsyncJSONContentMixin,
    AsyncTreeMixin,
    AsyncTSVContentMixin,
    JSONContentMixin,
    Table,
    TreeMixin,
    TSVContentMixin,
)

if TYPE_CHECKING:
    from typing_extensions import Self

__all__ = [
    "DATATYPES",
    "METADATA_EXTENSIONS",
    "AsyncBidsCodeDirectory",
    "AsyncBidsDatasetDescriptionFile",
    "AsyncBidsDirectory",
    "AsyncBidsFile",
    "AsyncBidsJSONFile",
    "AsyncBidsParticipantsFile",
    "AsyncBidsParticipantsSidecarFile",
    "AsyncBidsPath",
    "AsyncBidsPhenotypeFile",
    "AsyncBidsPhenotypeSidecarFile",
    "AsyncBidsSamplesFile",
    "AsyncBidsSamplesSidecarFile",
    "AsyncBidsScansFile",
    "AsyncBidsScansSidecarFile",
    "AsyncBidsSessionsFile",
    "AsyncBidsSessionsSidecarFile",
    "AsyncBidsSidecarFile",
    "AsyncBidsTSVFile",
    "AsyncBidsTableSidecarFile",
    "BidsCodeDirectory",
    "BidsDatasetDescriptionFile",
    "BidsDirectory",
    "BidsEntities",
    "BidsFile",
    "BidsJSONFile",
    "BidsNameError",
    "BidsParticipantsFile",
    "BidsParticipantsSidecarFile",
    "BidsPath",
    "BidsPathMixin",
    "BidsPhenotypeFile",
    "BidsPhenotypeSidecarFile",
    "BidsSamplesFile",
    "BidsSamplesSidecarFile",
    "BidsScansFile",
    "BidsScansSidecarFile",
    "BidsSessionsFile",
    "BidsSessionsSidecarFile",
    "BidsSidecarFile",
    "BidsTSVFile",
    "BidsTableSidecarFile",
    "PureBidsCodeDirectory",
    "PureBidsDatasetDescriptionFile",
    "PureBidsDirectory",
    "PureBidsFile",
    "PureBidsJSONFile",
    "PureBidsParticipantsFile",
    "PureBidsParticipantsSidecarFile",
    "PureBidsPath",
    "PureBidsPhenotypeFile",
    "PureBidsPhenotypeSidecarFile",
    "PureBidsSamplesFile",
    "PureBidsSamplesSidecarFile",
    "PureBidsScansFile",
    "PureBidsScansSidecarFile",
    "PureBidsSessionsFile",
    "PureBidsSessionsSidecarFile",
    "PureBidsSidecarFile",
    "PureBidsTSVFile",
    "PureBidsTableSidecarFile",
    "Table",
]


class BidsNameError(ValueError):
    """An edit that needs a BIDS name was asked of a name that is not one."""


class BidsEntities(dict):
    """BIDS entities of a name, `key -> label`, in file-name order.

    The comparisons follow the BIDS inheritance principle: `a < b` when a
    file with entities `a` inherits (strictly) from a file with entities
    `b`, i.e. every entity of `b` is in `a` with the same label and `a` has
    more.
    """

    SORTED_ENTITIES: ClassVar[tuple[str, ...]] = SORTED_ENTITIES
    """Entity keys in canonical file-name order."""

    def sorted(self) -> BidsEntities:
        """Return these entities in canonical order (unknown keys last)."""
        return BidsEntities(sort_entities(self))

    def __lt__(self, other: object) -> bool:
        """Whether this file inherits (strictly) from the other file."""
        if not isinstance(other, dict):
            return NotImplemented
        if set(self) == set(other):
            return False
        return {k: v for k, v in self.items() if k in other} == other

    def __le__(self, other: object) -> bool:
        """Whether this file inherits from the other file."""
        if not isinstance(other, dict):
            return NotImplemented
        return self < other or self == other

    def __gt__(self, other: object) -> bool:
        """Whether the other file inherits (strictly) from this file."""
        if not isinstance(other, dict):
            return NotImplemented
        if set(self) == set(other):
            return False
        return {k: v for k, v in other.items() if k in self} == self

    def __ge__(self, other: object) -> bool:
        """Whether the other file inherits from this file."""
        if not isinstance(other, dict):
            return NotImplemented
        return self > other or self == other


def _view(path: object) -> PurePath | None:
    """Return a plain `PurePath` view of a path, or `None`.

    A plain view is used so that no BIDS class (and so no dispatch) is
    involved, and nothing is read from a filesystem. An async driver has no
    such view, so its spelling is read instead.
    """
    try:
        try:
            return PurePath(path)
        except TypeError:
            return PurePath(str(path))
    except (TypeError, ValueError):
        return None


def _names(path: object) -> tuple[str, str] | None:
    """Read the name of a path and of its parent lexically, or `None`."""
    view = _view(path)
    return None if view is None else (view.name, view.parent.name)


class BidsPathMixin:
    """The lexical BIDS surface shared by every BIDS path family.

    `BidsPath`, `PureBidsPath` and `AsyncBidsPath` all use it.
    """

    __slots__ = ()

    # Set on each family root by `_seal`: the root, the classes defined in
    # this module (which dispatch on their name), and the class of each role.
    _root: ClassVar[type]
    _builtin: ClassVar[frozenset[type]] = frozenset()
    _by_role: ClassVar[dict[str, type]]
    # The role a class is dispatched for (see `_names.role_of`).
    _role: ClassVar[str | None] = None

    # These are defined by bagof's wrappers, which this mixin is used with.
    if TYPE_CHECKING:
        name: str
        parent: Self
        parents: tuple[Self, ...]
        wrapped: Any

        def with_name(self, name: str) -> Self: ...  # noqa: D102
        def __truediv__(self, other: object) -> Self: ...  # noqa: D105

    # -- dispatch ------------------------------------------------------------
    def __new__(cls, *args: object, **kwargs: object) -> Self:
        """Pick the class a path's name calls for.

        Constructing a family root (`BidsPath("x/participants.tsv")`) gives
        the specialised class; constructing a specialised class gives it, or
        a subclass of it that the name calls for. A subclass defined outside
        this module is never swapped for another class.
        """
        if args and cls in cls._builtin:
            names = _names(args[0])
            if names is not None:
                chosen = cls._class_for(*names)
                if issubclass(chosen, cls):
                    cls = chosen
        return object.__new__(cls)

    @classmethod
    def _class_for(cls, name: str, parent_name: str) -> type:
        """Pick the class, in this family, for a name in a parent directory."""
        return cls._by_role.get(role_of(name, parent_name), cls._root)

    def with_wrapped(self, wrapped: object) -> Self:
        """Return a path around `wrapped`, of the class its name calls for.

        Every derived path (`/`, `parent`, `with_name`, ...) is built here,
        so it is re-dispatched on its own name. A subclass defined outside
        this module keeps its own type.
        """
        new = super().with_wrapped(wrapped)  # type: ignore[misc]
        if type(self) in self._builtin:
            names = _names(wrapped)
            if names is not None:
                cls = self._class_for(*names)
                if type(new) is not cls:
                    new.__class__ = cls
        return new

    # -- parsed components ---------------------------------------------------
    @property
    def basename(self) -> str:
        """The name without its extension (`sub-01_T1w`)."""
        return parse_name(self.name).basename

    @property
    def extension(self) -> str:
        """Everything from the first dot of the name (`.nii.gz`), or `""`."""
        return parse_name(self.name).extension

    @property
    def entities(self) -> BidsEntities:
        """The BIDS entities of the name; empty for a non-BIDS name."""
        return BidsEntities(parse_name(self.name).entities)

    @property
    def suffix(self) -> str | None:  # type: ignore[override]
        """The BIDS suffix (`T1w`, `bold`), or `None`.

        !!! warning "This is not the file extension"
            See `extension` for `.nii.gz`.
        """
        return parse_name(self.name).suffix

    @property
    def datatype(self) -> str | None:
        """The datatype directory the path is in (`anat`, `func`), or `None`.

        A file inside a data file that is a directory (a CTF MEG
        `sub-01_meg.ds/`, an OME-Zarr `sub-01_BF.ome.zarr/`) is in the
        datatype directory of that data file.
        """
        view = _view(self.wrapped)
        return None if view is None else datatype_of(view.parts)

    @property
    def is_metadata(self) -> bool:
        """Whether the name is a metadata file (`.json`, `.tsv`, `.bval`, ...).

        A `.tsv` file whose BIDS suffix is a data suffix (`beh`, `motion`,
        `blood`) holds data, not metadata, and so does every file inside a
        data file that is a directory (`sub-01_meg.ds/`).
        """
        view = _view(self.wrapped)
        if view is not None and data_directory(view.parts) is not None:
            return False
        parsed = parse_name(self.name)
        return is_metadata(parsed.suffix, parsed.extension)

    @property
    def subject(self) -> str | None:
        """The subject label.

        It is read from the name's `sub` entity, else from the nearest
        `sub-<label>` directory above the path.
        """
        return self._label("sub")

    @property
    def session(self) -> str | None:
        """The session label.

        It is read from the name's `ses` entity, else from the nearest
        `ses-<label>` directory above the path.
        """
        return self._label("ses")

    def _label(self, key: str) -> str | None:
        label = parse_name(self.name).entities.get(key)
        if label is not None:
            return label
        for parent in self.parents:
            parsed = parse_name(parent.name)
            if parsed.suffix is None and list(parsed.entities) == [key]:
                return parsed.entities[key]
        return None

    # -- editors -------------------------------------------------------------
    def _parsed_bids(self, edit: str) -> ParsedName:
        parsed = parse_name(self.name)
        if not parsed.is_bids:
            raise BidsNameError(
                f"cannot {edit} of {self.name!r}: it is not a BIDS name "
                "(<key>-<label>_..._<suffix><extension>)"
            )
        return parsed

    def with_entities(
        self,
        entities: dict | None = None,
        *,
        keep_existing: bool = False,
        sort: bool | None = None,
        **extra_entities: object,
    ) -> Self:
        """Return a path whose name has the given entities.

        Parameters
        ----------
        entities
            Entities to set, `key -> label`. A label of `None` removes the
            entity.
        keep_existing
            Keep the name's other entities. By default they are replaced.
        sort
            Put the entities in canonical BIDS order. By default, they are
            sorted when `keep_existing` is true; otherwise they keep the
            order they are given in.
        **extra_entities
            More entities to set, as keywords.

        Raises
        ------
        BidsNameError
            If the name is not a BIDS name, or an entity it does not have is
            added to a name that is not a BIDS file name: one with a suffix,
            and entities or an extension (`sub-01_T1w.nii.gz`, `T1w.json`).
            A directory (`anat`, `sub-01`) or a bare word (`README`) gets no
            new entity.
        ValueError
            If an entity would not parse back, or the name would be empty.
        """
        parsed = self._parsed_bids("set the entities")
        if sort is None:
            sort = keep_existing
        new = dict(parsed.entities) if keep_existing else {}
        for key, label in {**(entities or {}), **extra_entities}.items():
            if label is None:
                new.pop(str(key), None)
                continue
            key, label = check_entity(key, label)
            if key not in parsed.entities and not parsed.is_file_name:
                raise BidsNameError(
                    f"cannot add the entity {key}-{label} to {self.name!r}: "
                    "it is not a BIDS name of a file, which has a suffix and "
                    "entities or an extension (<key>-<label>_..._<suffix>"
                    "<extension>)"
                )
            new[key] = label
        if sort:
            new = sort_entities(new)
        name = format_name(new, parsed.suffix, parsed.extension)
        if not parse_name(name).is_bids:
            raise ValueError(
                f"removing every entity of {self.name!r} would leave no name"
            )
        return self.with_name(name)

    def with_subject(self, subject: object) -> Self:
        """Return the path of another subject.

        Every `sub-<label>` directory above the path that names the current
        subject is renamed, and so is the name's `sub` entity. A name that
        has no `sub` entity gets one only if no directory names a subject.

        Raises
        ------
        BidsNameError
            If there is no subject to replace and the name is not a BIDS
            file name (a directory such as `anat`, or `README`).
        """
        return self._with_label("sub", subject)

    def with_session(self, session: object) -> Self:
        """Return the path of another session.

        Every `ses-<label>` directory above the path that names the current
        session is renamed, and so is the name's `ses` entity. A name that
        has no `ses` entity gets one only if no directory names a session.

        Raises
        ------
        BidsNameError
            If there is no session to replace and the name is not a BIDS
            file name (a directory such as `anat` or `sub-01`, or `README`).
        """
        return self._with_label("ses", session)

    def _with_label(self, key: str, label: object) -> Self:
        key, label = check_entity(key, label)
        old = self._label(key)
        path = self if old is None else self._rename_dirs(key, old, label)
        if old is None or key in parse_name(path.name).entities:
            return path.with_entities(keep_existing=True, **{key: label})
        return path

    def _rename_dirs(self, key: str, old: str, new: str) -> Self:
        """Rename every `key-old` directory above this path to `key-new`."""
        chain = [self, *self.parents]
        target = f"{key}-{old}"
        hits = [i for i in range(1, len(chain)) if chain[i].name == target]
        if not hits:
            return self
        top = hits[-1]
        path = chain[top].with_name(f"{key}-{new}")
        for ancestor in reversed(chain[1:top]):
            name = ancestor.name
            path = path / (f"{key}-{new}" if name == target else name)
        return path / self.name

    def with_suffix(self, suffix: str) -> Self:  # type: ignore[override]
        """Return a path whose name has another BIDS suffix.

        !!! warning "This is not the file extension"
            See `with_extension` to replace `.nii.gz`.

        Raises
        ------
        BidsNameError
            If the name is not a BIDS name.
        ValueError
            If `suffix` is empty, starts with a dot, or contains `_`, `-`,
            `.` or `/`.
        """
        parsed = self._parsed_bids("set the suffix")
        name = format_name(parsed.entities, check_suffix(suffix), parsed.extension)
        return self.with_name(name)

    def with_extension(self, extension: str) -> Self:
        """Return a path whose name has another extension (`.nii.gz`).

        Any name has an extension, so this works on non-BIDS names too.
        """
        return self.with_name(self.basename + check_extension(extension))

    def with_basename(self, basename: str) -> Self:
        """Return a path whose name has another basename, same extension."""
        if not basename or "." in basename or "/" in basename:
            raise ValueError(
                f"invalid basename {basename!r}: it must be non-empty and "
                "contain no '.' or '/'"
            )
        return self.with_name(basename + self.extension)


def _seal(root: type) -> None:
    """Record a family's classes and the class of each role on its root."""
    classes = {root}
    stack = [root]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in classes:
                classes.add(sub)
                stack.append(sub)
    root._root = root
    root._builtin = frozenset(classes)
    root._by_role = {
        c.__dict__["_role"]: c for c in classes if c.__dict__.get("_role")
    }


# -- concrete paths ------------------------------------------------------------
class BidsPath(TreeMixin, BidsPathMixin, Path):
    """A BIDS file or directory, on any storage `bagof.paths.Path` supports.

    The class is picked from the name; see the module documentation.

    A directory is also a mapping of its children
    (`dataset["sub-01"]["anat"]`, `keys()`, iteration), a JSON file a
    mapping of its content (`sidecar["RepetitionTime"]`, `read()`), and a
    TSV file a `Table` of rows (`read()`, `read_dataframe()`). A file's
    `metadata` is the `ChainMap` of the JSON sidecars that apply to it.

    The tree is read-only, except inside `with dataset.transaction():` or
    `with sidecar.edit() as content:`; see `brainfilter.transaction`.
    """

    __slots__ = ()


class BidsFile(BidsPath):
    """A BIDS file."""

    __slots__ = ()


class BidsDirectory(BidsPath):
    """A BIDS directory."""

    __slots__ = ()


class BidsCodeDirectory(BidsDirectory):
    """A BIDS `code/` directory."""

    __slots__ = ()
    _role = "code"


class BidsJSONFile(JSONContentMixin, BidsFile):
    """A BIDS JSON file."""

    __slots__ = ()


class BidsDatasetDescriptionFile(BidsJSONFile):
    """A BIDS `dataset_description.json` file."""

    __slots__ = ()
    _role = "dataset_description"


class BidsSidecarFile(BidsJSONFile):
    """A BIDS JSON sidecar."""

    __slots__ = ()
    _role = "sidecar"


class BidsTableSidecarFile(BidsSidecarFile):
    """A BIDS JSON sidecar describing a TSV table's columns."""

    __slots__ = ()


class BidsTSVFile(TSVContentMixin, BidsFile):
    """A BIDS TSV table."""

    __slots__ = ()
    _role = "table"


class BidsParticipantsFile(BidsTSVFile):
    """A BIDS `participants.tsv` file."""

    __slots__ = ()
    _role = "participants"


class BidsParticipantsSidecarFile(BidsTableSidecarFile):
    """A BIDS `participants.json` file."""

    __slots__ = ()
    _role = "participants_sidecar"


class BidsSessionsFile(BidsTSVFile):
    """A BIDS `[sub-<label>_]sessions.tsv` file."""

    __slots__ = ()
    _role = "sessions"


class BidsSessionsSidecarFile(BidsTableSidecarFile):
    """A BIDS `[sub-<label>_]sessions.json` file."""

    __slots__ = ()
    _role = "sessions_sidecar"


class BidsSamplesFile(BidsTSVFile):
    """A BIDS `samples.tsv` file."""

    __slots__ = ()
    _role = "samples"


class BidsSamplesSidecarFile(BidsTableSidecarFile):
    """A BIDS `samples.json` file."""

    __slots__ = ()
    _role = "samples_sidecar"


class BidsScansFile(BidsTSVFile):
    """A BIDS `[sub-<label>[_ses-<label>]_]scans.tsv` file."""

    __slots__ = ()
    _role = "scans"


class BidsScansSidecarFile(BidsTableSidecarFile):
    """A BIDS `[sub-<label>[_ses-<label>]_]scans.json` file."""

    __slots__ = ()
    _role = "scans_sidecar"


class BidsPhenotypeFile(BidsTSVFile):
    """A BIDS `phenotype/<measurement>.tsv` file."""

    __slots__ = ()
    _role = "phenotype"


class BidsPhenotypeSidecarFile(BidsTableSidecarFile):
    """A BIDS `phenotype/<measurement>.json` file."""

    __slots__ = ()
    _role = "phenotype_sidecar"


_seal(BidsPath)


# -- pure paths ----------------------------------------------------------------
class PureBidsPath(BidsPathMixin, PurePath):
    """A BIDS file or directory name, for lexical operations only.

    The same BIDS surface as `BidsPath`, over a `bagof.paths.PurePath`: a
    local path or a remote URL is parsed with no backend and no I/O.
    """

    __slots__ = ()


class PureBidsFile(PureBidsPath):
    """A BIDS file name."""

    __slots__ = ()


class PureBidsDirectory(PureBidsPath):
    """A BIDS directory name."""

    __slots__ = ()


class PureBidsCodeDirectory(PureBidsDirectory):
    """A BIDS `code/` directory name."""

    __slots__ = ()
    _role = "code"


class PureBidsJSONFile(PureBidsFile):
    """A BIDS JSON file name."""

    __slots__ = ()


class PureBidsDatasetDescriptionFile(PureBidsJSONFile):
    """A BIDS `dataset_description.json` name."""

    __slots__ = ()
    _role = "dataset_description"


class PureBidsSidecarFile(PureBidsJSONFile):
    """A BIDS JSON sidecar name."""

    __slots__ = ()
    _role = "sidecar"


class PureBidsTableSidecarFile(PureBidsSidecarFile):
    """A BIDS JSON sidecar name for a TSV table."""

    __slots__ = ()


class PureBidsTSVFile(PureBidsFile):
    """A BIDS TSV table name."""

    __slots__ = ()
    _role = "table"


class PureBidsParticipantsFile(PureBidsTSVFile):
    """A BIDS `participants.tsv` name."""

    __slots__ = ()
    _role = "participants"


class PureBidsParticipantsSidecarFile(PureBidsTableSidecarFile):
    """A BIDS `participants.json` name."""

    __slots__ = ()
    _role = "participants_sidecar"


class PureBidsSessionsFile(PureBidsTSVFile):
    """A BIDS `[sub-<label>_]sessions.tsv` name."""

    __slots__ = ()
    _role = "sessions"


class PureBidsSessionsSidecarFile(PureBidsTableSidecarFile):
    """A BIDS `[sub-<label>_]sessions.json` name."""

    __slots__ = ()
    _role = "sessions_sidecar"


class PureBidsSamplesFile(PureBidsTSVFile):
    """A BIDS `samples.tsv` name."""

    __slots__ = ()
    _role = "samples"


class PureBidsSamplesSidecarFile(PureBidsTableSidecarFile):
    """A BIDS `samples.json` name."""

    __slots__ = ()
    _role = "samples_sidecar"


class PureBidsScansFile(PureBidsTSVFile):
    """A BIDS `[sub-<label>[_ses-<label>]_]scans.tsv` name."""

    __slots__ = ()
    _role = "scans"


class PureBidsScansSidecarFile(PureBidsTableSidecarFile):
    """A BIDS `[sub-<label>[_ses-<label>]_]scans.json` name."""

    __slots__ = ()
    _role = "scans_sidecar"


class PureBidsPhenotypeFile(PureBidsTSVFile):
    """A BIDS `phenotype/<measurement>.tsv` name."""

    __slots__ = ()
    _role = "phenotype"


class PureBidsPhenotypeSidecarFile(PureBidsTableSidecarFile):
    """A BIDS `phenotype/<measurement>.json` name."""

    __slots__ = ()
    _role = "phenotype_sidecar"


_seal(PureBidsPath)


# -- async paths ---------------------------------------------------------------
class AsyncBidsPath(AsyncTreeMixin, BidsPathMixin, AsyncPath):
    """A BIDS file or directory whose I/O members are coroutines.

    The same BIDS surface and class dispatch as `BidsPath`, over a
    `bagof.paths.AsyncPath`. The tree, contents and metadata are coroutines
    too: `await dataset.child("sub-01")`, `await dataset.keys()`,
    `async for name in dataset`, `await sidecar.read()`,
    `await sidecar.get("RepetitionTime")`, `await table.read()`,
    `await data.read_metadata()` and `await data.sidecars()`. Edits go in
    `async with dataset.transaction():` or
    `async with sidecar.edit() as content:`, with `await sidecar.set()`,
    `delete()`, `update()` and `write()`.
    """

    __slots__ = ()


class AsyncBidsFile(AsyncBidsPath):
    """A BIDS file, with coroutine I/O."""

    __slots__ = ()


class AsyncBidsDirectory(AsyncBidsPath):
    """A BIDS directory, with coroutine I/O."""

    __slots__ = ()


class AsyncBidsCodeDirectory(AsyncBidsDirectory):
    """A BIDS `code/` directory, with coroutine I/O."""

    __slots__ = ()
    _role = "code"


class AsyncBidsJSONFile(AsyncJSONContentMixin, AsyncBidsFile):
    """A BIDS JSON file, with coroutine I/O."""

    __slots__ = ()


class AsyncBidsDatasetDescriptionFile(AsyncBidsJSONFile):
    """A BIDS `dataset_description.json` file, with coroutine I/O."""

    __slots__ = ()
    _role = "dataset_description"


class AsyncBidsSidecarFile(AsyncBidsJSONFile):
    """A BIDS JSON sidecar, with coroutine I/O."""

    __slots__ = ()
    _role = "sidecar"


class AsyncBidsTableSidecarFile(AsyncBidsSidecarFile):
    """A BIDS JSON sidecar describing a TSV table, with coroutine I/O."""

    __slots__ = ()


class AsyncBidsTSVFile(AsyncTSVContentMixin, AsyncBidsFile):
    """A BIDS TSV table, with coroutine I/O."""

    __slots__ = ()
    _role = "table"


class AsyncBidsParticipantsFile(AsyncBidsTSVFile):
    """A BIDS `participants.tsv` file, with coroutine I/O."""

    __slots__ = ()
    _role = "participants"


class AsyncBidsParticipantsSidecarFile(AsyncBidsTableSidecarFile):
    """A BIDS `participants.json` file, with coroutine I/O."""

    __slots__ = ()
    _role = "participants_sidecar"


class AsyncBidsSessionsFile(AsyncBidsTSVFile):
    """A BIDS `[sub-<label>_]sessions.tsv` file, with coroutine I/O."""

    __slots__ = ()
    _role = "sessions"


class AsyncBidsSessionsSidecarFile(AsyncBidsTableSidecarFile):
    """A BIDS `[sub-<label>_]sessions.json` file, with coroutine I/O."""

    __slots__ = ()
    _role = "sessions_sidecar"


class AsyncBidsSamplesFile(AsyncBidsTSVFile):
    """A BIDS `samples.tsv` file, with coroutine I/O."""

    __slots__ = ()
    _role = "samples"


class AsyncBidsSamplesSidecarFile(AsyncBidsTableSidecarFile):
    """A BIDS `samples.json` file, with coroutine I/O."""

    __slots__ = ()
    _role = "samples_sidecar"


class AsyncBidsScansFile(AsyncBidsTSVFile):
    """A BIDS `[sub-<label>[_ses-<label>]_]scans.tsv` file, with coroutine I/O."""

    __slots__ = ()
    _role = "scans"


class AsyncBidsScansSidecarFile(AsyncBidsTableSidecarFile):
    """A BIDS `[sub-<label>[_ses-<label>]_]scans.json` file, with coroutine I/O."""

    __slots__ = ()
    _role = "scans_sidecar"


class AsyncBidsPhenotypeFile(AsyncBidsTSVFile):
    """A BIDS `phenotype/<measurement>.tsv` file, with coroutine I/O."""

    __slots__ = ()
    _role = "phenotype"


class AsyncBidsPhenotypeSidecarFile(AsyncBidsTableSidecarFile):
    """A BIDS `phenotype/<measurement>.json` file, with coroutine I/O."""

    __slots__ = ()
    _role = "phenotype_sidecar"


_seal(AsyncBidsPath)
