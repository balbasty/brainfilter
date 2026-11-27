"""Filters on sidecar values, on participants.tsv and on entity presence."""
import json
import re
import typing

import pytest
import typing_extensions

import brainfilter.filter as filter_module
from brainfilter.bidspath import AsyncBidsPath, BidsPath, PureBidsPath
from brainfilter.conditions import Glob
from brainfilter.filter import Filter

Any = typing.Any
Never = typing_extensions.Never
Required = typing_extensions.Required

DATASET = {
    "dataset_description.json": {"Name": "values", "BIDSVersion": "1.10.0"},
    "participants.tsv": (
        "participant_id\tage\tgroup\n"
        "sub-01\t30\tcontrol\n"
        "sub-02\tn/a\tpatient\n"
        "sub-03\t17\tsham\n"
    ),
    "participants.json": {"age": {"Units": "year"}},
    "task-rest_bold.json": {
        "RepetitionTime": 2, "TaskName": "rest", "SliceTiming": [0.0, 0.5],
    },
    "sub-01/func/sub-01_task-rest_bold.nii.gz": b"",
    "sub-01/func/sub-01_task-rest_bold.json": {
        "EchoTime": 0.03, "PhaseEncodingDirection": "j", "IntendedFor": None,
        "Flag": True,
    },
    "sub-01/func/sub-01_task-rest_events.tsv": "onset\tduration\n0\t1\n",
    "sub-01/anat/sub-01_acq-mprage_T1w.nii.gz": b"",
    "sub-01/anat/sub-01_T1w.nii.gz": b"",
    "sub-02/func/sub-02_task-rest_bold.nii.gz": b"",
    "sub-02/func/sub-02_task-rest_bold.json": {
        "RepetitionTime": 1.5, "EchoTime": 0.025,
        "PhaseEncodingDirection": "j-", "B0FieldIdentifier": "fm", "Flag": 1,
    },
    "sub-03/func/sub-03_task-rest_bold.nii.gz": b"",
    "sub-04/anat/sub-04_T1w.nii.gz": b"",
}

BOLD = {s: f"sub-{s}/func/sub-{s}_task-rest_bold.nii.gz" for s in ("01", "02", "03")}
T1W = {
    "01": "sub-01/anat/sub-01_T1w.nii.gz",
    "01mp": "sub-01/anat/sub-01_acq-mprage_T1w.nii.gz",
    "04": "sub-04/anat/sub-04_T1w.nii.gz",
}


def _write(root, files):
    root = root.with_mode("w")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, str):
            path.write_text(content)
        else:
            path.write_text(json.dumps(content))


@pytest.fixture
def memory_store():
    pytest.importorskip("upath")
    from fsspec.implementations.memory import MemoryFileSystem

    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]
    yield
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(params=["local", "memory"])
def ds(request, tmp_path):
    if request.param == "memory":
        request.getfixturevalue("memory_store")
        root = BidsPath("memory://values")
    else:
        root = BidsPath(str(tmp_path / "values"))
    _write(root, DATASET)
    return root


def _data(paths, root):
    """The image files among `paths`, relative to `root`."""
    return {p.relative_to(root).as_posix() for p in paths
            if p.name.endswith(".nii.gz")}


def _all(paths, root):
    return [p.relative_to(root).as_posix() for p in paths]


# -- sidecar values -----------------------------------------------------------

