"""Build, read and filter BIDS trees on any storage backend.

The public API is importable from here:

```python
from brainfilter import AsyncBidsPath, BidsPath, Filter, PureBidsPath
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
from brainfilter.conditions import Glob, Regex
from brainfilter.filter import Filter
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
    "Filter",
    "Glob",
    "PureBidsPath",
    "ReadOnlyError",
    "Regex",
    "Table",
    "Transaction",
    "TransactionError",
    "Version",
    "__version__",
]
