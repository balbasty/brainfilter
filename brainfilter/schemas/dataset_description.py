# stdlib
from typing import Annotated, Literal, T

# internals
from brainfilter.validators import (
    JSONSchema,
    required,
    recommended,
    optional,
    # RecommendedIf,
    # NotRecommendedIf,
    # ProscribedIf,
)
from brainfilter.schemas.utils import URI, File
from brainfilter.validators import JSONFileValidator
from brainfilter.versioning import VersionSpecifier, VersionSwitch


SourceDatasetKey = Annotated[
    str,
    Literal["URL", "DOI", "Version"]
]

Container = Annotated[
    dict[str, T],
    JSONSchema({
        "Type": Annotated[str, required],
        "Tag": Annotated[str, required],
        "URI": Annotated[URI, recommended],
    })
]

GeneratedBy = Annotated[
    dict[str, T],
    JSONSchema({
        "Name": Annotated[str, required],
        "Version": Annotated[str, recommended],
        "Description": Annotated[str, optional],
        "CodeURL": Annotated[URI, optional],
        "Container": Annotated[Container, optional],
    })
]

DatasetDescription = Annotated[
    dict[str, T],
    JSONSchema({
        "Name": Annotated[
            str,
            required
        ],
        "BIDSVersion": Annotated[
            str,
            required
        ],
        "HEDVersion": Annotated[
            str | list[str],
            recommended,
            VersionSpecifier[">=1.4.1"]
        ],
        "DatasetLinks": Annotated[
            dict[str, str],
            optional,
            VersionSpecifier[">=1.8.0"]
        ],
        "DatasetType": Annotated[
            str,
            VersionSwitch[
                VersionSpecifier[">=1.10.1"],
                Literal["raw", "derivative", "study"],
                Literal["raw", "derivative"]
            ],
            recommended,
            VersionSpecifier[">=1.4.0"]
        ],
        "License": Annotated[
            str,
            recommended,
            # RecommendedIf[
            #     (lambda schema: not (schema["CITATION.cff"]).exists())
            # ],
            # NotRecommendedIf[
            #     (lambda schema: (schema["CITATION.cff"]).exists())
            # ],
        ],
        "Authors": Annotated[
            list[str],
            optional,
            # VersionSwitch[
            #     VersionSpecifier[">=1.10.1"],
            #     RecommendedIf[
            #         (lambda schema: not (schema["CITATION.cff"]).exists())
            #     ],
            #     ProscribedIf[
            #         (lambda schema: (schema["CITATION.cff"]).exists())
            #     ],
            # ],
        ],
        "Keywords": Annotated[
            list[str],
            optional,
            VersionSpecifier[">=1.10.1"],
        ],
        "Acknowledgements": Annotated[
            str,
            optional,
        ],
        "HowToAcknowledge": Annotated[
            str,
            optional,
            # NotRecommendedIf[
            #     (lambda schema: (schema["CITATION.cff"]).exists())
            # ],
        ],
        "Funding": Annotated[
            list[str],
            optional,
        ],
        "EthicsApprovals": Annotated[
            list[str],
            optional,
            VersionSpecifier[">=1.3.0"],
        ],
        "ReferencesAndLinks": Annotated[
            list[str],
            optional,
            # NotRecommendedIf[
            #     (lambda schema: (schema["CITATION.cff"]).exists())
            # ],
        ],
        "DatasetDOI": Annotated[
            VersionSwitch[
                VersionSpecifier[">=1.4.1"],
                URI,
                str
            ],
            optional,
        ],
        "GeneratedBy": Annotated[
            list[GeneratedBy],
            optional,
            VersionSpecifier[">=1.7.0"],
        ],
        "SourceDatasets": Annotated[
            list[dict[SourceDatasetKey, T]],
            optional,
            VersionSpecifier[">=1.7.0"],
        ],
    })
]

DatasetDescriptionFile = Annotated[
    File,
    JSONFileValidator(DatasetDescription),
]
