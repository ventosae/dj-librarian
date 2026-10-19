import xml.etree.ElementTree as ET

import pytest

from dj import rules


def xml_conditions(rule_list):
    smart = rules.build_smartlist(rule_list)
    smart.playlist_id = "12345"  # pyrekordbox sets this in create_smart_playlist
    root = ET.fromstring(smart.to_xml())
    return root, [c.attrib for c in root]


def test_genre_contains():
    _, (cond,) = xml_conditions([{"genre_contains": "funk"}])
    assert cond == {
        "PropertyName": "genre",
        "Operator": "8",
        "ValueUnit": "",
        "ValueLeft": "funk",
        "ValueRight": "",
    }


def test_comment_contains():
    _, (cond,) = xml_conditions([{"comment_contains": "#uplifting"}])
    assert (cond["PropertyName"], cond["Operator"], cond["ValueLeft"]) == (
        "comments",
        "8",
        "#uplifting",
    )


def test_bpm_range_is_scaled():
    _, (cond,) = xml_conditions([{"bpm_range": [85, 100]}])
    assert (cond["PropertyName"], cond["Operator"]) == ("bpm", "5")
    assert cond["ValueLeft"] == str(85 * rules.BPM_SCALE)
    assert cond["ValueRight"] == str(100 * rules.BPM_SCALE)


def test_rating_min_means_more_than_one_star_less():
    _, (cond,) = xml_conditions([{"rating_min": 3}])
    assert (cond["PropertyName"], cond["Operator"]) == ("rating", "3")
    assert cond["ValueLeft"] == str(2 * rules.RATING_STEP)


def test_added_last_days():
    _, (cond,) = xml_conditions([{"added_last_days": 30}])
    assert cond["PropertyName"] == rules.DATE_ADDED.value
    assert (cond["Operator"], cond["ValueLeft"], cond["ValueUnit"]) == ("6", "30", "day")


def test_several_rules_are_anded():
    root, conds = xml_conditions([{"genre_contains": "funk"}, {"bpm_range": [100, 115]}])
    assert root.attrib["LogicalOperator"] == "1"
    assert root.attrib["AutomaticUpdate"] == str(rules.AUTO_UPDATE)
    assert [c["PropertyName"] for c in conds] == ["genre", "bpm"]


def test_describe_shows_the_encoded_values():
    text = rules.describe([{"bpm_range": [85, 100]}, {"added_last_days": 30}])
    assert f"bpm IN_RANGE {85 * rules.BPM_SCALE}..{100 * rules.BPM_SCALE}" in text
    assert "IN_LAST 30 day" in text


@pytest.mark.parametrize(
    "rule_list",
    [
        None,
        [],
        "genre_contains: funk",
        [{"my_tag": "x"}],
        [{"genre_contains": "a", "comment_contains": "b"}],
        [{"genre_contains": ""}],
        [{"genre_contains": 5}],
        [{"bpm_range": [100]}],
        [{"bpm_range": [115, 100]}],
        [{"bpm_range": ["85", "100"]}],
        [{"rating_min": 0}],
        [{"rating_min": 6}],
        [{"rating_min": True}],
        [{"added_last_days": 0}],
        [{"added_last_days": 1.5}],
    ],
)
def test_bad_rules_raise(rule_list):
    with pytest.raises(ValueError):
        rules.build_smartlist(rule_list)


def test_uncalibrated_lists_only_inferred_encodings(monkeypatch):
    rule_list = [{"genre_contains": "funk"}, {"bpm_range": [85, 100]}]
    monkeypatch.setattr(rules, "CALIBRATED", set())
    assert rules.uncalibrated(rule_list) == {"bpm_range"}
    monkeypatch.setattr(rules, "CALIBRATED", {"bpm_range"})
    assert rules.uncalibrated(rule_list) == set()
