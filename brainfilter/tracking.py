"""
Containers and objects that track their parents.
"""
from functools import wraps
from typing import Any, Iterable, Iterator, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pandas import DataFrame, Series

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import numpy as np
    from pandas import DataFrame, Series  # noqa: F811
except ImportError:
    np = None


TRACKED_TYPES = {}


def tracks(cls: type) -> type:
    """Decorator to register a tracked type for a native type."""

    def decorator(tracked_cls: type) -> type:
        TRACKED_TYPES[cls] = tracked_cls
        return tracked_cls

    return decorator


def trackedtype(name: str, *bases: type) -> type:
    """Create a tracked type for the given native type(s)."""
    if len(bases) == 1:
        bases = (TrackedMixin, *bases)
    decorator = tracks(bases[-1])
    tracked_type = type(name, bases, {})
    return decorator(tracked_type)


def track(obj: Any, parent: Any) -> Any:
    """Wrap an object in a tracked type if applicable."""
    if getattr(obj, "_parent", None) is parent:
        return obj

    if isinstance(obj, TrackedMixin):
        obj = type(obj)(obj)
        obj._parent = parent
        return obj

    native_type = type(obj)
    if type(obj) in TRACKED_TYPES:
        tracked_type = TRACKED_TYPES[native_type]
        obj = tracked_type(obj)
        obj._parent = parent
        return obj

    for native_type, tracked_type in TRACKED_TYPES.items():
        if isinstance(obj, native_type):
            obj = tracked_type(obj)
            obj._parent = parent
            return obj

    return obj


class TrackedLeaf:
    """
    Leaf object that has no parent but know what to do when its tracked
    children change.
    """

    def _changed(self, child: Optional["TrackedMixin"] = None) -> None:
        """Called when a tracked child object changes."""
        return NotImplemented


class TrackedMixin:
    """Mixin class for tracked objects."""

    def __init__(self, *args, **kwargs) -> None:
        parent = None
        if len(args) == 1:
            parent = getattr(args[0], "_parent", None)
        try:
            super().__init__(*args, **kwargs)
        except TypeError:
            # Some builtin types (int, float, ...) defer to
            # object.__init__, which does not accept any arguments.
            super().__init__()
        self._parent = parent

    @property
    def parent(self) -> object | None:
        return self._parent

    @parent.setter
    def parent(self, parent: object | None) -> None:
        self._parent = parent

    @property
    def parents(self) -> Iterator[object]:
        if self.parent is None:
            return
        yield self.parent
        if hasattr(self.parent, "parents"):
            yield from self.parent.parents

    def _changed(self) -> None:
        if isinstance(self._parent, TrackedLeaf):
            self._parent._changed(child=self)
        elif isinstance(self._parent, TrackedMixin):
            self._parent._changed()

    @property
    def leaf(self) -> TrackedLeaf | None:
        for ancestor in self.parents:
            if isinstance(ancestor, TrackedLeaf):
                return ancestor
        return None

    def copy(self) -> "TrackedMixin":
        """Return a shallow copy of the tracked object."""
        obj = type(self)(self)
        obj._parent = self._parent
        return obj

    def detach_(self) -> None:
        """Detach the tracked object from its parent in place."""
        self._parent = None

    def detach(self) -> "TrackedMixin":
        """Return a detached copy of the tracked object."""
        obj = self.copy()
        obj._parent = None
        return obj


