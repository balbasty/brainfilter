# stdlib
from os import PathLike
from typing import Annotated, T

# internal
from brainfilter.validation import (
    FileValidator, DirectoryValidator, JSONFileValidator, TSVFileValidator
)
from brainfilter.validator_zoo import URIValidator, Minimum, Maximum

# optionals
try:
    from upath import UPath
except ImportError:
    UPath = None


PathType = UPath | PathLike if UPath else PathLike


URI = Annotated[str, URIValidator]
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
