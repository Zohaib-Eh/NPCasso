import pytest

from backend.game import tick
from backend.story import DIMENSIONS, add_evidence, anchor, cold_rate, leading_ending, phase, profile


def test_score_names_the_buried_truth(conn):
    add_evidence(conn, "p", "candor", 1, 1, None)
    add_evidence(conn, "p", "bravery", 1, 1, None)
    add_evidence(conn, "p", "loyalty", 1, 1, None)
    assert leading_ending(conn, "p") == "names_we_buried"


def test_negative_weights_name_the_end_of_all_things(conn):
    add_evidence(conn, "p", "forgiveness", -1, 1, None)
    add_evidence(conn, "p", "compassion", -1, 1, None)
    add_evidence(conn, "p", "independence", 1, 1, None)
    assert leading_ending(conn, "p") == "the_end_of_all_things"


def test_no_evidence_has_no_ending(conn):
    assert leading_ending(conn, "p") is None


def test_unknown_dimension_is_rejected(conn):
    with pytest.raises(ValueError):
        add_evidence(conn, "p", "evil", 1, None, None)


def test_death_ends_the_run_without_an_ending(conn):
    from backend.story import mark_died, report
    anchor(conn, "p", 0)
    add_evidence(conn, "p", "candor", 1, None, None)
    assert mark_died(conn, "p") == {"ok": True}
    out = report(conn, "p", 6.5)
    assert out["phase"] == "ended" and out["sustain"] is True and "ending" not in out


def test_the_winter_look_creeps_in_from_arrival_to_day_ten(conn):
    from backend.story import report
    anchor(conn, "p", 0)
    seen = [report(conn, "p", t)["winter"] for t in (0, 2.25, 4.5, 9, 12)]
    assert seen == [0.0, 0.25, 0.5, 1.0, 1.0]


def test_open_fact_is_only_the_season(conn):
    from backend.story import story_facts
    anchor(conn, "p", 0)
    facts = story_facts(conn, "p", 0.2)
    assert facts == {"season": "ordinary days, before the cold is a problem"}


def test_profile_averages_each_dimension_and_zeroes_the_unseen(conn):
    add_evidence(conn, "p", "candor", 1, None, None)
    add_evidence(conn, "p", "candor", 0.5, None, None)
    by = {r["dimension"]: r for r in profile(conn, "p")}
    assert list(by) == list(DIMENSIONS)
    assert by["candor"]["value"] == 0.75 and by["bravery"]["value"] == 0


def test_conduct_and_closing_lean(conn):
    from backend.story import conduct, story_facts
    anchor(conn, "p", 0)
    add_evidence(conn, "p", "candor", 1, 1, None)
    add_evidence(conn, "p", "bravery", 1, 1, None)
    add_evidence(conn, "p", "loyalty", 1, 1, None)
    assert conduct(conn, "p") == "the player says the hard thing and takes the risk"
    facts = story_facts(conn, "p", 6.5)
    assert facts["season"] == "winter is closing in"
    assert facts["lean"] == "a buried truth is coming due"
    assert facts["regard"] == "the player says the hard thing and takes the risk"
    assert "6" not in facts["season"] and "names_we_buried" not in facts["lean"]


def test_phase_follows_the_clock_day():
    assert phase(0.9) == "open"       # day 1
    assert phase(1) == "pressure"      # day 2
    assert phase(4.9) == "pressure"    # day 5
    assert phase(5) == "closing"       # day 6
    assert phase(8.9) == "closing"     # day 9
    assert phase(9) == "frozen"        # day 10


def test_cold_grows_toward_the_last_day():
    assert cold_rate(4.9) == 0
    assert 0 < cold_rate(5) < cold_rate(7) < cold_rate(8.5)


def test_open_tick_hides_a_leaning_score(conn):
    anchor(conn, "w:p", 0)
    add_evidence(conn, "w:p", "candor", 1, 1, None)
    add_evidence(conn, "w:p", "bravery", 1, 1, None)
    add_evidence(conn, "w:p", "loyalty", 1, 1, None)
    out = tick(conn, None, "w", "p", 0.5)
    assert out["phase"] == "open" and out["day"] == 1 and "ending" not in out
    assert out["cold"] == 0 and out["sustain"] is True


def test_pressure_hides_a_leaning_score(conn):
    anchor(conn, "w:p", 0)
    add_evidence(conn, "w:p", "candor", 1, 1, None)
    add_evidence(conn, "w:p", "bravery", 1, 1, None)
    add_evidence(conn, "w:p", "loyalty", 1, 1, None)
    out = tick(conn, None, "w", "p", 3.0)
    assert out["phase"] == "pressure" and out["day"] == 4 and "ending" not in out


def test_closing_tick_names_the_ending(conn):
    anchor(conn, "w:p", 0)
    add_evidence(conn, "w:p", "candor", 1, 1, None)
    add_evidence(conn, "w:p", "bravery", 1, 1, None)
    add_evidence(conn, "w:p", "loyalty", 1, 1, None)
    out = tick(conn, None, "w", "p", 6.5)
    assert out["phase"] == "closing" and out["ending"] == "names_we_buried"
    assert out["day"] == 7 and out["time"] == "12:00"
    assert out["cold"] > 0 and out["sustain"] is True


def test_closing_without_evidence_names_nothing(conn):
    anchor(conn, "w:p", 0)
    out = tick(conn, None, "w", "p", 6)
    assert out["phase"] == "closing" and "ending" not in out


def test_day_ten_cannot_be_sustained(conn):
    anchor(conn, "w:p", 0)
    out = tick(conn, None, "w", "p", 9)
    assert out["phase"] == "frozen" and out["day"] == 10 and out["sustain"] is False


def test_arrival_starts_the_count_even_in_an_old_world(conn):
    out = tick(conn, None, "w", "p", 40.25)
    assert out["day"] == 1 and out["phase"] == "open" and out["time"] == "06:00"
