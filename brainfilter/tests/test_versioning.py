from brainfilter import versioning as V


def test_normalize_version_string():
    S2S = V.normalize_version_string
    # v and spaces
    assert S2S("v1.2.3") == "1.2.3"
    assert S2S("v 1.2.3") == "1.2.3"
    assert S2S("  v1.2.3  ") == "1.2.3"
    # Already normalized
    assert S2S("1") == "1"
    assert S2S("1.2") == "1.2"
    assert S2S("1.2.3") == "1.2.3"
    assert S2S("1.2.3a1") == "1.2.3a1"
    assert S2S("1.2.3b2") == "1.2.3b2"
    assert S2S("1.2.3rc3") == "1.2.3rc3"
    assert S2S("1.2.3.post4") == "1.2.3.post4"
    assert S2S("1.2.3.dev5") == "1.2.3.dev5"
    # Aliases
    assert S2S("1.2.3-alpha1") == "1.2.3a1"
    assert S2S("1.2.3-beta2") == "1.2.3b2"
    assert S2S("1.2.3-pre3") == "1.2.3rc3"
    assert S2S("1.2.3-pre3") == "1.2.3rc3"
    assert S2S("1.2.3-preview3") == "1.2.3rc3"
    assert S2S("1.2.3-c3") == "1.2.3rc3"
    assert S2S("1.2.3rev4") == "1.2.3.post4"
    assert S2S("1.2.3r4") == "1.2.3.post4"
    assert S2S("1.2.3dev5") == "1.2.3.dev5"
    # Integers
    assert S2S("0001") == "1"
    assert S2S("01.002.0003") == "1.2.3"
    # Wildcard
    assert S2S("*") == "*"
    # Local
    assert S2S("1.2.3+local") == "1.2.3+local"
    assert S2S("v1.2.3+local-3") == "1.2.3+local.3"
    assert S2S("  v1.2.3  +  local  ") == "1.2.3+local"


def test_version_string_to_tuple():
    S2T = V.version_string_to_tuple
    assert S2T("1") == (1,)
    assert S2T("1.2") == (1, 2)
    assert S2T("1.2.3") == (1, 2, 3)
    assert S2T("1.2.3a1") == (1, 2, 3, "a1")
    assert S2T("1.2.3b2") == (1, 2, 3, "b2")
    assert S2T("1.2.3rc3") == (1, 2, 3, "rc3")
    assert S2T("1.2.3.post4") == (1, 2, 3, "post4")
    assert S2T("1.2.3.dev5") == (1, 2, 3, "dev5")
    assert S2T("*") == ("*",)
    assert S2T("1.2.3+local.3") == (1, 2, 3, "+", "local", 3)


def test_is_version_valid():
    S2B = V.is_version_valid
    assert S2B("1")
    assert S2B("1.2")
    assert S2B("1.2.3")
    assert S2B("1.2.3a1")
    assert S2B("1.2.3b2")
    assert S2B("1.2.3rc3")
    assert S2B("1.2.3.post4")
    assert S2B("1.2.3.dev5")
    assert S2B("*", is_spec=True)
    assert S2B("1.2.3+local.3")
    assert S2B("1.2.3 alpha")

    assert not S2B("*")
    assert not S2B("version 1.2.3")
    assert not S2B("1.2..3")
    assert not S2B("1.2.3-unknown")


def test_compare_versions():
    CV = V.compare_versions
    assert not CV("1.2.3", "==", "1.2.4")
    assert CV("1.2.3", "<", "1.2.4")
    assert CV("1.2.3", "<=", "1.2.3")
    assert CV("1.2.3", ">", "1.2.2")
    assert CV("1.2.3", ">=", "1.2.3")
    assert CV("1.2.3", "!=", "1.2.4")

    # ----------------------------------------------
    # Examples from https://peps.python.org/pep-0440
    # ----------------------------------------------

    # https://peps.python.org/pep-0440/#version-matching

    assert CV("1.1.post1", "==", "1.1") is False
    assert CV("1.1.post1", "==", "1.1.post1")
    assert CV("1.1.post1", "==", "1.1.*")

    assert CV("1.1a1", "==", "1.1") is False
    assert CV("1.1a1", "==", "1.1a1")
    assert CV("1.1a1", "==", "1.1.*")

    assert CV("1.1", "==", "1.1")
    assert CV("1.1", "==", "1.1.0")
    assert CV("1.1", "==", "1.1.dev1") is False
    assert CV("1.1", "==", "1.1a1") is False
    assert CV("1.1", "==", "1.1.post1") is False
    assert CV("1.1", "==", "1.1.*")

    # https://peps.python.org/pep-0440/#version-exclusion

    assert CV("1.1.post1", "!=", "1.1")
    assert CV("1.1.post1", "!=", "1.1.post1") is False
    assert CV("1.1.post1", "!=", "1.1.*") is False

    # https://peps.python.org/pep-0440/#inclusive-ordered-comparison

    # https://peps.python.org/pep-0440/#exclusive-ordered-comparison

    assert CV("1.7.1", ">", "1.7")
    assert CV("1.7.0.post1", ">", "1.7") is False
    assert CV("1.7.1", ">", "1.7.post2")
    assert CV("1.7.0.post3", ">", "1.7.post2")
    assert CV("1.7.0", ">", "1.7.post2") is False

    assert CV("1.7.1", "<", "1.7.1rc1") is False
    assert CV("1.7.1a1", "<", "1.7.1rc1")
