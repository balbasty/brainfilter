# stdlib
import re
from typing import Annotated

# internals
from brainfilter.re import bids_label
from brainfilter.schemas.utils import Directory, JSONFile, TSVFile
from brainfilter.validation import DirectorySchema

prefix = f"sub-{bids_label}_ses-{bids_label}"

SessionDirSchema = DirectorySchema({
})

SessionDir = Annotated[Directory, SessionDirSchema]
SessionFile = TSVFile
SessionsJSONFile = JSONFile
