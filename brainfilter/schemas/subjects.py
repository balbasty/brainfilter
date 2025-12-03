# stdlib
import re
from typing import Annotated

# internals
from brainfilter.re import bids_label
from brainfilter.validation import DirectorySchema, Optional, Required
from brainfilter.schemas.sessions import (
    SessionDir, SessionFile, SessionDirSchema
)
from brainfilter.schemas.utils import Directory, TSVFile, JSONFile


SubjectDirSchemaWithSessions = DirectorySchema({
    re.compile(f"ses-{bids_label}"): Annotated[
        SessionDir,
        Required,
    ],
    re.compile(f"sub-{bids_label}_sessions.tsv"): Annotated[
        SessionFile,
        Optional,
    ],
})
SubjectDirSchema = SubjectDirSchemaWithSessions | SessionDirSchema

SubjectDir = Annotated[Directory, SubjectDirSchema]
ParticipantsFile = TSVFile
ParticipantsJSONFile = JSONFile
