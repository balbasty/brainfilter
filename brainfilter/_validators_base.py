# stdlib
import csv
import json
import logging
import re
import typing as t
from abc import ABC, abstractmethod
from fnmatch import fnmatch
from os import PathLike
from types import GenericAlias, UnionType
from typing import (
    Annotated, Any, Callable, Literal, T, Union,
    get_origin, get_args
)

# internals
from brainfilter.versioning import (
    Version, VersionSpecifier, VersionSwitch, version_is_satisfied
)
from ._validators_req import (
    RequirementLevel,
    required, recommended, optional, proscribed, not_recommended,
    RequiredIf, RecommendedIf, ProscribedIf, NotRecommendedIf
)

# optionals
try:
    from upath import UPath
    Path = UPath
except ImportError:
    UPath = None
    from pathlib import Path

lg = logging.getLogger(__name__)


PathType = (UPath | PathLike) if UPath else PathLike
PathTypes = (UPath, PathLike) if UPath else (PathLike,)


# ----------------------------------------------------------------------
#  Helpers
# ----------------------------------------------------------------------


def ensure_path(obj: T) -> PathType:
    if isinstance(obj, PathTypes):
        return obj
    else:
        return Path(obj)


def ensure_validator(obj: T) -> "Validator":
    if isinstance(obj, Validator):
        return obj
    elif isinstance(obj, type):
        return HintValidator(obj)
    elif get_args(obj):  # type hint
        return HintValidator(obj)
    elif isinstance(obj, re.Pattern):
        return WrappedValidator(lambda x: bool(obj.match(x)))
    elif isinstance(obj, str):
        return WrappedValidator(lambda x: fnmatch(x, obj))
    elif isinstance(obj, dict):
        return JSONSchema(obj)
    elif callable(obj):
        return WrappedValidator(obj)
    elif obj is T:
        return HintValidator(Any)
    else:
        raise TypeError(f"Cannot convert {obj!r} to Validator.")


def generate_for_version(
    schema: Union["Validator", type],
    version: Version | tuple[int | str, ...] | str
) -> Union["Validator", type]:
    """
    Take a schema that contains version switches and generate a schema
    appropriate for the given version.

    Parameters
    ----------
    schema : Validator | type
        The schema to process.
    version : Version | tuple[int, ...]
        The version to generate the schema for.

    Returns
    -------
    Validator | type
        The generated schema.
    """

    if get_origin(schema) is get_origin(VersionSwitch):
        spec, schema_if_true, schema_otherwise = get_args(schema)
        if version_is_satisfied(spec, version):
            schema = schema_if_true
        else:
            schema = schema_otherwise
        schema = generate_for_version(schema, version)

    # ------------------------------------------------------------------
    # This case assumes that VersionSpecifier[...] is equivalent to
    # VersionSwitch[VersionSpecifier[...], Proscribed, None]
    #
    # I have commented it ourt and instead remove keys from the schema
    # when they do not match the target version. This lets the schema
    # decide if extra keys are allowed or not.
    # ------------------------------------------------------------------

    # elif get_origin(schema) is get_origin(VersionSpecifier):
    #     spec = get_args(schema)[0]
    #     if version_is_satisfied(spec, version):
    #         schema = None
    #     else:
    #         schema = Proscribed

    elif get_args(schema):
        args = tuple(
            generate_for_version(arg, version)
            for arg in get_args(schema)
        )
        schema = GenericAlias(get_origin(schema), args)

    elif isinstance(schema, (list, tuple)):
        schema = type(schema)(
            generate_for_version(item, version)
            for item in schema
        )

    elif isinstance(schema, dict):

        # --------------------------------------------------------------
        # Use this version to treat VersionSpecifer as a VersionSwitch
        # (see earlier comment).
        # --------------------------------------------------------------

        # schema = type(schema)({
        #     generate_for_version(k, version):
        #     generate_for_version(v, version)
        #     for k, v in schema.items()
        # })

        # --------------------------------------------------------------
        # Use this version to completely remove keys that do not match
        # the target version (see earlier comment).
        # --------------------------------------------------------------

        new_schema = {}
        for k, v in schema.items():

            # Check whether this key is version-dependent
            if get_origin(v) is Annotated:
                in_this_version = True
                for arg in get_args(v)[1:]:
                    if get_origin(arg) is get_origin(VersionSpecifier):
                        if not version_is_satisfied(arg, version):
                            in_this_version = False
                            break
                if not in_this_version:
                    continue

            new_k = generate_for_version(k, version)
            new_v = generate_for_version(v, version)
            new_schema[new_k] = new_v

        schema = type(schema)(new_schema)

    return schema

