import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Set
from fastapi import WebSocket, WebSocketDisconnect

from server.config import Config


# Action permission sets per role
MODERATOR_ACTIONS: Set[str] = {
    "start_rapid_fire",
    "start_buzzer_battle",
    "open_question",
    "mark_correct",
    "mark_wrong",
    "confirm_first_buzz",
    "lock_buzzers",
    "unlock_buzzers",
    "reveal_answer",
    "next_question",
    "previous_question",
    "skip_question",
    "start_sudden_death",
    "end_match",
    "start_timer",
    "pause_timer",
    "resume_timer",
    "reset_timer",
    "adjust_timer",
    "set_total_questions",
    "configure_routing",
    "switch_turn",
    "select_question",
    "mark_question_won",
    "mark_question_dead",
    "reset_question_matrix",
    "undo_last_action",
    "warning_logged",
    "foul_penalty",
    "set_buzzer_source_mode",
    "advance_and_load_next",
}

ADMIN_ACTIONS: Set[str] = MODERATOR_ACTIONS | {
    "toggle_stage_lock",
    "set_display_view",
    "setup_match",
    "admin_adjust_score",
    "reset_match",
    "init_default_tournament",
    "reset_scores_keep_roster",
    "resolve_wild_card_tie",
    "override_quarterfinal_pairings",
    "admin_update_team",
    "set_buzzer_source_mode",
}
HUB_ACTIONS: Set[str] = {
    "toggle_stage_lock",
    "set_buzzer_source_mode",
    "advance_and_load_next",
    "reset_scores_keep_roster",
    "hub_esp32_test",
    "hub_esp32_reset",
    "hub_assign_role",
    "hub_swap_buzzers",
    "hub_test_buzz_all",
    "hub_test_buzz_a",
    "hub_test_buzz_b",
    "hub_run_diagnostic",
    "hub_set_test_mode",
    "hub_lock_buzzers",
    "hub_unlock_buzzers",
    "hub_clear_buzz",
    "hub_reset_round",
    "hub_ping_device",
    "hub_kick_device",
}

BUZZER_ACTIONS: Set[str] = {"buzz"}

DEFAULT_AUTHORIZED_IPS: Set[str] = {"127.0.0.1", "192.168.137.1"}


class ConnectedDevice:
    def __init__(self, websocket: WebSocket, device_id: str, ip: str, device_name: str = "", user_agent: str = ""):
        self.websocket: WebSocket = websocket
        self.device_id: str = device_id
        self.ip: str = ip
        self.device_name: str = device_name or device_id
        self.user_agent: str = user_agent
        self.role: str = "unauthenticated"
        self.authenticated: bool = False
        self.connected_at: str = datetime.now(timezone.utc).isoformat()
        self.last_ping: str = self.connected_at
        self.last_seen_at: str = self.connected_at
        self.latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "user_agent": self.user_agent,
            "role": self.role,
            "ip": self.ip,
            "authenticated": self.authenticated,
            "connected_at": self.connected_at,
            "last_ping": self.last_ping,
            "last_seen_at": self.last_seen_at,
            "latency_ms": round(self.latency_ms, 2),
        }


