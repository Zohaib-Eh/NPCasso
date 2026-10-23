from eval.run import load_scenarios, run_all


def test_scenarios_split():
    sc = load_scenarios()
    assert len(sc) >= 10
    for s in sc:
        assert len(s["messages"]["train"]) >= 3 and len(s["messages"]["heldout"]) >= 2, s["id"]
    heldout_npcs = {m["npc"] for s in sc for m in s["messages"]["heldout"] if isinstance(m, dict)}
    assert heldout_npcs & {"rowan", "mira"}


def test_mock_eval_all_pass():
    out = run_all("mock", "all")
    s = out["summary"]
    assert s["scenarios"] >= 10 and s["runs"] > s["scenarios"]
    failed = [r for r in out["results"] if not r["passed"]]
    assert failed == [], failed[:3]
