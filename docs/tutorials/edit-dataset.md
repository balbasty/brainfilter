# Editing a dataset safely

A dataset rarely comes out of the scanner or the converter exactly right. A
repetition time recorded in the wrong units, a column missing from
`participants.tsv`, or a sidecar that was never written are all common, and all
cheap to fix by hand in an editor, one file at a time. Across a hundred
subjects, or on a bucket you cannot open in an editor, that stops being
practical. This tutorial shows how to make such edits with brainfilter, and how
to keep them safe: each file is replaced in one step, edits that belong together
can be grouped, and a failure leaves you with a precise account of what changed.

The examples run in order, on a small dataset held in memory (`memory://`, from
universal-pathlib), so you can paste them into a Python session. Reading a
dataset is covered in [Reading metadata](read-metadata.md), and the model behind
the behaviour described here is in
[Modes and transactions](../concepts/modes-and-transactions.md).

## A dataset to edit

You first need something to edit. A path is read-only unless you ask for
otherwise, so building the dataset is already a first use of a writable path:
pass `mode="w"` when you create it.

```pycon
>>> from brainfilter import BidsPath
>>> ds = BidsPath("memory://ds", mode="w")
>>> ds.mode
'w'
>>> (ds / "dataset_description.json").write({"Name": "Demo", "BIDSVersion": "1.10.0"})
>>> (ds / "participants.tsv").write([
...     {"participant_id": "sub-01", "age": "30", "sex": "F"},
...     {"participant_id": "sub-02", "age": "n/a", "sex": "M"},
...     {"participant_id": "sub-03", "age": "1.50", "sex": "F"},
... ])
>>> for sub in ("sub-01", "sub-02"):
...     func = ds / sub / "func"
...     (func / f"{sub}_task-rest_bold.json").write({"RepetitionTime": 20.0, "TaskName": "rest"})
...     (func / f"{sub}_task-rest_bold.nii.gz").touch()
>>> (ds / "sub-01" / "anat" / "sub-01_T1w.nii.gz").touch()
```

Writing to a path that does not exist yet creates the file, and any directories
above it. The two bold sidecars carry a `RepetitionTime` of `20.0`, which should
have been `2.0`: that is the mistake we are going to fix.

### Putting a new file where it belongs

A BIDS file name already says where the file goes: its subject, its session
and, through its suffix, its datatype. The `//` operator reads that for you, so
you write the name once and the directories follow from it. Nothing is read
from the dataset, and the result is a path like any other, with the same mode.

```pycon
>>> ds // "sub-03_ses-1_T1w.nii.gz"
BidsPath('memory://ds/sub-03/ses-1/anat/sub-03_ses-1_T1w.nii.gz', mode='w')
>>> ds // "sub-03_sessions.tsv"
BidsSessionsFile('memory://ds/sub-03/sub-03_sessions.tsv', mode='w')
>>> ds // "task-rest_bold.json"
BidsSidecarFile('memory://ds/task-rest_bold.json', mode='w')
```

Some suffixes belong to more than one datatype: an `events.tsv` may describe a
functional run, an EEG recording or a behavioural task. The name alone cannot
settle that, so name the datatype in front of it, or start from a datatype
directory. The left side may be any directory on the way to the file, and the
directories it already has are reused.

```pycon
>>> ds // "func/sub-03_task-rest_events.tsv"
BidsTSVFile('memory://ds/sub-03/func/sub-03_task-rest_events.tsv', mode='w')
>>> ds / "sub-03" / "func" // "sub-03_task-rest_events.tsv"
BidsTSVFile('memory://ds/sub-03/func/sub-03_task-rest_events.tsv', mode='w')
```

A name that cannot be placed, or a starting directory that does not lead to its
place, raises a `BidsNameError` that says what to write instead. The `/`
operator never moves anything: it joins a path exactly as written, which is how
to write a file BIDS does not name, such as a `README`.

If you already have a dataset, build a writable path the same way, from a local
directory or a URL, or turn a read-only path into a writable one with
`with_mode`. The original path is left as it was.

