# stdlib
import types as ts
import typing as t
from abc import ABC
from enum import Enum
from collections import abc
from fractions import Fraction
from inspect import get_annotations
from numbers import Complex, Number, Integral, Real, Rational

# internals
from ._adaptors_base import (
    Adaptor, AdaptorChain, HintAdaptor, register_adaptor,
)
from ._adaptors_utils import (_get_origin, _issubclass, _t, _tt)
from ._validators_base import Validator


# ======================================================================
# Adaptor implementations
# ======================================================================


@register_adaptor(_t.Annotated)
class AnnotatedAdaptor(HintAdaptor):

    def __init__(self, hint: t.Any) -> None:
        if _get_origin(hint) not in _tt.Annotated:
            raise TypeError(f"Expected an Annotated hint, got {hint}")
        super().__init__(hint)

    def __call__(self, value: t.Any) -> t.Any:
        args = t.get_args(self.hint)
        adaptor = Adaptor(args[0])
        extra_adaptors = [
            Adaptor(arg) for arg in args[1:]
            if isinstance(arg, Adaptor) or _get_origin(arg) in _tt.Literal
        ]
        if extra_adaptors:
            adaptor = AdaptorChain(adaptor, *extra_adaptors)
        return adaptor(value)


@register_adaptor(Validator)
class ValidatorAdaptor(HintAdaptor):
    """An adaptor that uses a Validator."""

    MaxType = Validator

    def __init__(self, hint: t.Union[Validator, t.Type[Validator]]) -> None:
        super().__init__(hint)
        origin = _get_origin(self.hint)
        if isinstance(origin, type) and not _issubclass(origin, self.MaxType):
            raise TypeError(f"Expected a Validator hint, got {self.hint}")
        if not isinstance(origin, type) and not isinstance(hint, self.MaxType):
            raise TypeError(f"Expected a Validator hint, got {self.hint}")

    def __call__(self, value: t.Any) -> t.Any:
        hint = self.hint
        if not isinstance(hint, Validator):
            hint = hint()
        hint(value)
        return value


@register_adaptor(*_tt.Any)
class AnyAdaptor(HintAdaptor):
    """A pass through adaptor."""

    MaxType = t.Any

    def __init__(self, hint: t.Any = t.Any) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> t.Any:
        return value


@register_adaptor(None, type(None))
class NoneAdaptor(HintAdaptor):
    """A pass through adaptor."""

    def __init__(self, hint: None = None) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> None:
        if value is not None:
            raise TypeError(f"Expected None, got {value}")
        return value


@register_adaptor(*_tt.Union, *_tt.Optional, ts.UnionType)
class UnionAdaptor(HintAdaptor):
    """An adaptor for unions."""

    _UnionLike = (*_tt.Union, *_tt.Optional, ts.UnionType)

    def __init__(self, hint: t.Any) -> None:
        super().__init__(hint)
        if _get_origin(self.hint) not in self._UnionLike:
            raise TypeError(f"Expected a Union hint, got {self.hint}")

    def __call__(self, value: t.Any) -> t.Any:
        hints = t.get_args(self.hint)
        if _get_origin(self.hint) in _tt.Optional:
            hints += (None,)
        for hint in hints:
            adaptor = Adaptor(hint)
            try:
                return adaptor(value)
            except Exception:
                continue
        raise TypeError(
            f"Value {value} does not match any type in {self.hint}"
        )


@register_adaptor(*_tt.Literal)
class LiteralAdaptor(HintAdaptor):
    """An adaptor for literals."""

    def __init__(self, hint: t.Any) -> None:
        super().__init__(hint)
        if _get_origin(self.hint) is not _tt.Literal:
            raise TypeError(f"Expected a Literal hint, got {self.hint}")

    def __call__(self, value: t.Any) -> t.Any:
        args = t.get_args(self.hint)
        if value not in args:
            raise TypeError(f"Expected one of {args}, got {value}")
        return value


@register_adaptor(Enum)
class EnumAdaptor(HintAdaptor):
    """An adaptor for Enums."""

    MaxType = Enum

    def __init__(self, hint: t.Any = Enum) -> None:
        super().__init__(hint)
        if not _issubclass(_get_origin(self.hint), self.MaxType):
            raise TypeError(f"Expected an Enum hint, got {self.hint}")

    def __call__(self, value: t.Any) -> Enum:
        cls = _get_origin(self.hint)
        if value in (item.value for item in cls):
            value = cls(value)
        if isinstance(value, str):
            value = cls[value]
        if not isinstance(value, cls):
            raise TypeError(f"Expected an instance of {cls}, got {value}")
        return value