@pytest.mark.parametrize("kwargs, expected", [
    # a plain value is compared with ==, and the nearest sidecar wins
    ({"RepetitionTime": 2.0}, {BOLD["01"], BOLD["03"]}),
    ({"RepetitionTime": 2}, {BOLD["01"], BOLD["03"]}),
    ({"RepetitionTime": 1.5}, {BOLD["02"]}),
    ({"RepetitionTime": "2"}, set()),               # a string is not a number
    ({"TaskName": "rest"}, set(BOLD.values())),
    ({"TaskName": "Rest"}, set()),                  # strings are exact
    # a test
    ({"EchoTime": lambda t: t < 0.028}, {BOLD["02"]}),
    # a set is any of; a list is one value, compared whole
    ({"PhaseEncodingDirection": {"j", "j-"}}, {BOLD["01"], BOLD["02"]}),
    ({"SliceTiming": [0.0, 0.5]}, set(BOLD.values())),
    ({"SliceTiming": [0, 0.5]}, set(BOLD.values())),
    ({"SliceTiming": (0.0, 0.5)}, set(BOLD.values())),
    ({"SliceTiming": [0.5]}, set()),
    ({"SliceTiming": {0.0, 0.5}}, set()),           # neither is the list
    # presence
    ({"B0FieldIdentifier": Any}, {BOLD["02"]}),
    ({"B0FieldIdentifier": Required}, {BOLD["02"]}),
    ({"B0FieldIdentifier": Never},
     {BOLD["01"], BOLD["03"], *T1W.values()}),
    ({"B0FieldIdentifier": {Never, "fm"}},
     set(BOLD.values()) | set(T1W.values())),
    # None is the JSON null, and null is there
    ({"IntendedFor": None}, {BOLD["01"]}),
    ({"IntendedFor": Any}, {BOLD["01"]}),
    # a bool is not a number
    ({"Flag": True}, {BOLD["01"]}),
    ({"Flag": 1}, {BOLD["02"]}),
    # a glob or a regex matches text only
    ({"TaskName": Glob("re*")}, set(BOLD.values())),
    ({"TaskName": re.compile("res")}, set()),       # the whole value
    ({"RepetitionTime": Glob("2*")}, set()),
    # several fields: all of them
    ({"RepetitionTime": 2, "EchoTime": Any}, {BOLD["01"]}),
    ({"sidecar": {"RepetitionTime": 2}, "EchoTime": Any}, {BOLD["01"]}),
])
def test_sidecar_values(ds, kwargs, expected):
    assert _data(Filter(**kwargs).walk(ds), ds) == expected


def test_sidecar_filters_keep_the_metadata_of_the_kept_data(ds):
    kept = _all(Filter(RepetitionTime=1.5).walk(ds), ds)
    assert kept == [
        "dataset_description.json", "participants.json", "participants.tsv",
        "sub-02/func/sub-02_task-rest_bold.json", BOLD["02"],
        "task-rest_bold.json",
    ]


def test_a_test_that_raises_on_a_wrong_value_fails(ds):
    for field, test in [
        ("RepetitionTime", lambda v: v.lower() == "2"),   # AttributeError
        ("TaskName", lambda v: v < 3),                    # TypeError
        ("TaskName", lambda v: int(v) == 0),              # ValueError
    ]:
        assert _data(Filter(**{field: test}).walk(ds), ds) == set()
    with pytest.raises(KeyError):
        Filter(TaskName=lambda v: {}[v]).walk(ds)


@pytest.mark.parametrize("keyword, meant", [
    ("Subjects", "subjects"), ("Subject", "subjects"), ("Sessions", "sessions"),
    ("Datatypes", "datatypes"), ("Suffix", "suffixes"), ("Tasks", "tasks"),
    ("Exclude_Subjects", "exclude_subjects"), ("Participants", "participants"),
    ("Acq", "acq"), ("Run", "run"), ("Runs", "run"), ("Sub", "sub"),
])
def test_a_capitalised_keyword_is_a_misspelling(keyword, meant):
    with pytest.raises(TypeError, match=f"write {meant}=.*sidecar="):
        Filter(**{keyword: "01"})
    # a sidecar field of that name goes in the mapping
    assert set(Filter(sidecar={keyword: "01"}).sidecar) == {keyword}


def test_sidecar_keywords_and_mapping():
    with pytest.raises(TypeError, match="RepetitionTime"):
        Filter(RepetitionTime=2, sidecar={"RepetitionTime": 2})
    with pytest.raises(TypeError, match="sidecar"):
        Filter(repetitiontime=2)
    f = Filter(sidecar={"weird-name": 1}, EchoTime=Any)
    assert set(f.sidecar) == {"weird-name", "EchoTime"}


