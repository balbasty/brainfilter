"""Build, read and filter BIDS trees on any storage backend.

The public API is importable from here:

```python
from brainfilter import AsyncBidsPath, BidsPath, BidsFilter, PureBidsPath
```
"""
from brainfilter.bidspath import (
    AsyncBidsPath,
    BidsEntities,
    BidsNameError,
    BidsPath,
    PureBidsPath,
    ReadOnlyError,
    Table,
)
from brainfilter.conditions import Glob, Not, Regex
from brainfilter.filter import BidsFilter
from brainfilter.transaction import AsyncTransaction, Transaction, TransactionError
from brainfilter.versioning import Version

try:
    from brainfilter._version import __version__
except ImportError:  # running from a source tree that was never built
    __version__ = "0+unknown"

__all__ = [
    "AsyncBidsPath",
    "AsyncTransaction",
    "BidsEntities",
    "BidsNameError",
    "BidsPath",
    "BidsFilter",
    "Glob",
    "Not",
    "PureBidsPath",
    "ReadOnlyError",
    "Regex",
    "Table",
    "Transaction",
    "TransactionError",
    "Version",
    "__version__",
]

# Show exported names as `brainfilter.X` (in reprs and tracebacks), not
# under the private module that defines them.
for _name in __all__:
    _obj = globals()[_name]
    if getattr(_obj, "__module__", "").startswith("brainfilter._"):
        _obj.__module__ = __name__
del _name, _obj
