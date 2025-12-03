"""
Hierarchy of dictionaries.

- Reads are taken from all dictionaries in the hierarchy.
- Writes are made to the inner-most dictionary only.

This behaviour is required to implement BIDS inheritance.
"""
from collections.abc import MutableMapping
from typing import Any

from brainfilter.tracking import track, tracks, TrackedLeaf, TrackedMixin


def trackback(obj: Any, leaf: TrackedLeaf) -> Any:
    """Track an object back to its parent leaf."""
    obj = ParentDict(obj)
    obj._leaf = leaf
    return obj


class ParentDict(dict):
    """A dictionary that is inherited by a leaf dictionary."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._leaf = None

    def __getitem__(self, key: str) -> Any:
        future = FutureKeyValue(key, super().__getitem__(key))
        future._parent = self._leaf
        return future.value


class FutureKeyValue(TrackedMixin):
    """
    A (key, value) pair that keeps a reference to a parent dictionary,
    and whose value is tracked.

    When the value emits a change, the parent dictionary is updated.
    """

    def __init__(self, key: str, value: Any) -> None:
        super().__init__()
        self.key = key
        self.value = track(value, self)

    def _changed(self) -> None:
        self._parent[self.key] = self.value
        super()._changed()


class HDict(MutableMapping):
    """A hierarchical dictionary.

    The first dictionary is the leaf dictionary, where writes are made.
    The remaining dictionaries are inherited dictionaries, where reads are
    made.
    """

    def __init__(self, *dicts) -> None:
        """
        Parameters
        ----------
        leaf : dict
            The leaf dictionary, where writes are made.
        *inherited : dict
            The inherited dictionaries, where reads are made.
        """
        super().__init__()
        if dicts:
            self._leaf, *self._inherited = dicts
        else:
            self._leaf, self._inherited = {}, []
        self._inherited = [trackback(d, self._leaf) for d in self._inherited]

    def __len__(self) -> int:
        keys = set(self._leaf.keys())
        for d in self._inherited:
            keys.update(d.keys())
        return len(keys)

    def __iter__(self):
        yield from self._leaf.keys()
        keys = set(self._leaf.keys())
        for d in self._inherited:
            for key in d.keys():
                if key not in keys:
                    keys.add(key)
                    yield key

    def __getitem__(self, key: str) -> Any:
        if key in self._leaf:
            return self._leaf[key]
        for d in self._inherited:
            if key in d:
                return d[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: object) -> None:
        self._leaf[key] = value

    def __delitem__(self, key: str) -> None:
        if key in self._leaf:
            del self._leaf[key]
        elif key not in self.keys():
            raise KeyError(key)

    def __str__(self) -> str:
        return str(dict(self))

    def __repr__(self) -> str:
        args = (self._leaf, *self._inherited)
        args = ", ".join(repr(d) for d in args)
        return f"HDict({args})"


@tracks(HDict)
class TrackedHDict(TrackedMixin, HDict):
    """A tracked hierarchical dictionary."""

    def __init__(self, *args, **kwargs):
        if len(args) == 1 and isinstance(args[0], HDict):
            args = (args[0]._leaf, *args[0]._inherited)
            super().__init__()
            self._leaf = args[0]
            self._inherited = args[1:]
            self._parent = getattr(args[0], "_parent", None)
        else:
            super().__init__(*args, **kwargs)
