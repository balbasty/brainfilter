# Installation

brainfilter is a pure-Python package that runs on Python 3.10 or later. Its
only required dependency is [bagof-paths](https://github.com/bagofseeds/bagof-paths),
which supplies the uniform path interface that brainfilter builds on, and
which `pip` installs automatically.

## Install from PyPI

```bash
pip install brainfilter
```

This is enough to read, filter and edit datasets on local disk. Reading a
table as a pandas `DataFrame` with `as_dataframe()` needs
[pandas](https://pandas.pydata.org), which is not installed by default.

## Install from source

```bash
pip install git+https://github.com/balbasty/brainfilter
```

To work on the library itself, clone the repository and install it in
editable mode with the test dependencies:

```bash
git clone https://github.com/balbasty/brainfilter
cd brainfilter
pip install -e ".[test]"
pytest
```

The `test` extra brings in `pytest`, `anyio`, `pandas` and
`universal-pathlib`, which provides the in-memory store that the tests run
against.

## Remote backends

A path such as `s3://openneuro.org/ds000001` or
`https://example.org/data/ds000001` is a perfectly good argument to
[`BidsPath`][brainfilter.BidsPath] without any further installation. It can be
split into parts, renamed, and parsed into entities, because those operations
only look at the text. Reading from it is a different matter. Listing a
folder or opening a file needs a library that knows how to talk to the store,
and brainfilter does not ship one.

Without such a library, the first read fails and says what is missing:

```pycon
>>> from brainfilter import BidsPath
>>> BidsPath("s3://openneuro.org/ds000001").keys()
Traceback (most recent call last):
  ...
bagof.paths._errors.UnsupportedPathOperation: 'iterdir' is not supported: no backend is installed to perform I/O on 's3://'; install universal-pathlib or cloudpathlib, or pass driver= a path class
```

Two libraries can fill that role, and brainfilter uses whichever it finds.

[universal-pathlib](https://universal-pathlib.readthedocs.io) (imported as
`upath`) is built on [fsspec](https://filesystem-spec.readthedocs.io) and
reaches any store that fsspec supports. It is the first choice when both are
installed. It does not include the code for any particular store: each one
comes from its own fsspec package, which you install next to it.

[cloudpathlib](https://cloudpathlib.drivendata.org) offers a path class per
cloud provider, built on the provider's own SDK. brainfilter uses it for a
scheme that universal-pathlib does not recognise, or when you ask for it
explicitly.

For most people the first option is the better one, and the packages to
install depend on where the data lives.

=== "S3"

    ```bash
    pip install universal-pathlib s3fs
    ```

    This covers `s3://` URLs, such as the public
    [OpenNeuro](https://openneuro.org) bucket. cloudpathlib's equivalent is
    `pip install "cloudpathlib[s3]"`.

=== "Google Cloud Storage"

    ```bash
    pip install universal-pathlib gcsfs
    ```

    This covers `gs://` URLs. cloudpathlib's equivalent is
    `pip install "cloudpathlib[gs]"`.

=== "HTTP and HTTPS"

    ```bash
    pip install universal-pathlib aiohttp
    ```

    This covers `http://` and `https://` URLs. A web server can serve a file
    to anyone who has its URL, but it rarely lets a client list a folder, so
    an HTTP dataset is practical when you know the names of the files you
    want, and not when you want to discover them.

Other stores follow the same pattern. A URL scheme is matched by an fsspec
package (`adlfs` for Azure, `sshfs` for SFTP, and so on) and the
[fsspec documentation](https://filesystem-spec.readthedocs.io/en/latest/api.html#built-in-implementations)
lists them. Credentials are not part of the installation; they are passed
when the path is built, as the
[remote filtering tutorial](../tutorials/filter-remote.md) shows. The
[Paths and backends](../concepts/paths-and-backends.md) page explains how a
backend is chosen.

## Check the installation

```python
import brainfilter

print(brainfilter.__version__)
```

A quick way to confirm that a remote backend works is to list a public
dataset. The call below needs network access and the S3 packages installed
above.

```python
from brainfilter import BidsPath

ds = BidsPath("s3://openneuro.org/ds000001", storage_options={"anon": True})
print(ds["dataset_description.json"]["Name"])
```

```text
Balloon Analog Risk-taking Task
```
