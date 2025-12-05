# stdlib
import collections as c
import contextlib
import typing as t
import re
from collections import abc
from sys import version_info

# optionals
try:
    import typing_extensions as tx
except ImportError:
    tx = None


_DEPRECATEDMAP = {
    # --- builtins ---
    "List": list,
    "Dict": dict,
    "Set": set,
    "FrozenSet": frozenset,
    "Tuple": tuple,
    "Type": type,
    # --- collections ---
    "DefaultDict": c.defaultdict,
    "OrderedDict": c.OrderedDict,
    "ChainMap": c.ChainMap,
    "Counter": c.Counter,
    "Deque": c.deque,
    # --- other ---
    "Pattern": re.Pattern,
    "Match": re.Match,
    "AbstractSet": abc.Set,
    # --- abc containers ---
    "ByteString": abc.ByteString,
    "Collection": abc.Collection,
    "Container": abc.Container,
    "ItemsView": abc.ItemsView,
    "KeysView": abc.KeysView,
    "Mapping": abc.Mapping,
    "MutableMapping": abc.MutableMapping,
    "MutableSequence": abc.MutableSequence,
    "MutableSet": abc.MutableSet,
    "Sequence": abc.Sequence,
    "ValuesView": abc.ValuesView,
    # --- abc async ---
    "Coroutine": abc.Coroutine,
    "AsyncGenerator": abc.AsyncGenerator,
    "AsyncIterable": abc.AsyncIterable,
    "AsyncIterator": abc.AsyncIterator,
    "Awaitable": abc.Awaitable,
    # --- abc others ---
    "Iterable": abc.Iterable,
    "Iterator": abc.Iterator,
    "Callable": abc.Callable,
    "Generator": abc.Generator,
    "Hashable": abc.Hashable,
    "Reversible": abc.Reversible,
    "Sized": abc.Sized,
    # --- abc contextlib ---
    "ContextManager": contextlib.AbstractContextManager,
    "AsyncContextManager": contextlib.AbstractAsyncContextManager,
}


class _T:
    # Helper to get typing attributes with fallback to typing_extensions

    def __getattr__(self, name: str) -> t.Any:
        if version_info >= (3, 9) and name in _DEPRECATEDMAP:
            return _DEPRECATEDMAP[name]
        return getattr(t, name, getattr(tx, name))


class _TT:
    # Helper to get typing and typing_extensions attributes

    def __getattr__(self, name: str) -> t.Tuple:
        versions = []
        if name in _DEPRECATEDMAP:
            versions.append(_DEPRECATEDMAP[name])
        if hasattr(t, name):
            versions.append(getattr(t, name))
        if hasattr(tx, name):
            versions.append(getattr(tx, name))
        return tuple(versions)


_t = _T()       # Most up-to-date hint (builtin -> typing -> typing_extensions)
_tt = _TT()     # All versions of a hint (builtin, typing, typing_extensions)


def _issubclass(cls: t.Any, base: t.Any) -> bool:
    # Robust version of issubclass
    if not isinstance(cls, type) or not isinstance(base, type):
        return False
    cls = _get_origin(cls, unfold_annotated=True)
    base = _get_origin(base, unfold_annotated=True)
    return issubclass(cls, base)


def _get_origin(hint: t.Any, unfold_annotated: bool = False) -> t.Any:
    # Robust version of get_origin
    if unfold_annotated:
        hint = _unfold_annotated(hint)
    return t.get_origin(hint) or hint


def _unfold_annotated(hint: t.Any) -> t.Any:
    # Unfold Annotated hints
    origin = _get_origin(hint) or hint
    if origin in _tt.Annotated:
        args = t.get_args(hint)
        if args:
            return _unfold_annotated(args[0])
    return hint
