import os
import time
import asyncio
import csv
import io
import json
import re
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from server.config import Config
from server.esp32_bridge import ESP32Bridge
from server.engine.game_engine import GameEngine
from server.engine.models import RoundPhase
from server.persistence import PersistenceManager
from server.network import get_network_info
from server.qr_service import generate_qr_svg, get_role_urls
from server.timer import ServerTimer
from server.ws_manager import WebSocketManager, ConnectedDevice

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "web" / "static"
WEB_DIR = BASE_DIR / "web"

config = Config.load()
persistence = PersistenceManager(data_dir=config.data_dir, logs_dir=BASE_DIR / "logs")
engine = GameEngine(auto_init_tournament=True)
engine.snapshot_saver = persistence.save_match_snapshot
timer = ServerTimer()
ws_manager = WebSocketManager(config=config)
start_time = time.time()
admin_sessions: set[str] = set()
hub_sessions: set[str] = set()
moderator_sessions: set[str] = set()
hub_test_mode = False
last_state_saved_at: Optional[str] = None
buzzer_arrivals: Dict[str, float] = {}
_persist_lock = asyncio.Lock()
_persist_tasks: set[asyncio.Task] = set()


async def esp32_on_event(name: str, payload: Dict[str, Any]) -> None:
    await ws_manager.broadcast_event(name, **payload)


async def esp32_on_buzz(side: str) -> bool:
    global hub_test_mode
    async with ws_manager._lock:
        if engine.buzzer_source_mode == "MOBILE":
            await ws_manager.broadcast_event(
                "esp32_buzz_rejected",
                side=side,
                reason="Buzzer mode is currently MOBILE failover (switch to ESP32 Primary in /buzzers)",
            )
            return False
        if not engine.current_match:
            await ws_manager.broadcast_event("esp32_buzz_rejected", side=side, reason="No active match configured")
            return False
        team_id = (
            engine.current_match.team_a_id if side == "TEAM_A" else engine.current_match.team_b_id
        )
        if not team_id:
            await ws_manager.broadcast_event("esp32_buzz_rejected", side=side, reason="Team not configured in match")
            return False

        if hub_test_mode:
            await ws_manager.broadcast_event("test_buzz_received", team=team_id, side=side)
            await ws_manager.broadcast_event("buzz_first", team=team_id, source="esp32")
            return True

        arrival_ms = time.time_ns() / 1_000_000
        try:
            result = engine.buzz(team_id=team_id)
        except (ValueError, RuntimeError) as err:
            await ws_manager.broadcast_event("esp32_buzz_rejected", team=team_id, side=side, reason=str(err))
            return False

        previous_arrival = max(buzzer_arrivals.values()) if buzzer_arrivals else None
        buzzer_arrivals[team_id] = arrival_ms
        delta_ms = round(arrival_ms - previous_arrival, 3) if previous_arrival is not None else None
        result["arrival_timestamp_ms"] = round(arrival_ms, 3)
        result["delta_ms"] = delta_ms

        state_snapshot = get_state()
        await ws_manager.broadcast_event(
            "buzz_first",
            team=team_id,
            timestamp=result.get("press_timestamp"),
            source="esp32",
        )
        await ws_manager.broadcast_event(
            "fairness_telemetry",
            team=team_id,
            arrival_timestamp_ms=round(arrival_ms, 3),
            delta_ms=delta_ms,
        )
        await ws_manager.broadcast_state(state_snapshot)
        schedule_persistence(
            state_snapshot,
            role="esp32",
            device=esp_bridge.locked_ip or "esp32",
            action="buzz",
            payload={"side": side, "team_id": team_id},
            reason="ESP32 hardware buzz",
        )
        return True


esp_bridge = ESP32Bridge(config=config, on_buzz=esp32_on_buzz, on_event=esp32_on_event)


def save_state() -> None:
    global last_state_saved_at
    persistence.save_state(engine.get_state())
    last_state_saved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_persistence_snapshot(
    state_snapshot: Dict[str, Any],
    role: str,
    device: str,
    action: Optional[str],
    payload: Dict[str, Any],
    reason: str,
) -> None:
    global last_state_saved_at
    persistence.save_state(state_snapshot)
    last_state_saved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if action:
        persistence.log_audit(
            role=role,
            device=device,
            action=action,
            details=payload,
            reason=reason,
        )


async def _persist_snapshot_async(
    state_snapshot: Dict[str, Any],
    role: str,
    device: str,
    action: Optional[str],
    payload: Dict[str, Any],
    reason: str,
) -> None:
    async with _persist_lock:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            _write_persistence_snapshot,
            state_snapshot,
            role,
            device,
            action,
            payload,
            reason,
        )


def _persist_done(task: asyncio.Task) -> None:
    _persist_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        print(f"[Persistence] Async save failed: {error}")


def schedule_persistence(
    state_snapshot: Dict[str, Any],
    role: str = "system",
    device: str = "server",
    action: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    reason: str = "",
) -> None:
    task = asyncio.create_task(
        _persist_snapshot_async(
            state_snapshot,
            role,
            device,
            action,
            payload or {},
            reason,
        )
    )
    _persist_tasks.add(task)
    task.add_done_callback(_persist_done)


async def on_timer_tick(seconds: int) -> None:
    engine.round.timer_seconds_remaining = seconds
    engine.round.timer_running = True
    state_snapshot = get_state()
    await ws_manager.broadcast_event(
        "timer_tick",
        seconds=seconds,
        seconds_remaining=seconds,
        running=True,
    )
    await ws_manager.broadcast_state(state_snapshot)
    schedule_persistence(state_snapshot, role="system", device="timer", reason="timer tick")


