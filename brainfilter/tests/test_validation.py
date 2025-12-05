from typing import Annotated

from brainfilter import validators as V
from brainfilter import validator_zoo as Z
from brainfilter import schemas as S


def test_json_schema_validator():
    schema = V.JSONSchema({
        "name": Annotated[str, V.required],
        "age": Annotated[int, Z.Minimum(0), V.required],
    })

    # Valid data
    valid_data = {"name": "Alice", "age": 30}
    assert schema(valid_data)

    # Invalid data: missing required field
    invalid_data_1 = {"name": "Bob"}
    assert not schema(invalid_data_1)

    # Invalid data: wrong type
    invalid_data_2 = {"name": "Charlie", "age": -5}
    assert not schema(invalid_data_2)


def test_directory_validator(tmp_path):

    from fsspec.implementations.memory import MemoryFileSystem
    from upath import UPath
    import json
    import re

    fs = MemoryFileSystem()
    fs.makedirs("/dataset/sub-01/anat/", exist_ok=True)
    fs.touch("/dataset/sub-01/anat/sub-01_T1w.nii.gz")
    with fs.open("dataset/dataset_description.json", "w") as f:
        json.dump({
            "Name": "Test Dataset",
            "BIDSVersion": "1.6.0",
        }, f)

    schema = V.DirectorySchema({
        "dataset_description.json": Annotated[
            S.dataset_description.DatasetDescriptionFile,
            V.required,
        ],
        re.compile(r"sub-\d+"): Annotated[
            S.utils.Directory,
            V.required,
            V.DirectorySchema({
                "anat": Annotated[
                    S.utils.Directory,
                    V.optional,
                    V.DirectorySchema({
                        re.compile(r"sub-\d+_T1w\.nii\.gz"):
                        Annotated[
                            S.utils.File,
                            V.required,
                        ],
                        re.compile(r"sub-\d+_T1w\.json"):
                        Annotated[
                            S.utils.File,
                            V.optional,
                        ],
                    }),
                ],
                "func": Annotated[
                    S.utils.Directory,
                    V.optional,
                    V.DirectorySchema({
                        re.compile(r"sub-\d+_task-\w+_bold\.nii\.gz"):
                        Annotated[
                            S.utils.File,
                            V.required,
                        ],
                        re.compile(r"sub-\d+_task-\w+_bold\.json"):
                        Annotated[
                            S.utils.File,
                            V.optional,
                        ],
                    }),
                ]
            })
        ],
    })

    # Valid directory
    assert schema(UPath("memory://dataset", fs=fs))

    # Invalid directory
    fs.touch("/dataset/WRONG_FILE")
    assert not schema(UPath("memory://dataset", fs=fs))