@register_adaptor(*_tt.Type)
class TypeAdaptor(HintAdaptor):
    """An adaptor for types."""
    # (Almost?) equivalent to Any, but does an explicit check

    MaxType = type

    def __init__(self, hint: t.Any = type) -> None:
        super().__init__(hint)
        if _get_origin(self.hint) is not type:
            raise TypeError(f"Expected a type hint, got {self.hint}")

    def __call__(self, value) -> type:
        args = t.get_args(self.hint)
        if not isinstance(value, type):
            raise TypeError(f"Expected a type, got {value}")
        if args and not _issubclass(value, args[0]):
            raise TypeError(f"Expected a subtype of {args[0]}, got {value}")
        return value


class IsInstanceAdaptor(HintAdaptor):
    """An adaptor that checks isinstance."""

    def __init__(self, hint: type | t.Type[t.Any] = t.Any) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> t.Any:
        cls = _get_origin(self.hint)
        if not isinstance(value, cls):
            raise TypeError(f"Expected an instance of {cls}, got {value}")
        return value


@register_adaptor(object)
class ObjectAdaptor(IsInstanceAdaptor):
    """An adaptor for objects."""
    # (Almost?) equivalent to Any, but does an explicit check

    MaxType = object

    def __init__(self, hint: t.Any = object) -> None:
        super().__init__(hint)


# ----------------------------------------------------------------------
# Adaptor implementations: Casts
# ----------------------------------------------------------------------


class CastAdaptor(HintAdaptor):
    """An adaptor that casts to a target type."""

    def __init__(self, hint: type | t.Type[t.Any] = t.Any) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> t.Any:
        cls = _get_origin(self.hint)
        if not isinstance(value, cls):
            value = cls(value)
        return value


@register_adaptor(int, Integral)
class IntAdaptor(CastAdaptor):
    """An adaptor for integers."""

    MaxType = Integral

    def __init__(self, hint: t.Any = int) -> None:
        super().__init__(hint)


@register_adaptor(float, Real, Number)
class FloatAdaptor(CastAdaptor):
    """An adaptor for floats."""

    MaxType = Number

    def __init__(self, hint: t.Any = float) -> None:
        super().__init__(hint)


@register_adaptor(Fraction, Rational)
class FractionAdaptor(CastAdaptor):
    """An adaptor for fractions."""

    MaxType = Rational

    def __init__(self, hint: t.Any = Fraction) -> None:
        super().__init__(hint)


@register_adaptor(str)
class StrAdaptor(CastAdaptor):
    """An adaptor for strings."""

    MaxType = str

    def __init__(self, hint: t.Any = str) -> None:
        super().__init__(hint)


@register_adaptor(bool)
class BoolAdaptor(CastAdaptor):
    """An adaptor for booleans."""

    MaxType = bool

    def __init__(self, hint: t.Any = bool) -> None:
        super().__init__(hint)


@register_adaptor(complex, Complex)
class ComplexAdaptor(CastAdaptor):
    """An adaptor for complex numbers."""

    MaxType = Complex

    def __init__(self, hint: t.Any = complex) -> None:
        super().__init__(hint)


# ----------------------------------------------------------------------
# Adaptor implementations: Collections
# ----------------------------------------------------------------------


@register_adaptor(
    *_tt.List,
    *_tt.Sequence,
    *_tt.MutableSequence,
    *_tt.Iterable,
)
class ListAdaptor(HintAdaptor):
    """An adaptor for lists."""

    MaxType = abc.Iterable
    Fallback = list

    def __init__(self, hint: t.Any = list) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> list:
        cls = _get_origin(self.hint)
        args = t.get_args(self.hint)

        cls_fallback = cls
        if _issubclass(cls, ABC):
            cls_fallback = self.Fallback

        # Adapt items
        if args:
            if len(args) > 2 or (len(args) == 2 and args[1] is not ...):
                raise TypeError(
                    "List hint must have zero or one type argument"
                )
            item_adaptor = Adaptor(args[0])
            value = (item_adaptor(item) for item in value)

        # Adapt container
        if not isinstance(value, cls):
            value = cls_fallback(value)
        return value


