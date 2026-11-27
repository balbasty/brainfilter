"""Conditions that test a path or a label: globs, regexes and their combinations.

A condition is a callable that takes a value (a string or a path) and
returns whether it matches. `Glob` and `Regex` test one pattern; `And`
and `Or` combine conditions; `Globish` and `Regexish` build a single
condition, or an any-of, from one or several patterns.
"""
import fnmatch
import os
import re
from functools import reduce
from pathlib import Path
from typing import Iterator


class NotACondition:
    """Placeholder for a value that is not a condition: raises when built."""

    class Error(TypeError):
        """Raised when a value cannot be used as a condition."""

    def __init__(self, *args) -> None:
        raise self.Error("Not a condition:", *args)


class NotAGlob(NotACondition):
    """Placeholder for a value that is not a glob: raises when built."""

    class Error(NotACondition.Error):
        """Raised when a value cannot be used as a glob."""

    def __init__(self, *args) -> None:
        raise self.Error("Not a glob:", *args)


class NotARegex(NotACondition):
    """Placeholder for a value that is not a regex: raises when built."""

    class Error(NotACondition.Error):
        """Raised when a value cannot be used as a regex."""

    def __init__(self, *args) -> None:
        raise self.Error("Not a regex:", *args)


class Not:
    """The opposite of a filter value: `BidsFilter(sub=Not("02"))`.

    It takes any value a filter keyword takes (a value, a set, a glob, a
    regex, a test, `typing.Never` or `typing.Any`) and keeps what that
    value does not. On an entity, a file without the entity passes
    `Not(x)` unless `x` matches such a file (`Never` among its values), so
    `Not(Never)` keeps the files that have the entity. `Not(Not(x))` is
    `x`.
    """

    def __new__(cls, value: object) -> object:
        """Build the opposite of `value`; `Not(Not(x))` is `x`."""
        if isinstance(value, Not):
            return value.value
        self = super().__new__(cls)
        self.value = value
        return self

    def __repr__(self) -> str:
        return f"Not({self.value!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Not) and other.value == self.value

    def __hash__(self) -> int:
        return hash(("Not", repr(self.value)))


class Condition:
    """Base class of all conditions: a test applied to a path or a string."""

    def __call__(self, value: str | Path) -> bool:
        """Check whether a path fulfills the condition."""
        return NotImplemented


class Regexish(Condition):
    """A regex, or any-of (`Or`) several regexes.

    `Regexish("a", "b")` matches a value that matches `a` or `b`, the same
    rule as `Globish`. `full=` is passed on to each `Regex`, including one
    given already built (`Regexish(Regex("a"), full=True)`) that did not
    choose for itself; a `Regex` built with an explicit `full=` keeps it.
    """

    def __new__(cls, *args, **kwargs) -> "Regexish":
        """Build a `Regex`, or an `Or` of regexes when given several."""
        if cls is not Regexish:
            return super().__new__(cls)
        elif len(args) > 1:
            return Or(*(Regexish(arg, **kwargs) for arg in args))
        elif len(args) == 0:
            raise ValueError("At least one argument required")
        elif isinstance(args[0], Condition):
            return default_full(args[0], kwargs.get("full"))
        else:
            return Regex(args[0], **kwargs)


class Regex(Regexish):
    """A regex condition.

    With `full=True` it must match the whole value (`re.Pattern.fullmatch`);
    with `full=False` it matches a value it is found anywhere in
    (`re.Pattern.search`). The default, `full=None`, leaves the choice to
    where the regex is used: it searches, except where a whole value is
    expected, such as a label filter of `brainfilter.BidsFilter`.
    """

    def __init__(
        self, pattern: re.Pattern | str, full: bool | None = None
    ) -> None:
        if pattern is self:
            # `Regexish(regex)` returned `regex`, which Python re-initializes
            return
        if isinstance(pattern, Regex):
            if full is None:
                full = pattern.full
            pattern = pattern.pattern
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        self.pattern = pattern
        self.full = full

    def __str__(self) -> str:
        return str(self.pattern)

    def __repr__(self) -> str:
        if self.full is not None:
            return f"Regex({str(self)}, full={self.full})"
        return f"Regex({str(self)})"

    def __call__(self, value: str | Path) -> bool:
        """Check whether the value matches the regex."""
        if self.full:
            return self.pattern.fullmatch(str(value)) is not None
        return self.pattern.search(str(value)) is not None


def default_full(cond: Condition, full: bool | None) -> Condition:
    """Give `full` to the regexes in `cond` that left it to their caller.

    A `Regex` whose `full` is `None` becomes one with `full`; one with an
    explicit `full` is kept. `And` and `Or` are rebuilt around their
    conditions; any other condition is returned as it is.
    """
    if full is None:
        return cond
    if isinstance(cond, Regex):
        return cond if cond.full is not None else Regex(cond.pattern, full=full)
    if type(cond) in (And, Or):
        return type(cond)(*(default_full(c, full) for c in cond.cond))
    return cond