def test_sidecars_are_read_once_and_only_for_passing_data(ds, monkeypatch):
    read = []
    real = filter_module._read_json

    def counting(path):
        read.append(path.name)
        return real(path)

    monkeypatch.setattr(filter_module, "_read_json", counting)
    Filter(EchoTime=Any).walk(ds)
    assert sorted(read) == sorted({
        "task-rest_bold.json", "sub-01_task-rest_bold.json",
        "sub-02_task-rest_bold.json",
    })
    read.clear()
    Filter(subjects="02", EchoTime=Any).walk(ds)
    assert sorted(read) == ["sub-02_task-rest_bold.json", "task-rest_bold.json"]
    read.clear()
    Filter(subjects="02").walk(ds)
    assert read == []


def test_select_reads_sidecars_from_path_objects(ds):
    f = Filter(RepetitionTime=2)
    listing = [p for p in ds.rglob("*") if p.is_file()]
    assert f.select(listing, root=ds) == f.walk(ds)
    with pytest.raises(TypeError, match="path objects"):
        f.select([p.relative_to(ds).as_posix() for p in listing])
    pure = [PureBidsPath(p.relative_to(ds).as_posix()) for p in listing]
    with pytest.raises(TypeError, match="path objects"):
        f.select(pure)


# -- participants.tsv ---------------------------------------------------------

@pytest.mark.parametrize("kwargs, expected", [
    ({"participants": {"age": lambda a: a >= 18}}, {"01"}),
    ({"participants": {"group": {"control", "sham"}}}, {"01", "03"}),
    ({"participants": {"group": "patient", "age": None}}, {"02"}),
    ({"participants": {"age": 30}}, {"01"}),          # 30.0 in the table
    ({"participants": {"age": Any}}, {"01", "02", "03"}),
    ({"participants": {"weight": Never}}, {"01", "02", "03"}),
    ({"participants": {"weight": Any}}, set()),
    ({"participants": {"weight": 3}}, set()),
    ({"participants": {"group": Glob("c*")}}, {"01"}),
    # with subjects=: both
    ({"participants": {"group": {"control", "patient"}},
      "subjects": ["02", "03"]}, {"02"}),
    ({"participants": {}}, {"01", "02", "03", "04"}),   # no filter
])
def test_participants(ds, kwargs, expected):
    kept = Filter(**kwargs).walk(ds)
    subjects = {p.subject for p in kept if p.name.endswith(".nii.gz")}
    assert subjects == expected


def test_participants_keep_the_metadata_of_the_kept_data(ds):
    kept = _all(Filter(participants={"group": "control"}).walk(ds), ds)
    assert kept == [
        "dataset_description.json", "participants.json", "participants.tsv",
        T1W["01"], T1W["01mp"],
        "sub-01/func/sub-01_task-rest_bold.json", BOLD["01"],
        "sub-01/func/sub-01_task-rest_events.tsv", "task-rest_bold.json",
    ]


def test_participants_are_read_once(ds, monkeypatch):
    read = []
    real = filter_module._read_rows

    def counting(path):
        read.append(path.name)
        return real(path)

    monkeypatch.setattr(filter_module, "_read_rows", counting)
    Filter(participants={"age": Any}).walk(ds)
    assert read == ["participants.tsv"]


def test_participants_need_a_table(tmp_path):
    root = BidsPath(str(tmp_path))
    _write(root, {k: v for k, v in DATASET.items() if k != "participants.tsv"})
    f = Filter(participants={"age": Any})
    with pytest.raises(FileNotFoundError, match="participants.tsv"):
        f.walk(root)
    listing = [p for p in root.rglob("*") if p.is_file()]
    with pytest.raises(FileNotFoundError, match="participants.tsv"):
        f.select(listing, root=root)
    with pytest.raises(FileNotFoundError, match="participants.tsv"):
        f.walk(str(tmp_path / "missing"))
    assert Filter().walk(root)                      # no filter, no need


def test_participants_need_an_id_column(tmp_path):
    root = BidsPath(str(tmp_path))
    _write(root, {**DATASET, "participants.tsv": "id\tage\nsub-01\t3\n"})
    with pytest.raises(ValueError, match="participant_id"):
        Filter(participants={"age": 3}).walk(root)