async def on_timer_expired() -> None:
    engine.round.timer_running = False
    engine.round.timer_seconds_remaining = 0
    state_snapshot = get_state()
    await ws_manager.broadcast_event(
        "timer_expired",
        seconds=0,
        seconds_remaining=0,
        running=False,
    )
    await ws_manager.broadcast_state(state_snapshot)
    schedule_persistence(
        state_snapshot,
        role="system",
        device="timer",
        action="timer_expired",
        payload={"phase": engine.round.phase},
        reason="time limit reached",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: restore saved state if available
    saved_state = persistence.load_state()
    if saved_state:
        try:
            engine.restore_state(saved_state)
            print("[Server] Restored existing game state from state.json")
        except Exception as e:
            print(f"[Server] Failed to restore saved state: {e}. Keeping default initialized state.")
    else:
        # Save initial state
        save_state()
        print("[Server] Initialized new tournament state and saved to state.json")

    if esp_bridge.enabled:
        started = await esp_bridge.start()
        print(f"[Server] ESP32 UDP listener {'ready on port ' + str(esp_bridge.port) if started else 'unavailable'}")
    else:
        print("[Server] ESP32 UDP listener disabled by configuration")

    yield

    # Shutdown
    timer.pause()
    await esp_bridge.stop()
    print("[Server] Server shutting down")


app = FastAPI(
    title="EEE Brain Battle - Game Engine Server",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static directory for shared theme and debug assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# -----------------------------------------------------------------------------
# REST Endpoints
# -----------------------------------------------------------------------------


@app.get("/api/state")
def get_state() -> Dict[str, Any]:
    """Returns the current full game state."""
    state = engine.get_state()
    state["stage_locked"] = ws_manager.stage_locked
    state["buzzer_source_mode"] = engine.buzzer_source_mode
    state["esp32_detected"] = bool(esp_bridge.online)
    state["esp32_ip"] = esp_bridge.locked_ip
    state["mobile_a_connected"] = any(d.role == "buzzer_a" for d in ws_manager.active_connections.values())
    state["mobile_b_connected"] = any(d.role == "buzzer_b" for d in ws_manager.active_connections.values())
    return state


@app.get("/api/devices")
def get_devices() -> Dict[str, Any]:
    """Returns list of currently connected devices and latencies."""
    return {"devices": ws_manager.get_devices()}


@app.get("/api/health")
def get_health() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - start_time, 2),
        "version": "1.0.0",
        "timestamp": time.time(),
    }


@app.get("/api/network")
@app.get("/api/network-info")
def get_network() -> Dict[str, Any]:
    """Auto-detects hotspot and LAN IP addresses for clients to connect."""
    return get_network_info(port=config.port)


@app.get("/api/stage/status")
def stage_status() -> Dict[str, Any]:
    """Read-only view of stage-device authorization and ESP32 link status."""
    payload = ws_manager.stage_lock_state()
    payload["esp32"] = esp_bridge.status()
    return payload


@app.get("/api/hub/esp32")
def hub_esp32_status(request: Request) -> Dict[str, Any]:
    require_hub(request)
    return esp_bridge.status()


@app.get("/api/hub/status")
def hub_status(request: Request) -> Dict[str, Any]:
    require_hub(request)
    state_file = persistence.state_file
    saved_at = last_state_saved_at
    if state_file.exists():
        saved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(state_file.stat().st_mtime))
    return {
        "bind": f"{config.host}:{config.port}",
        "saved_at": saved_at,
        "state_file": str(state_file),
        "devices": len(ws_manager.active_connections),
        "test_mode": hub_test_mode,
    }


@app.post("/api/admin/auth")
async def admin_auth(request: Request) -> JSONResponse:
    body = await request.json()
    if not config.validate_auth("admin", str(body.get("pin", ""))):
        raise HTTPException(status_code=401, detail="Invalid Admin PIN")
    token = os.urandom(24).hex()
    admin_sessions.add(token)
    response = JSONResponse({"success": True, "expires_in": 43200})
    response.set_cookie("admin_session", token, httponly=True, samesite="strict", max_age=43200)
    return response


@app.post("/api/moderator/auth")
async def moderator_auth(request: Request) -> JSONResponse:
    body = await request.json()
    if not config.validate_auth("moderator", str(body.get("pin", ""))):
        raise HTTPException(status_code=401, detail="Invalid Moderator PIN")
    token = os.urandom(24).hex()
    moderator_sessions.add(token)
    response = JSONResponse({"success": True, "expires_in": 43200})
    response.set_cookie("moderator_session", token, httponly=True, samesite="strict", max_age=43200)
    return response


@app.post("/api/moderator/logout")
async def moderator_logout(request: Request) -> JSONResponse:
    token = request.cookies.get("moderator_session")
    if token:
        moderator_sessions.discard(token)
    response = JSONResponse({"success": True})
    response.delete_cookie("moderator_session")
    return response


@app.get("/api/moderator/session")
def moderator_session_status(request: Request) -> Dict[str, Any]:
    token = request.cookies.get("moderator_session")
    return {"authenticated": bool(token and token in moderator_sessions)}


@app.post("/api/hub/auth")
async def hub_auth(request: Request) -> JSONResponse:
    body = await request.json()
    if not config.validate_auth("hub", str(body.get("pin", ""))):
        raise HTTPException(status_code=401, detail="Invalid Hub PIN")
    token = os.urandom(24).hex()
    hub_sessions.add(token)
    response = JSONResponse({"success": True, "expires_in": 43200})
    response.set_cookie("hub_session", token, httponly=True, samesite="strict", max_age=43200)
    return response


@app.post("/api/hub/logout")
async def hub_logout(request: Request) -> JSONResponse:
    token = request.cookies.get("hub_session")
    if token:
        hub_sessions.discard(token)
    response = JSONResponse({"success": True})
    response.delete_cookie("hub_session")
    return response


