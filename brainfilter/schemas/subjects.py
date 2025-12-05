# stdlib
import re
from typing import Annotated

# internals
from brainfilter.re import bids_label
from brainfilter.validators import DirectorySchema, optional, required
from brainfilter.schemas.sessions import (
    SessionDir, SessionFile, SessionDirSchema
)
from brainfilter.schemas.utils import Directory, TSVFile, JSONFile


SubjectDirSchemaWithSessions = DirectorySchema({
    re.compile(f"ses-{bids_label}"): Annotated[
        SessionDir,
        required,
    ],
    re.compile(f"sub-{bids_label}_sessions.tsv"): Annotated[
        SessionFile,
        optional,
    ],
})
SubjectDirSchema = SubjectDirSchemaWithSessions | SessionDirSchema

SubjectDir = Annotated[Directory, SubjectDirSchema]
ParticipantsFile = TSVFile
ParticipantsJSONFile = JSONFile