# ----------------------------------------------------------------------
#  Context
# ----------------------------------------------------------------------


ValidationMode = Literal["strict", "warn", "ignore", "bool"]


class ValidationContext:
    """
    A context manager for validation settings.

    Its attributes are accessed by validators at run time.
    When validation fails, their behavior depends on the current settings:
    - "bool": return False
    - "strict": log an error and return False
    - "warn": log a warning and return True
    - "ignore": log an info message and return True
    - "failfast": raise an exception immediately

    Attributes
    ----------
    REQUIRED : {"strict", "warn", "ignore", "bool"}, default="strict"
        The validation mode for required items.
    RECOMMENDED : {"strict", "warn", "ignore", "bool"}, default="warn"
        The validation mode for recommended items.
    VALUE : {"strict", "warn", "ignore", "bool"}, default="strict"
        The validation mode for value formatting.
    FAILFAST : bool, default=False
        Whether to raise exceptions immediately on validation failure.

    Examples
    --------
    >>> with ValidationContext("bool"):
    >>>     valid = validator(value)
    ...
    >>> with ValidationContext("strict", "failfast"):
    >>>     schema(data)
    ...
    >>> with ValidationContext(required="warn", value="ignore"):
    ...     valid = validator(value)

    """

    REQUIRED: ValidationMode = "strict"
    RECOMMENDED: ValidationMode = "warn"
    VALUE: ValidationMode = "strict"
    FAILFAST: bool = False

    def __init__(self, *defaults, **kwargs) -> None:
        """

        Parameters
        ----------
        *defaults : tuple
            Positional arguments to set all modes to the same value.
            Can be one of {"strict", "warn", "ignore", "bool"} and/or
            "failfast".

        Other Parameters
        ----------------
        required : {"strict", "warn", "ignore", "bool"}, optional
            The validation mode for required items.
        recommended : {"strict", "warn", "ignore", "bool"}, optional
            The validation mode for recommended items.
        value : {"strict", "warn", "ignore", "bool"}, optional
            The validation mode for value formatting.
        failfast : bool, optional
            Whether to raise exceptions immediately on validation failure.

        """
        default = None
        if "strict" in defaults:
            default = "strict"
        elif "warn" in defaults:
            default = "warn"
        elif "ignore" in defaults:
            default = "ignore"
        elif "bool" in defaults:
            default = "bool"

        if default:
            kwargs.setdefault("required", default)
            kwargs.setdefault("recommended", default)
            kwargs.setdefault("value", default)
        else:
            kwargs.setdefault("required", self.REQUIRED)
            kwargs.setdefault("recommended", self.RECOMMENDED)
            kwargs.setdefault("value", self.VALUE)

        if "failfast" in defaults:
            kwargs.setdefault("failfast", True)
        else:
            kwargs.setdefault("failfast", self.FAILFAST)

        self.required = kwargs["required"]
        self.recommended = kwargs["recommended"]
        self.value = kwargs["value"]
        self.failfast = kwargs["failfast"]

    def __enter__(self) -> "ValidationContext":
        self._prev_required = ValidationContext.REQUIRED
        self._prev_recommended = ValidationContext.RECOMMENDED
        self._prev_value = ValidationContext.VALUE
        self._prev_failfast = ValidationContext.FAILFAST

        ValidationContext.REQUIRED = self.required
        ValidationContext.RECOMMENDED = self.recommended
        ValidationContext.VALUE = self.value
        ValidationContext.FAILFAST = self.failfast

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        ValidationContext.REQUIRED = self._prev_required
        ValidationContext.RECOMMENDED = self._prev_recommended
        ValidationContext.VALUE = self._prev_value
        ValidationContext.FAILFAST = self._prev_failfast


# ----------------------------------------------------------------------
#  Exceptions
# ----------------------------------------------------------------------


class CoreError(Exception):
    """Base class for core exceptions."""
    pass


class WrongHintError(CoreError, TypeError):
    """Exception raised for invalid type hints."""
    pass


class ValidationError(Exception):
    """Exception raised for validation errors."""
    pass


class WrongValueError(ValidationError, ValueError):
    """Exception raised for value validation errors."""
    pass


class RequiredError(ValidationError, KeyError):
    """Exception raised for missing required items."""
    pass


class RecommendedError(ValidationError, KeyError):
    """Exception raised for missing recommended items."""
    pass