@register_adaptor(*_tt.Set, *_tt.FrozenSet, *_tt.MutableSet, *_tt.AbstractSet)
class SetAdaptor(ListAdaptor):

    Fallback = set
    MaxType = abc.Set

    def __init__(self, hint: t.Any = set) -> None:
        super().__init__(hint)


@register_adaptor(*_tt.Tuple)
class TupleAdaptor(HintAdaptor):
    """An adaptor for tuples."""

    MaxType = tuple

    def __init__(self, hint: t.Any = tuple) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> tuple:
        cls = _get_origin(self.hint)
        args = t.get_args(self.hint)

        # Convert to target container (in case of generator input)
        if not isinstance(value, cls):
            value = cls(value)

        # Adapt items
        if args:
            if len(args) == 2 and args[1] is ...:
                item_adaptor = Adaptor(args[0])
                value = (item_adaptor(item) for item in value)
            elif len(args) == len(value):
                value = tuple(
                    Adaptor(arg)(item) for arg, item in zip(args, value)
                )
            else:
                raise TypeError(
                    f"Expected a tuple of length {len(args)} but got "
                    f"{len(value)}"
                )

        # Adapt container
        if not isinstance(value, cls):
            value = cls(value)
        return value


@register_adaptor(
    *_tt.Dict,
    *_tt.OrderedDict,
    *_tt.Mapping,
    *_tt.MutableMapping,
)
class DictAdaptor(HintAdaptor):
    """An adaptor for dictionaries."""

    Fallback = dict
    MaxType = abc.Mapping

    def __init__(self, hint: t.Any = dict) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> dict:
        cls = _get_origin(self.hint)
        args = t.get_args(self.hint)

        cls_fallback = cls
        if _issubclass(cls, ABC):
            cls_fallback = self.Fallback

        # Adapt keys and values
        if args:
            if len(args) != 2:
                raise TypeError(
                    "Dict hint must have exactly two type arguments"
                )
            key_adaptor = Adaptor(args[0])
            value_adaptor = Adaptor(args[1])
            value = (
                (key_adaptor(key), value_adaptor(val))
                for key, val in value.items()
            )

        # Adapt container + ensure a copy is made
        if not isinstance(value, cls):
            value = cls_fallback(**value)

        return value


@register_adaptor(*_tt.TypedDict)
class TypedDictAdaptor(DictAdaptor):
    """An adaptor for TypedDicts."""

    Fallback = dict

    def __init__(self, hint: t.Any = _t.TypedDict) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> dict:
        cls = _get_origin(self.hint)

        annotations = get_annotations(cls)
        required_keys = getattr(cls, "__required_keys__", set())

        # Adapt keys and values
        value = (
            (key, Adaptor(annotations.get(key, t.Any))(val))
            for key, val in value.items()
        )

        # Adapt container
        if _issubclass(cls, ABC):
            value = self.Fallback(**value)

        # Check for missing required keys
        for key in required_keys:
            if key not in value:
                raise KeyError(f"Missing key '{key}' for TypedDict {cls}")

        for key in value:
            if key not in annotations:
                raise KeyError(f"Unexpected key '{key}' for TypedDict {cls}")

        return value


# ----------------------------------------------------------------------
# Adaptor implementations: Other
# ----------------------------------------------------------------------


@register_adaptor(range)
class RangeAdaptor(HintAdaptor):
    """An adaptor for ranges."""

    MaxType = range

    def __init__(self, hint: t.Any = range) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> range:
        if not isinstance(value, range):
            if isinstance(value, Number):
                value = range(value)
            elif isinstance(value, abc.Mapping):
                value = range(**value)
            else:
                value = range(*value)
        return value


@register_adaptor(slice)
class SliceAdaptor(HintAdaptor):
    """An adaptor for slices."""

    MaxType = slice

    def __init__(self, hint: t.Any = slice) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> slice:
        if not isinstance(value, slice):
            if value is None or isinstance(value, Number):
                value = slice(value)
            elif isinstance(value, abc.Mapping):
                value = slice(**value)
            else:
                value = slice(*value)
        return value
