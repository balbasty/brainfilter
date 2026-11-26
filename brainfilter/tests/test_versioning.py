import pytest

from brainfilter import versioning as V
from brainfilter.versioning import Version


def test_normalize_version_string():
    S2S = V.normalize_version_string
    # v and spaces
    assert S2S("v1.2.3") == "1.2.3"
    assert S2S("v 1.2.3") == "1.2.3"
    assert S2S("  v1.2.3  ") == "1.2.3"
    # Already normalized
    assert S2S("1.2.3") == "1.2.3"
    # Implicit zeros
    assert S2S("1") == "1.0.0"
    assert S2S("1.2") == "1.2.0"
    # Integers
    assert S2S("0001") == "1.0.0"
    assert S2S("01.002.0003") == "1.2.3"
    # Pre-release and build metadata
    assert S2S("1.10.0-dev") == "1.10.0-dev"
    assert S2S("v1.2.3-rc.1+build.5") == "1.2.3-rc.1+build.5"
    assert S2S((1, 2, 3)) == "1.2.3"


def test_version_parts():
    v = Version("1.10.0-dev+abc")
    assert (v.major, v.minor, v.patch) == (1, 10, 0)
    assert v.release == (1, 10, 0)
    assert v.pre == "dev"
    assert v.build == "abc"
    assert Version("0.7.3-dev").pre == "dev"
    assert Version("1.9.0").pre is None
    assert repr(Version("1.2")) == "Version('1.2.0')"


def test_is_version_valid():
    S2B = V.is_version_valid
    assert S2B("1")
    assert S2B("1.2")
    assert S2B("1.2.3")
    assert S2B("1.10.0-dev")
    assert S2B("0.7.3-dev")
    assert S2B("1.2.3-rc.1")
    assert S2B("1.2.3+local.3")
    assert S2B("1.9.*", is_spec=True)

    assert not S2B("*")
    assert not S2B("1.9.*")
    assert not S2B("version 1.2.3")
    assert not S2B("1.2..3")
    assert not S2B("1.2.3.4")
    assert not S2B("1.2.3-")
    assert not S2B("1.2.3-dev..1")
    with pytest.raises(ValueError):
        Version("1.2..3")


def test_ordering():
    assert Version("1.10.0") > Version("1.9.0")  # numeric, not lexical
    assert Version("1.10.0-dev") < Version("1.10.0")
    assert Version("1.10.0-dev") > Version("1.9.1")
    assert Version("0.7.3-dev") < Version("0.7.3")
    assert Version("1.10.0-dev") != Version("1.10.0")  # ordering keeps semver
    # semver pre-release precedence
    chain = [
        "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
        "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0",
    ]
    versions = list(map(Version, chain))
    assert versions == sorted(versions)
    assert all(a < b for a, b in zip(versions, versions[1:]))
    # build metadata is ignored
    assert Version("1.2.3+a") == Version("1.2.3+b")
    assert hash(Version("1.2.3+a")) == hash(Version("1.2.3"))
    # implicit zeros
    assert Version("1.1") == Version("1.1.0")
    assert Version("1.1") < Version("1.1.1")


def test_version_rejects_non_string_input():
    # a float read from JSON loses the version it meant (1.10 is 1.1)
    for bad in (1.10, 1, None, True, ["1", "10"]):
        with pytest.raises(TypeError):
            Version(bad)
    with pytest.raises(TypeError):
        V.normalize_version_string(1.10)
    with pytest.raises(TypeError):
        V.version_is_satisfied(">=1.8", 1.10)
    # the accepted inputs
    assert Version("1.10") == Version((1, 10)) == Version(Version("1.10"))


def test_version_compares_with_versions_only():
    v = Version("1.0")
    # unequal to anything that is not a Version, without raising
    assert (v == "latest") is False
    assert v != "latest"
    assert v != "1.0"
    assert v != (1, 0, 0)
    assert v != 1.0
    assert v != None  # noqa: E711
    assert v in ["latest", Version("1.0.0")]
    assert v not in ["latest", "1.0"]
    # ordering against a non-Version raises TypeError, as for any
    # unorderable pair, never ValueError from parsing
    for other in ("x", "1.1", (1, 1), 1):
        with pytest.raises(TypeError):
            v < other
        with pytest.raises(TypeError):
            v >= other
    # hashing agrees with equality
    assert "1.0" not in {v}
    assert Version("1.0.0") in {v}
    assert Version("v1.0.0+build") in {v}
    assert {Version("1"), Version("1.0"), Version("1.0.0+a")} == {v}
    assert len({Version("1.0.0-dev"), Version("1.0.0")}) == 2
    assert {v: "x"}[Version("1.0.0")] == "x"