class Globish(Condition):
    """A glob, or any-of (`OrGlob`) several globs.

    `Globish("a", "b")` matches a value that matches `a` or `b`, the same
    rule as `Regexish`.
    """

    def __new__(cls, *args) -> "Globish":
        """Build a `Glob`, or an `OrGlob` of globs when given several."""
        if cls is not Globish:
            return super().__new__(cls)
        elif len(args) > 1:
            return OrGlob(*map(Globish, args))
        elif len(args) == 0:
            raise ValueError("At least one argument required")
        elif isinstance(args[0], Condition):
            return args[0]
        else:
            return Glob(args[0])


class Glob(Globish):
    """A glob condition, matched with `fnmatch`.

    A pattern that starts with `/` is anchored at the filesystem root;
    any other pattern is relative to the current directory when iterated.
    """

    def __init__(self, pattern: str | Path) -> None:
        if pattern is self:
            # `Globish(glob)` returned `glob`, which Python re-initializes
            return
        if isinstance(pattern, Glob):
            pattern = str(pattern)
        pattern = str(pattern)
        if pattern[:1] in ("/", os.sep):
            root = Path("/")
            pattern = pattern[1:]
        else:
            root = Path(".")
        self.pattern = pattern
        self.root = root

    def __str__(self) -> str:
        return str(self.root / self.pattern)

    def __repr__(self) -> str:
        return f"Glob({str(self)})"

    def __call__(self, value: str | Path) -> bool:
        """Check whether the value matches the glob."""
        return fnmatch.fnmatch(str(value), str(self))

    def __iter__(self) -> Iterator[Path]:
        """Iterate over paths in the glob."""
        yield from self.root.glob(self.pattern)

    def __truediv__(self, other: str | Path | Globish) -> Globish:
        """Append a path or glob pattern to this glob."""
        if isinstance(other, OrGlob):
            return OrGlob(*(self / cond for cond in other.cond))
        if isinstance(other, Glob):
            other = other.pattern
        if isinstance(other, (str, Path)):
            return Glob(self.root / self.pattern / other)
        return NotImplemented

    def __rtruediv__(self, other: str | Path) -> Globish:
        """Prepend a path (e.g., a dataset root) to this glob."""
        if isinstance(other, (str, Path)):
            return Glob(Path(other) / self.pattern)
        return NotImplemented


def _as_conditions(cond: tuple, self: Condition) -> list[Condition]:
    """Coerce patterns to conditions (str -> Glob, re.Pattern -> Regex)."""
    if len(cond) == 1 and cond[0] is self:
        # `Globish(obj)` returned `obj`, which Python re-initializes
        return self.cond
    return [
        c if isinstance(c, Condition) else
        Regex(c) if isinstance(c, re.Pattern) else
        Glob(c) if isinstance(c, (str, Path)) else
        NotACondition(c)
        for c in cond
    ]


class And(Condition):
    """All-of: matches a value that matches every condition."""

    def __init__(self, *cond: Condition | re.Pattern | str) -> None:
        self.cond = _as_conditions(cond, self)

    def __call__(self, value: str | Path) -> bool:
        """Check whether the value matches every condition."""
        return all(cond(value) for cond in self.cond)


class Or(Condition):
    """Any-of: matches a value that matches at least one condition."""

    def __init__(self, *cond: Condition | re.Pattern | str) -> None:
        self.cond = _as_conditions(cond, self)

    def __call__(self, value: str | Path) -> bool:
        """Check whether the value matches at least one condition."""
        return any(cond(value) for cond in self.cond)


class OrGlob(Or, Globish):
    """Any-of several globs; iterating yields the union of their paths."""

    def __init__(self, *cond) -> None:
        super().__init__(*cond)
        if not all(isinstance(cond, Globish) for cond in self.cond):
            raise NotAGlob.Error("All conditions must be globs")

    def __truediv__(self, other: str | Path | Globish) -> Globish:
        """Append a path or glob pattern to each glob."""
        return OrGlob(*(cond / other for cond in self.cond))

    def __rtruediv__(self, other: str | Path) -> Globish:
        """Prepend a path (e.g., a dataset root) to each glob."""
        if isinstance(other, (str, Path)):
            return OrGlob(*(other / cond for cond in self.cond))
        return NotImplemented

    def __iter__(self) -> Iterator[Path]:
        """Iterate over the union of all glob patterns."""
        yield from set(path for cond in self.cond for path in cond)


class AndGlob(And, Globish):
    """All-of several globs; iterating yields the intersection of their paths."""

    def __init__(self, *cond) -> None:
        super().__init__(*cond)
        if not all(isinstance(cond, Globish) for cond in self.cond):
            raise NotAGlob.Error("All conditions must be globs")

    def __iter__(self) -> Iterator[Path]:
        """Iterate over the intersection of all glob patterns."""
        yield from reduce(set.intersection, map(set, self.cond))