@tracks(dict)
class TrackedDict(TrackedMixin, dict):
    """A dictionary that tracks its parent object."""

    def __init__(self, *args, **kwargs) -> None:
        if len(args) > 1:
            raise TypeError(
                f"TrackedDict expected at most 1 positional argument, "
                f"got {len(args)}."
            )
        parent = None
        if args:
            parent = getattr(args[0], "_parent", None)
            if isinstance(args[0], dict):
                args = ({
                    key: track(value, self)
                    for key, value in args[0].items()
                },)
            else:
                args = ((
                    (key, track(value, self))
                    for key, value in args[0]
                ),)
        kwargs = {
            key: track(value, self)
            for key, value in kwargs.items()
        }
        super().__init__(*args, **kwargs)
        self._parent = parent

    @wraps(dict.__setitem__)
    def __setitem__(self, key: Any, value: Any) -> None:
        value = track(value, self)
        super().__setitem__(key, value)
        self._changed()

    @wraps(dict.update)
    def update(self, *args, **kwargs) -> None:
        if args:
            if len(args) > 1:
                raise TypeError(
                    f"TrackedDict update expected at most 1 positional "
                    f"argument, got {len(args)}."
                )
            args = (((k, track(v, self)) for k, v in args[0].items()),)
        kwargs = {k: track(v, self) for k, v in kwargs.items()}
        super().update(*args, **kwargs)
        self._changed()

    @wraps(dict.setdefault)
    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key not in self:
            default = track(default, self)
            super().setdefault(key, default)
            self._changed()
            return default
        return self[key]

    @wraps(dict.clear)
    def clear(self) -> None:
        super().clear()
        self._changed()

    def __truediv__(self, other: Any) -> "TrackedDict":
        # PathLike API
        return self[other]


@tracks(list)
class TrackedList(TrackedMixin, list):
    """A list that tracks its parent object."""

    def __init__(self, *args, **kwargs) -> None:
        if len(args) > 1:
            raise TypeError(
                f"TrackedList expected at most 1 positional argument, "
                f"got {len(args)}."
            )
        parent = None
        if args:
            parent = getattr(args[0], "_parent", None)
            args = ((track(v, self) for v in args[0]),)
        super().__init__(*args, **kwargs)
        self._parent = parent

    @wraps(list.__setitem__)
    def __setitem__(self, index: int | slice, value: Any) -> None:
        if isinstance(index, slice):
            value = [track(v, self) for v in value]
        else:
            value = track(value, self)
        super().__setitem__(index, value)
        self._changed()

    @wraps(list.append)
    def append(self, value: Any) -> None:
        value = track(value, self)
        super().append(value)
        self._changed()

    @wraps(list.extend)
    def extend(self, values: Iterable[Any]) -> None:
        values = [track(v, self) for v in values]
        super().extend(values)
        self._changed()

    @wraps(list.insert)
    def insert(self, index: int, value: Any) -> None:
        value = track(value, self)
        super().insert(index, value)
        self._changed()

    @wraps(list.remove)
    def remove(self, value: Any) -> None:
        super().remove(value)
        self._changed()

    @wraps(list.reverse)
    def reverse(self) -> None:
        super().reverse()
        self._changed()

    @wraps(list.sort)
    def sort(self, *args, **kwargs) -> None:
        super().sort(*args, **kwargs)
        self._changed()

    @wraps(list.clear)
    def clear(self) -> None:
        super().clear()
        self._changed()

    @wraps(list.__add__)
    def __add__(self, other: Iterable[Any]) -> "TrackedList":
        return type(self)(super().__add__(other))

    def __radd__(self, other: Iterable[Any]) -> "TrackedList":
        return type(self)(super().__radd__(other))

    @wraps(list.__mul__)
    def __mul__(self, other: int) -> "TrackedList":
        return type(self)(super().__mul__(other))

    @wraps(list.__rmul__)
    def __rmul__(self, other: int) -> "TrackedList":
        return type(self)(super().__mul__(other))