@app.get("/api/hub/session")
def hub_session_status(request: Request) -> Dict[str, Any]:
    token = request.cookies.get("hub_session")
    return {"authenticated": bool(token and token in hub_sessions)}


def require_stage_access(request: Request) -> None:
    host = request.client.host if request.client else "unknown"
    if not ws_manager.is_ip_authorized(host):
        raise HTTPException(
            status_code=403,
            detail=f"Stage devices are locked: {host} is not in the authorized allowlist",
        )


def require_admin(request: Request) -> None:
    require_stage_access(request)
    token = request.cookies.get("admin_session")
    if not token or token not in admin_sessions:
        raise HTTPException(status_code=401, detail="Admin authentication required")


def require_hub(request: Request) -> None:
    require_stage_access(request)
    token = request.cookies.get("hub_session")
    if not token or token not in hub_sessions:
        raise HTTPException(status_code=401, detail="Hub authentication required")


@app.get("/api/admin/state")
def admin_state(request: Request) -> Dict[str, Any]:
    require_admin(request)
    return engine.get_state()


@app.get("/api/admin/logs")
def admin_logs(request: Request, limit: int = 300) -> Dict[str, Any]:
    require_admin(request)
    entries = engine.get_state().get("log", [])
    return {
        "logs": entries[-max(1, min(limit, 1000)):],
        "audit_log": persistence.read_audit_log(limit),
    }


