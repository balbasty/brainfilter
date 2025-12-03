# stdlib
from typing import Annotated

# internals
from brainfilter.re import bids_label
from brainfilter.schemas.utils import Directory, JSONFile, TSVFile
from brainfilter.schemas.mri import (
    AnatDirectory, FuncDirectory, FmapDirectory,
    DwiDirectory, PerfDirectory,
)
from brainfilter.validation import DirectorySchema, Optional

prefix = f"sub-{bids_label}_ses-{bids_label}"

SessionDirSchema = DirectorySchema({
    "anat": Annotated[AnatDirectory, Optional],
    "func": Annotated[FuncDirectory, Optional],
    "dwi": Annotated[DwiDirectory, Optional],
    "perf": Annotated[PerfDirectory, Optional],
    "fmap": Annotated[FmapDirectory, Optional],
})

SessionDir = Annotated[Directory, SessionDirSchema]
SessionFile = TSVFile
SessionsJSONFile = JSONFile