@tracks(set)
class TrackedSet(TrackedMixin, set):
    """A set that tracks its parent object."""

    def __init__(self, *args, **kwargs) -> None:
        if len(args) > 1:
            raise TypeError(
                f"TrackedSet expected at most 1 positional argument, "
                f"got {len(args)}."
            )
        parent = None
        if args:
            parent = getattr(args[0], "_parent", None)
            args = ((track(v, self) for v in args[0]),)
        super().__init__(*args, **kwargs)
        self._parent = parent

    @wraps(set.add)
    def add(self, value: Any) -> None:
        value = track(value, self)
        super().add(value)
        self._changed()

    @wraps(set.update)
    def update(self, values: Iterable[Any]) -> None:
        values = [track(v, self) for v in values]
        super().update(values)
        self._changed()

    @wraps(set.discard)
    def discard(self, value: Any) -> None:
        super().discard(value)
        self._changed()

    @wraps(set.intersection_update)
    def intersection_update(self, *s) -> None:
        super().intersection_update(*s)
        self._changed()

    @wraps(set.symmetric_difference_update)
    def symmetric_difference_update(self, s) -> None:
        super().symmetric_difference_update(s)
        self._changed()

    @wraps(set.remove)
    def remove(self, value: Any) -> None:
        super().remove(value)
        self._changed()

    @wraps(set.clear)
    def clear(self) -> None:
        super().clear()
        self._changed()

    @wraps(set.__or__)
    def __or__(self, other: Iterable[Any]) -> "TrackedSet":
        return type(self)(super().__or__(other))

    @wraps(set.__ror__)
    def __ror__(self, value):
        return type(self)(super().__ror__(value))

    @wraps(set.__and__)
    def __and__(self, other: Iterable[Any]) -> "TrackedSet":
        return type(self)(super().__and__(other))

    @wraps(set.__rand__)
    def __rand__(self, other: Iterable[Any]) -> "TrackedSet":
        return type(self)(super().__rand__(other))


@tracks(tuple)
class TrackedTuple(TrackedMixin, tuple):

    def __init__(self, *args, **kwargs):
        if len(args) > 1:
            raise TypeError(
                f"TrackedTuple expected at most 1 positional argument, "
                f"got {len(args)}."
            )
        parent = None
        if args:
            parent = getattr(args[0], "_parent", None)
            args = ((track(v, self) for v in args[0]),)
        super().__init__(*args, **kwargs)
        self._parent = parent


trackedtype("TrackedInt", int)
trackedtype("TrackedFloat", float)
trackedtype("TrackedComplex", complex)
# NOTE: `bool` is not subclassable and therefore cannot be tracked.


@tracks(bytes)
class TrackedBytes(TrackedMixin, bytes):
    """A bytes object that tracks its parent object."""

    @wraps(bytes.__getitem__)
    def __getitem__(self, index: slice | int) -> Any:
        item = super().__getitem__(index)
        return track(item, self)


@tracks(str)
class TrackedStr(TrackedMixin, str):
    """A string that tracks its parent object."""

    @wraps(str.__getitem__)
    def __getitem__(self, index: slice | int) -> Any:
        item = super().__getitem__(index)
        return track(item, self)


