# Reading sidecars and tables

A BIDS dataset keeps most of its information outside the images. Acquisition
parameters live in JSON files called *sidecars*, and everything tabular, from
the list of participants to the onsets of the events in a run, lives in TSV
files. brainfilter reads both through the same path object you use to walk the
dataset, so that a JSON file behaves like a dictionary and a TSV file behaves
like a dictionary of columns. This page goes through each of them in turn, then
looks at how the values of a table receive their types.

Nothing here writes to the dataset, and every read goes to the files again, so
you always see what is on disk. A value that a read returns is a copy: changing
it changes nothing in the dataset. [Editing a dataset](edit-dataset.md) covers
writing.

## A small dataset to read

The examples use a dataset with one subject, one run of a resting-state task,
and three participants. It is built in memory with `memory://`, which needs
[universal-pathlib](../getting-started/installation.md) and no files on disk.
Building the dataset requires writing, which a path only allows when it is
created with `mode="w"`; you can skip this block and point `BidsPath` at any
dataset of your own instead.

```python
from brainfilter import BidsPath

w = BidsPath("memory://toy", mode="w")
w["dataset_description.json"] = {"Name": "Toy dataset", "BIDSVersion": "1.9.0"}

(w / "participants.tsv").write_text(
    "participant_id\tage\tsex\tsite\tlanguages\theight\tweight\tvisit\n"
    "sub-01\t30\tF\t02\ten,fr\t170\t70.5\t2024-01-31\n"
    "sub-02\tn/a\tM\t10\ten\t182\t68\t2024-02-07\n"
    "sub-03\t25.5\tF\t02\tde,en\tn/a\tn/a\tn/a\n"
)
w["participants.json"] = {
    "age": {"Description": "Age at scan", "Units": "years"},
    "sex": {"Levels": {"F": "female", "M": "male"}},
    "languages": {"Delimiter": ","},
    "height": {"Format": "number"},
    "visit": {"Format": "date"},
}

w["task-rest_bold.json"] = {"TaskName": "rest", "RepetitionTime": 2.0}
func = w / "sub-01" / "func"
func["sub-01_task-rest_bold.json"] = {"RepetitionTime": 2.5, "EchoTime": 0.03}
(func / "sub-01_task-rest_bold.nii.gz").write_bytes(b"")
(func / "sub-01_task-rest_events.tsv").write_text(
    "onset\tduration\ttrial_type\tresponse_time\n"
    "0.5\t1\tgo\t0.43\n"
    "4\t1\tstop\tn/a\n"
)
func["sub-01_task-rest_events.json"] = {
    "trial_type": {"Levels": {"go": "respond", "stop": "withhold"}}
}
```

From here on the dataset is opened for reading. A path is read-only unless you
ask otherwise, and a directory is a mapping from the names of its children to
paths, so you reach a file by indexing down from the root.

```pycon
>>> ds = BidsPath("memory://toy")
>>> ds.keys()
['dataset_description.json', 'participants.json', 'participants.tsv', 'sub-01', 'task-rest_bold.json']
>>> bold = ds["sub-01"]["func"]["sub-01_task-rest_bold.nii.gz"]
```

## JSON files are mappings

A JSON file is a mapping of its keys. Indexing gives the value, and the other
read-only methods of a dictionary (`in`, `keys()`, `values()`, `items()`,
`get()` and iteration) work as you would expect.

```pycon
>>> description = ds["dataset_description.json"]
>>> description["Name"]
'Toy dataset'
>>> "Authors" in description
False
>>> description.get("Authors", [])
[]
>>> list(description.keys())
['Name', 'BIDSVersion']
```

Each of these reads the file. When you want several values, or you want a
plain dictionary to hand to other code, `as_dict()` reads the file once and
returns everything it holds.

```pycon
>>> description.as_dict()
{'Name': 'Toy dataset', 'BIDSVersion': '1.9.0'}
```

## The sidecars of a data file

An image rarely has a JSON file of its own that holds everything about it.
BIDS lets a parameter that is shared by many files be written once, higher up
in the tree, and a file *inherits* whatever the sidecars above it say. Here
the repetition time of the whole task is given at the root, and the subject's
sidecar overrides it for the images it describes.