def test_select_with_participants_needs_a_root(ds):
    f = Filter(participants={"group": "control"})
    listing = [p.relative_to(ds).as_posix()
               for p in ds.rglob("*") if p.is_file()]
    with pytest.raises(TypeError, match="root"):
        f.select(listing)
    # path strings under a root that can be read
    under = [f"{ds}/{rel}" for rel in listing]
    assert f.select(under, root=str(ds)) == [str(p) for p in f.walk(ds)]


def test_participants_with_orphan_metadata():
    # a metadata file that applies to no data file is judged on its subject
    listing = ["participants.tsv", "sub-01/beh/sub-01_task-x_events.tsv",
               "sub-02/beh/sub-02_task-x_events.tsv"]
    plan = filter_module._Plan(Filter(participants={"age": Any}), listing,
                               subjects={"01"})
    assert plan.finish({}) == [
        "participants.tsv", "sub-01/beh/sub-01_task-x_events.tsv",
    ]


# -- presence and absence of an entity ------------------------------------------

PRESENCE = [
    "sub-01/anat/sub-01_T1w.nii.gz",
    "sub-01/anat/sub-01_acq-mprage_T1w.nii.gz",
    "sub-01/anat/sub-01_acq-fse_T1w.nii.gz",
    "sub-01/func/sub-01_task-rest_run-1_bold.nii.gz",
    "sub-01/func/sub-01_task-rest_run-2_bold.nii.gz",
    "sub-01/func/sub-01_task-rest_bold.nii.gz",
]


def _images(f, listing=PRESENCE):
    return {i for i, p in enumerate(PRESENCE) if p in f.select(listing)}


# typing and typing_extensions give distinct objects on older Pythons
ABSENT_MARKERS = [typing.NoReturn, typing_extensions.Never, typing_extensions.NoReturn,
          None, *filter(None, [getattr(typing, "Never", None)])]
PRESENT_MARKERS = [typing.Any, typing_extensions.Any, typing_extensions.Required,
        *filter(None, [getattr(typing, "Required", None)])]


@pytest.mark.parametrize("never", ABSENT_MARKERS)
def test_never_keeps_files_without_the_entity(never):
    assert _images(Filter(acq=never)) == {0, 3, 4, 5}
    assert _images(Filter(entities={"acq": never})) == {0, 3, 4, 5}
    assert _images(Filter(run=never)) == {0, 1, 2, 5}
    assert _images(Filter(task=never)) == {0, 1, 2}
    if never is not None:   # None is no filter on a label keyword
        assert _images(Filter(tasks=never)) == {0, 1, 2}
        assert _images(Filter(sessions=never)) == set(range(len(PRESENCE)))
        assert _images(Filter(subjects=never)) == set()
        assert _images(Filter(datatypes=never)) == set()


LABEL_KEYWORDS = [
    "subjects", "exclude_subjects", "sessions", "datatypes", "suffixes",
    "tasks",
]


@pytest.mark.parametrize("keyword", LABEL_KEYWORDS)
def test_none_is_no_filter_on_a_label_keyword(keyword):
    import inspect

    assert inspect.signature(Filter).parameters[keyword].default is None
    assert _images(Filter(**{keyword: None})) == set(range(len(PRESENCE)))
    with pytest.raises(TypeError, match=f"{keyword}=.*Never"):
        Filter(**{keyword: [None, "x"]})


def test_none_is_never_on_an_entity_keyword():
    assert _images(Filter(sub=None)) == set()
    assert _images(Filter(entities={"task": None})) == {0, 1, 2}
    assert _images(Filter(task=[None, "rest"])) == set(range(len(PRESENCE)))


@pytest.mark.parametrize("anything", PRESENT_MARKERS)
def test_any_keeps_files_with_the_entity(anything):
    assert _images(Filter(acq=anything)) == {1, 2}
    assert _images(Filter(run=anything)) == {3, 4}
    assert _images(Filter(sessions=anything)) == set()