if np:

    @tracks(np.ndarray)
    class TrackedNDArray(TrackedMixin, np.ndarray):
        """A NumPy ndarray that tracks its parent object."""

        @wraps(np.ndarray.__getitem__)
        def __getitem__(self, index: Any) -> Any:
            item = super().__getitem__(index)
            return track(item, self)

        @wraps(np.ndarray.__setitem__)
        def __setitem__(self, index: Any, value: Any) -> None:
            super().__setitem__(index, value)
            self._changed()

        @wraps(np.ndarray.byteswap)
        def byteswap(self, inplace: bool = False) -> "TrackedNDArray":
            value = super().byteswap(inplace=inplace)
            if inplace:
                value = track(value, self)
            return value

        @wraps(np.ndarray.fill)
        def fill(self, value: Any) -> None:
            super().fill(value)
            self._changed()

        @wraps(np.ndarray.put)
        def put(self, indices: Any, values: Any, mode: str = 'raise') -> None:
            super().put(indices, values, mode=mode)
            self._changed()

        @wraps(np.ndarray.setfield)
        def setfield(self, field: str, value: Any, offset: int = 0) -> None:
            super().setfield(field, value, offset=offset)
            self._changed()

        @wraps(np.ndarray.sort)
        def sort(self, *args, **kwargs) -> None:
            super().sort(*args, **kwargs)
            self._changed()

        @wraps(np.ndarray.reshape)
        def reshape(self, *args, **kwargs) -> "TrackedNDArray":
            reshaped = super().reshape(*args, **kwargs)
            if np.shares_memory(reshaped, self):
                reshaped = track(reshaped, self)
            return reshaped

        @wraps(np.ndarray.swapaxes)
        def swapaxes(self, axis1, axis2):
            return track(super().swapaxes(axis1, axis2), self)

        @wraps(np.ndarray.transpose)
        def transpose(self, *axes):
            return track(super().transpose(*axes), self)

        @wraps(np.ndarray.view)
        def view(self, *args, **kwargs) -> "TrackedNDArray":
            viewed = super().view(*args, **kwargs)
            if np.shares_memory(viewed, self):
                viewed = track(viewed, self)
            return viewed

    @tracks(np.bytes_)
    class TrackedNpBytes(TrackedMixin, np.bytes_):
        """A np.bytes_ object that tracks its parent object."""

        def __getitem__(self, index: slice | int) -> Any:
            item = super().__getitem__(index)
            return track(item, self)

    tracks(np.bool_)(type("TrackedNpBool", (TrackedMixin, np.bool_), {}))
    tracks(np.int8)(type("TrackedNpI1", (TrackedMixin, np.int8), {}))
    tracks(np.int16)(type("TrackedNpI2", (TrackedMixin, np.int16), {}))
    tracks(np.int32)(type("TrackedNpI4", (TrackedMixin, np.int32), {}))
    tracks(np.int64)(type("TrackedNpI8", (TrackedMixin, np.int64), {}))
    tracks(np.uint8)(type("TrackedNpU1", (TrackedMixin, np.uint8), {}))
    tracks(np.uint16)(type("TrackedNpU2", (TrackedMixin, np.uint16), {}))
    tracks(np.uint32)(type("TrackedNpU4", (TrackedMixin, np.uint32), {}))
    tracks(np.uint64)(type("TrackedNpU8", (TrackedMixin, np.uint64), {}))
    tracks(np.float16)(type("TrackedNpF2", (TrackedMixin, np.float16), {}))
    tracks(np.float32)(type("TrackedNpF4", (TrackedMixin, np.float32), {}))
    tracks(np.float64)(type("TrackedNpF8", (TrackedMixin, np.float64), {}))
    tracks(np.complex64)(type("TrackedNpC8", (TrackedMixin, np.complex64), {}))
    tracks(np.complex128)(type("TrackedNpC16", (TrackedMixin, np.complex128), {}))  # noqa: E501