class WebSocketManager:
    """Manages active WebSocket connections, role authentication,
    permission enforcement, device registry, and broadcasts.
    """

    def __init__(self, config: Config):
        self.config: Config = config
        self.active_connections: Dict[str, ConnectedDevice] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        stage_config = config.stage_config
        configured_ips = stage_config.get("authorized_ips", [])
        self.authorized_ips: Set[str] = set(DEFAULT_AUTHORIZED_IPS) | {
            str(ip).strip() for ip in configured_ips if str(ip).strip()
        }
        self.stage_locked: bool = bool(stage_config.get("locked", False))

    def stage_lock_state(self) -> Dict[str, Any]:
        return {
            "stage_locked": bool(self.stage_locked),
            "authorized_ips": sorted(self.authorized_ips),
        }

    def is_ip_authorized(self, ip: str) -> bool:
        return not self.stage_locked or str(ip) in self.authorized_ips

    def toggle_stage_lock(
        self,
        stage_locked: Optional[bool] = None,
        authorized_ips: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Limits stage connections to an IP allowlist when locked."""
        if stage_locked is None:
            self.stage_locked = not self.stage_locked
        else:
            self.stage_locked = bool(stage_locked)
        if authorized_ips is not None:
            extra = {str(ip).strip() for ip in authorized_ips if str(ip).strip()}
            self.authorized_ips = set(DEFAULT_AUTHORIZED_IPS) | extra
        return self.stage_lock_state()

    def register(
        self,
        websocket: WebSocket,
        client_host: str,
        device_id: Optional[str] = None,
        device_name: str = "",
        user_agent: str = "",
    ) -> ConnectedDevice:
        requested_id = (device_id or "").strip()
        if not requested_id or requested_id in self.active_connections:
            requested_id = f"dev_{uuid.uuid4().hex[:8]}"
        device = ConnectedDevice(websocket, requested_id, client_host, device_name, user_agent)
        self.active_connections[requested_id] = device
        return device

    def unregister(self, device_id: str) -> None:
        if device_id in self.active_connections:
            del self.active_connections[device_id]

    def update_identity(self, device: ConnectedDevice, requested_id: str, device_name: str, user_agent: str) -> None:
        requested_id = requested_id.strip()
        if requested_id and requested_id != device.device_id and requested_id not in self.active_connections:
            self.active_connections.pop(device.device_id, None)
            device.device_id = requested_id
            self.active_connections[requested_id] = device
        if device_name.strip():
            device.device_name = device_name.strip()[:120]
        if user_agent.strip():
            device.user_agent = user_agent.strip()[:240]

    def get_devices(self) -> List[Dict[str, Any]]:
        return [dev.to_dict() for dev in self.active_connections.values()]

    def is_action_allowed(self, role: str, action: str) -> bool:
        """Enforces role-based action permissions.
        - display: read-only, no actions
        - hub: read-only, no actions
        - moderator: match flow actions
        - admin: setup, score adjustments, reset, plus moderator actions
        - buzzer_a / buzzer_b: only buzz()
        """
        if role == "admin":
            return action in ADMIN_ACTIONS
        elif role == "hub":
            return action in HUB_ACTIONS
        elif role == "moderator":
            return action in MODERATOR_ACTIONS
        elif role in ("buzzer_a", "buzzer_b"):
            return action in BUZZER_ACTIONS
        elif role in ("display", "hub"):
            return False
        return False

    async def send_to_device(self, device_id: str, message: Dict[str, Any]) -> None:
        device = self.active_connections.get(device_id)
        if device:
            try:
                await device.websocket.send_json(message)
            except Exception:
                pass

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcasts a JSON message to all authenticated connected clients."""
        dead_devices = []
        for dev_id, dev in list(self.active_connections.items()):
            if dev.authenticated:
                try:
                    await dev.websocket.send_json(message)
                except Exception:
                    dead_devices.append(dev_id)

        for dev_id in dead_devices:
            self.unregister(dev_id)

    async def broadcast_except(self, message: Dict[str, Any], excluded_device_id: str) -> None:
        dead_devices = []
        for dev_id, dev in list(self.active_connections.items()):
            if dev.authenticated and dev_id != excluded_device_id:
                try:
                    await dev.websocket.send_json(message)
                except Exception:
                    dead_devices.append(dev_id)
        for dev_id in dead_devices:
            self.unregister(dev_id)

    async def broadcast_state(self, state: Dict[str, Any]) -> None:
        """Broadcasts full state update."""
        if isinstance(state, dict):
            state["stage_locked"] = self.stage_locked
        await self.broadcast({"type": "state", "data": state})

    async def broadcast_event(self, name: str, **kwargs: Any) -> None:
        """Broadcasts a named event notification."""
        payload = {"type": "event", "name": name}
        payload.update(kwargs)
        await self.broadcast(payload)

    async def broadcast_event_except(self, excluded_device_id: str, name: str, **kwargs: Any) -> None:
        payload = {"type": "event", "name": name}
        payload.update(kwargs)
        await self.broadcast_except(payload, excluded_device_id)

    def assign_role(self, device_id: str, role: str) -> Dict[str, Any]:
        device = self.active_connections.get(device_id)
        if not device:
            raise ValueError("Device is not connected")
        if role not in {"unassigned", "buzzer_a", "buzzer_b", "display", "moderator", "admin", "hub"}:
            raise ValueError("Invalid device role")
        if role in {"buzzer_a", "buzzer_b"} and device.role != role:
            for other in self.active_connections.values():
                if other.device_id != device_id and other.role == role:
                    other.role, device.role = device.role, other.role
                    return device.to_dict()
        device.role = role
        return device.to_dict()

    def swap_buzzers(self) -> List[Dict[str, Any]]:
        buzzer_a = next((device for device in self.active_connections.values() if device.role == "buzzer_a"), None)
        buzzer_b = next((device for device in self.active_connections.values() if device.role == "buzzer_b"), None)
        if not buzzer_a or not buzzer_b:
            raise ValueError("Both Buzzer A and Buzzer B must be connected to swap them")
        buzzer_a.role, buzzer_b.role = "buzzer_b", "buzzer_a"
        return [buzzer_a.to_dict(), buzzer_b.to_dict()]
