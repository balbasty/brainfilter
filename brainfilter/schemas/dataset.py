# stdlib
import re
from typing import Annotated

# internals
from brainfilter.re import bids_label
from brainfilter.validation import (
    DirectorySchema, JSONFileValidator, TSVFileValidator,
    Required, Recommended, Optional,
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
        Required,
    ],
    VersionSwitch[
        VersionSpecifier[">=1.9.0"],
        re.compile(r"README(\.md|\.rst|\.txt)?"),
        "README"
    ]: Annotated[
        File,
        VersionSwitch[
            VersionSpecifier[">=1.8.0"],
            Required,
            Recommended,
        ],
    ],
    "CITATION.cff": Annotated[
        CitationFile,
        Optional,
        VersionSpecifier[">=1.9.0"]
    ],
    "CHANGES": Annotated[
        ChangeFile,
        Optional,
    ],
    "LICENSE": Annotated[
        File,
        Optional,
        VersionSpecifier[">=1.4.0"]
    ],
    "sourcedata": Annotated[
        Directory,
        Optional,
    ],
    "code": Annotated[
        Directory,
        Optional,
    ],
    "phenotype": Annotated[
        Directory,
        Optional,
        VersionSpecifier[">=1.0.1"]
    ],
    "participants.tsv": Annotated[
        ParticipantsFile,
        Recommended,
    ],
    "participants.json": Annotated[
        ParticipantsJSONFile,
        Recommended,
    ],
    "sessions.json": Annotated[
        SessionsJSONFile,
        Optional,
    ],
    "samples.tsv": Annotated[
        TSVFileValidator,
        Optional,
    ],
    "samples.json": Annotated[
        JSONFileValidator,
        Optional,
    ],
    re.compile(f"sub-{bids_label}"): Annotated[
        SubjectDir,
        Optional,
    ],
})

BIDSDataset = Annotated[Directory, BIDSDatasetSchema]