if pd:

    from pandas.core.generic import NDFrame

    class TrackedNDFrame:

        # @wraps(NDFrame.__getitem__)
        def __getitem__(self, index: slice | int) -> Any:
            item = super().__getitem__(index)
            return track(item, self)

        # @wraps(NDFrame.__setitem__)
        def __setitem__(self, key: Any, value: Any) -> None:
            super().__setitem__(key, value)
            self._changed()

        @wraps(NDFrame.bfill)
        def bfill(self, *args, **kwargs) -> "TrackedNDFrame":
            filled = super().bfill(*args, **kwargs)
            if kwargs.get('inplace', False):
                filled = track(filled, self)
            return filled

        @wraps(NDFrame.clip)
        def clip(self, *args, **kwargs) -> "TrackedNDFrame":
            clipped = super().clip(*args, **kwargs)
            if kwargs.get('inplace', False):
                clipped = track(clipped, self)
            return clipped

        @wraps(NDFrame.drop)
        def drop(self, *args, **kwargs) -> "TrackedDataFrame":
            dropped = super().drop(*args, **kwargs)
            if kwargs.get('inplace', False):
                dropped = track(dropped, self)
            return dropped

        # @wraps(OpsMixin.drop_duplicates)
        def drop_duplicates(self, *args, **kwargs) -> "TrackedNDFrame":
            deduped = super().drop_duplicates(*args, **kwargs)
            if kwargs.get('inplace', False):
                deduped = track(deduped, self)
            return deduped

        # @wraps(NDFrame.dropna)
        def dropna(self, *args, **kwargs) -> "TrackedNDFrame":
            dropped = super().dropna(*args, **kwargs)
            if kwargs.get('inplace', False):
                dropped = track(dropped, self)
            return dropped

        @wraps(NDFrame.ffill)
        def ffill(self, *args, **kwargs) -> "TrackedNDFrame":
            filled = super().ffill(*args, **kwargs)
            if kwargs.get('inplace', False):
                filled = track(filled, self)
            return filled

        @wraps(NDFrame.fillna)
        def fillna(self, *args, **kwargs) -> "TrackedNDFrame":
            filled = super().fillna(*args, **kwargs)
            if kwargs.get('inplace', False):
                filled = track(filled, self)
            return filled

        @wraps(NDFrame.items)
        def items(self) -> Iterator[tuple[Any, Any]]:
            for key, value in super().items():
                yield key, track(value, self)

        @wraps(NDFrame.values)
        def values(self) -> Iterator[Any]:
            for value in super().values():
                yield track(value, self)

        # @wraps(NDFrame.update)
        def update(self, other: Series | dict | Iterable[tuple]) -> None:
            super().update(other)
            self._changed()

        # @wraps(NDFrame.rename)
        def rename(self, *args, **kwargs) -> "TrackedNDFrame":
            renamed = super().rename(*args, **kwargs)
            if kwargs.get('inplace', False):
                renamed = track(renamed, self)
            return renamed

        @wraps(NDFrame.rename_axis)
        def rename_axis(self, *args, **kwargs) -> "TrackedNDFrame":
            renamed = super().rename_axis(*args, **kwargs)
            if kwargs.get('inplace', False):
                renamed = track(renamed, self)
            return renamed

        @wraps(NDFrame.replace)
        def replace(self, *args, **kwargs) -> "TrackedNDFrame":
            replaced = super().replace(*args, **kwargs)
            if kwargs.get('inplace', False):
                replaced = track(replaced, self)
            return replaced

        @wraps(NDFrame.sort_index)
        def sort_index(self, *args, **kwargs) -> "TrackedNDFrame":
            sorteddf = super().sort_index(*args, **kwargs)
            if kwargs.get('inplace', False):
                sorteddf = track(sorteddf, self)
            return sorteddf

        @wraps(NDFrame.sort_values)
        def sort_values(self, *args, **kwargs) -> "TrackedNDFrame":
            sortedser = super().sort_values(*args, **kwargs)
            if kwargs.get('inplace', False):
                sortedser = track(sortedser, self)
            return sortedser

    @tracks(pd.DataFrame)
    class TrackedDataFrame(TrackedNDFrame, pd.DataFrame):
        """A pandas DataFrame that tracks its parent object."""

        @property
        @wraps(pd.DataFrame.at)
        def at(self) -> Any:
            return track(super().at, self)

        @property
        @wraps(pd.DataFrame.iat)
        def iat(self) -> Any:
            return track(super().iat, self)

        @property
        @wraps(pd.DataFrame.loc)
        def loc(self) -> Any:
            return track(super().loc, self)

        @property
        @wraps(pd.DataFrame.iloc)
        def iloc(self) -> Any:
            return track(super().iloc, self)

        @wraps(pd.DataFrame.insert)
        def insert(self, *args, **kwargs) -> None:
            super().insert(*args, **kwargs)
            self._changed()

        @wraps(pd.DataFrame.isetitem)
        def isetitem(self, loc, value) -> None:
            super().isetitem(loc, value)
            self._changed()

        @wraps(pd.DataFrame.iterrows)
        def iterrows(self) -> Iterator[tuple[Any, Any]]:
            for index, row in super().iterrows():
                yield index, track(row, self)

        @wraps(pd.DataFrame.set_index)
        def set_index(self, *args, **kwargs) -> "TrackedDataFrame":
            setindexed = super().set_index(*args, **kwargs)
            if kwargs.get('inplace', False):
                setindexed = track(setindexed, self)
            return setindexed

        @wraps(pd.DataFrame.transpose)
        def transpose(self, *args, copy: bool = False) -> "TrackedDataFrame":
            transposed = super().transpose(*args, copy=copy)
            if not copy:
                transposed = track(transposed, self)
            return transposed

        def update(self, other: DataFrame | dict | Iterable[tuple]) -> None:
            super().update(other)
            self._changed()

    @tracks(pd.Series)
    class TrackedSeries(TrackedMixin, pd.Series):
        """A pandas Series that tracks its parent object."""

        @property
        def array(self, *args, **kwargs) -> TrackedNDArray:
            array = super().array(*args, **kwargs)
            return track(array, self)