```pycon
>>> reader = BidsPath("memory://ds")
>>> reader.mode
'r'
>>> writer = reader.with_mode("w")
>>> writer.mode, reader.mode
('w', 'r')
```

Every path derived from a writable path is writable too: its children, its
parent, the paths a listing or a glob yields, and `sidecars`. You open the
dataset once, and the mode follows you down the tree.

## What a read-only path refuses

Before changing anything, it is worth seeing what protects you. On the
read-only `reader`, the same edit fails and the file is left alone.

```pycon
>>> from brainfilter import ReadOnlyError
>>> bold_read_only = reader["sub-01"]["func"]["sub-01_task-rest_bold.json"]
>>> try:
...     bold_read_only["RepetitionTime"] = 2.0
... except ReadOnlyError as error:
...     print(error)
cannot write to 'memory://ds/sub-01/func/sub-01_task-rest_bold.json': the path is read-only; get a writable path with path.with_mode('w'), or build it with mode='w'
```

The refusal is a `ReadOnlyError`, a subclass of `PermissionError`, so code that
already handles permission failures handles this one too. The same error comes
from `with reader:`, from `reader.transaction()`, and from the `Path` members
that change the filesystem, such as `write_text`, `unlink` or `mkdir`.

## Fixing a value in one file

On a writable path, assigning to a key of a JSON file changes the file at once.
The file is read, the key is set, and the file is replaced in a single atomic
step, so another reader sees either the old file or the new one and never a
half-written one.

```pycon
>>> bold = ds["sub-01"]["func"]["sub-01_task-rest_bold.json"]
>>> bold["RepetitionTime"] = 2.0
>>> bold.as_dict()
{'RepetitionTime': 2.0, 'TaskName': 'rest'}
```

The other write forms work the same way: `del` removes a key, `update` sets
several keys in one replace, and `write` replaces the whole content of the file.

```pycon
>>> bold.update(EchoTime=0.03, SliceTiming=[0.0, 1.0])
>>> del bold["SliceTiming"]
>>> bold.as_dict()
{'RepetitionTime': 2.0, 'TaskName': 'rest', 'EchoTime': 0.03}
```

Every one of these is a complete read, change and replace. That is what keeps
each write safe, and it is also why, outside a transaction, a change made to a
value you have already read does not reach the file.

