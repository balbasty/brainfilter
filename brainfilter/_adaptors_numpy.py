# stdlib
import typing as t

# internals
from ._adaptors_base import HintAdaptor, register_adaptor

# optionals
try:
    import numpy as np
    ndarray = np.ndarray
except ImportError:
    np = None

try:
    import pandas as pd
    DataFrame, Series = pd.DataFrame, pd.Series
except ImportError:
    pd = None

if t.TYPE_CHECKING:
    from numpy import ndarray
    from pandas import DataFrame, Series


if np:

    @register_adaptor(np.ndarray)
    class NumpyArrayAdaptor(HintAdaptor):
        """An adaptor for numpy arrays."""

        MaxType = np.ndarray

        def __init__(self, hint: t.Any = np.ndarray) -> None:
            super().__init__(hint)

        def __call__(self, value: t.Any) -> ndarray:  # type: ignore
            value = np.asanyarray(value)
            return value

if pd:

    @register_adaptor(pd.DataFrame)
    class DataFrameAdaptor(HintAdaptor):
        """An adaptor for pandas DataFrames."""

        MaxType = pd.DataFrame

        def __init__(self, hint: t.Any = pd.DataFrame) -> None:
            super().__init__(hint)

        def __call__(self, value: t.Any) -> DataFrame:  # type: ignore
            if not isinstance(value, pd.DataFrame):
                value = pd.DataFrame(value)
            return value

    @register_adaptor(pd.Series)
    class SeriesAdaptor(HintAdaptor):
        """An adaptor for pandas Series."""

        MaxType = pd.Series

        def __init__(self, hint: t.Any = pd.Series) -> None:
            super().__init__(hint)

        def __call__(self, value: t.Any) -> Series:  # type: ignore
            if not isinstance(value, pd.Series):
                value = pd.Series(value)
            return value