def test_compare_versions():
    CV = V.compare_versions
    assert not CV("1.2.3", "==", "1.2.4")
    assert CV("1.2.3", "<", "1.2.4")
    assert CV("1.2.3", "<=", "1.2.3")
    assert CV("1.2.3", ">", "1.2.2")
    assert CV("1.2.3", ">=", "1.2.3")
    assert CV("1.2.3", "!=", "1.2.4")

    assert CV("1.1", "==", "1.1")
    assert CV("1.1", "==", "1.1.0")
    assert CV("1.1", "==", "1.1.*")
    # a pre-release version counts as its release
    assert CV("1.1.0-a1", "==", "1.1")
    assert CV("1.1.0-a1", "==", "1.1.*")
    assert CV("1.1.0-a1", "!=", "1.1") is False
    assert CV(Version("1.1.0-a1"), "==", Version("1.1"))

    assert CV("1.2.0", "!=", "1.1.*")
    assert CV("1.1.5", "!=", "1.1.*") is False

    assert CV("1.7.1", ">", "1.7")
    assert CV("1.7.0", ">", "1.7") is False
    assert CV("1.7.1-dev", ">", "1.7.0")

    with pytest.raises(ValueError):
        CV("1.9.0", ">=", "1.9.*")
    with pytest.raises(ValueError):
        CV("1.9.0", "~=", "1.9")


@pytest.mark.parametrize("comparator", V.COMPARATORS)
@pytest.mark.parametrize(
    "spec", ["1.10.0-dev", "1.10.0-rc1", "1.10-alpha.1", "1.10.0-dev+abc"]
)
def test_compare_versions_refuses_pre_release_spec(comparator, spec):
    for version in ("1.10.0", "1.10.0-alpha", "1.9.0"):
        with pytest.raises(ValueError, match="Pre-releases are not allowed"):
            V.compare_versions(version, comparator, spec)
    with pytest.raises(ValueError, match="Pre-releases are not allowed"):
        V.compare_versions("1.10.0", comparator, Version(spec))
    with pytest.raises(ValueError, match="Pre-releases are not allowed"):
        V.version_is_satisfied(comparator + spec, "1.10.0")


def test_pre_release_spec_examples():
    # each of these used to give a wrong answer silently
    OK = V.version_is_satisfied
    with pytest.raises(ValueError):
        OK("!=1.10.0-dev", "1.10.0")
    with pytest.raises(ValueError):
        OK(">=1.10.0-rc1", "1.10.0-alpha")
    with pytest.raises(ValueError):
        OK("<1.10.0-dev", "1.10.0-alpha")
    # refused even when an earlier segment already fails
    with pytest.raises(ValueError):
        OK(">=2, <2.1.0-dev", "1.0.0")
    # build metadata in a specifier is still ignored
    assert OK(">=1.10.0+abc", "1.10.0")


def test_split_specifiers():
    SS = V.split_specifiers
    assert SS(">=1.8") == [(">=", "1.8")]
    assert SS(">=1.8, <2") == [(">=", "1.8"), ("<", "2")]
    assert SS("1.9.0") == [("==", "1.9.0")]
    assert SS("  != 1.9.* ") == [("!=", "1.9.*")]
    for bad in ("", "  ", " , ", ">=1.8,,", ",<2", ">=1.8,", ">=1.8,,<2",
                ">=1.8, ,<2"):
        with pytest.raises(ValueError, match="[Ee]mpty"):
            SS(bad)
        with pytest.raises(ValueError, match="[Ee]mpty"):
            V.version_is_satisfied(bad, "1.9.0")


def test_version_is_satisfied():
    OK = V.version_is_satisfied
    assert OK(">=1.8", "1.9.0")
    assert OK(">=1.8", "1.8.0")
    assert not OK(">=1.8", "1.7.9")
    assert OK("<2", "1.10.0")
    assert not OK("<2", "2.0.0")
    assert OK("==1.9.*", "1.9.0")
    assert OK("==1.9.*", "1.9.1-dev")
    assert not OK("==1.9.*", "1.10.0")
    assert OK(">=1.8, <2", "1.10.0-dev")
    assert not OK(">=1.8, <2", "2.1.0")
    # a dev version counts as its release
    assert OK(">=1.10", "1.10.0-dev")
    assert OK("==1.10.*", "1.10.0-dev")
    assert not OK("<1.10", "1.10.0-dev")
    assert OK("==1.10", "1.10.0-dev")
    assert not OK(">1.10", "1.10.0-dev")
    assert OK(">=1.10.0", "1.10.0-dev")
    assert OK(">=0.7, <0.8", "0.7.3-dev")
    assert OK("1.9.0", Version("1.9"))
    assert OK(">=1.8", (1, 9, 0))