# ----------------------------------------------------------------------
#  Validators
# ----------------------------------------------------------------------


class Validator(ABC):
    """
    Base class for validators.

    A validator is a callable that takes a value and returns True if the value
    is valid according to some criteria, and False otherwise.
    """

    @abstractmethod
    def __call__(self, value: T, prefix: str = "") -> bool:
        return NotImplemented

    def _fail(
        self,
        key: Literal["REQUIRED", "RECOMMENDED", "VALUE"],
        msg: str = ""
    ) -> None:
        mode = getattr(ValidationContext, key)
        if mode == "warn":
            lg.warning(msg)
        elif mode == "strict":
            lg.error(msg)
            if ValidationContext.FAILFAST:
                raise {
                    "VALUE": WrongValueError,
                    "REQUIRED": RequiredError,
                    "RECOMMENDED": RecommendedError,
                }[key](msg)
            else:
                return False
        elif mode == "ignore":
            lg.info(msg)
        else:
            lg.debug(msg)
        return False if mode == "bool" else True

    def _fail_value(self, msg: str = "") -> None:
        return self._fail("VALUE", msg)

    def _fail_required(self, msg: str = "") -> None:
        return self._fail("REQUIRED", msg)

    def _fail_recommended(self, msg: str = "") -> None:
        return self._fail("RECOMMENDED", msg)

    def _flatten_and(self) -> list["Validator"]:
        return [self]

    def _flatten_or(self) -> list["Validator"]:
        return [self]

    def _flatten_xor(self) -> list["Validator"]:
        return [self]

    def __or__(self, other: "Validator") -> "OrValidator":
        return OrValidator(self, other)

    def __ior__(self, other: "Validator") -> "OrValidator":
        return OrValidator(self, other)

    def __ror__(self, other: "Validator") -> "OrValidator":
        return OrValidator(other, self)

    def __and__(self, other: "Validator") -> "AndValidator":
        return AndValidator(self, other)

    def __iand__(self, other: "Validator") -> "AndValidator":
        return AndValidator(self, other)

    def __rand__(self, other: "Validator") -> "AndValidator":
        return AndValidator(other, self)

    def __xor__(self, other: "Validator") -> "XorValidator":
        return XorValidator(self, other)

    def __ixor__(self, other: "Validator") -> "XorValidator":
        return XorValidator(self, other)

    def __rxor__(self, other: "Validator") -> "XorValidator":
        return XorValidator(other, self)


class OrValidator(list, Validator):
    """A validator that combines multiple validators with logical OR."""

    def __init__(self, *validators: list[Validator]) -> None:
        if len(validators) == 0:
            raise ValueError("OrValidator requires at least one validator.")

        if len(validators) == 1:
            validators = validators[0]

        super().__init__(
            concrete_validator
            for validator in validators
            for concrete_validator in validator._flatten_or()
        )

    def __call__(self, value: T, prefix: str) -> bool:
        result = False
        with ValidationContext(value="bool"):
            for validator in self:
                result |= validator(value, prefix)
                if result:
                    break
        return result or self._fail_value(
            f"{prefix}{value!r} is invalid. None of the options matched."
        )

    def _flatten_or(self):
        all = []
        for validator in self:
            all += validator._flatten_or()
        return all

    def __ior__(self, other: Validator) -> "OrValidator":
        if isinstance(other, OrValidator):
            self.extend(other.validators)
        else:
            self.append(other)
        return

    def __or__(self, other: Validator) -> "OrValidator":
        if isinstance(other, OrValidator):
            return OrValidator(*(self + other))
        else:
            return OrValidator(*(self + [other]))

    def __ror__(self, other: Validator) -> "OrValidator":
        if isinstance(other, OrValidator):
            return OrValidator(*(other + self))
        else:
            return OrValidator(*([other] + self))


class AndValidator(list, Validator):
    """A validator that combines multiple validators with logical AND."""

    def __init__(self, *validators: list[Validator]) -> None:
        if len(validators) == 0:
            raise ValueError("AndValidator requires at least one validator.")

        if len(validators) == 1:
            validators = validators[0]

        super().__init__(
            concrete_validator
            for validator in validators
            for concrete_validator in validator._flatten_and()
        )

    def __call__(self, value: T, prefix: str) -> bool:
        result = True
        for validator in self:
            result &= validator(value, prefix)
            if not result:
                break
        return result

    def _flatten_and(self):
        all = []
        for validator in self:
            all += validator._flatten_and()
        return all

    def __iand__(self, other: Validator) -> "AndValidator":
        if isinstance(other, AndValidator):
            self.extend(other.validators)
        else:
            self.append(other)
        return

    def __and__(self, other: Validator) -> "AndValidator":
        if isinstance(other, AndValidator):
            return AndValidator(*(self + other))
        else:
            return AndValidator(*(self + [other]))

    def __rand__(self, other: Validator) -> "AndValidator":
        if isinstance(other, AndValidator):
            return AndValidator(*(other + self))
        else:
            return AndValidator(*([other] + self))