@app.get("/api/admin/report")
def admin_report(request: Request, format: str = "json") -> Response:
    require_admin(request)
    state = engine.get_state()
    if format.lower() == "json":
        report = dict(state)
        report["audit_log"] = persistence.read_audit_log()
        return JSONResponse(report, headers={"Content-Disposition": 'attachment; filename="eee_brain_battle_report.json"'})
    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="format must be json or csv")

    teams = state.get("teams", {})
    matches = state["event"]["bracket"]["matches"]
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["SECTION 1: 12-TEAM CUMULATIVE & MATCH-BY-MATCH STANDINGS"])
    writer.writerow(
        ["Team ID", "Team Name", "Designated Speaker", "Total Points", "Matches Played", "Wins", "Losses"]
        + [f"M{number}" for number in range(1, 14)]
    )
    for team_id in sorted(teams):
        team = teams[team_id]
        win_loss = team.get("win_loss") or {}
        row = [
            team_id,
            team.get("name", team_id),
            team.get("designated_speaker", ""),
            team.get("total_points", 0),
            team.get("matches_played", 0),
            win_loss.get("wins", 0),
            win_loss.get("losses", 0),
        ]
        row.extend(team.get("match_scores", {}).get(str(number), 0) for number in range(1, 14))
        writer.writerow(row)
    writer.writerow([])

    writer.writerow(["SECTION 2: MATCH-BY-MATCH RESULTS BREAKDOWN"])
    writer.writerow(
        ["Match", "Stage", "Status", "Team A ID", "Team A Name", "Team B ID", "Team B Name",
         "Winner", "Loser", "Score A", "Score B", "Rapid Fire A", "Buzzer A", "Fouls A",
         "Answered A", "Rapid Fire B", "Buzzer B", "Fouls B", "Answered B"]
    )
    for match in matches:
        team_a = match.get("team_a_id")
        team_b = match.get("team_b_id")
        scores = match.get("scores", {})
        stats = match.get("stats", {})

        def stat(team_id: Optional[str], key: str) -> int:
            return int((stats.get(team_id) or {}).get(key, 0)) if team_id else 0

        writer.writerow([
            match["match_number"], match.get("stage", ""), match.get("status", ""),
            team_a or "", teams.get(team_a, {}).get("name", "") if team_a else "",
            team_b or "", teams.get(team_b, {}).get("name", "") if team_b else "",
            match.get("winner_id") or "", match.get("loser_id") or "",
            scores.get(team_a, 0) if team_a else 0, scores.get(team_b, 0) if team_b else 0,
            stat(team_a, "rapid_fire_points"), stat(team_a, "buzzer_points"),
            stat(team_a, "foul_penalties"), stat(team_a, "questions_answered"),
            stat(team_b, "rapid_fire_points"), stat(team_b, "buzzer_points"),
            stat(team_b, "foul_penalties"), stat(team_b, "questions_answered"),
        ])
    writer.writerow([])

    writer.writerow(["SECTION 3: FULL TIMESTAMPED AUDIT LOG"])
    writer.writerow(["Timestamp", "Source", "Role", "Device", "Action", "Reason", "Details"])
    audit_rows = []
    for entry in state.get("log", []):
        audit_rows.append({
            "timestamp": entry.get("timestamp", ""), "source": "engine", "role": "engine",
            "device": "engine", "action": entry.get("action", ""), "reason": "",
            "details": json.dumps(entry.get("details", {}), separators=(",", ":")),
        })
    pattern = re.compile(
        r'^\[([^\]]+)\]\s+role=(\S+)\s+device=(\S+)\s+action=(\S+)\s+reason="(.*?)"\s+details=(.*)$'
    )
    for line in persistence.read_audit_log():
        parsed = pattern.match(line)
        if parsed:
            audit_rows.append({
                "timestamp": parsed.group(1), "source": "persistence", "role": parsed.group(2),
                "device": parsed.group(3), "action": parsed.group(4), "reason": parsed.group(5),
                "details": parsed.group(6),
            })
        else:
            audit_rows.append({
                "timestamp": "", "source": "persistence", "role": "", "device": "",
                "action": "raw", "reason": "", "details": line,
            })
    audit_rows.sort(key=lambda item: item["timestamp"])
    for row in audit_rows:
        writer.writerow([row[key] for key in
                         ("timestamp", "source", "role", "device", "action", "reason", "details")])

    return Response(output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="eee_brain_battle_audit_sheet.csv"'})


@app.get("/api/hub/qr")
def hub_qr(request: Request, ip: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    require_hub(request)
    network = get_network_info(port or config.port)
    selected_ip = ip or network["primary_ip"]
    urls = get_role_urls(selected_ip, port or config.port)
    return {
        "ip": selected_ip,
        "urls": urls,
        "qr": {role: generate_qr_svg(item["url"]) for role, item in urls.items()},
    }


@app.get("/api/hub/backup")
def hub_backup(request: Request) -> Response:
    require_hub(request)
    return JSONResponse(engine.get_state(), headers={"Content-Disposition": 'attachment; filename="state-backup.json"'})


@app.post("/api/hub/restore")
async def hub_restore(request: Request) -> Dict[str, Any]:
    require_hub(request)
    body = await request.json()
    state = body.get("state", body)
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="A JSON state object is required")
    try:
        engine.restore_state(state)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid state backup: {exc}") from exc
    save_state()
    persistence.log_audit("hub", "rest", "restore_state", {}, "Hub backup restore")
    await ws_manager.broadcast_state(engine.get_state())
    return {"restored": True}


@app.get("/debug", response_class=HTMLResponse)
def get_debug_page() -> str:
    """Minimal debug page for testing all Phase 1 capabilities."""
    debug_file = WEB_DIR / "debug.html"
    if debug_file.exists():
        with open(debug_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Debug page not found</h1>"


def _read_web_page(filename: str) -> str:
    page = WEB_DIR / filename
    if page.exists():
        return page.read_text(encoding="utf-8")
    return f"<h1>{filename} not found</h1>"


@app.get("/", response_class=HTMLResponse)
def get_root_page() -> str:
    return _read_web_page("hub.html")


@app.get("/display", response_class=HTMLResponse)
def get_display_page() -> str:
    return _read_web_page("display.html")


@app.get("/admin", response_class=HTMLResponse)
def get_admin_page() -> str:
    return _read_web_page("admin.html")


@app.get("/results", response_class=HTMLResponse)
def get_results_page() -> str:
    return _read_web_page("results.html")


@app.get("/moderator", response_class=HTMLResponse)
def get_moderator_page() -> str:
    return _read_web_page("moderator.html")


@app.get("/buzzer/a", response_class=HTMLResponse)
def get_buzzer_a_page() -> str:
    return _read_web_page("buzzer_a.html")


@app.get("/buzzer/b", response_class=HTMLResponse)
def get_buzzer_b_page() -> str:
    return _read_web_page("buzzer_b.html")


@app.get("/hub", response_class=HTMLResponse)
def get_hub_page() -> str:
    return _read_web_page("hub.html")


@app.get("/buzzers", response_class=HTMLResponse)
def get_buzzers_page() -> str:
    return _read_web_page("buzzers.html")


@app.get("/api/buzzers/mode")
def get_buzzer_mode() -> Dict[str, Any]:
    return {
        "buzzer_source_mode": engine.buzzer_source_mode,
        "esp32_detected": bool(esp_bridge.online),
        "esp32_ip": esp_bridge.locked_ip,
        "last_command": getattr(esp_bridge, "last_command", None),
        "mobile_a_connected": any(d.role == "buzzer_a" for d in ws_manager.active_connections.values()),
        "mobile_b_connected": any(d.role == "buzzer_b" for d in ws_manager.active_connections.values()),
    }


@app.post("/api/buzzers/mode")
async def post_buzzer_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = payload.get("mode") or payload.get("buzzer_source_mode")
    if not mode or str(mode).upper() not in ("ESP32", "MOBILE"):
        raise HTTPException(status_code=400, detail="mode must be 'ESP32' or 'MOBILE'")
    normalized = str(mode).upper()
    engine.strict_esp32 = (normalized == "ESP32")
    res = engine.set_buzzer_source_mode(normalized)
    save_state()
    await ws_manager.broadcast_event("buzzer_source_mode_changed", mode=normalized)
    await ws_manager.broadcast_state(get_state())
    return {"buzzer_source_mode": normalized, "success": True}


@app.get("/api/buzzers/qr")
def get_buzzers_qr(ip: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    network = get_network_info(port or config.port)
    selected_ip = ip or network["primary_ip"]
    urls = get_role_urls(selected_ip, port or config.port)
    return {
        "primary_ip": selected_ip,
        "urls": urls,
        "qr": {role: generate_qr_svg(item["url"]) for role, item in urls.items()},
    }


@app.get("/api/tournament/progress")
def get_tournament_progress_endpoint() -> Dict[str, Any]:
    return engine.get_tournament_progress()


@app.post("/api/tournament/advance-and-load-next")
async def post_advance_and_load_next() -> Dict[str, Any]:
    timer.pause()
    esp_bridge.send_reset()
    res = engine.advance_and_load_next()
    state_snapshot = get_state()
    await ws_manager.broadcast_event("match_advanced", **res)
    await ws_manager.broadcast_state(state_snapshot)
    schedule_persistence(state_snapshot, role="system", device="rest", action="advance_and_load_next", payload=res)
    return res


@app.post("/api/tournament/reset-scores-keep-roster")
async def post_reset_scores_keep_roster() -> Dict[str, Any]:
    timer.pause()
    esp_bridge.send_reset()
    res = engine.reset_scores_keep_roster()
    state_snapshot = get_state()
    await ws_manager.broadcast_event("scores_reset_keep_roster", **res)
    await ws_manager.broadcast_state(state_snapshot)
    schedule_persistence(state_snapshot, role="system", device="rest", action="reset_scores_keep_roster", payload=res)
    return res


# -----------------------------------------------------------------------------
# WebSocket Endpoint
# -----------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    client_ip = websocket.client.host if websocket.client else "unknown"
    if not ws_manager.is_ip_authorized(client_ip):
        await websocket.close(code=4403)
        print(f"[WebSocket] Rejected unauthorized stage device {client_ip} (HTTP 403)")
        return
    await websocket.accept()
    device = ws_manager.register(websocket, client_ip)

    try:
        # Step 1: Handshake awaiting 'hello'
        handshake_raw = await websocket.receive_text()
        try:
            import json
            handshake = json.loads(handshake_raw)
        except Exception:
            await websocket.send_json({"type": "auth_error", "message": "Expected JSON handshake"})
            await websocket.close(code=1008)
            ws_manager.unregister(device.device_id)
            return

        if handshake.get("type") != "hello":
            await websocket.send_json({"type": "auth_error", "message": "First message must be {type: 'hello'}"})
            await websocket.close(code=1008)
            ws_manager.unregister(device.device_id)
            return

        role = handshake.get("role", "")
        pin_or_code = handshake.get("pin_or_code", handshake.get("pin", handshake.get("pairing", "")))

        if not config.validate_auth(role, pin_or_code):
            await websocket.send_json(
                {
                    "type": "auth_error",
                    "message": f"Authentication failed for role '{role}'. Invalid PIN or code.",
                }
            )
            await websocket.close(code=1008)
            ws_manager.unregister(device.device_id)
            return

        ws_manager.update_identity(
            device,
            str(handshake.get("device_id", "")),
            str(handshake.get("device_name", "")),
            str(handshake.get("user_agent", "")),
        )
        device.role = role
        device.authenticated = True
        device.last_seen_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Send welcome and current state immediately (handles automatic reconnect)
        await websocket.send_json(
            {
                "type": "welcome",
                "device_id": device.device_id,
                "role": device.role,
                "authenticated": True,
            }
        )
        await websocket.send_json({"type": "state", "data": engine.get_state()})
        await ws_manager.broadcast_event_except(device.device_id, "device_connected", device=device.to_dict())

        # Step 2: Main message loop
        while True:
            msg_raw = await websocket.receive_text()
            try:
                import json
                msg = json.loads(msg_raw)
            except Exception:
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload"})
                continue

            msg_type = msg.get("type")
            if msg_type == "buzz":
                msg = {
                    "type": "action",
                    "action": "buzz",
                    "payload": msg,
                    "reason": "Buzzer pressed",
                }
                msg_type = "action"

            # --- Ping / Pong & Latency measurement ---
            if msg_type == "ping":
                device.last_ping = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                device.last_seen_at = device.last_ping
                c_time = msg.get("client_time")
                await websocket.send_json(
                    {
                        "type": "pong",
                        "client_time": c_time,
                        "server_time": time.time(),
                    }
                )
                continue

            if msg_type == "latency_report":
                device.last_seen_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                lat = msg.get("latency_ms")
                if lat is not None:
                    try:
                        device.latency_ms = float(lat)
                    except ValueError:
                        pass
                continue

            if msg_type in {"device_event_ack", "hub_test_ack"}:
                device.last_seen_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await ws_manager.broadcast_event(
                    "device_event_ack",
                    device=device.to_dict(),
                    event=msg.get("event", ""),
                    acknowledgment=msg_type,
                )
                continue

            # --- Actions ---
            if msg_type == "action":
                action = msg.get("action")
                payload = msg.get("payload", {})
                reason = msg.get("reason", "")

                if not action:
                    await websocket.send_json({"type": "error", "message": "Action name missing"})
                    continue

                # Check role permissions
                if not ws_manager.is_action_allowed(device.role, action):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Permission denied: role '{device.role}' cannot execute '{action}'",
                        }
                    )
                    continue

                # Lock to serialize game engine state updates
                async with ws_manager._lock:
                    try:
                        res = await execute_engine_action(device, action, payload, reason)
                        state_snapshot = get_state()
                        await ws_manager.broadcast_state(state_snapshot)
                        await websocket.send_json(
                            {
                                "type": "action_ack",
                                "action": action,
                                "success": True,
                                "result": res,
                            }
                        )
                        schedule_persistence(
                            state_snapshot,
                            role=device.role,
                            device=device.device_id,
                            action=action,
                            payload=payload,
                            reason=reason,
                        )
                        if action == "buzz" and isinstance(res, dict):
                            await ws_manager.broadcast_event(
                                "fairness_telemetry",
                                team=res.get("team_id"),
                                arrival_timestamp_ms=res.get("arrival_timestamp_ms"),
                                delta_ms=res.get("delta_ms"),
                            )
                        if action in {"open_question", "next_question"} and isinstance(res, dict):
                            if res.get("warning"):
                                await ws_manager.broadcast_event(
                                    "question_bank_warning",
                                    message=res["warning"],
                                    remaining=res.get("remaining", 0),
                                )

                    except Exception as e:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "action": action,
                                "message": str(e),
                            }
                        )
                continue

            await websocket.send_json({"type": "error", "message": f"Unknown message type '{msg_type}'"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket] Error on device {device.device_id}: {e}")
    finally:
        if device.authenticated:
            await ws_manager.broadcast_event("device_disconnected", device=device.to_dict())
        ws_manager.unregister(device.device_id)


async def execute_engine_action(
    device: ConnectedDevice, action: str, payload: Dict[str, Any], reason: str
) -> Any:
    """Executes validated action on the pure game engine or timer."""
    global hub_test_mode
    # Special buzzer handling: verify team identity based on buzzer role
    if action == "buzz":
        if engine.buzzer_source_mode == "ESP32" and (esp_bridge.online or getattr(engine, "strict_esp32", False)):
            return {
                "status": "ignored",
                "reason": "ESP32 Primary Active — Mobile Buzzers in Standby",
                "buzzer_source_mode": engine.buzzer_source_mode,
            }
        if hub_test_mode:
            await ws_manager.broadcast_event("test_buzz_received", team=payload.get("team"))
            return {"test_mode": True, "team_id": payload.get("team")}
        target_team = payload.get("team")
        if device.role == "buzzer_a":
            if not engine.current_match or not engine.current_match.team_a_id:
                raise ValueError("Current match has no Team A configured")
            target_team = engine.current_match.team_a_id
        elif device.role == "buzzer_b":
            if not engine.current_match or not engine.current_match.team_b_id:
                raise ValueError("Current match has no Team B configured")
            target_team = engine.current_match.team_b_id

        if not target_team:
            raise ValueError("Team must be specified for buzz action")

        arrival_ms = time.time_ns() / 1_000_000
        res = engine.buzz(team_id=target_team, timestamp=payload.get("timestamp"))
        previous_arrival = max(buzzer_arrivals.values()) if buzzer_arrivals else None
        buzzer_arrivals[target_team] = arrival_ms
        delta_ms = round(arrival_ms - previous_arrival, 3) if previous_arrival is not None else None
        res["arrival_timestamp_ms"] = round(arrival_ms, 3)
        res["delta_ms"] = delta_ms
        # Broadcast buzz event for client animation
        await ws_manager.broadcast_event(
            "buzz_first",
            team=target_team,
            timestamp=res.get("press_timestamp"),
        )
        return res

    elif action == "confirm_first_buzz":
        res = engine.confirm_first_buzz(payload.get("team_id"))
        await ws_manager.broadcast_event("buzz_confirmed", team=res.get("confirmed_team"))
        return res

    elif action == "setup_match":
        stage = payload.get("stage", engine.stage)
        match_num = int(payload.get("match_number", 1))
        t_a = payload.get("team_a_id")
        t_b = payload.get("team_b_id")
        if not t_a or not t_b:
            raise ValueError("Both team_a_id and team_b_id are required")
        engine.setup_match(stage, match_num, t_a, t_b)
        timer.pause()
        return {"match_number": match_num}

    elif action == "set_display_view":
        result = engine.set_display_view(payload.get("view", "auto"))
        await ws_manager.broadcast_event("display_view_changed", view=result["view"])
        return result

    elif action == "set_total_questions":
        return engine.set_total_questions(int(payload.get("total_questions", 15)))

    elif action == "configure_routing":
        return engine.configure_routing(payload.get("mode", "BUZZER_OPEN"),
                                        payload.get("start_side", "A"),
                                        int(payload.get("block_size", 10)))

    elif action == "switch_turn":
        result = engine.switch_turn(int(payload.get("reset_seconds", 120)))
        timer.reset(int(payload.get("reset_seconds", 120)))
        esp_bridge.send_reset()
        return result

    elif action == "select_question":
        return engine.select_question(int(payload.get("question_number", 1)))

    elif action == "mark_question_won":
        return engine.mark_question_won(payload.get("team_id"))

    elif action == "mark_question_dead":
        return engine.mark_question_dead()

    elif action == "reset_question_matrix":
        return engine.reset_question_matrix()

    elif action == "undo_last_action":
        return engine.undo_last_action()

    elif action in {"warning_logged", "foul_penalty"}:
        violation = str(payload.get("violation", "")).strip()
        team_id = payload.get("team_id")
        if not violation or not team_id:
            raise ValueError("Team and violation reason are required")
        return engine.apply_violation(team_id, violation, 5 if action == "foul_penalty" else 0)

    elif action == "admin_update_team":
        members = [str(m).strip() for m in payload.get("members", []) if str(m).strip()]
        return engine.update_team(payload.get("team_id", ""), payload.get("name", ""),
                                  members, payload.get("designated_speaker", ""),
                                  payload.get("accent_color"))

    elif action == "init_default_tournament":
        engine.init_default_tournament()
        timer.pause()
        return {"reset": True}

    elif action == "start_rapid_fire":
        team_id = payload.get("team_id")
        duration = int(payload.get("duration_seconds", 120))
        if not team_id:
            raise ValueError("team_id is required to start Rapid Fire")
        engine.start_rapid_fire(team_id, duration)
        timer.start(duration, on_tick=on_timer_tick, on_expired=on_timer_expired)
        engine.round.timer_running = True
        engine.round.timer_seconds_remaining = duration
        await ws_manager.broadcast_event(
            "timer_started",
            seconds=duration,
            seconds_remaining=duration,
            running=True,
        )
        return {"team_id": team_id, "duration": duration}

    elif action == "start_buzzer_battle":
        engine.start_buzzer_battle()
        timer.pause()
        timer.reset(0)
        engine.round.timer_running = False
        engine.round.timer_seconds_remaining = 0
        esp_bridge.send_reset()
        await ws_manager.broadcast_event(
            "timer_reset",
            seconds=0,
            seconds_remaining=0,
            running=False,
        )
        await ws_manager.broadcast_event("buzzer_battle_started", phase=RoundPhase.BUZZER_BATTLE.value)
        return {"phase": RoundPhase.BUZZER_BATTLE.value}

    elif action == "open_question":
        buzzer_arrivals.clear()
        res = engine.open_question()
        esp_bridge.send_reset()
        return res

    elif action == "mark_correct":
        team_id = payload.get("team_id")
        res = engine.mark_correct(team_id)
        if not (isinstance(res, dict) and res.get("duplicate")):
            await ws_manager.broadcast_event("score_changed", result=res)
        return res

    elif action == "mark_wrong":
        team_id = payload.get("team_id")
        res = engine.mark_wrong(team_id)
        if not (isinstance(res, dict) and res.get("duplicate")):
            if engine.buzzers.passed_to_team:
                passed_side = "A" if engine.current_match and engine.buzzers.passed_to_team == engine.current_match.team_a_id else "B"
                esp_bridge.send_pass(passed_side)
            await ws_manager.broadcast_event("score_changed", result=res)
        return res

    elif action == "reveal_answer":
        engine.reveal_answer()
        await ws_manager.broadcast_event("answer_revealed")
        return {"revealed": True}

    elif action == "lock_buzzers":
        engine.lock_buzzers()
        return {"locked": True}

    elif action == "unlock_buzzers":
        engine.unlock_buzzers()
        esp_bridge.send_reset()
        return {"locked": False}

    elif action == "next_question":
        buzzer_arrivals.clear()
        res = engine.next_question()
        esp_bridge.send_reset()
        return res

    elif action == "previous_question":
        return engine.previous_question()

    elif action == "skip_question":
        return engine.mark_question_dead()

    elif action == "start_sudden_death":
        engine.start_sudden_death()
        timer.pause()
        timer.reset(0)
        engine.round.timer_running = False
        engine.round.timer_seconds_remaining = 0
        esp_bridge.send_reset()
        await ws_manager.broadcast_event(
            "timer_reset",
            seconds=0,
            seconds_remaining=0,
            running=False,
        )
        await ws_manager.broadcast_event("sudden_death_started", phase=RoundPhase.SUDDEN_DEATH.value)
        return {"phase": RoundPhase.SUDDEN_DEATH.value}

    elif action == "end_match":
        res = engine.end_match()
        timer.pause()
        await ws_manager.broadcast_event("match_ended", result=res)
        return res

    elif action == "advance_winner":
        match_number = payload.get("match_number")
        if match_number is None or str(match_number).strip() == "":
            raise ValueError("match_number is required for advance_winner")
        winner_id = payload.get("winner_id") or None
        res = engine.advance_winner(match_number=match_number, winner_id=winner_id)
        timer.pause()
        esp_bridge.send_reset()
        await ws_manager.broadcast_event("match_advanced", **res)
        return res

    elif action == "advance_and_load_next":
        timer.pause()
        esp_bridge.send_reset()
        res = engine.advance_and_load_next()
        await ws_manager.broadcast_event("match_advanced", **res)
        return res

    elif action == "reset_scores_keep_roster":
        timer.pause()
        esp_bridge.send_reset()
        res = engine.reset_scores_keep_roster()
        await ws_manager.broadcast_event("scores_reset_keep_roster", **res)
        return res

    elif action == "admin_adjust_score":
        team_id = payload.get("team_id")
        delta = int(payload.get("delta", 0))
        if not team_id:
            raise ValueError("team_id required for admin_adjust_score")
        if not reason.strip():
            raise ValueError("A mandatory reason is required for score adjustments")
        res = engine.admin_adjust_score(team_id, delta, reason)
        await ws_manager.broadcast_event("score_adjusted", result=res)
        return res

    elif action == "reset_match":
        timer.pause()
        engine.reset_match()
        return {"reset": True}

    elif action == "resolve_wild_card_tie":
        winning_team = payload.get("winning_team_id")
        if not winning_team:
            raise ValueError("winning_team_id required")
        engine.resolve_wild_card_tie(winning_team)
        return {"resolved": True}

    elif action == "override_quarterfinal_pairings":
        pairings = payload.get("pairings", [])
        res = engine.override_quarterfinal_pairings(pairings)
        await ws_manager.broadcast_event("quarterfinal_pairings_overridden", pairings=pairings)
        return res

    elif action == "toggle_stage_lock":
        result = ws_manager.toggle_stage_lock(
            payload.get("stage_locked"),
            payload.get("authorized_ips"),
        )
        await ws_manager.broadcast_event("stage_lock_changed", **result)
        return result

    elif action == "set_buzzer_source_mode":
        mode = payload.get("mode") or payload.get("buzzer_source_mode", "ESP32")
        normalized = str(mode).upper()
        engine.strict_esp32 = (normalized == "ESP32")
        result = engine.set_buzzer_source_mode(normalized)
        await ws_manager.broadcast_event("buzzer_source_mode_changed", mode=normalized)
        return result

    elif action == "hub_esp32_test":
        result = esp_bridge.send_test()
        await ws_manager.broadcast_event("esp32_test", **result)
        return result

    elif action == "hub_esp32_reset":
        result = esp_bridge.reset()
        await ws_manager.broadcast_event("esp32_reset", **result)
        return result

    elif action == "hub_assign_role":
        device_id = payload.get("device_id")
        role = payload.get("role")
        before_roles = {
            connected_id: connected.role
            for connected_id, connected in ws_manager.active_connections.items()
        }
        assigned = ws_manager.assign_role(device_id, role)
        for connected_id, connected in ws_manager.active_connections.items():
            if before_roles.get(connected_id) != connected.role:
                await ws_manager.broadcast_event(
                    "device_role_assigned",
                    device=connected.to_dict(),
                )
        return assigned

    elif action == "hub_swap_buzzers":
        devices = ws_manager.swap_buzzers()
        for assigned in devices:
            await ws_manager.broadcast_event("device_role_assigned", device=assigned)
        return {"devices": devices}

    elif action == "hub_test_buzz_all":
        for role in ("buzzer_a", "buzzer_b"):
            target = next((item for item in ws_manager.active_connections.values() if item.role == role), None)
            if target:
                await ws_manager.send_to_device(
                    target.device_id,
                    {"type": "event", "name": "hub_test_pulse", "target_role": role},
                )
        return {"test_pulse": True}

    elif action in {"hub_test_buzz_a", "hub_test_buzz_b"}:
        role = "buzzer_a" if action.endswith("_a") else "buzzer_b"
        device = next((item for item in ws_manager.active_connections.values() if item.role == role), None)
        if not device:
            raise ValueError(f"{role.replace('_', ' ').title()} is not connected")
        await ws_manager.send_to_device(device.device_id, {"type": "event", "name": "hub_test_pulse"})
        return {"test_pulse": True, "role": role}

    elif action == "hub_set_test_mode":
        hub_test_mode = bool(payload.get("enabled", False))
        await ws_manager.broadcast_event("hub_test_mode_changed", enabled=hub_test_mode)
        return {"enabled": hub_test_mode}

    elif action == "hub_run_diagnostic":
        checks = {"state_writable": False, "buzzer_a_pulse": False, "buzzer_b_pulse": False}
        try:
            save_state()
            checks["state_writable"] = True
        except IOError:
            checks["state_writable"] = False
        for role, key in (("buzzer_a", "buzzer_a_pulse"), ("buzzer_b", "buzzer_b_pulse")):
            target = next((item for item in ws_manager.active_connections.values() if item.role == role), None)
            if target:
                await ws_manager.send_to_device(
                    target.device_id,
                    {"type": "event", "name": "hub_test_pulse", "target_role": role, "diagnostic": True},
                )
                checks[key] = True
                await ws_manager.send_to_device(
                    target.device_id,
                    {"type": "event", "name": "hub_ping_request", "diagnostic": True},
                )
        checks["connected_devices"] = len(ws_manager.active_connections)
        checks["passed"] = checks["state_writable"] and checks["buzzer_a_pulse"] and checks["buzzer_b_pulse"]
        await ws_manager.broadcast_event("diagnostic_complete", checks=checks)
        return checks

    elif action == "hub_lock_buzzers":
        engine.lock_buzzers()
        await ws_manager.broadcast_event("buzzers_locked")
        return {"locked": True}

    elif action == "hub_unlock_buzzers":
        engine.unlock_buzzers()
        await ws_manager.broadcast_event("buzzers_unlocked")
        return {"locked": False}

    elif action == "hub_clear_buzz":
        result = engine.confirm_first_buzz("clear")
        esp_bridge.send_reset()
        await ws_manager.broadcast_event("buzz_cleared")
        return result

    elif action == "hub_reset_round":
        timer.pause()
        result = engine.reset_round()
        esp_bridge.send_reset()
        await ws_manager.broadcast_event("round_reset")
        return result

    elif action == "hub_ping_device":
        device_id = str(payload.get("device_id", ""))
        target = ws_manager.active_connections.get(device_id)
        if not target:
            raise ValueError("Device is not connected")
        await ws_manager.send_to_device(device_id, {"type": "event", "name": "hub_ping_request"})
        return {"device_id": device_id, "sent": True}

    elif action == "hub_kick_device":
        device_id = str(payload.get("device_id", ""))
        target = ws_manager.active_connections.get(device_id)
        if not target:
            raise ValueError("Device is not connected")
        await target.websocket.close(code=4000, reason="Disconnected by Control Hub")
        return {"device_id": device_id, "kicked": True}

    # Timer actions
    elif action == "start_timer":
        sec = int(payload.get("seconds", 120))
        timer.start(sec, on_tick=on_timer_tick, on_expired=on_timer_expired)
        engine.round.timer_seconds_remaining = sec
        engine.round.timer_duration_seconds = sec
        engine.round.timer_running = True
        await ws_manager.broadcast_event(
            "timer_started",
            seconds=sec,
            seconds_remaining=sec,
            running=True,
        )
        return {"seconds": sec}

    elif action == "pause_timer":
        timer.pause()
        engine.round.timer_running = False
        engine.round.timer_seconds_remaining = timer.seconds_remaining
        await ws_manager.broadcast_event(
            "timer_paused",
            seconds=timer.seconds_remaining,
            seconds_remaining=timer.seconds_remaining,
            running=False,
        )
        return {"paused": True, "seconds": timer.seconds_remaining}

    elif action == "resume_timer":
        if timer.seconds_remaining <= 0 and engine.round.timer_seconds_remaining > 0:
            timer.seconds_remaining = engine.round.timer_seconds_remaining
        if timer._on_tick is None:
            timer._on_tick = on_timer_tick
        if timer._on_expired is None:
            timer._on_expired = on_timer_expired
        timer.resume()
        engine.round.timer_running = timer.is_running
        engine.round.timer_seconds_remaining = timer.seconds_remaining
        await ws_manager.broadcast_event(
            "timer_started",
            seconds=timer.seconds_remaining,
            seconds_remaining=timer.seconds_remaining,
            running=timer.is_running,
        )
        return {"resumed": timer.is_running, "seconds": timer.seconds_remaining}

    elif action == "reset_timer":
        sec = int(payload.get("seconds", 120))
        timer.reset(sec)
        engine.round.timer_seconds_remaining = sec
        engine.round.timer_duration_seconds = sec
        engine.round.timer_running = False
        await ws_manager.broadcast_event(
            "timer_reset",
            seconds=sec,
            seconds_remaining=sec,
            running=False,
        )
        return {"seconds": sec}

    elif action == "adjust_timer":
        delta = int(payload.get("delta_seconds", 0))
        target_sec = payload.get("seconds")
        current = timer.seconds_remaining if timer.is_running else engine.round.timer_seconds_remaining
        new_sec = max(0, int(target_sec)) if target_sec is not None else max(0, current + delta)

        was_running = timer.is_running or engine.round.timer_running
        timer.seconds_remaining = new_sec
        engine.round.timer_seconds_remaining = new_sec
        engine.round.timer_duration_seconds = max(engine.round.timer_duration_seconds, new_sec)
        if was_running:
            if timer._on_tick is None:
                timer._on_tick = on_timer_tick
            if timer._on_expired is None:
                timer._on_expired = on_timer_expired
            timer.resume()
        else:
            timer.pause()
        engine.round.timer_running = timer.is_running
        await ws_manager.broadcast_event(
            "timer_tick",
            seconds=new_sec,
            seconds_remaining=new_sec,
            running=timer.is_running,
        )
        return {"seconds": new_sec, "running": timer.is_running}

    else:
        raise ValueError(f"Unknown action: {action}")
