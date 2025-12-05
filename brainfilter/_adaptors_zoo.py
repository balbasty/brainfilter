# stdlib
import typing as t
from numbers import Integral, Number

# internals
from ._adaptors_base import Adaptor, HintAdaptor
from ._adaptors_numpy import np, pd

# ----------------------------------------------------------------------
# Adaptor implementations: Traits
# ----------------------------------------------------------------------


class HasAttr(HintAdaptor):
    """An adaptor that checks for the presence of an attribute."""

    def __init__(self, hint: str) -> None:
        super().__init__(hint)
        if not isinstance(self.hint, str):
            raise TypeError(f"Expected a string hint, got {self.hint}")

    def __call__(self, value: t.Any) -> t.Any:
        if not hasattr(value, self.hint):
            raise TypeError(
                f"Expected an object with attribute '{self.hint}', "
                f"got {value}"
            )
        return value


class HasMethod(HasAttr):
    """An adaptor that checks for the presence of a method."""

    def __init__(self, hint: str) -> None:
        super().__init__(hint)

    def __call__(self, value: t.Any) -> t.Any:
        value = super().__call__(value)
        method = getattr(value, self.hint)
        if not callable(method):
            raise TypeError(
                f"Expected an object with method '{self.hint}', got {value}"
            )
        return value


# ----------------------------------------------------------------------
# Adaptors that modify values or check properties
# ----------------------------------------------------------------------


class Default(Adaptor):
    """An adaptor that provides a default value."""

    def __init__(self, default: t.Any = None) -> None:
        super().__init__()
        self.default = default

    def __call__(self, *args) -> t.Any:
        if args:
            return args[0] if len(args) == 1 else args
        else:
            return self.default


class Clamp(Adaptor):
    """An adaptor that clamps numeric values."""

    OneOrTwoNumbers = t.Union[
        t.Tuple[t.Optional[Number]],
        t.Tuple[t.Optional[Number], t.Optional[Number]]
    ]

    def __init__(self, *args: OneOrTwoNumbers) -> None:
        if len(args) > 2:
            raise TypeError(
                f"Expected one or two numeric arguments, got {args}"
            )
        if args:
            mn = None
            mx = args[-1]
            if len(args) == 2:
                mn = args[0]

        if mn is not None and not isinstance(mn, Number):
            raise TypeError(f"Expected a numeric min value, got {mn}")
        if mx is not None and not isinstance(mx, Number):
            raise TypeError(f"Expected a numeric max value, got {mx}")

        super().__init__()
        self.mn = mn
        self.mx = mx

    def __call__(self, value: t.Any) -> Number:
        if np and isinstance(value, np.ndarray):
            return np.clip(value, self.mn, self.mx)
        if pd and isinstance(value, (pd.Series, pd.DataFrame)):
            return value.clip(self.mn, self.mx)

        if self.mn is not None and value < self.mn:
            value = self.mn
        if self.mx is not None and value > self.mx:
            value = self.mx
        return value


class ClampMin(Clamp):
    """An adaptor that clamps numeric values to a minimum."""

    def __init__(self, mn: Number | None = None) -> None:
        super().__init__(mn, None)


class ClampMax(Clamp):
    """An adaptor that clamps numeric values to a maximum."""

    def __init__(self, mx: Number | None = None) -> None:
        super().__init__(None, mx)


class ClampLength(Adaptor):
    """An adaptor that clamps the length of collections."""

    OneOrTwoIntegers = t.Union[
        t.Tuple[t.Optional[Integral]],
        t.Tuple[t.Optional[Integral], t.Optional[Integral]]
    ]
    DEFAULT = object()

    def __init__(self, *args: OneOrTwoIntegers, **kwargs) -> None:
        if len(args) > 2:
            raise TypeError(
                f"Expected one or two numeric arguments, got {args}"
            )
        if args:
            mn = None
            mx = args[-1]
            if len(args) == 2:
                mn = args[0]

        if mn is not None and not isinstance(mn, Integral):
            raise TypeError(f"Expected an integral min value, got {mn}")
        if mx is not None and not isinstance(mx, Integral):
            raise TypeError(f"Expected an integral max value, got {mx}")

        super().__init__()
        self.mn = mn
        self.mx = mx
        self.default = kwargs.get("default", self.DEFAULT)

    def __call__(self, value: t.Any) -> t.Any:

        otype = type(value)
        length = len(value)

        if self.mn is not None and length < self.mn:

            if self.default is not self.DEFAULT:
                default = self.default
            elif length > 0:
                default = value[-1]
            else:
                default = None

            extra = [default] * (self.mn - length)
            value = list(value) + extra

        if self.mx is not None and length > self.mx:

            value = value[:self.mx]

        return otype(value)