class XorValidator(list, Validator):
    """A validator that combines multiple validators with logical XOR."""

    def __init__(self, *validators: list[Validator]) -> None:
        if len(validators) == 0:
            raise ValueError("XorValidator requires at least one validator.")

        if len(validators) == 1:
            validators = validators[0]

        super().__init__(
            concrete_validator
            for validator in validators
            for concrete_validator in validator._flatten_and()
        )

    def __call__(self, value: T, prefix: str) -> bool:
        result = False
        for validator in self:
            result ^= validator(value, prefix)
        return result

    def _flatten_xor(self):
        all = []
        for validator in self:
            all += validator._flatten_xor()
        return all

    def __ixor__(self, other: Validator) -> "XorValidator":
        if isinstance(other, XorValidator):
            self.extend(other.validators)
        else:
            self.append(other)
        return

    def __xor__(self, other: Validator) -> "XorValidator":
        if isinstance(other, XorValidator):
            return XorValidator(*(self + other))
        else:
            return XorValidator(*(self + [other]))

    def __rxor__(self, other: Validator) -> "XorValidator":
        if isinstance(other, XorValidator):
            return XorValidator(*(other + self))
        else:
            return XorValidator(*([other] + self))


class WrappedValidator(Validator):
    """A validator that wraps a callable."""

    def __init__(
        self,
        callable: Callable[[T], bool],
        msg: str = ""
    ) -> None:
        if msg:
            msg += ": "
        self.callable = callable
        self.msg = msg

    def __call__(self, value: T, prefix: str = "") -> bool:
        result = self.callable(value)
        return result or self._fail_value(
            f"{prefix}{self.msg}{value!r} is invalid."
        )


class HintValidator(Validator):
    """A validator that validates a value against a type hint."""

    def __init__(self, hint: type) -> None:
        self.hint = hint
        self.cls, self.args, self.annotations = self._split_hint()

    def _split_hint(self) -> tuple[type, tuple, tuple]:
        annotations = ()
        hint = self.hint
        args = get_args(hint)
        if args:
            hint = get_origin(hint)

        if hint is Annotated:
            hint, *annotations = args
            args = get_args(hint)
            if args:
                hint = get_origin(hint)

        return hint, args, annotations

    def _validate_list(self, value: T, args: tuple, prefix: str = "") -> bool:
        result = True

        if not isinstance(value, (list, tuple, set)):
            result &= self._fail_value(f"{prefix}{value!r} is not an array.")

        elif args:
            assert len(args) <= 1, "Invalid list hint"
            item_type = args[0] if args else Any
            item_validator = ensure_validator(item_type)
            for item in value:
                result &= item_validator(item, prefix)

        return result

    def _validate_tuple(self, value: T, args: tuple, prefix: str = "") -> bool:
        result = True

        if not isinstance(value, (list, tuple, set)):
            result &= self._fail_value(f"{prefix}{value!r} is not an array.")

        elif args and args != (Ellipsis,):
            if len(args) == 2 and args[1] is Ellipsis:
                args = args[:1] * len(value)
            if len(args) != len(value):
                result &= self._fail_value(
                    f"{prefix}{value!r} does not match expected length"
                )
            else:
                for item, arg in zip(value, args):
                    item_validator = ensure_validator(arg, prefix)
                    result &= item_validator(item)

        return result

    def _validate_dict(self, value: T, args: tuple, prefix: str = "") -> bool:
        result = True

        if not isinstance(value, dict):
            result &= self._fail_value(f"{prefix}{value!r} is not an object.")

        elif args:
            assert len(args) <= 2, "Invalid dict hint"
            key_type, value_type = args[:2]
            key_validator = ensure_validator(key_type)
            value_validator = ensure_validator(value_type)
            for k, v in value.items():
                result &= key_validator(k, prefix)
                result &= value_validator(v, prefix + f"{k!r}: ")

        return result

    def _validate_literal(
        self, value: T, args: tuple, prefix: str = ""
    ) -> bool:
        result = True
        if value not in args:
            result &= self._fail_value(
                f"{prefix}{value!r} is not one of the allowed literals: "
                f"{args!r}."
            )
        return result

    def _validate_union(self, value: T, args: tuple, prefix: str = "") -> bool:
        result = False
        for arg in args:
            arg_validator = ensure_validator(arg)
            with ValidationContext(value="bool"):
                result |= arg_validator(value, prefix)
            if result:
                break
        return result or self._fail_value(
            f"{prefix}{value!r} does not match any type in the union: "
            f"{args!r}."
        )

    def __call__(self, value: T, prefix: str = "") -> bool:
        cls, args, annotations = self.cls, self.args, self.annotations

        result = True

        # Validate core type
        if cls in (set, list, t.Set, t.List, t.Sequence):
            result &= self._validate_list(value, args, prefix)

        elif cls in (tuple, t.Tuple):
            result &= self._validate_tuple(value, args, prefix)

        elif cls in (dict, t.Dict, t.Mapping):
            result &= self._validate_dict(value, args, prefix)

        elif cls is Literal:
            result &= self._validate_literal(value, args, prefix)

        elif cls in (Union, UnionType):
            result &= self._validate_union(value, args, prefix)

        elif cls is Any:
            result &= True

        else:
            assert isinstance(cls, type), "Invalid hint"
            if not isinstance(value, cls):
                result &= self._fail_value(
                    f"{prefix}{value!r} is not of type {cls.__name__}."
                )

        # Apply validations from annotations
        for annotation in annotations:

            if get_origin(annotation) is Literal:
                result &= self._validate_literal(
                    value, get_args(annotation), prefix
                )

            elif isinstance(annotation, Validator):
                result &= annotation(value, prefix)

        return result


