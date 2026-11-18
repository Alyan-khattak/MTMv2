import json

from state.state_manager import StateManager


def test_save_creates_state_and_bak(tmp_path):
    sm = StateManager(tmp_path / "state.json")
    sm.save({})
    assert sm.path.exists() and sm.bak.exists() and not sm.tmp.exists()


def test_crash_leaves_bak_and_recovers(tmp_path):
    sm = StateManager(tmp_path / "state.json")
    sm.save({"messages": [{"id": "a"}]})
    sm.save({"messages": [{"id": "b"}]})
    # simulated crash: half-written tmp, and state.json corrupted
    sm.tmp.write_text('{"messages": [')
    sm.path.write_text("{broken")
    sm2 = StateManager(tmp_path / "state.json")
    state = sm2.load()
    assert state["messages"] == [{"id": "a"}]  # .bak holds the previous good state
    assert not sm2.tmp.exists() and sm2.warnings


def test_empty_start(tmp_path):
    assert StateManager(tmp_path / "x.json").load()["active_plan_id"] is None