!!! warning "Outside a `with` block, editing a nested value in place saves nothing"

    Outside a block, a value that a read returns is a copy. When it is a list or
    a dictionary, changing it in place changes the copy, not the file. Write the
    changed value back instead, or make the edit inside a `with` block, where a
    nested value is the file's own and changing it in place is saved (see
    [Grouping edits in a transaction](#grouping-edits-in-a-transaction)).

    ```pycon
    >>> bold["Extra"] = {"Coil": "head"}
    >>> bold["Extra"]["Coil"] = "neck"        # changes a copy: nothing is saved
    >>> bold["Extra"]
    {'Coil': 'head'}
    >>> extra = bold["Extra"]
    >>> extra["Coil"] = "neck"
    >>> bold["Extra"] = extra                  # this one is saved
    >>> bold["Extra"]
    {'Coil': 'neck'}
    ```

    The same holds for the rows returned by `as_list()` on a table, which are
    copies inside a block too.

## Fixing a value across a dataset

To repair every affected file, loop over them. A glob on a writable path yields
writable paths, so each file can be edited directly as it comes out of the loop.

```pycon
>>> for sidecar in ds.glob("sub-*/func/*_bold.json"):
...     sidecar["RepetitionTime"] = 2.0
```

This works, and for two files it is fine. Notice what it does, though: each
assignment is its own replace. If the loop were to stop halfway, because the
store went away or because you interrupted it, some sidecars would be fixed and
others would not, and nothing would tell you which. A dataset in that state is
worse than one that is consistently wrong, because the next person to look at it
cannot see that anything happened.

## Grouping edits in a transaction

When several writes belong together, put them in a block with `with ds:`. Inside
the block, writes are kept in memory, and every read sees them, so the code in
the block behaves as if the files had already changed. When the block ends
cleanly, each file that changed is written once.

```pycon
>>> with ds:
...     for sidecar in ds.glob("sub-*/func/*_bold.json"):
...         sidecar["RepetitionTime"] = 2.0
...     sub2 = ds["sub-02"]["func"]["sub-02_task-rest_bold.json"]
...     print(sub2["RepetitionTime"])
2.0
```

Inside the block, a nested value can also be changed in place. There, a key of a
JSON file gives the transaction's own value rather than a copy, so a change to a
list or a dictionary it holds is saved when the block ends, like an assignment.

```pycon
>>> sub2 = ds["sub-02"]["func"]["sub-02_task-rest_bold.json"]
>>> sub2["Extra"] = {"Coils": ["head"]}
>>> with ds:
...     sub2["Extra"]["Coils"].append("neck")
...     sub2.as_dict()["Extra"]["Coils"].append("spine")   # a copy: not saved
>>> sub2["Extra"]
{'Coils': ['head', 'neck']}
```

Only a key of a JSON file, and a column of a table, give the transaction's own
values. Reads that load a whole file, such as `as_dict()` and `as_list()`,
return copies inside a block too, so you can keep one as a snapshot. A value you
assign is copied in, so changing your own object afterwards changes nothing.

The block gives you the path itself, so `with ds as d:` is the same as `d = ds`
followed by `with ds:`. If you want a report of what was written, ask for the
transaction object instead with `ds.transaction()`.

```pycon
>>> with ds.transaction() as tx:
...     ds["sub-02"]["func"]["sub-02_task-rest_bold.json"]["EchoTime"] = 0.03
>>> [str(path) for path in tx.written]
['memory://ds/sub-02/func/sub-02_task-rest_bold.json']
```

`tx.written` lists the files that were actually written, in the order in which
the transaction first used them. A file that was read but not changed is not
written, and a new file is created only once it has content, so the list is also
a quick check that the transaction touched what you expected and nothing more.

While the block is open, the files on disk have not changed yet. A read through
brainfilter sees your edits; reading the raw text of the file does not.

```pycon
>>> path = ds["sub-01"]["func"]["sub-01_task-rest_bold.json"]
>>> with ds:
...     path["RepetitionTime"] = 5.0
...     print(path["RepetitionTime"])
...     print('"RepetitionTime": 5.0' in path.read_text())
5.0
False
>>> '"RepetitionTime": 5.0' in path.read_text()
True
>>> path["RepetitionTime"] = 2.0
```

The last line puts the value back for the rest of the tutorial.

Reading the raw text is fine, but writing it is not. A raw write to a JSON or TSV
file the block covers, such as `write_text`, `unlink` or `rename`, would be
overwritten when the block commits, so brainfilter refuses it. Make such a write
through brainfilter inside the block, or after the block ends. Raw writes to
other files, such as an image, are allowed.

```pycon
>>> with ds:
...     path["RepetitionTime"] = 2.0
...     try:
...         path.write_text("{}")
...     except RuntimeError as error:
...         print(str(error).partition(": a")[0])
cannot write to 'memory://ds/sub-01/func/sub-01_task-rest_bold.json' with write_text()
```

### When the block raises

If the block ends with an exception, nothing is written. The exception
propagates unchanged, and the files are exactly as they were when the block
began.

```pycon
>>> try:
...     with ds:
...         path["RepetitionTime"] = 99.0
...         raise ValueError("wrong subject list")
... except ValueError as error:
...     print(error)
wrong subject list
>>> path["RepetitionTime"]
2.0
```

The same is true when the content cannot be written. Before the first file is
replaced, every changed file is turned into its final text. A value that cannot
be written, such as a tab inside a TSV cell, fails at that point, and then
nothing has been written.

```pycon
>>> with ds:
...     path["RepetitionTime"] = 99.0
...     ds["participants.tsv"]["note"] = ["a\tb", "c", "d"]
Traceback (most recent call last):
  ...
ValueError: row 0 of column 'note' holds a tab or a line break ('a\tb'), which a BIDS table cannot hold: it has no quoting; replace them, e.g. with spaces
>>> path["RepetitionTime"]
2.0
```

### When the store fails partway

The one thing a transaction cannot offer is atomicity across files. Each file is
replaced in one step, but the files are replaced one after the other, and on a
remote store there is no operation that replaces several objects at once. If the
store refuses one of the writes, the commit stops there.

!!! warning "A transaction is not rolled back"

    Files written before a failure stay written. The commit stops at the first
    failure, so the files that follow it are not attempted, and their edits are
    dropped.

brainfilter then raises a `TransactionError`, which says exactly where things
stand. The following output comes from a store that refuses the second file of a
commit (a permission failure injected for this page, since memory stores do not
fail on their own).

```python
try:
    with ds:
        for sidecar in ds.glob("sub-*/func/*_bold.json"):
            sidecar["RepetitionTime"] = 2.0
        ds["participants.tsv"]["handedness"] = ["R", "L", "R"]
except TransactionError as error:
    print(error.written)      # [BidsSidecarFile('memory://ds/sub-01/func/sub-01_task-rest_bold.json', mode='w')]
    print(error.failed)       # memory://ds/sub-02/func/sub-02_task-rest_bold.json
    print(error.not_written)  # the failed file, then every file after it
    print(repr(error.__cause__))
    # CommitError(13, "could not commit the staged version of
    # 'memory://ds/sub-02/func/sub-02_task-rest_bold.json' ([Errno 13] ...")
```

`written` holds the files that were replaced, in order, and `not_written` holds
the failed file and every file after it. Because the order is the order in which
the transaction first used each file, the outcome is always a prefix of a known
sequence: a file you touched later is never written ahead of one you touched
earlier. The store's own error is available as `error.__cause__`, and
`error.errno` carries its error number. With the report in hand, you can fix the
cause and run the edits again; edits that were already applied are simply set to
the same values.

If the commit is interrupted by something that is not an error, such as
`KeyboardInterrupt`, that exception propagates as itself. It carries a note,
shown in the traceback, that lists the files written and the files not written.

Outside a transaction there is no report to give. A write that the store
refuses raises its own error directly, a `CommitError` from bagof-paths, and
leaves the old file in place.

## Editing a table

A TSV file behaves as a mapping from column names to lists of values. Assigning
to a name adds the column, or replaces it if it exists, and `del` removes one.
Give one value per row, as a list.

```pycon
>>> table = ds["participants.tsv"]
>>> table["handedness"] = ["R", "L", "R"]
>>> table.as_dict()["handedness"]
['R', 'L', 'R']
>>> ds["participants.tsv"].read_text()
'participant_id\tage\tsex\thandedness\nsub-01\t30\tF\tR\nsub-02\tn/a\tM\tL\nsub-03\t1.50\tF\tR\n'
```

Look at the text that was written. The `age` column was not part of the edit, and
its cells are byte for byte what they were: the `1.50` of `sub-03` was not
rewritten as `1.5`. This is the round-trip guarantee. A cell you did not change
keeps its exact text, and only a changed or new cell is written from its value.
Reading a table and writing it back therefore never reformats the data you did
not touch.

A cell you do change is written from its Python value. `None` becomes `n/a`, a
`bool` becomes `true` or `false`, and a `float` is written in its shortest form.

```pycon
>>> table["age"] = [31, None, 1.5]
>>> ds["participants.tsv"].read_text().splitlines()[1:]
['sub-01\t31\tF\tR', 'sub-02\tn/a\tM\tL', 'sub-03\t1.50\tF\tR']
```

Here `1.5` equals the value that was already in the cell, so the cell kept its
text `1.50`, while `31` replaced `30`. The comparison is made on the value, not
on the text, and an unchanged value never causes a rewrite.

Inside a `with` block, a column is the transaction's own, so a single cell can
be set in place. The other cells keep their text in the same way.

```pycon
>>> with ds:
...     table["sex"][2] = "M"
>>> ds["participants.tsv"].read_text().splitlines()[3]
'sub-03\t1.50\tM\tR'
```

brainfilter refuses a column that cannot be what you meant, and says why.

```pycon
>>> table["site"] = "A"
Traceback (most recent call last):
  ...
TypeError: the values of column 'site' cannot be a str: give one value per row, as a list (a string is not split into its characters); to give every row the same value, repeat it: [value] * number_of_rows
>>> table["site"] = ["A", "A"]
Traceback (most recent call last):
  ...
ValueError: column 'site' is given 2 values, but the table has 3 rows: give one value per row
>>> table["site"] = ["A"] * 3
>>> del table["handedness"]
>>> table.keys()
['participant_id', 'age', 'sex', 'site']
```

Adding a row is a whole-file write, since a row is not addressable by name. Read
the rows, extend the list, and write it back. The cells that were already there
keep their text here as well.

```pycon
>>> rows = table.as_list()
>>> table.write([*rows, {"participant_id": "sub-04", "age": 28, "sex": "F", "site": "B"}])
>>> table.as_dict()["participant_id"]
['sub-01', 'sub-02', 'sub-03', 'sub-04']
```

Column edits belong in a transaction as well when they go together with other
files. A new column that matches a change in a sidecar, say, should appear in
both places or in neither.

## Writing to a sidecar

A data file does not carry its metadata itself. The metadata lives in JSON
sidecars, and under the BIDS inheritance principle a file may be described by
several of them, from the most specific to the most general. The `sidecars`
property lists the ones that apply, nearest first, and `sidecar` presents them
as one merged mapping. Reading from it gives the nearest value. Writing to it
changes the nearest sidecar, the one closest to the data file.

```pycon
>>> run = ds["sub-01"]["func"]["sub-01_task-rest_bold.nii.gz"]
>>> [str(s) for s in run.sidecars]
['memory://ds/sub-01/func/sub-01_task-rest_bold.json']
>>> run.sidecar["FlipAngle"] = 90
>>> ds["sub-01"]["func"]["sub-01_task-rest_bold.json"].as_dict()
{'RepetitionTime': 2.0, 'TaskName': 'rest', 'EchoTime': 0.03, 'Extra': {'Coil': 'neck'}, 'FlipAngle': 90}
```

The value went into the file next to the image, and not into a file higher up
that would have changed every run beneath it. If you intend the change to apply
more widely, write to the more general sidecar directly instead.

A file that no sidecar applies to has an empty `sidecar`, and there is no file to
receive the write. brainfilter refuses, and tells you how to create the sidecar.

```pycon
>>> t1w = ds["sub-01"]["anat"]["sub-01_T1w.nii.gz"]
>>> t1w.sidecars
()
>>> t1w.sidecar["EchoTime"] = 0.002
Traceback (most recent call last):
  ...
TypeError: cannot write the sidecar of 'memory://ds/sub-01/anat/sub-01_T1w.nii.gz': no JSON sidecar applies to it, so there is no file to write it to; create one first, e.g. `(path.parent / 'sub-01_T1w.json').write({...})`
```

Following that advice creates the missing sidecar. From then on, `sidecar`
finds it.

```pycon
>>> (t1w.parent / "sub-01_T1w.json").write({"EchoTime": 0.002})
>>> t1w.sidecar["FlipAngle"] = 9
>>> t1w.sidecar.as_dict()
{'EchoTime': 0.002, 'FlipAngle': 9}
```

Inside a transaction, a read of `sidecar` also sees the edits that have been
made in the block, including a sidecar that has not been written yet.

## Where to go next

The [concepts page on modes and transactions](../concepts/modes-and-transactions.md)
explains how the mode travels with a path, which operations a read-only path
refuses, and what the atomicity guarantees do and do not cover, in particular
across processes. If your dataset lives in a bucket and you have many files to
edit, [Async access](async.md) shows the same edits with coroutines. The
reference for the classes used here is under [`BidsPath`](../api/paths.md#brainfilter.BidsPath),
[`Transaction`](../api/transactions.md#brainfilter.Transaction) and
[`TransactionError`](../api/transactions.md#brainfilter.TransactionError).
