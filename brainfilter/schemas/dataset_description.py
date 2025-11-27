# stdlib
from typing import Annotated, Literal, T

# internals
from brainfilter.validation import (
    JSONSchema,
    Required,
    Recommended,
    Optional,
    # RecommendedIf,
    # NotRecommendedIf,
    # ProscribedIf,
)
from brainfilter.schemas.utils import URI, File
from brainfilter.validation import JSONFileValidator
from brainfilter.versioning import VersionSpecifier, VersionSwitch


SourceDatasetKey = Annotated[
    str,
    Literal["URL", "DOI", "Version"]
]

Container = Annotated[
    dict[str, T],
    JSONSchema({
        "Type": Annotated[str, Required],
        "Tag": Annotated[str, Required],
        "URI": Annotated[URI, Recommended],
    })
]

GeneratedBy = Annotated[
    dict[str, T],
    JSONSchema({
        "Name": Annotated[str, Required],
        "Version": Annotated[str, Recommended],
        "Description": Annotated[str, Optional],
        "CodeURL": Annotated[URI, Optional],
        "Container": Annotated[Container, Optional],
    })
]

DatasetDescription = Annotated[
    dict[str, T],
    JSONSchema({
        "Name": Annotated[
            str,
            Required
        ],
        "BIDSVersion": Annotated[
            str,
            Required
        ],
        "HEDVersion": Annotated[
            str | list[str],
            Recommended,
            VersionSpecifier[">=1.4.1"]
        ],
        "DatasetLinks": Annotated[
            dict[str, str],
            Optional,
            VersionSpecifier[">=1.8.0"]
        ],
        "DatasetType": Annotated[
            str,
            VersionSwitch[
                VersionSpecifier[">=1.10.1"],
                Literal["raw", "derivative", "study"],
                Literal["raw", "derivative"]
            ],
            Recommended,
            VersionSpecifier[">=1.4.0"]
        ],
        "License": Annotated[
            str,
            Recommended,
            # RecommendedIf[
            #     (lambda schema: not (schema["CITATION.cff"]).exists())
            # ],
            # NotRecommendedIf[
            #     (lambda schema: (schema["CITATION.cff"]).exists())
            # ],
        ],
        "Authors": Annotated[
            list[str],
            Optional,
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
            Optional,
            VersionSpecifier[">=1.10.1"],
        ],
        "Acknowledgements": Annotated[
            str,
            Optional,
        ],
        "HowToAcknowledge": Annotated[
            str,
            Optional,
            # NotRecommendedIf[
            #     (lambda schema: (schema["CITATION.cff"]).exists())
            # ],
        ],
        "Funding": Annotated[
            list[str],
            Optional,
        ],
        "EthicsApprovals": Annotated[
            list[str],
            Optional,
            VersionSpecifier[">=1.3.0"],
        ],
        "ReferencesAndLinks": Annotated[
            list[str],
            Optional,
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
            Optional,
        ],
        "GeneratedBy": Annotated[
            list[GeneratedBy],
            Optional,
            VersionSpecifier[">=1.7.0"],
        ],
        "SourceDatasets": Annotated[
            list[dict[SourceDatasetKey, T]],
            Optional,
            VersionSpecifier[">=1.7.0"],
        ],
    })
]

DatasetDescriptionFile = Annotated[
    File,
    JSONFileValidator(DatasetDescription),
]