class ValueInRange(Adaptor):
    """An adaptor that checks if a numeric value is within a range."""

    OneOrTwoNumbers = t.Union[
        t.Tuple[t.Optional[Number]],
        t.Tuple[t.Optional[Number], t.Optional[Number]]
    ]

    def __init__(self, *args: OneOrTwoNumbers, **kwargs) -> None:
        inclusive = kwargs.get("inclusive", True)
        if len(args) > 2:
            raise TypeError(
                f"Expected one or two numeric arguments, got {args}"
            )
        if args:
            mn = None
            mx = args[-1]
            if len(args) == 2:
                mn = args[0]

        if mn is not None and not isinstance(mn, Number):
            raise TypeError(f"Expected a numeric min value, got {mn}")
        if mx is not None and not isinstance(mx, Number):
            raise TypeError(f"Expected a numeric max value, got {mx}")

        super().__init__()
        self.mn = mn
        self.mx = mx
        self.inclusive = inclusive

    def __call__(self, value: t.Any) -> Number:
        mn, mx, incl = self.mn, self.mx, self.inclusive

        if mn is not None and value < mn or (not incl and value == mn):
            raise ValueError(f"Value {value} is less than minimum {mn}")
        if mx is not None and value > mx or (not incl and value == mx):
            raise ValueError(f"Value {value} is greater than maximum {mx}")
        return value


class Minimum(ValueInRange):
    """An adaptor that checks if a numeric value is above a minimum."""

    def __init__(self, mn: Number | None = None, **kwargs) -> None:
        super().__init__(mn, None, **kwargs)


class Maximum(ValueInRange):
    """An adaptor that checks if a numeric value is below a maximum."""

    def __init__(self, mx: Number | None = None, **kwargs) -> None:
        super().__init__(None, mx, **kwargs)


class LengthBetween(Adaptor):
    """An adaptor that checks the length of collections."""

    OneOrTwoIntegers = t.Union[
        t.Tuple[t.Optional[Integral]],
        t.Tuple[t.Optional[Integral], t.Optional[Integral]]
    ]

    def __init__(self, *args: OneOrTwoIntegers, **kwargs) -> None:
        inclusive = kwargs.get("inclusive", True)
        if len(args) > 2:
            raise TypeError(
                f"Expected one or two numeric arguments, got {args}"
            )
        if args:
            mn = None
            mx = args[-1]
            if len(args) == 2:
                mn = args[0]

        if mn is not None and not isinstance(mn, Integral):
            raise TypeError(f"Expected an integral min value, got {mn}")
        if mx is not None and not isinstance(mx, Integral):
            raise TypeError(f"Expected an integral max value, got {mx}")

        super().__init__()
        self.mn = mn
        self.mx = mx
        self.inclusive = inclusive

    def __call__(self, value: t.Any) -> t.Any:
        mn, mx, incl = self.mn, self.mx, self.inclusive
        length = len(value)
        if mn is not None and length < mn or (not incl and length == mn):
            raise ValueError(
                f"Length {length} is less than minimum {mn}"
            )
        if mx is not None and length > mx or (not incl and length == mx):
            raise ValueError(
                f"Length {length} is greater than maximum {mx}"
            )
        return value


class MinLength(LengthBetween):
    """
    An adaptor that checks if the length of a collection is above a minimum.
    """

    def __init__(self, mn: Integral | None = None, **kwargs) -> None:
        super().__init__(mn, None, **kwargs)


class MaxLength(LengthBetween):
    """
    An adaptor that checks if the length of a collection is below a maximum.
    """

    def __init__(self, mx: Integral | None = None, **kwargs) -> None:
        super().__init__(None, mx, **kwargs)