The `sidecars` property of a data file lists the JSON files that apply to it,
nearest first.

```pycon
>>> bold.sidecars
(BidsSidecarFile('memory://toy/sub-01/func/sub-01_task-rest_bold.json'), BidsSidecarFile('memory://toy/task-rest_bold.json'))
```

The `sidecar` property (singular) is the merged view of those files. It looks
up a key in the nearest sidecar that has it, so `RepetitionTime` comes from the
subject's sidecar and `TaskName` falls through to the one at the root.

```pycon
>>> bold.sidecar["RepetitionTime"]
2.5
>>> bold.sidecar["TaskName"]
'rest'
>>> bold.sidecar.as_dict()
{'TaskName': 'rest', 'RepetitionTime': 2.5, 'EchoTime': 0.03}
```

The result of `sidecar` is a standard-library `collections.ChainMap`, so you
can also read it as a mapping, and `as_dict()` flattens it into an ordinary
dictionary in which the nearest sidecar wins. The files themselves are still
available one by one, in the same order, through `bold.sidecars`. If no sidecar
applies to a file, `sidecars` is an empty tuple and `sidecar` is empty.

Which files count as "applying to" a data file, and in which order, is the
subject of [Sidecar inheritance](../concepts/inheritance.md).

## TSV files are mappings of columns

A TSV file works the same way, with one difference: the keys are column names
and the values are columns. Indexing a table by a column name returns that
column as a list with one entry per row.

```pycon
>>> participants = ds["participants.tsv"]
>>> participants.keys()
['participant_id', 'age', 'sex', 'site', 'languages', 'height', 'weight', 'visit']
>>> participants["age"]
[30.0, None, 25.5]
>>> "sex" in participants
True
```

To load the whole table at once, you can choose the shape that suits what you
are doing. `as_dict()` gives the columns, and `columns()` is another name for
the same thing.

```pycon
>>> participants.as_dict()["sex"]
['F', 'M', 'F']
```

`as_list()` gives the rows, each as a dictionary from column name to value,
and `rows()` goes through the same rows one at a time.

```pycon
>>> participants.as_list()[1]
{'participant_id': 'sub-02', 'age': None, 'sex': 'M', 'site': '10', 'languages': ['en'], 'height': 182.0, 'weight': '68', 'visit': datetime.date(2024, 2, 7)}
>>> [row["participant_id"] for row in participants.rows() if row["age"] is None]
['sub-02']
```

`as_dataframe()` returns a pandas `DataFrame`, which needs pandas to be
installed. Missing values become `NaN` or `None`, and numeric columns receive
numeric dtypes.

```pycon
>>> frame = participants.as_dataframe()
>>> frame[["participant_id", "age", "height"]]
  participant_id   age  height
0         sub-01  30.0   170.0
1         sub-02   NaN   182.0
2         sub-03  25.5     NaN
>>> frame["age"].dtype
dtype('float64')
```

Events files read the same way. The sidecar of `events.tsv` is the `events.json`
next to it, which will matter in a moment.

```pycon
>>> events = ds["sub-01"]["func"]["sub-01_task-rest_events.tsv"]
>>> events.as_list()
[{'onset': 0.5, 'duration': 1.0, 'trial_type': 'go', 'response_time': 0.43}, {'onset': 4.0, 'duration': 1.0, 'trial_type': 'stop', 'response_time': None}]
```

## Where the types come from

Look at what the reads above returned. `age` is a list of floats, although the
file has `30` for the first participant. The missing age is `None`, not the
string `"n/a"`. `site` kept its leading zero, `visit` became a date, and
`languages` became a list of lists. A TSV file stores only text, so brainfilter
has to decide a type for each column, and it does so by the following rules,
from the first that applies.

1. **The column's description in the table's JSON sidecar.** If it has a
   `Format`, that is the type. `number` is a `float` (even when every value
   is integral), `integer` and `index` are an `int`, `boolean` is a `bool`
   written `true` or `false`, and `date`, `datetime` and `time` are a
   `datetime.date`, a `datetime.datetime` and a `datetime.time`, accepted in strict ISO 8601 only. Any
   other format is text. In the dataset above, `participants.json` says that
   `height` is a number, so the whole-number `170` reads as `170.0`, and that
   `visit` is a date.
