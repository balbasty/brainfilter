# stdlib
from os import PathLike
from typing import Annotated, T

# internal
from brainfilter.validators import (
    FileValidator, DirectoryValidator, JSONFileValidator, TSVFileValidator,
)
from brainfilter.adaptors import Minimum, Maximum

# optionals
try:
    from upath import UPath
except ImportError:
    UPath = None

# optional
try:
    import uritools
except ImportError:
    uritools = None


# ----------------------------------------------------------------------
# URI types
# ----------------------------------------------------------------------


class URI(str):

    def __new__(cls, value: str) -> "URI":
        value = value0 = str(value)
        if uritools:
            if not uritools.isuri(value):
                value = uritools.urijoin("file:///", value)
            if not uritools.isuri(value):
                raise TypeError(f"Not a valid URI: {value0!r}")
        return str.__new__(cls, value)


class DOI(URI):

    def __new__(cls, value: str) -> "DOI":
        value = value0 = str(value)
        if uritools:
            if not uritools.isuri(value):
                value = uritools.urijoin("https://doi.org/", value)
            if not uritools.isuri(value):
                raise TypeError(f"Not a valid DOI: {value0!r}")
            if uritools.urisplit(value).scheme == "doi":
                value = uritools.urijoin(
                    "https://doi.org/",
                    uritools.urisplit(value).path
                )
        return URI.__new__(cls, value)


PathType = UPath | PathLike if UPath else PathLike
File = Annotated[PathType, FileValidator()]
Directory = Annotated[PathType, DirectoryValidator()]
JSONFile = Annotated[PathType, JSONFileValidator()]
TSVFile = Annotated[PathType, TSVFileValidator()]
TSVGZFile = Annotated[PathType, TSVFileValidator()]
BvalFile = Annotated[PathType, FileValidator()]  # TODO: BVAL validator
BvecFile = Annotated[PathType, FileValidator()]  # TODO: BVEC validator
NiftiFile = Annotated[PathType, FileValidator()]  # TODO: NIfTI validator
CitationFile = Annotated[PathType, FileValidator()]  # TODO: CFF validator
ChangeFile = Annotated[PathType, FileValidator()]  # TODO: CHANGELOG validator
Positive = Annotated[T, Minimum(0)]
StrictlyPositive = Annotated[T, Minimum(0, inclusive=False)]
Negative = Annotated[T, Maximum(0)]
StrictlyNegative = Annotated[T, Maximum(0, inclusive=False)]
