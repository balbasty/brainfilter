"""Semantic versions, as used by BIDS.

`BIDSVersion` and the BIDS schema versions are semver: `X.Y.Z` with an
optional pre-release suffix (`1.10.0-dev`, `0.7.3-dev`) and optional build
metadata (`1.2.3+abc`). This module parses and compares such versions and
tests them against simple specifiers (`>=1.8`, `<2`, `==1.9.*`,
`>=1.8, <2`).

Two rules, one per kind of operation:

* **Ordering** (`<`, `==`, `sorted`, ... on `Version`) follows semver
  precedence: a pre-release sorts before its release
  (`Version("1.10.0-dev") < Version("1.10.0")`).
* **Specifier tests** (`compare_versions`, `version_is_satisfied`) compare
  releases only: a pre-release or dev version counts as its release.
  `1.10.0-dev` satisfies `>=1.10` and `==1.10.*`, and does not satisfy
  `<1.10`. A pre-release written in a specifier (`>=1.10.0-rc1`) would be
  ambiguous under that rule, so it is refused with a `ValueError`.

Build metadata is ignored by both. A version or specifier may omit
trailing components, which default to zero (`1.8` is `1.8.0`).

A `Version` compares equal only to another `Version`, never to a string
or a tuple: `Version("1.0") == "1.0"` is False, and ordering against a
string raises `TypeError`. Equal spellings (`"1.0"`, `"v1.0.0"`) cannot all
share one hash, so comparing with strings would break sets and dicts.
Convert first: `Version("1.0") == Version("1.0.0")`. This matches
`packaging.version.Version`.
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
    """A semantic version `X.Y.Z[-pre][+build]`.

    Built from a string (`"1.10.0-dev"`), a tuple (`(1, 10, 0)`) or another
    `Version`. A number is refused with a `TypeError`: `1.10` is the float
    `1.1`, so it cannot be read back as the version it was meant to be.

    Versions compare and hash with each other only (see the module
    docstring); comparing with anything else is unequal, and ordering
    against it raises `TypeError`.
    """

    def __init__(self, version: "str | tuple[int | str, ...] | Version") -> None:
        if isinstance(version, Version):
            self.release, self.pre, self.build = (
                version.release, version.pre, version.build
            )
            return
        if isinstance(version, tuple):
            version = ".".join(map(str, version))
        if not isinstance(version, str):
            raise TypeError(
                f"A version must be a string, a tuple or a Version, "
                f"not {type(version).__name__}: {version!r}. Write it as a "
                f"string, e.g. Version(\"1.10.0\")"
            )
        match = _VERSION.fullmatch(version.strip())
        if not match:
            raise ValueError(f"Invalid version: {version!r}")
        release = tuple(int(x) for x in match["release"].split("."))
        self.release: tuple[int, int, int] = (release + (0, 0))[:3]
        self.pre: str | None = match["pre"]
        self.build: str | None = match["build"]

    @property
    def major(self) -> int:
        """The major release number."""
        return self.release[0]

    @property
    def minor(self) -> int:
        """The minor release number."""
        return self.release[1]

    @property
    def patch(self) -> int:
        """The patch release number."""
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
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self) -> int:
        # Consistent with __eq__: equal versions share a key (build ignored)
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

    A bare version means `==`. An empty specifier, or an empty segment
    between commas (`">=1.8,,<2"`, `",<2"`, `">=1.8,"`), raises
    `ValueError`.
    """
    if not specifier.strip():
        raise ValueError(f"Empty version specifier: {specifier!r}")
    out = []
    for spec in specifier.split(","):
        spec = spec.strip()
        if not spec:
            raise ValueError(
                f"Empty segment in version specifier: {specifier!r}"
            )
        for comparator in COMPARATORS:
            if spec.startswith(comparator):
                spec = spec[len(comparator):].strip()
                break
        else:
            comparator = "=="
        out.append((comparator, spec))
    return out


def compare_versions(
    version: "Version | str | tuple[int | str, ...]",
    comparator: str,
    spec_version: "Version | str | tuple[int | str, ...]",
) -> bool:
    """Test `version <comparator> spec_version`.

    Only releases are compared: a pre-release counts as its release
    (`1.10.0-dev` satisfies `>=1.10` and `==1.10.0`). A pre-release in
    `spec_version` (`1.10.0-rc1`) raises `ValueError`, since it is
    ambiguous under that rule; write the release (`1.10.0`) instead.

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

    spec_parsed = Version(spec_version)
    if spec_parsed.pre is not None:
        raise ValueError(
            f"Pre-releases are not allowed in a version specifier: "
            f"{comparator}{spec_version}. A pre-release version counts as "
            f"its release when tested, so write the release instead: "
            f"{comparator}{'.'.join(map(str, spec_parsed.release))}"
        )
    release, spec = version.release, spec_parsed.release
    if comparator == "==":
        return release == spec
    if comparator == "!=":
        return release != spec
    if comparator == ">=":
        return release >= spec
    if comparator == "<=":
        return release <= spec
    if comparator == ">":
        return release > spec
    if comparator == "<":
        return release < spec
    raise ValueError(f"Unknown comparator: {comparator!r}")


def version_is_satisfied(
    specifier: str,
    version: "Version | str | tuple[int | str, ...]",
) -> bool:
    """Whether `version` satisfies every comma-separated specifier.

    A pre-release counts as its release, and a pre-release in `specifier`
    raises `ValueError` (see `compare_versions`). Every segment is checked,
    even once one has failed.
    """
    return all([
        compare_versions(version, comparator, spec)
        for comparator, spec in split_specifiers(specifier)
    ])
