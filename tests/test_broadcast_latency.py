import time

from starlette.testclient import TestClient

import server.main as main


def _drain_until_ack(websocket, action):
    while True:
        message = websocket.receive_json()
        if message.get("type") == "action_ack" and message.get("action") == action:
            return message


def _wait_for_persistence(events, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(name == "persist_done" for name, _ in events):
            return
        time.sleep(0.01)
    raise AssertionError("persistence did not complete")


def test_actions_broadcast_state_before_blocking_persistence(monkeypatch):
    events = []
    real_save = main.persistence.save_state

    def slow_save(state):
        events.append(("persist_start", time.perf_counter()))
        time.sleep(0.4)
        real_save(state)
        events.append(("persist_done", time.perf_counter()))

    real_broadcast = main.ws_manager.broadcast_state

    async def recording_broadcast(state):
        events.append(("broadcast", time.perf_counter()))
        await real_broadcast(state)

    monkeypatch.setattr(main.persistence, "save_state", slow_save)
    monkeypatch.setattr(main.ws_manager, "broadcast_state", recording_broadcast)

    try:
        with TestClient(main.app) as client:
            main.engine.init_default_tournament()
            main.timer.pause()

            with client.websocket_connect("/ws") as websocket:
                websocket.send_json(
                    {"type": "hello", "role": "moderator", "pin_or_code": "1111"}
                )
                assert websocket.receive_json()["type"] == "welcome"
                assert websocket.receive_json()["type"] == "state"

                checks = [
                    ("start_timer", {"seconds": 120}, None),
                    (
                        "mark_correct",
                        {},
                        lambda: (
                            main.engine.start_rapid_fire("team_1", 120),
                            main.engine.open_question(),
                        ),
                    ),
                    ("next_question", {}, None),
                ]

                for action, payload, prepare in checks:
                    if prepare:
                        prepare()
                    events.clear()
                    websocket.send_json(
                        {
                            "type": "action",
                            "action": action,
                            "payload": payload,
                            "reason": "latency regression test",
                        }
                    )
                    ack = _drain_until_ack(websocket, action)
                    assert ack["success"] is True
                    _wait_for_persistence(events)

                    broadcast_times = [at for name, at in events if name == "broadcast"]
                    persist_starts = [at for name, at in events if name == "persist_start"]
                    assert broadcast_times
                    assert persist_starts
                    assert min(broadcast_times) < min(persist_starts)
                    assert min(persist_starts) - min(broadcast_times) < 0.05

                    main.timer.pause()
    finally:
        main.timer.pause()
        main.engine.init_default_tournament()