def test_presence_mixes_with_values():
    assert _images(Filter(acq={Never, "mprage"})) == {0, 1, 3, 4, 5}
    assert _images(Filter(acq=[Never, "mprage"])) == {0, 1, 3, 4, 5}
    assert _images(Filter(acq=(None, Glob("f*")))) == {0, 2, 3, 4, 5}
    assert _images(Filter(acq={Any, "mprage"})) == {1, 2}
    assert _images(Filter(run={Never, 2})) == {0, 1, 2, 4, 5}


def test_label_tests_are_functions_of_the_label():
    assert _images(Filter(run=lambda r: int(r) > 1)) == {4}
    assert _images(Filter(acq=lambda a: a.startswith("m"))) == {1}


def test_an_empty_filter_still_keeps_everything():
    assert _images(Filter()) == set(range(len(PRESENCE)))
    assert _images(Filter(acq=[])) == set(range(len(PRESENCE)))


ORPHAN = ["sub-01/beh/sub-01_task-x_events.tsv"]


@pytest.mark.parametrize("value, kept", [
    ("x", True),             # a filter on an entity it does not have passes
    (Never, True),           # it does not have it
    ({Never, "x"}, True),
    (Any, False),            # ... unless it asks for the entity to be there
    (Required, False),
    ({Any, "x"}, False),     # ... beside values too
    ({Any, Never}, True),    # ... but for one that admits it is not
])
def test_presence_on_metadata_judged_on_its_own_name(value, kept):
    assert Filter(acq=value).select(ORPHAN) == (ORPHAN if kept else [])


@pytest.mark.parametrize("value, kept", [
    (2, True), ({2, None}, True), (Never, True), ({Never, 2}, True),
    (Any, False), (Required, False), ({Any, 2}, False), ({Any, Never}, True),
])
def test_sidecar_filters_on_metadata_judged_on_its_own_name(value, kept):
    plan = filter_module._Plan(Filter(RepetitionTime=value), ORPHAN)
    assert plan.reads == set()
    assert plan.finish({}) == (ORPHAN if kept else [])


@pytest.mark.parametrize("content, error, message", [
    ("{bad", json.JSONDecodeError, "sub-01_task-rest_bold.json.*not valid JSON"),
    ("[1, 2]", TypeError, "sub-01_task-rest_bold.json.*not hold a JSON object"),
])
def test_a_sidecar_that_cannot_be_read(tmp_path, content, error, message):
    root = BidsPath(str(tmp_path))
    _write(root, DATASET)
    _write(root, {"sub-01/func/sub-01_task-rest_bold.json": content})
    with pytest.raises(error, match=message):
        Filter(EchoTime=Any).walk(root)
    listing = [p for p in root.rglob("*") if p.is_file()]
    with pytest.raises(error, match=message):
        Filter(EchoTime=Any).select(listing, root=root)


@pytest.mark.anyio
@pytest.mark.parametrize("content, error", [
    ("{bad", json.JSONDecodeError), ("[1, 2]", TypeError),
])
async def test_awalk_a_sidecar_that_cannot_be_read(tmp_path, content, error):
    _write(BidsPath(str(tmp_path)), DATASET)
    _write(BidsPath(str(tmp_path)),
           {"sub-01/func/sub-01_task-rest_bold.json": content})
    with pytest.raises(error, match="sub-01_task-rest_bold.json"):
        await Filter(EchoTime=Any).awalk(str(tmp_path))


# -- the dataset root ------------------------------------------------------------

ROOTLESS = {
    "task-rest_bold.json": {"RepetitionTime": 2},
    "sub-01/sub-01_task-rest_bold.json": {"EchoTime": 0.03},
    "sub-01/func/sub-01_task-rest_bold.nii.gz": b"",
    "sub-01/func/sub-01_task-rest_bold.json": {"Flag": True},
    "sub-02/func/sub-02_task-rest_bold.nii.gz": b"",
}
DESCRIPTION = {"dataset_description.json": {"Name": "x", "BIDSVersion": "1.10.0"}}


def _selects(f, root):
    """What walk keeps, after checking that select and awalk keep it too."""
    import asyncio

    kept = _all(f.walk(root), root)
    listing = [p for p in root.rglob("*") if p.is_file()]
    assert _all(f.select(listing, root=root), root) == kept
    aroot = AsyncBidsPath(str(root))
    assert _all(asyncio.run(f.awalk(aroot)), aroot) == kept
    return kept


