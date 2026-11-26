"""Semantic versions, as used by BIDS.

`BIDSVersion` and the BIDS schema versions are semver: `X.Y.Z` with an
optional pre-release suffix (`1.10.0-dev`, `0.7.3-dev`) and optional build
metadata (`1.2.3+abc`). This module parses and compares such versions and
tests them against simple specifiers (`>=1.8`, `<2`, `==1.9.*`,
`>=1.8, <2`).

Ordering follows semver precedence: a pre-release sorts before its release
(`1.10.0-dev < 1.10.0`), and build metadata is ignored. A version or
specifier may omit trailing components, which default to zero
(`1.8` is `1.8.0`).
"""
import re
from functools import total_ordering

_VERSION = re.compile(
    r"""
    v?\s*
    (?P<release>[0-9]+(?:\.[0-9]+){0,2})
    (?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?
    (?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?
    """,
    re.VERBOSE,
)

_WILDCARD = re.compile(r"v?\s*(?P<prefix>[0-9]+(?:\.[0-9]+){0,1})\.\*")

COMPARATORS = ("==", "!=", ">=", "<=", ">", "<")


@total_ordering
class Version:
    """A semantic version `X.Y.Z[-pre][+build]`."""

    def __init__(self, version: "str | tuple[int | str, ...] | Version") -> None:
        if isinstance(version, Version):
            self.release, self.pre, self.build = (
                version.release, version.pre, version.build
            )
            return
        if isinstance(version, tuple):
            version = ".".join(map(str, version))
        match = _VERSION.fullmatch(str(version).strip())
        if not match:
            raise ValueError(f"Invalid version: {version!r}")
        release = tuple(int(x) for x in match["release"].split("."))
        self.release: tuple[int, int, int] = (release + (0, 0))[:3]
        self.pre: str | None = match["pre"]
        self.build: str | None = match["build"]

    @property
    def major(self) -> int:
        return self.release[0]

    @property
    def minor(self) -> int:
        return self.release[1]

    @property
    def patch(self) -> int:
        return self.release[2]

    def _key(self) -> tuple:
        if self.pre is None:
            # A release sorts after all of its pre-releases
            return (self.release, (1,))
        ids = tuple(
            (0, int(x), "") if x.isdigit() else (1, 0, x)
            for x in self.pre.split(".")
        )
        return (self.release, (0, ids))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (str, tuple)):
            other = Version(other)
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other: object) -> bool:
        if isinstance(other, (str, tuple)):
            other = Version(other)
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __str__(self) -> str:
        version = ".".join(map(str, self.release))
        if self.pre is not None:
            version += "-" + self.pre
        if self.build is not None:
            version += "+" + self.build
        return version

    def __repr__(self) -> str:
        return f"Version({str(self)!r})"


def normalize_version_string(version: "str | tuple[int | str, ...]") -> str:
    """Return the canonical spelling of a version (`v01.2` -> `1.2.0`)."""
    return str(Version(version))


def is_version_valid(version: str, is_spec: bool = False) -> bool:
    """Whether `version` is a valid version (or a wildcard if `is_spec`)."""
    if is_spec and _WILDCARD.fullmatch(str(version).strip()):
        return True
    return bool(_VERSION.fullmatch(str(version).strip()))


def split_specifiers(specifier: str) -> list[tuple[str, str]]:
    """Split `">=1.8, <2"` into `[(">=", "1.8"), ("<", "2")]`.

    A bare version means `==`.
    """
    out = []
    for spec in specifier.split(","):
        spec = spec.strip()
        if not spec:
            continue
        for comparator in COMPARATORS:
            if spec.startswith(comparator):
                spec = spec[len(comparator):].strip()
                break
        else:
            comparator = "=="
        out.append((comparator, spec))
    if not out:
        raise ValueError(f"Empty version specifier: {specifier!r}")
    return out


def compare_versions(
    version: "Version | str | tuple[int | str, ...]",
    comparator: str,
    spec_version: "Version | str | tuple[int | str, ...]",
) -> bool:
    """Test `version <comparator> spec_version`.

    `spec_version` may end with `.*` (`1.9.*`) with `==` and `!=`: it then
    matches every version, pre-releases included, whose release starts
    with that prefix.
    """
    version = Version(version)

    wildcard = (
        _WILDCARD.fullmatch(spec_version.strip())
        if isinstance(spec_version, str) else None
    )
    if wildcard:
        if comparator not in ("==", "!="):
            raise ValueError(
                f"Wildcards are only allowed with == and !=: "
                f"{comparator}{spec_version}"
            )
        prefix = tuple(int(x) for x in wildcard["prefix"].split("."))
        match = version.release[:len(prefix)] == prefix
        return match if comparator == "==" else not match

    spec_version = Version(spec_version)
    if comparator == "==":
        return version == spec_version
    if comparator == "!=":
        return version != spec_version
    if comparator == ">=":
        return version >= spec_version
    if comparator == "<=":
        return version <= spec_version
    if comparator == ">":
        return version > spec_version
    if comparator == "<":
        return version < spec_version
    raise ValueError(f"Unknown comparator: {comparator!r}")


def version_is_satisfied(
    specifier: str,
    version: "Version | str | tuple[int | str, ...]",
) -> bool:
    """Whether `version` satisfies every comma-separated specifier."""
    return all(
        compare_versions(version, comparator, spec)
        for comparator, spec in split_specifiers(specifier)
    )
