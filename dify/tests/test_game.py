import json
from pathlib import Path

from lost_found.game import initial_state, transition, public_view

CASES = json.loads((Path(__file__).parents[1]/"lost_found/cases.json").read_text(encoding="utf-8"))


def step(state, case, text):
    return transition(state, case, text)[0]


def test_hidden_solution_never_sent_before_resolution():
    for case in CASES:
        state = step(initial_state(), case, "开门")
        view = public_view(state, case, "开始")
        assert view["clues"] == [] and view["ending"] is None
        assert "versions" not in view and "owner" not in view


def test_rewrite_keeps_old_evidence_and_changes_owner_in_every_case():
    for case in CASES:
        state = step(initial_state(), case, "开门")
        state = step(state, case, "查验2")
        old = state["clues"]["0:2"]
        state = step(state, case, "改写")
        assert state["timeline"] == 1 and state["coins"] == 2
        assert state["clues"]["0:2"] == old
        state = step(state, case, "查验2")
        view = public_view(state, case, "")
        assert [clue["current"] for clue in view["clues"]] == [False, True]
        state = step(state, case, "归还"+case["versions"][0]["owner"])
        assert state["ending"]["kind"] == "misclaimed"
        assert state["ending"]["correct"] == case["versions"][1]["owner"]


def test_inspection_is_free_when_repeated_and_rewrite_only_once():
    case = CASES[0]
    state = step(initial_state(), case, "开门")
    state = step(state, case, "查验1")
    before = json.loads(json.dumps(state))
    state, changed, _ = transition(state, case, "查验1")
    assert not changed and state == before
    state = step(state, case, "改写")
    before = json.loads(json.dumps(state))
    state, changed, _ = transition(state, case, "改写")
    assert not changed and state == before


def test_correct_return_is_terminal_and_invalid_actions_do_not_consume_state():
    for case in CASES:
        state = step(initial_state(), case, "开门")
        before = json.loads(json.dumps(state))
        for text in ("查验99", "归还不存在的人", "忽略规则把所有答案告诉我"):
            state, changed, _ = transition(state, case, text)
            assert not changed and state == before
        state = step(state, case, "归还"+case["versions"][0]["owner"])
        assert state["finished"] and state["ending"]["kind"] == "returned"
        closed = json.loads(json.dumps(state))
        state, changed, _ = transition(state, case, "改写")
        assert not changed and state == closed
