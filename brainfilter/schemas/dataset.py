# stdlib
import re
from typing import Annotated

# internals
from brainfilter.re import bids_label
from brainfilter.validators import (
    DirectorySchema, JSONFileValidator, TSVFileValidator,
    required, recommended, optional,
)
from brainfilter.schemas.utils import File, Directory
from brainfilter.versioning import VersionSpecifier, VersionSwitch
from brainfilter.schemas.dataset_description import DatasetDescriptionFile
from brainfilter.schemas.utils import CitationFile, ChangeFile
from brainfilter.schemas.subjects import (
    SubjectDir, ParticipantsFile, ParticipantsJSONFile
)
from brainfilter.schemas.sessions import SessionsJSONFile


BIDSDatasetSchema = DirectorySchema({
    "dataset_description.json": Annotated[
        DatasetDescriptionFile,
        required,
    ],
    VersionSwitch[
        VersionSpecifier[">=1.9.0"],
        re.compile(r"README(\.md|\.rst|\.txt)?"),
        "README"
    ]: Annotated[
        File,
        VersionSwitch[
            VersionSpecifier[">=1.8.0"],
            required,
            recommended,
        ],
    ],
    "CITATION.cff": Annotated[
        CitationFile,
        optional,
        VersionSpecifier[">=1.9.0"]
    ],
    "CHANGES": Annotated[
        ChangeFile,
        optional,
    ],
    "LICENSE": Annotated[
        File,
        optional,
        VersionSpecifier[">=1.4.0"]
    ],
    "sourcedata": Annotated[
        Directory,
        optional,
    ],
    "code": Annotated[
        Directory,
        optional,
    ],
    "phenotype": Annotated[
        Directory,
        optional,
        VersionSpecifier[">=1.0.1"]
    ],
    "participants.tsv": Annotated[
        ParticipantsFile,
        recommended,
    ],
    "participants.json": Annotated[
        ParticipantsJSONFile,
        recommended,
    ],
    "sessions.json": Annotated[
        SessionsJSONFile,
        optional,
    ],
    "samples.tsv": Annotated[
        TSVFileValidator,
        optional,
    ],
    "samples.json": Annotated[
        JSONFileValidator,
        optional,
    ],
    re.compile(f"sub-{bids_label}"): Annotated[
        SubjectDir,
        optional,
    ],
})

BIDSDataset = Annotated[Directory, BIDSDatasetSchema]