def test_without_a_description_nothing_is_inherited(tmp_path):
    root = BidsPath(str(tmp_path / "rootless"))
    _write(root, ROOTLESS)
    bold = "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert [s.name for s in (root / bold).sidecars] == [
        "sub-01_task-rest_bold.json"
    ]
    # the sidecar beside the file still applies; the ones above do not
    assert _data(Filter(Flag=True).walk(root), root) == {bold}
    assert _data(Filter(RepetitionTime=2).walk(root), root) == set()
    assert _data(Filter(EchoTime=Any).walk(root), root) == set()
    # describing nothing, the sidecars above are judged on their own names
    # (rule 3), as a filter on a field they do not have
    assert _selects(Filter(EchoTime=Any), root) == []
    assert _selects(Filter(RepetitionTime=2), root) == [
        "sub-01/sub-01_task-rest_bold.json", "task-rest_bold.json",
    ]
    # and they do not come along with the data either
    kept = _selects(Filter(datatypes="func"), root)
    assert kept == [
        "sub-01/func/sub-01_task-rest_bold.json", bold,
        "sub-02/func/sub-02_task-rest_bold.nii.gz",
    ]
    # and on their subject
    assert "task-rest_bold.json" in _selects(Filter(subjects="02"), root)
    assert "sub-01/sub-01_task-rest_bold.json" not in _selects(
        Filter(subjects="02"), root
    )


def test_with_a_description_sidecars_are_inherited(tmp_path):
    root = BidsPath(str(tmp_path / "rooted"))
    _write(root, {**ROOTLESS, **DESCRIPTION})
    bold = "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert _data(Filter(RepetitionTime=2).walk(root), root) == {
        bold, "sub-02/func/sub-02_task-rest_bold.nii.gz",
    }
    assert _selects(Filter(EchoTime=Any), root) == [
        "dataset_description.json",
        "sub-01/func/sub-01_task-rest_bold.json", bold,
        "sub-01/sub-01_task-rest_bold.json", "task-rest_bold.json",
    ]
    assert "task-rest_bold.json" in _selects(Filter(datatypes="func"), root)


def test_a_nested_description_is_the_root_of_what_is_below_it(tmp_path):
    root = BidsPath(str(tmp_path / "nested"))
    _write(root, {
        **ROOTLESS, **DESCRIPTION, "sub-01/dataset_description.json": {},
    })
    bold = "sub-01/func/sub-01_task-rest_bold.nii.gz"
    assert [s.name for s in (root / bold).sidecars] == [
        "sub-01_task-rest_bold.json", "sub-01_task-rest_bold.json",
    ]
    assert _data(Filter(RepetitionTime=2).walk(root), root) == {
        "sub-02/func/sub-02_task-rest_bold.nii.gz",
    }
    assert _data(Filter(EchoTime=0.03).walk(root), root) == {bold}
    kept = _selects(Filter(subjects="01", datatypes="func"), root)
    assert "task-rest_bold.json" not in kept
    assert "sub-01/sub-01_task-rest_bold.json" in kept


