import typing as t
from types import GenericAlias


class RequirementLevel:

    optional: t.ClassVar["RequirementLevel"]
    recommended: t.ClassVar["RequirementLevel"]
    required: t.ClassVar["RequirementLevel"]
    not_recommended: t.ClassVar["RequirementLevel"]
    deprecated: t.ClassVar["RequirementLevel"]
    proscribed: t.ClassVar["RequirementLevel"]

    def __new__(
        cls, value: t.Union[str, "RequirementLevel"]
    ) -> "RequirementLevel":
        if isinstance(value, RequirementLevel):
            return value
        elif value == "optional":
            return cls.optional
        elif value == "recommended":
            return cls.recommended
        elif value == "required":
            return cls.required
        elif value == "not_recommended":
            return cls.not_recommended
        elif value == "deprecated":
            return cls.deprecated
        elif value == "proscribed":
            return cls.proscribed
        else:
            raise ValueError(f"Invalid RequirementLevel: {value!r}")

    def __repr__(self) -> str:
        mod = self.__module__
        cls = self.__class__.__name__
        name = {
            self.optional: "optional",
            self.recommended: "recommended",
            self.required: "required",
            self.not_recommended: "not_recommended",
            self.deprecated: "deprecated",
            self.proscribed: "proscribed",
        }
        return f"{mod}.{cls}.{name.get(self, 'unknown')}"

    def __str__(self) -> str:
        return {
            self.optional: "optional",
            self.recommended: "recommended",
            self.required: "required",
            self.not_recommended: "not_recommended",
            self.deprecated: "deprecated",
            self.proscribed: "proscribed",
        }.get(self, "unknown")


def _new_singleton(cls):
    if cls._instance is None:
        cls._instance = object.__new__(cls)
    return cls._instance


def _make_dict():
    return {"_instance": None, "__new__": _new_singleton}


OptionalType = type("OptionalType", (RequirementLevel,), _make_dict())
RecommendedType = type("RecommendedType", (RequirementLevel,), _make_dict())
RequiredType = type("RequiredType", (RecommendedType,), _make_dict())
NotRecommendedType = type("NotRecommendedType", (RequirementLevel,), _make_dict())  # noqa: E501
DeprecatedType = type("DeprecatedType", (NotRecommendedType,), _make_dict())
ProscribedType = type("ProscribedType", (NotRecommendedType,), _make_dict())

optional = RequirementLevel.optional = OptionalType()
recommended = RequirementLevel.recommended = RecommendedType()
required = RequirementLevel.required = RequiredType()
not_recommended = RequirementLevel.not_recommended = NotRecommendedType()
deprecated = RequirementLevel.deprecated = DeprecatedType()
proscribed = RequirementLevel.proscribed = ProscribedType()

Optional = t.Annotated[t.T, optional]
Recommended = t.Annotated[t.T, recommended]
Required = t.Annotated[t.T, required]
NotRecommended = t.Annotated[t.T, recommended]
Deprecated = t.Annotated[t.T, deprecated]
Proscribed = t.Annotated[t.T, proscribed]

RequiredIf = GenericAlias(
    type("RequiredIf", (RequirementLevel,), {}),
    (t.TypeVar("Cond"), )
)
RecommendedIf = GenericAlias(
    type("RecommendedIf", (RequirementLevel,), {}),
    (t.TypeVar("Cond"), )
)
ProscribedIf = GenericAlias(
    type("ProscribedIf", (RequirementLevel,), {}),
    (t.TypeVar("Cond"), )
)
NotRecommendedIf = GenericAlias(
    type("NotRecommendedIf", (RequirementLevel,), {}),
    (t.TypeVar("Cond"), )
)
