# PEP440-compliant versioning utilities
import operator
from types import GenericAlias
from typing import Callable, TypeVar, get_args, get_origin


class Version(tuple):
    ...


VersionSpecifier = GenericAlias(
    type("VersionSpecifier", (), {}),
    (TypeVar("Spec"), )
)

VersionSwitch = GenericAlias(
    type("VersionSpecifier", (), {}),
    (TypeVar("Cond"), TypeVar("A"), TypeVar("B"))
)


def normalize_version_string(version: str | tuple[int | str, ...]) -> str:
    # https://peps.python.org/pep-0440/#normalization
    if isinstance(version, tuple):
        version = ".".join(map(str, version))
    version = str(version)
    version, *local = version.split("+", 1)
    version = version.strip().lower()
    # Preceding v
    if version[:1] == "v":
        version = version[1:]
    # Standardize separators
    version = version.replace(" ", "")
    version = version.replace("-", ".")
    version = version.replace("_", ".")
    # Alternative spellings
    version = version.replace("alpha", "a")
    version = version.replace("beta", "b")
    version = version.replace("preview", "rc")
    version = version.replace("pre", "rc")
    version = version.replace("c", "rc").replace("rrc", "rc")
    version = version.replace("rev", "post")
    version = version.replace("r", "post").replace("postc", "rc")
    # Remove dots before pre-release tags
    version = version.replace(".a", "a")
    version = version.replace(".b", "b")
    version = version.replace(".rc", "rc")
    # Insert dot before post-release tags
    version = version.replace("d", ".d").replace("..d", ".d")
    version = version.replace("p", ".p").replace("..p", ".p")
    # Normalize integers + implicit zeros
    parts = version.split(".")
    dig = "0123456789*"
    parts = [
        p
        if "*" in p
        else
        (
            str(int(p[:-len(p.lstrip(dig))] or "0")) +
            p.strip(dig) +
            str(int(p[len(p.rstrip(dig)):] or "0"))
        )
        if any(c in p for c in {"a", "b", "rc"})
        else
        (
            p.strip(dig) +
            str(int(p[len(p.rstrip(dig)):] or "0"))
        )
        if any(p.startswith(x) for x in {"post", "dev"})
        else
        str(int(p)) if p.isdigit()
        else
        p
        for p in parts
    ]
    version = ".".join(parts)
    # Reattach local version
    if local:
        local = local[0].strip()
        local = local.replace(" ", "")
        local = local.replace("-", ".")
        local = local.replace("_", ".")
        version += "+" + local.strip()
    return version


def version_string_to_tuple(version: str) -> tuple[int | str, ...]:
    # Normalize version string
    version = normalize_version_string(version)

    # Split local version (and keep "+" as a separator)
    version, *local = version.split("+", 1)

    # Insert separators before pre-release
    version = version.replace("a", ".a")
    version = version.replace("b", ".b")
    version = version.replace("rc", ".rc")

    if local:
        version = (version, "+", local[0])
    else:
        version = (version,)

    # Split across separators
    version = (vv for v in version for vv in v.split("."))
    version = (int(v) if v.isdigit() else v for v in version)
    version = tuple(version)
    return version


def is_version_valid(version: str, is_spec: bool = False) -> bool:
    # https://peps.python.org/pep-0440/#summary-of-permitted-suffixes-and-relative-ordering

    # Normalize version string
    version = normalize_version_string(version)

    # Remove local version
    version = version.split("+", 1)[0]

    # Insert separators before pre-release
    version = version.replace("a", ".a")
    version = version.replace("b", ".b")
    version = version.replace("rc", ".rc")

    # Split across separators
    parts = version.split(".")

    prerelease = prerelease_number = None
    postrelease = postrelease_number = None
    devrelease = devrelease_number = None

    for part in parts:
        part = part.strip()

        # Empty
        if not part:
            return False

        # Pre-release
        has_prerelease = any(x in part for x in {"a", "b", "rc"})
        if has_prerelease:
            if prerelease or postrelease or devrelease:
                return False

            if "a" in part:
                prerelease = "a"
                part, prerelease_number = part.split("a", 1)
            elif "b" in part:
                prerelease = "b"
                part, prerelease_number = part.split("b", 1)
            elif "rc" in part:
                prerelease = "rc"
                part, prerelease_number = part.split("rc", 1)

            if prerelease_number == "*" and is_spec:
                continue
            if not prerelease_number.isdigit():
                return False

            continue

        # Post-release
        has_postrelease = part.startswith("post")
        if has_postrelease:
            if postrelease or devrelease:
                return False

            postrelease = "post"
            part, postrelease_number = "", part[4:]
            if postrelease_number == "*" and is_spec:
                continue
            if not postrelease_number.isdigit():
                return False

            continue

        # Dev-release
        has_devrelease = part.startswith("dev")
        if has_devrelease:
            if devrelease:
                return False

            devrelease = "dev"
            part, devrelease_number = "", part[3:]
            if devrelease_number == "*" and is_spec:
                continue
            if not devrelease_number.isdigit():
                return False

            continue

        # Version segment
        if prerelease or postrelease or devrelease:
            return False

        if part == "*" and is_spec:
            continue
        if not part.isdigit():
            return False

    return True