SHAPES = {
    "rooted": {**DATASET},
    "rootless": {k: v for k, v in DATASET.items()
                 if k != "dataset_description.json"},
    "nested": {**DATASET, "sub-01/dataset_description.json": {},
               "sub-01/sub-01_task-rest_bold.json": {"X": 1},
               "sub-02/sub-02_task-rest_bold.json": {"X": 2}},
    "in a session": {
        **DESCRIPTION,
        "T1w.json": {}, "ses-1_T1w.json": {},
        "sub-01/sub-01_T1w.json": {},
        "sub-01/ses-1/dataset_description.json": {},
        "sub-01/ses-1/sub-01_ses-1_T1w.json": {},
        "sub-01/ses-1/anat/sub-01_ses-1_T1w.nii.gz": b"",
        "sub-01/ses-1/anat/sub-01_ses-1_T1w.json": {},
        "sub-01/ses-2/anat/sub-01_ses-2_T1w.nii.gz": b"",
    },
    "ignored": {**DATASET, ".bidsignore": "*.json\nsub-02/\n"},
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_sidecars_a_filter_reads_are_path_sidecars(tmp_path, shape):
    root = BidsPath(str(tmp_path / "shape"))
    _write(root, SHAPES[shape])
    listing = sorted(p.relative_to(root).as_posix()
                     for p in root.rglob("*") if p.is_file())
    ignore = filter_module._BidsIgnore.parse(
        (root / ".bidsignore").read_text() if ".bidsignore" in listing else ""
    )
    plan = filter_module._Plan(Filter(), listing, ignore)
    chains = filter_module._sidecar_chains(
        plan.data.values(), plan.meta, plan.scopes
    )
    assert chains
    for item, chain in chains.items():
        expected = tuple(s.relative_to(root).as_posix()
                         for s in (root / item).sidecars)
        assert chain == expected, item


# -- async ----------------------------------------------------------------------

@pytest.fixture(params=["local", "memory"])
def ads(request, tmp_path):
    if request.param == "memory":
        request.getfixturevalue("memory_store")
        _write(BidsPath("memory://values"), DATASET)
        request.getfixturevalue("async_memory")
        return AsyncBidsPath("memory://values")
    _write(BidsPath(str(tmp_path / "values")), DATASET)
    return AsyncBidsPath(str(tmp_path / "values"))


ASYNC_FILTERS = [
    Filter(RepetitionTime=2), Filter(EchoTime=lambda t: t < 0.028),
    Filter(B0FieldIdentifier=Never), Filter(IntendedFor=None),
    Filter(participants={"group": {"control", "sham"}}),
    Filter(participants={"age": Any}, PhaseEncodingDirection=Any),
    Filter(acq={Never, "mprage"}, run=Never),
]


@pytest.mark.anyio
async def test_awalk_values(ads, tmp_path, monkeypatch):
    local = BidsPath(str(tmp_path / "expected"))   # what walk keeps
    _write(local, DATASET)
    for f in ASYNC_FILTERS:
        kept = await f.awalk(ads)
        assert all(isinstance(p, AsyncBidsPath) for p in kept)
        assert _all(kept, ads) == _all(f.walk(local), local)
    read = []
    real = filter_module._aread_json

    async def counting(path):
        read.append(path.name)
        return await real(path)

    monkeypatch.setattr(filter_module, "_aread_json", counting)
    await Filter(EchoTime=Any).awalk(ads)
    assert sorted(read) == sorted({
        "task-rest_bold.json", "sub-01_task-rest_bold.json",
        "sub-02_task-rest_bold.json",
    })


@pytest.mark.anyio
async def test_awalk_reads_and_lists_a_few_at_a_time(tmp_path, monkeypatch):
    import asyncio

    files = dict(DATASET)
    for s in range(10):
        files[f"sub-1{s}/func/sub-1{s}_task-rest_bold.nii.gz"] = b""
        files[f"sub-1{s}/func/sub-1{s}_task-rest_bold.json"] = {"EchoTime": 1}
    _write(BidsPath(str(tmp_path)), files)
    monkeypatch.setattr(filter_module, "_CONCURRENCY", 3)
    running, most = 0, {}

    def counting(name, real):
        async def call(path):
            nonlocal running
            running += 1
            most[name] = max(most.get(name, 0), running)
            await asyncio.sleep(0.001)
            try:
                return await real(path)
            finally:
                running -= 1
        return call

    for name in ("_aread_json", "_alist"):
        monkeypatch.setattr(filter_module, name,
                            counting(name, getattr(filter_module, name)))
    kept = await Filter(EchoTime=Any).awalk(str(tmp_path))
    assert len(_data(kept, AsyncBidsPath(str(tmp_path)))) == 12
    assert most == {"_aread_json": 3, "_alist": 3}


@pytest.mark.anyio
async def test_awalk_participants_need_a_table(tmp_path):
    _write(BidsPath(str(tmp_path)),
           {k: v for k, v in DATASET.items() if k != "participants.tsv"})
    with pytest.raises(FileNotFoundError, match="participants.tsv"):
        await Filter(participants={"age": Any}).awalk(str(tmp_path))
