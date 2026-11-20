import os
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional


class PersistenceManager:
    """Handles atomic state persistence to state.json and appending to audit.log.
    Safe against mid-write crashes using write-to-temp-then-atomic-rename.
    """

    def __init__(self, data_dir: Path, logs_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir)
        self.logs_dir = Path(logs_dir) if logs_dir is not None else self.data_dir / "logs"
        self.state_file = self.data_dir / "state.json"
        self.audit_file = self.data_dir / "audit.log"
        self.ensure_data_dir()

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def save_match_snapshot(self, match_number: int, payload: Dict[str, Any]) -> Path:
        """Atomically writes logs/match_<number>_snapshot.json for a concluded match."""
        self.ensure_data_dir()
        target = self.logs_dir / f"match_{int(match_number)}_snapshot.json"
        temp_file = self.logs_dir / (
            f"match_{int(match_number)}_snapshot.json.{os.getpid()}.{datetime.now().timestamp()}.tmp"
        )
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, target)
        except Exception as exc:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise IOError(f"Failed to save match snapshot {target}: {exc}") from exc
        return target

    def save_state(self, state: Dict[str, Any]) -> None:
        """Atomically saves game state to state.json.
        Writes to a temporary file in the same directory, flushes, syncs to disk,
        and atomically renames to state.json.
        """
        self.ensure_data_dir()
        temp_file = self.data_dir / f"state.json.{os.getpid()}.{datetime.now().timestamp()}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace on Windows / POSIX
            os.replace(temp_file, self.state_file)
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise IOError(f"Failed to atomically save state to {self.state_file}: {e}") from e

    def load_state(self) -> Optional[Dict[str, Any]]:
        """Loads state from state.json if present; returns None otherwise."""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else None
        except Exception as e:
            print(f"[Persistence] Error loading state from {self.state_file}: {e}")
            return None

    def log_audit(
        self,
        role: str,
        device: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        reason: str = "",
    ) -> None:
        """Appends action/score changes to audit.log.
        Format: [ISO_TIME] role=<role> device=<device> action=<action> reason="<reason>" details=<json>
        """
        self.ensure_data_dir()
        now_str = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details or {}, separators=(",", ":"))
        safe_reason = reason.replace('"', '\\"')
        log_line = (
            f"[{now_str}] role={role} device={device} action={action} "
            f'reason="{safe_reason}" details={details_json}\n'
        )

        try:
            with open(self.audit_file, "a", encoding="utf-8") as f:
                f.write(log_line)
                f.flush()
        except Exception as e:
            print(f"[Persistence] Error writing audit log to {self.audit_file}: {e}")

    def read_audit_log(self, limit: int = 1000) -> list[str]:
        if not self.audit_file.exists():
            return []
        with open(self.audit_file, "r", encoding="utf-8") as file:
            lines = file.read().splitlines()
        return lines[-max(1, min(int(limit), 5000)):]