def split_specifiers(specifier: str) -> list[tuple[str, str]]:
    """Split a version specifier string into individual specifiers."""
    specifiers = specifier.split(",")
    specifiers = [s.strip() for s in specifiers if s.strip()]

    comparators, versions = [], []
    for specifier in specifiers:
        if specifier[:2] in {">=", "<=", "~=", "!=", "==", "^="}:
            comparator = specifier[:2]
            specifier = specifier[2:].strip()
        elif specifier[:1] in {">", "<", "=", "^", "~"}:
            comparator = specifier[:1]
            specifier = specifier[1:].strip()
        else:
            comparator = "=="
        comparators.append(comparator)
        versions.append(specifier)

    return list(zip(comparators, versions))


def version_is_satisfied(
    specifier: type | str,
    version: Version | tuple[int | str, ...]
) -> bool:
    """Check if a version satisfies a version specifier."""

    # Normalize inputs
    if get_origin(specifier) is get_origin(VersionSpecifier):
        specifier = get_args(specifier)[0]

    # Parse specifiers
    specifiers = split_specifiers(specifier)
    comparators, versions = zip(*specifiers)

    # Normalize versions and convert to comparable tuples
    version = version_string_to_tuple(version)
    versions = map(version_string_to_tuple, versions)

    # Test each specifier
    for comp, v in zip(comparators, versions):
        if not compare_versions(version, comp, v):
            return False
    return True


