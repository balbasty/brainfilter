import typing as t

from .validators import RequirementLevel
from .adaptors import Adaptor, Default


class SDict(dict):
    """
    A schema-enforced dictionary.

    `SDict` classes are defined similarly to `TypedDict` classes,
    but adapt and validate their contents at runtime.

    >>> from brainfilter.sdict import SDict
    ...
    >>> class MySchema(SDict):
    >>>    x: int
    >>>    y: float = 2.0
    ...
    >>> data = MySchema(x=5)
    >>> print(data)
    {'x': 5, 'y': 2.0}
    ...
    >>> data['x'] = 10
    >>> print(data)
    {'x': 10, 'y': 2.0}
    ...
    >>> data['z'] = 3  # Raises AttributeError
    Traceback (most recent call last):
        ...
    AttributeError: Attribute 'z' not defined in schema
    ...
    >>> data['y'] = 'not a float'  # Raises TypeError
    Traceback (most recent call last):
        ...
    ValueError: could not convert string to float: 'not a float'

    Alternatively, the schema can be defined by passing a `schema` argument
    to the class definition:

    >>> my_schema = {
    >>>     'x': int,
    >>>     'y': float,
    >>> }
    ...
    >>> class MySchema(SDict, schema=my_schema):
    ...
    >>> data = MySchema(x=5)
    >>> print(data)
    {'x': 5, 'y': None}

    When required keys are missing, or proscribed keys are present,
    an exception is raised.

    >>> class MySchema(SDict):
    >>>    x: int
    >>>    y: float
    ...
    >>> data = MySchema(x=5)  # Raises KeyError
    Traceback (most recent call last):
        ...
    KeyError: "Key 'y' is required but missing"

    When recommended keys are missing, or not recommended keys are present,
    an error is raised if `strict=True` is set in the class definition.

    >>> from brainfilter.validators import Recommended
    ...
    >>> class MySchema(SDict, strict=True):
    >>>    x: int
    >>>    y: Recommended[float]
    ...
    >>> data = MySchema(x=5)  # Raises Warning
    Traceback (most recent call last):
        ...
    Warning: Key 'y' is recommended but missing

    Keys are annotated as required, unless otherwise specified
    using the `required`, `recommended`, `optional`, `not_recommended`,
    and `proscribed` validators. The default requirement level can be changed
    by setting the `recommendation` argument in the class definition.

    >>> from brainfilter.validators import recommended
    ...
    >>> class MySchema(SDict, recommendation=recommended):
    >>>    x: int
    >>>    y: float
    ...
    >>> data = MySchema(x=5)  # No warning raised
    >>> print(data)
    {'x': 5, 'y': None}

    By default, extra keys not defined in the schema are not allowed.
    To allow extra keys, set `extra_keys=True` in the class definition.

    >>> class MySchema(SDict, extra_keys=True):
    >>>    x: int
    ...
    >>> data = MySchema(x=5, z=10)
    >>> print(data)
    {'x': 5, 'z': 10}
    """

    def __init_subclass__(cls, /, **kwargs) -> None:
        strict: bool = kwargs.pop("strict", False)
        schema: dict = kwargs.pop("schema", {})
        extra_keys: bool = kwargs.pop("extra_keys", False)
        recommendation = RequirementLevel(kwargs.pop(
            "recommendation",
            RequirementLevel.required
        ))

        def get_requirement(hint: t.Any) -> RequirementLevel:
            args = t.get_args(t.Annotated[hint, None])
            for arg in args:
                if isinstance(arg, RequirementLevel):
                    return arg
            return recommendation

        requirements = {}
        defaults: dict = {}

        bases = (cls,)
        while bases:
            # Update schema from current bases
            for base in reversed(bases):
                # Get base schema
                base_schema = dict(getattr(base, "__schema__", {}))
                base_schema.update(getattr(base, "__annotations__", {}))

                # Update requirements
                base_requirements = dict(getattr(base, "__requirements__", {}))
                for key in base_schema:
                    hint = base_schema[key]
                    base_requirements.setdefault(key, get_requirement(hint))
                base_requirements.update(requirements)
                requirements = base_requirements

                # Update schema
                base_schema.update(schema)
                schema = base_schema

                # Update defaults
                base_defaults = dict(getattr(base, "__defaults__", {}))
                for key, value in base.__dict__.items():
                    if key in base_schema:
                        base_defaults[key] = value
                base_defaults.update(defaults)
                defaults = base_defaults

            # Build next bases
            new_bases = ()
            for base in bases:
                for base_base in base.__bases__:
                    if base_base not in new_bases:
                        new_bases += (base_base,)
            bases = new_bases

        super().__init_subclass__(**kwargs)
        cls.__schema__ = schema
        cls.__strict__ = strict
        cls.__defaults__ = defaults
        cls.__extra_keys__ = extra_keys
        cls.__requirements__ = requirements

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._assign_defaults()
        self._check_requirements()
        self._adapt()

    def _adapt(self) -> None:
        cls = type(self)
        for key, val in list(self.items()):
            if key not in cls.__schema__:
                continue
            hint = cls.__schema__[key]
            adaptor = Adaptor(hint)
            self[key] = adaptor(val)

    def _assign_defaults(self) -> None:
        cls = type(self)
        for key, val in cls.__defaults__.items():
            if key not in self:
                self[key] = val
        for key, val in cls.__schema__.items():
            if key not in self:
                args = t.get_args(t.Annotated[val, None])
                for arg in args:
                    if isinstance(arg, Default):
                        self[key] = arg()
                        break

    def _check_requirements(self) -> None:
        cls = type(self)

        # Check extra keys
        if not cls.__extra_keys__:
            for key in self.keys():
                if key not in cls.__schema__:
                    raise KeyError(f"Key '{key}' not defined in schema")

        # Check missing keys
        for key, req in cls.__requirements__.items():

            if key in self:
                if req == RequirementLevel.proscribed:
                    raise ValueError(f"Key '{key}' is proscribed")
                elif cls.__strict__:
                    if req == RequirementLevel.not_recommended:
                        raise ValueError(f"Key '{key}' is not recommended")
                    if req == RequirementLevel.deprecated:
                        raise ValueError(f"Key '{key}' is deprecated")

            else:

                if req == RequirementLevel.required:
                    raise KeyError(f"Key '{key}' is required but missing")
                elif cls.__strict__:
                    if req == RequirementLevel.recommended:
                        raise Warning(
                            f"Key '{key}' is recommended but missing"
                        )

    def __setitem__(self, name: t.Any, value: t.Any) -> None:
        cls = type(self)
        if name in cls.__schema__:
            hint = cls.__schema__[name]
            adaptor = Adaptor(hint)
            value = adaptor(value)
            for arg in t.get_args(t.Annotated[hint, None]):
                if isinstance(arg, Adaptor):
                    value = arg(value)
            super().__setitem__(name, value)
        elif cls.__extra_keys__:
            super().__setitem__(name, value)
        else:
            raise AttributeError(f"Attribute '{name}' not defined in schema")

    def __delitem__(self, key):
        cls = type(self)
        req = cls.__requirements__.get(key, None)
        if req == RequirementLevel.required:
            raise ValueError(
                f"Key '{key}' is required and cannot be deleted"
            )
        if cls.__strict__ and req == RequirementLevel.recommended:
            raise ValueError(
                f"Key '{key}' is recommended and cannot be deleted"
            )
        return super().__delitem__(key)

    def __getattr__(self, name: t.Any) -> t.Any:
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(f"Attribute '{name}' not found") from e

    def update(self, *args, **kwargs) -> None:
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def clear(self) -> None:
        cls = type(self)
        if cls.__strict__:
            if any(
                isinstance(req, RequirementLevel.recommended)
                for req in cls.__requirements__.values()
            ):
                raise ValueError(
                    "Cannot clear SDict with required or recommended keys"
                )
        elif any(
            isinstance(req, RequirementLevel.required)
            for req in cls.__requirements__.values()
        ):
            raise ValueError("Cannot clear SDict with required keys")

        super().clear()

    def pop(self, key: t.Any, default: t.Any = None) -> t.Any:
        cls = type(self)
        req = cls.__requirements__.get(key, None)
        if req == RequirementLevel.required:
            raise ValueError(
                f"Key '{key}' is required and cannot be deleted"
            )
        if cls.__strict__ and req == RequirementLevel.recommended:
            raise ValueError(
                f"Key '{key}' is recommended and cannot be deleted"
            )
        return super().pop(key, default)

    def popitem(self) -> tuple[t.Any, t.Any]:
        cls = type(self)
        if len(self) == 0:
            raise KeyError("popitem(): dictionary is empty")
        lastkey = next(reversed(iter(self.keys())))
        req = cls.__requirements__.get(lastkey, None)
        if req == RequirementLevel.required:
            raise ValueError(
                f"Key '{lastkey}' is required and cannot be deleted"
            )
        if cls.__strict__ and req == RequirementLevel.recommended:
            raise ValueError(
                f"Key '{lastkey}' is recommended and cannot be deleted"
            )
        return super().popitem()

    def setdefault(self, key: t.Any, default: t.Any = None) -> t.Any:
        if key not in self:
            self[key] = default
        return self[key]