class FileValidator(Validator):

    def __call__(self, value: T, prefix: str = "") -> bool:
        result = ensure_path(value).is_file()
        return result or self._fail_value(f"{prefix}{value!r} is not a file.")


class DirectoryValidator(Validator):

    def __call__(self, value: T, prefix: str = "") -> bool:
        result = ensure_path(value).is_dir()
        return result or self._fail_value(
            f"{prefix}{value!r} is not a directory."
        )


# ----------------------------------------------------------------------
#  Schemas
# ----------------------------------------------------------------------


class _dict(dict):

    def copy(self) -> "_dict":
        return type(self)(self)


class Schema(_dict, Validator):
    """Base class for validators that validate structured data."""

    @classmethod
    def _requirement(cls, annotations: tuple, value: T) -> RequirementLevel:
        requirement = optional
        for annot in annotations:
            # Required
            if annot is required:
                return required
            if get_origin(annot) is RequiredIf:
                cond = ensure_validator(get_args(annot)[0])
                with ValidationContext(value="ignore"):
                    if cond(value):
                        return required
            # Proscribed
            if annot is proscribed:
                return proscribed
            if get_origin(annot) is ProscribedIf:
                cond = ensure_validator(get_args(annot)[0])
                with ValidationContext(value="ignore"):
                    if cond(value):
                        return proscribed
            # Recommended
            if annot is recommended:
                requirement = recommended
            if get_origin(annot) is RecommendedIf:
                cond = ensure_validator(get_args(annot)[0])
                with ValidationContext(value="ignore"):
                    if cond(value):
                        requirement = recommended
            # NotRecommended
            if annot is not_recommended:
                requirement = not_recommended
            if get_origin(annot) is NotRecommendedIf:
                cond = ensure_validator(get_args(annot)[0])
                with ValidationContext(value="ignore"):
                    if cond(value):
                        requirement = not_recommended
        return requirement