def compare_versions(
    version: tuple[int | str, ...] | str,
    comparator: str,
    spec_version: tuple[int | str, ...] | str,
) -> bool:

    if isinstance(version, str):
        version = version_string_to_tuple(version)

    if isinstance(spec_version, str):
        spec_version = version_string_to_tuple(spec_version)

    if comparator in {"~=", "~"}:
        # https://peps.python.org/pep-0440/#compatible-release
        upper_bound = list(spec_version)
        n = len(upper_bound)
        while isinstance(upper_bound[n-1], str):
            n -= 1
        upper_bound = upper_bound[:n]
        upper_bound[-1] = "*"

        return (
            compare_versions(version, ">=", spec_version) and
            compare_versions(version, "==", tuple(upper_bound))
        )

    if comparator in {"^=", "^"}:
        # https://python-poetry.org/docs/dependency-specification/#caret-requirements
        upper_bound = []
        i = 0
        while spec_version[i] == 0 and i < len(spec_version):
            upper_bound.append(0)
            i += 1
        if i:
            upper_bound = upper_bound[:-1]
            i -= 1
        upper_bound[-1] += 1

        return (
            compare_versions(version, ">=", spec_version) and
            compare_versions(version, "<", tuple(upper_bound))
        )

    # Split local version and tags
    if "+" in version:
        local = version[version.index("+")+1:]
        version = version[:version.index("+")]
    else:
        local = ()
    tags = tuple(v for v in version if isinstance(v, str) and v != "*")
    version = tuple(v for v in version if isinstance(v, int) or v == "*")

    if "+" in spec_version:
        if comparator in {"<", "<=", ">", ">="}:
            raise ValueError(
                "Local versions are not allowed with "
                "<, <=, >, or >= specifiers."
            )
        spec_local = spec_version[spec_version.index("+")+1:]
        spec_version = spec_version[:spec_version.index("+")]
    else:
        spec_local = ()
    spec_tags = tuple(
        v for v in spec_version if isinstance(v, str) and v != "*"
    )
    spec_version = tuple(
        v for v in spec_version if isinstance(v, int) or v == "*"
    )

    # Zero-pad versions for comparison
    common_len = min(len(version), len(spec_version))
    pad = (len(spec_version) - common_len)
    pad_spec = (len(version) - common_len)
    version += (0,) * pad
    if spec_version[-1:] == ("*",):
        spec_version += ('*',) * pad_spec
    else:
        spec_version += (0,) * pad_spec

    common_len = min(len(tags), len(spec_tags))
    pad = (len(spec_tags) - common_len)
    pad_spec = (len(tags) - common_len)
    tags += (0,) * pad
    if spec_tags[-1:] == ("*",):
        spec_tags += ('*',) * pad_spec
    elif not spec_tags and spec_version[-1:] == ("*",):
        spec_tags += ('*',) * pad_spec
    else:
        spec_tags += (0,) * pad_spec

    version += tags
    spec_version += spec_tags

    if comparator in {"=", "=="}:
        ok = (local == spec_local) if local else True
        ok &= all(
            compare_numbers(v1, operator.eq, v2)
            for v1, v2 in zip(version, spec_version)
        )
        return ok

    elif comparator == "!=":
        ok = (local != spec_local) if local else False
        ok |= any(
            compare_numbers(v1, operator.ne, v2)
            for v1, v2 in zip(version, spec_version)
        )
        return ok

    elif comparator == ">":
        print(version, spec_version)
        for v1, v2 in zip(version, spec_version):
            if (
                (isinstance(v1, str) and v1.startswith("post"))
                and
                (isinstance(v2, int) or not v2.startswith("post"))
            ):
                # The exclusive ordered comparison >V MUST NOT allow a
                # post-release of the given version unless V itself is a
                # post release.
                return False
            if compare_numbers(v1, operator.eq, v2):
                continue
            return compare_numbers(v1, operator.gt, v2)
        return False

    elif comparator == "<":
        for v1, v2 in zip(version, spec_version):
            if compare_numbers(v1, operator.eq, v2):
                continue
            return compare_numbers(v1, operator.lt, v2)
        return False

    elif comparator == ">=":
        for v1, v2 in zip(version, spec_version):
            if compare_numbers(v1, operator.eq, v2):
                continue
            return compare_numbers(v1, operator.gt, v2)
        return True

    elif comparator == "<=":
        for v1, v2 in zip(version, spec_version):
            if compare_numbers(v1, operator.eq, v2):
                continue
            return compare_numbers(v1, operator.lt, v2)
        return True

    else:
        raise ValueError(f"Unknown comparator: {comparator}")


TAG_ORDER = ("dev", "a", "b", "rc", "", "post")


def compare_numbers(
    a: int | str, comp: Callable[[int, int], bool], b: int | str
) -> bool:
    # Wildcard -> always true
    if a == "*" or b == "*":
        if comp in {operator.eq, operator.ge, operator.le}:
            return True
        else:
            return False

    # Both integers -> direct comparison
    if isinstance(a, int) and isinstance(b, int):
        return comp(a, b)

    # Always put string first
    if isinstance(b, str):
        a, b = b, a
        comp = {
            operator.gt: operator.lt,
            operator.lt: operator.gt,
            operator.ge: operator.le,
            operator.le: operator.ge,
        }.get(comp, comp)

    assert isinstance(a, str)

    # Split tag and number
    a_tag = a.rstrip("0123456789*")
    a = a[len(a_tag):]
    if a != "*":
        a = int(a)

    if isinstance(b, str):
        b_tag = b.rstrip("0123456789*")
        b = b[len(b_tag):]
        if b != "*":
            b = int(b)
    else:
        b_tag = ""

    # Compare tags first, then numbers
    if comp is operator.eq:
        return a_tag == b_tag and (a == b or "*" in {a, b})
    elif comp is operator.ne:
        return a_tag != b_tag or (a != b and "*" not in {a, b})
    elif a_tag == b_tag:
        return ("*" in {a, b}) or comp(a, b)
    else:
        return comp(TAG_ORDER.index(a_tag), TAG_ORDER.index(b_tag))
