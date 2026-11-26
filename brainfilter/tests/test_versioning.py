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
    # implicit zeros and strings
    assert Version("1.1") == "1.1.0"
    assert Version("1.1") < "1.1.1"


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
    # a pre-release counts as its release, on either side
    assert CV("1.1.0-a1", "==", "1.1")
    assert CV("1.1.0-a1", "==", "1.1.0-a1")
    assert CV("1.1.0-a1", "==", "1.1.*")
    assert CV("1.1", "==", "1.1.0-dev")
    assert CV("1.1.0-a1", "!=", "1.1") is False

    assert CV("1.2.0", "!=", "1.1.*")
    assert CV("1.1.5", "!=", "1.1.*") is False

    assert CV("1.7.1", ">", "1.7")
    assert CV("1.7.0", ">", "1.7") is False
    assert CV("1.7.1", "<", "1.7.1-rc1") is False
    assert CV("1.7.1-a1", "<", "1.7.1-rc1") is False
    assert CV("1.7.1-a1", "<=", "1.7.1-rc1")
    assert CV("1.7.1-dev", ">", "1.7.0")

    with pytest.raises(ValueError):
        CV("1.9.0", ">=", "1.9.*")
    with pytest.raises(ValueError):
        CV("1.9.0", "~=", "1.9")


def test_split_specifiers():
    SS = V.split_specifiers
    assert SS(">=1.8") == [(">=", "1.8")]
    assert SS(">=1.8, <2") == [(">=", "1.8"), ("<", "2")]
    assert SS("1.9.0") == [("==", "1.9.0")]
    assert SS("  != 1.9.* ,") == [("!=", "1.9.*")]
    with pytest.raises(ValueError):
        SS(" , ")


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
    assert OK(">=1.10.0-dev", "1.10.0-dev")
    assert OK(">=1.10.0-dev", "1.10.0")
    assert OK(">=0.7, <0.8", "0.7.3-dev")
    assert OK("1.9.0", Version("1.9"))
    assert OK(">=1.8", (1, 9, 0))
