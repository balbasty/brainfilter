import fnmatch
import os
import re
from functools import reduce
from pathlib import Path
from typing import Iterator


class NotACondition:

    class Error(TypeError):
        ...

    def __init__(self, *args) -> None:
        raise self.Error("Not a condition:", *args)


class NotAGlob(NotACondition):

    class Error(NotACondition.Error):
        ...

    def __init__(self, *args) -> None:
        raise self.Error("Not a glob:", *args)


class NotARegex(NotACondition):

    class Error(NotACondition.Error):
        ...

    def __init__(self, *args) -> None:
        raise self.Error("Not a regex:", *args)


class Condition:

    def __call__(self, value: str | Path) -> bool:
        """Check whether a path fullfills the condition."""
        return NotImplemented


class Regexish(Condition):
    """A regex, or any-of (`Or`) several regexes.

    `Regexish("a", "b")` matches a value that matches `a` or `b`, the same
    rule as `Globish`. `full=True` is passed on to each `Regex`.
    """

    def __new__(cls, *args, **kwargs) -> "Regexish":
        if cls is not Regexish:
            return super().__new__(cls)
        elif len(args) > 1:
            return Or(*(Regexish(arg, **kwargs) for arg in args))
        elif len(args) == 0:
            raise ValueError("At least one argument required")
        elif isinstance(args[0], Condition):
            return args[0]
        else:
            return Regex(args[0], **kwargs)


class Regex(Regexish):
    """A regex condition.

    By default it matches a value it is found anywhere in
    (`re.Pattern.search`); with `full=True` it must match the whole value
    (`re.Pattern.fullmatch`).
    """

    def __init__(self, pattern: re.Pattern | str, full: bool = False) -> None:
        if pattern is self:
            # `Regexish(regex)` returned `regex`, which Python re-initializes
            return
        if isinstance(pattern, Regex):
            pattern = pattern.pattern
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        self.pattern = pattern
        self.full = full

    def __str__(self) -> str:
        return str(self.pattern)

    def __repr__(self) -> str:
        if self.full:
            return f"Regex({str(self)}, full=True)"
        return f"Regex({str(self)})"

    def __call__(self, value: str | Path) -> bool:
        if self.full:
            return self.pattern.fullmatch(str(value)) is not None
        return self.pattern.search(str(value)) is not None


class Globish(Condition):
    """A glob, or any-of (`OrGlob`) several globs.

    `Globish("a", "b")` matches a value that matches `a` or `b`, the same
    rule as `Regexish`.
    """

    def __new__(cls, *args) -> "Globish":
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

    def __init__(self, *cond: Condition | re.Pattern | str) -> None:
        self.cond = _as_conditions(cond, self)

    def __call__(self, value: str | Path) -> bool:
        return all(cond(value) for cond in self.cond)


class Or(Condition):

    def __init__(self, *cond: Condition | re.Pattern | str) -> None:
        self.cond = _as_conditions(cond, self)

    def __call__(self, value: str | Path) -> bool:
        return any(cond(value) for cond in self.cond)


class OrGlob(Or, Globish):

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

    def __init__(self, *cond) -> None:
        super().__init__(*cond)
        if not all(isinstance(cond, Globish) for cond in self.cond):
            raise NotAGlob.Error("All conditions must be globs")

    def __iter__(self) -> Iterator[Path]:
        """Iterate over the intersection of all glob patterns."""
        yield from reduce(set.intersection, map(set, self.cond))
