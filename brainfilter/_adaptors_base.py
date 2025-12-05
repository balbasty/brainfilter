import typing as t
from abc import ABC, abstractmethod

# internals
from ._adaptors_utils import _get_origin, _issubclass, _tt


# ======================================================================
# Adaptor registry
# ======================================================================


ADAPTORS = {}


def register_adaptor(*hints: t.Any) -> t.Callable[[type], type]:
    """Register an adaptor class.

    Parameters
    ----------
    *hints : Any
        The target type(s) or type hint(s).

    Returns
    -------
    Callable[[type], type]
        A decorator that registers the adaptor class.
    """

    def decorator(adaptor: type) -> type:
        for hint in hints:
            ADAPTORS[hint] = adaptor
        return adaptor

    return decorator


def get_adaptor(hint: t.Any) -> type:
    """Get an adaptor class.

    Parameters
    ----------
    hint : Any
        The target type or type hint.

    Returns
    -------
    adaptor : type
        The adaptor class.
    """
    # Find it directly
    if hint in ADAPTORS:
        return ADAPTORS[hint]

    # Find the best matching adaptor (via issubclass)
    NOHINT = object()
    best_hint, best_adaptor = NOHINT, NOHINT
    for adaptor_hint, adaptor in ADAPTORS.items():
        if _issubclass(hint, adaptor_hint):
            if best_hint is NOHINT:
                best_hint = adaptor_hint
                best_adaptor = adaptor
            elif _issubclass(adaptor_hint, best_hint):
                best_hint = adaptor_hint
                best_adaptor = adaptor
        elif _issubclass(
            _get_origin(hint),
            _get_origin(adaptor_hint)
        ):
            if best_hint is NOHINT:
                best_hint = adaptor_hint
                best_adaptor = adaptor
            elif _issubclass(
                _get_origin(adaptor_hint),
                _get_origin(best_hint)
            ):
                best_hint = adaptor_hint
                best_adaptor = adaptor

    if best_adaptor is not NOHINT:
        ADAPTORS[hint] = best_adaptor

    # Find the best matching adaptor (via isinstance)
    for adaptor_hint, adaptor in ADAPTORS.items():
        if isinstance(hint, adaptor_hint):
            if best_hint is NOHINT:
                best_hint = adaptor_hint
                best_adaptor = adaptor
            elif _issubclass(adaptor_hint, best_hint):
                best_hint = adaptor_hint
                best_adaptor = adaptor

    if best_adaptor is not NOHINT:
        ADAPTORS[hint] = best_adaptor

    raise KeyError(f"No adaptor registered for {hint}")


# ======================================================================
# Adaptor ABC
# ======================================================================


class Adaptor(ABC):
    """Base class for adaptors."""

    MaxType = None

    def __new__(cls, hint: t.Any = t.Any) -> "Adaptor":
        if cls is Adaptor:
            if isinstance(hint, Adaptor):
                cls = type(hint)
            else:
                cls = get_adaptor(hint)
        return super().__new__(cls)

    @abstractmethod
    def __call__(self, value: t.Any) -> t.Any:
        raise NotImplementedError


class AdaptorChain(list, Adaptor):
    """An adaptor that chains multiple adaptors."""

    def __init__(self, *adaptors: Adaptor) -> None:
        adaptors_ = []
        for adaptor in adaptors:
            if isinstance(adaptor, list):
                adaptors_.extend(adaptor)
            else:
                adaptors_.append(Adaptor(adaptor))
        super().__init__(adaptors_)

    def __call__(self, value: t.Any) -> t.Any:
        for adaptor in self:
            value = adaptor(value)
        return value

    def __repr__(self) -> str:
        mod = self.__class__.__module__
        cls = self.__class__.__name__
        return f"{mod}.{cls}({list(self)!r})"

    def __str__(self) -> str:
        cls = self.__class__.__name__
        return f"{cls}({list(self)!s})"


class HintAdaptor(Adaptor):
    """An adaptor that checks against a hint."""

    def __init__(self, hint: t.Any = t.Any) -> None:
        if isinstance(hint, HintAdaptor):
            hint = hint.hint
        MaxType = type(self).MaxType
        if MaxType not in (None, *_tt.Any):
            origin = _get_origin(hint)
            if not _issubclass(origin, MaxType):
                raise TypeError(f"Expected an {MaxType} hint, got {hint}")
        self.hint = hint

    def __repr__(self) -> str:
        mod = self.__class__.__module__
        cls = self.__class__.__name__
        return f"{mod}.{cls}({self.hint!r})"

    def __str__(self) -> str:
        cls = self.__class__.__name__
        return f"{cls}({self.hint!s})"
