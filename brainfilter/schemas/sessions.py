# stdlib
from typing import Annotated

# internals
from brainfilter.re import bids_label
from brainfilter.schemas.utils import Directory, JSONFile, TSVFile
from brainfilter.schemas.mri import (
    AnatDirectory, FuncDirectory, FmapDirectory,
    DwiDirectory, PerfDirectory,
)
from brainfilter.validators import DirectorySchema, optional

prefix = f"sub-{bids_label}_ses-{bids_label}"

SessionDirSchema = DirectorySchema({
    "anat": Annotated[AnatDirectory, optional],
    "func": Annotated[FuncDirectory, optional],
    "dwi": Annotated[DwiDirectory, optional],
    "perf": Annotated[PerfDirectory, optional],
    "fmap": Annotated[FmapDirectory, optional],
})

SessionDir = Annotated[Directory, SessionDirSchema]
SessionFile = TSVFile
SessionsJSONFile = JSONFile
