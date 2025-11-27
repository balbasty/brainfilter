# stdlib
from typing import T

# internals
from brainfilter.validation import Validator, WrappedValidator

# optional
try:
    from uritools import isuri
except ImportError:
    isuri = None

# ----------------------------------------------------------------------
#  URI
# ----------------------------------------------------------------------

if isuri:
    URIValidator = WrappedValidator(isuri, "Not a valid URI.")
else:
    URIValidator = None

# ----------------------------------------------------------------------
#  Generic Validators
# ----------------------------------------------------------------------


class Minimum(Validator):

    def __init__(self, value: T, inclusive: bool = True) -> None:
        self.value = value
        self.inclusive = inclusive

    def __call__(self, value: T, prefix: str = "") -> bool:
        if self.inclusive:
            result = value >= self.value
        else:
            result = value > self.value
        return result or self._fail_value(
            f"{prefix}{value!r} is less than minimum {self.value!r}."
        )


class Maximum(Validator):

    def __init__(self, value: T, inclusive: bool = True) -> None:
        self.value = value
        self.inclusive = inclusive

    def __call__(self, value: T, prefix: str = "") -> bool:
        if self.inclusive:
            result = value <= self.value
        else:
            result = value < self.value
        return result or self._fail_value(
            f"{prefix}{value!r} is greater than maximum {self.value!r}."
        )


class Length(Validator):

    def __init__(self, length: int) -> None:
        self.length = length

    def __call__(self, value: T, prefix: str = "") -> bool:
        result = len(value) == self.length
        return result or self._fail_value(
            f"{prefix}{value!r} does not have length {self.length}."
        )


class MinLength(Validator):

    def __init__(self, length: int) -> None:
        self.length = length

    def __call__(self, value: T, prefix: str = "") -> bool:
        result = len(value) >= self.length
        return result or self._fail_value(
            f"{prefix}{value!r} does not have minimum length {self.length}."
        )


class MaxLength(Validator):

    def __init__(self, length: int) -> None:
        self.length = length

    def __call__(self, value: T, prefix: str = "") -> bool:
        result = len(value) <= self.length
        return result or self._fail_value(
            f"{prefix}{value!r} exceeds maximum length {self.length}."
        )
