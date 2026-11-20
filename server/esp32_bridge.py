import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from server.config import Config

PREFIX = "EEECI:"
HELLO_COMMANDS = {"HELLO", "PING"}
BUZZ_COMMANDS = {"TEAM_A", "TEAM_B"}
VALID_COMMANDS = BUZZ_COMMANDS | {"TIE", "ACK", "RESET", "TEST", "PONG"} | HELLO_COMMANDS


class ESP32Bridge:
    """Offline UDP listener for the ESP32 breadboard buzzer.

    Accepts plain (TEAM_A) and prefixed (EEECI:TEAM_A) packets. The source IP is
    locked on HELLO/PING; a later HELLO re-locks onto a new source. A 150ms
    anti-bounce guard suppresses mechanical contact chatter on buzz packets.
    """

    def __init__(
        self,
        config: Config,
        on_buzz: Callable[[str], Awaitable[bool]],
        on_event: Callable[[str, Dict[str, Any]], Awaitable[None]],
    ):
        esp_config = config.esp32_config
        self.enabled: bool = bool(esp_config.get("enabled", True))
        self.host: str = str(esp_config.get("host", "0.0.0.0"))
        self.port: int = int(esp_config.get("port", 4210))
        self.out_port: int = int(esp_config.get("out_port", 4211))
        self.anti_bounce_ms: int = max(0, int(esp_config.get("anti_bounce_ms", 150)))
        self._on_buzz = on_buzz
        self._on_event = on_event
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._tasks: set[asyncio.Task] = set()
        self.locked_ip: Optional[str] = None
        self.locked_addr: Optional[Tuple[str, int]] = None
        self.last_seen_at: Optional[float] = None
        self.last_command: Optional[str] = None
        self.last_buzz_at: float = 0.0
        self.packets_received: int = 0
        self.rejected_packets: int = 0
        self.start_error: Optional[str] = None

    @staticmethod
    def parse_packet(raw: str) -> Optional[Tuple[str, str]]:
        """Returns (command, payload) for plain or EEECI:-prefixed packets."""
        text = raw.replace("\x00", " ").strip().upper()
        if not text:
            return None
        if text.startswith(PREFIX):
            text = text[len(PREFIX):].strip()
        elif ":" in text and text.split(":", 1)[0] in VALID_COMMANDS:
            text = text.split(":", 1)[1].strip()
        parts = text.replace(":", " ").split()
        if not parts:
            return None
        command = parts[0]
        if command not in VALID_COMMANDS:
            return None
        return command, " ".join(parts[1:])

    def _iso(self, value: Optional[float]) -> Optional[str]:
        if value is None:
            return None
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    @property
    def online(self) -> bool:
        if not self.locked_ip or self.last_seen_at is None:
            return False
        return (time.time() - self.last_seen_at) <= 15.0

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "listening": self._transport is not None,
            "online": self.online,
            "locked_ip": self.locked_ip,
            "last_seen_at": self._iso(self.last_seen_at),
            "last_command": self.last_command,
            "port": self.port,
            "out_port": self.out_port,
            "prefix": PREFIX,
            "anti_bounce_ms": self.anti_bounce_ms,
            "packets_received": self.packets_received,
            "rejected_packets": self.rejected_packets,
            "start_error": self.start_error,
        }

    async def _reject(self, ip: str, reason: str, code: int = 403) -> None:
        self.rejected_packets += 1
        await self._on_event("esp32_rejected", {
            "ip": ip,
            "reason": reason,
            "code": code,
            "locked_ip": self.locked_ip,
        })

    async def handle_packet(self, data: bytes, ip: str, remote_port: Optional[int] = None) -> None:
        self.packets_received += 1
        parsed = self.parse_packet(data.decode("utf-8", errors="ignore"))
        if not parsed:
            await self._reject(ip, "unknown or malformed packet", 400)
            return
        command, extra = parsed
        self.last_command = command
        now = time.time()

        if command in HELLO_COMMANDS:
            if command == "PING" and self.locked_ip and ip != self.locked_ip:
                await self._reject(ip, "source IP is locked; send HELLO to re-lock")
                return
            previous = self.locked_ip
            self.locked_ip = ip
            self.locked_addr = (ip, self.out_port)
            self.last_seen_at = now
            await self._on_event("esp32_hello" if command == "HELLO" else "esp32_ping", {
                "ip": ip,
                "previous_ip": previous,
                "re_locked": previous is not None and previous != ip,
            })
            self._send("PONG", (ip, self.out_port))
            return

        if not self.locked_ip:
            await self._reject(ip, "waiting for ESP32 HELLO/PING handshake")
            return
        if ip != self.locked_ip:
            await self._reject(ip, "source IP is locked to another device")
            return

        self.last_seen_at = now
        if command == "ACK":
            return
        if command == "RESET":
            await self._on_event("esp32_reset_requested", {"ip": ip, "reason": extra})
            return
        if command == "TIE":
            await self._on_event("esp32_tie", {"ip": ip})
            return

        if now - self.last_buzz_at < (self.anti_bounce_ms / 1000.0):
            await self._reject(ip, "anti-bounce guard", 429)
            return
        self.last_buzz_at = now
        accepted = await self._on_buzz(command)
        await self._on_event("esp32_buzz", {
            "ip": ip,
            "side": command,
            "accepted": accepted,
            "extra": extra,
        })

    def _send(self, payload: str, address: Optional[Tuple[str, int]] = None) -> bool:
        if not self._transport:
            return False
        addr = address or self.locked_addr or ((self.locked_ip, self.out_port) if self.locked_ip else None)
        if not addr:
            return False
        try:
            self._transport.sendto(payload.encode("utf-8"), addr)
            return True
        except (OSError, RuntimeError):
            return False

    async def start(self) -> bool:
        if not self.enabled or self._transport is not None:
            return self._transport is not None
        try:
            loop = asyncio.get_running_loop()
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _ESP32Protocol(self),
                local_addr=(self.host, self.port),
            )
            self.start_error = None
            await self._on_event("esp32_status", self.status())
            return True
        except (OSError, RuntimeError, Exception) as exc:
            self.start_error = str(exc)
            await self._on_event("esp32_status", self.status())
            return False

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        for task in list(self._tasks):
            if not task.done():
                task.cancel()

    def send_pong(self, ip: Optional[str] = None) -> bool:
        target_ip = ip or self.locked_ip
        if not target_ip:
            return False
        return self._send("PONG", (target_ip, self.out_port))

    def send_reset(self) -> Dict[str, Any]:
        sent = False
        if self.locked_ip:
            sent = self._send("RESET", (self.locked_ip, self.out_port))
        return {"sent": sent, "locked_ip": self.locked_ip, "target_port": self.out_port}

    def send_test(self) -> Dict[str, Any]:
        sent = False
        if self.locked_ip:
            sent = self._send("TEST", (self.locked_ip, self.out_port))
        return {"sent": sent, "locked_ip": self.locked_ip, "target_port": self.out_port}

    def test_pulse(self) -> Dict[str, Any]:
        return self.send_test()

    def send_pass(self, side: str) -> bool:
        """Sends PASS_A or PASS_B when buzzers.passed_to_team triggers."""
        cmd = "PASS_A" if str(side).upper() in ("A", "TEAM_A") else "PASS_B"
        return self._send(f"{cmd}", (self.locked_ip, self.out_port) if self.locked_ip else None)

    def reset(self) -> Dict[str, Any]:
        sent = False
        if self.locked_ip:
            sent = self._send("RESET", (self.locked_ip, self.out_port))
        self.locked_ip = None
        self.locked_addr = None
        self.last_seen_at = None
        self.last_command = None
        self.last_buzz_at = 0.0
        return {"sent": sent, "lock_cleared": True, "status": self.status()}


class _ESP32Protocol(asyncio.DatagramProtocol):
    def __init__(self, bridge: ESP32Bridge):
        self.bridge = bridge

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.bridge._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        task = asyncio.create_task(self.bridge.handle_packet(data, addr[0], addr[1] if len(addr) > 1 else None))
        self.bridge._tasks.add(task)
        task.add_done_callback(self.bridge._tasks.discard)

    def error_received(self, exc: Exception) -> None:
        self.bridge.rejected_packets += 1

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self.bridge._transport = None