2. **The standard BIDS definition of the column.** `age` is not described as a
   number in `participants.json` above, yet it reads as one, because BIDS
   defines it so. The same holds for `onset` and `duration` in the events
   file, which read as floats although the file writes `4` and `1`.
   `participant_id` and `trial_type` are strings, and `acq_time` is a
   `datetime.datetime`.
3. **The values themselves.** A column with neither is an `int` if every value
   is an integer as Python writes it, otherwise a `float` if every value is a
   float as Python writes it, otherwise text.

The inference of the third rule is deliberately lossless. It only picks a
number when writing it back would give the exact text that was read. That is
why `site`, with values such as `02`, stays text, and why `weight`, which mixes
`70.5` and `68`, stays text too instead of turning `68` into `68.0`. Booleans
and dates are never guessed; they need a `Format`.

```pycon
>>> participants["site"]
['02', '10', '02']
>>> participants["weight"]
['70.5', '68', None]
>>> participants["height"]
[170.0, 182.0, None]
>>> participants["visit"]
[datetime.date(2024, 1, 31), datetime.date(2024, 2, 7), None]
```

A declared type is only used if every value of the column parses as it. If
`participants.json` declared `visit` an `integer`, its dates would not parse,
and the column would fall back to the next rule instead of failing. A declared
type is also stricter in the other direction than inference: a `site` declared
as an `integer` reads as `[2, 10, 2]`, because `02` is a valid integer. The
file is not changed by that, and a cell that is left alone keeps its exact text
if the table is written back.

### Missing values, levels and delimiters

In every column, the BIDS missing value `n/a` reads as `None`. The same
happens inside a list, where a missing item is `None`.

A column that the sidecar describes with `Levels` is categorical, and its
values stay as text, since they are the keys of `Levels`. This is what happens
to `sex` above, and to `trial_type` in the events file. The `Levels` themselves
come from the sidecar, if you need the descriptions.

```pycon
>>> participants["sex"]
['F', 'M', 'F']
>>> events.sidecar["trial_type"]["Levels"]
{'go': 'respond', 'stop': 'withhold'}
```

A column that the sidecar describes with a `Delimiter` holds several values per
cell, and reads as a list for each row, typed by the column's type. The cell
`en,fr` of `languages` is `['en', 'fr']`.

```pycon
>>> participants["languages"]
[['en', 'fr'], ['en'], ['de', 'en']]
```

### Reading the text as it is

Sometimes you want the file, not an interpretation of it: to check what a cell
really says, or to apply a conversion of your own. Every loading method takes
`raw=True`, which returns each value as its exact text, with `n/a` kept as
`"n/a"` and nothing split into lists. This applies to `as_dict()`, `columns()`,
`as_list()` and `rows()`.

```pycon
>>> participants.as_dict(raw=True)["age"]
['30', 'n/a', '25.5']
>>> participants.as_dict(raw=True)["languages"]
['en,fr', 'en', 'de,en']
```

A BIDS table has no quoting. A cell is the exact text between two tabs, so
`"q"` reads as `"q"`, with its quotes, and a UTF-8 byte-order mark at the start
of a file is skipped.

!!! note "A table is typed by its own sidecar"
    A table is typed using its own `sidecar`, which is the merged JSON that
    applies to it. For `participants.tsv` that is `participants.json`, and for
    an events file it is the `events.json` that applies to it, found in the
    way the previous section describes. A table without any sidecar still has
    types: they simply come from the standard definitions and the values.

## Where to go next

The rules that decide which sidecars apply to a file are written down in
[Sidecar inheritance](../concepts/inheritance.md), and the paths that carry all
of this in [Paths and storage backends](../concepts/paths-and-backends.md).
To keep only part of a dataset, see
[Filtering a local dataset](filter-local.md). The reference for the classes on
this page is in [`BidsPath`](../api/paths.md#brainfilter.BidsPath) and
[`Table`](../api/tables.md#brainfilter.Table).