class JSONSchema(Schema):
    """A validator that validates a JSON object against a schema."""

    def __call__(self, obj: T, prefix: str = "") -> bool:
        result = True

        if not isinstance(obj, dict):
            result = result or self._fail_value(
                f"{prefix}{obj!r} is not an object."
            )

        # Check that each key-value pair in the object is valid
        for key, value in obj.items():
            for schema_key, schema_hint in self.items():
                key_validator = ensure_validator(schema_key)
                with ValidationContext(value="bool"):
                    key_valid = key_validator(key, prefix)
                if key_valid:
                    key_prefix = f"{prefix}{key!r}: "
                    schema_validator = ensure_validator(schema_hint)
                    result &= schema_validator(value, prefix=key_prefix)
                    break

        # Check that all required keys are present
        for schema_key, schema_hint in self.items():
            if get_origin(schema_hint) is not Annotated:
                continue

            annotations = get_args(schema_hint)[1:]
            requirement = self._requirement(annotations, obj)
            if requirement is optional:
                continue

            present = False
            key_validator = ensure_validator(schema_key)
            with ValidationContext(value="bool"):
                for key in obj.keys():
                    if key_validator(key, prefix):
                        present = True
                        break

            if present:
                if requirement is recommended:
                    result &= self._fail_recommended(
                        f"{prefix}Unrecommended item {key!r} is present."
                    )
                elif requirement is proscribed:
                    result &= self._fail_required(
                        f"{prefix}Proscribed item {key!r} is present."
                    )
            else:
                if requirement is recommended:
                    result &= self._fail_recommended(
                        f"{prefix}Recommended item {schema_key!r} is missing."
                    )
                else:
                    result &= self._fail_required(
                        f"{prefix}Required item {schema_key!r} is missing."
                    )

        # All checks passed
        return result


class DirectorySchema(Schema, DirectoryValidator):
    """A validator that validates a directory against a schema."""

    def __call__(self, value: T, prefix: str = "") -> bool:
        value = ensure_path(value)
        result = super().__call__(value, prefix)

        if not value.is_dir():
            return result

        prefix_dir = prefix + f"In directory {value!s}: "
        prefix_file = prefix

        # Check that each file in the directory is valid
        for file in value.iterdir():

            # Find a matching item in the schema
            key_valid = False
            for key, schema in self.items():
                key_validator = ensure_validator(key)
                with ValidationContext(value="bool"):
                    key_valid = key_validator(file.name, prefix_dir)
                if key_valid:
                    schema_validator = ensure_validator(schema)
                    result &= schema_validator(file, prefix=prefix_file)
                    break

            if not key_valid:
                result &= self._fail_value(
                    f"{prefix_dir}Unexpected item {file.name!r} is present."
                )

        # Check that all required keys are present
        for key, schema in self.items():
            if get_origin(schema) is not Annotated:
                continue

            annotations = get_args(schema)[1:]
            requirement = self._requirement(annotations, value)
            if requirement is optional:
                continue

            present = False
            key_validator = ensure_validator(key)
            with ValidationContext(value="bool"):
                for file in value.iterdir():
                    if key_validator(file.name, prefix_dir):
                        present = True
                        break

            if present:
                if requirement is recommended:
                    result &= self._fail_recommended(
                        f"{prefix_dir}Unrecommended file {key!r} is present."
                    )
                elif requirement is proscribed:
                    result &= self._fail_required(
                        f"{prefix_dir}Proscribed file {key!r} is present."
                    )
            else:
                if requirement is recommended:
                    result &= self._fail_recommended(
                        f"{prefix_dir}Recommended file {key!r} is missing."
                    )
                elif requirement is required:
                    result &= self._fail_required(
                        f"{prefix_dir}Required file {key!r} is missing."
                    )

        # All checks passed
        return result


class JSONFileValidator(FileValidator, HintValidator):
    """A validator that validates a JSON file against a schema."""

    def __init__(self, schema: type | dict | JSONSchema | None = None) -> None:
        if isinstance(schema, dict):
            schema = JSONSchema(schema)
        if isinstance(schema, JSONSchema):
            schema = Annotated[dict[str, T], schema]
        schema = schema or dict[str, T]
        super().__init__(schema)

    def __call__(self, value: T, prefix: str = "") -> bool:
        value = ensure_path(value)
        result = FileValidator.__call__(self, value, prefix)

        if not value.is_file():
            return result

        prefix += f"In file {value!s}: "

        content = json.loads(value.read_text())
        return HintValidator.__call__(self, content, prefix)


class TSVFileValidator(FileValidator, HintValidator):
    """A validator that validates a TSV file."""

    def __init__(self, schema: type | dict | JSONSchema | None = None) -> None:
        if isinstance(schema, dict):
            schema = JSONSchema(schema)
        if isinstance(schema, JSONSchema):
            schema = Annotated[dict[str, T], schema]
        schema = schema or dict[str, T]
        super().__init__(schema)

    def __call__(self, value: T, prefix: str = "") -> bool:
        value = ensure_path(value)
        result = FileValidator.__call__(self, value, prefix)

        if not value.is_file():
            return result

        prefix += f"In file {value!s}: "

        content = [row for row in csv.DictReader(value.open(), delimiter="\t")]
        for row in content:
            result &= HintValidator.__call__(self, row, prefix)
        return result
