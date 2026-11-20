import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8000,
    "data_dir": "data",
    "esp32": {"enabled": True, "port": 4210, "out_port": 4211, "anti_bounce_ms": 150},
    "stage": {"authorized_ips": ["127.0.0.1", "192.168.137.1"]},
    "auth": {
        "display": {"pin": ""},
        "moderator": {"pin": "1111"},
        "admin": {"pin": "2222"},
        "hub": {"pin": "3333"},
        "buzzer_a": {"pairing_code": "BUZZ_A"},
        "buzzer_b": {"pairing_code": "BUZZ_B"}
    }
}


class Config:
    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        self._config = config_dict or DEFAULT_CONFIG

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Config":
        if config_path is None:
            # Check default locations
            candidates = [
                Path("config.json"),
                Path(__file__).parent.parent / "config.json"
            ]
            for candidate in candidates:
                if candidate.exists():
                    config_path = candidate
                    break

        cfg = json.loads(json.dumps(DEFAULT_CONFIG)) # deep copy

        if config_path and config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        cls._deep_update(cfg, loaded)
            except Exception as e:
                print(f"[Config] Error loading {config_path}: {e}")

        # Environment variable overrides
        if "HOST" in os.environ:
            cfg["host"] = os.environ["HOST"]
        if "PORT" in os.environ:
            try:
                cfg["port"] = int(os.environ["PORT"])
            except ValueError:
                pass
        if "DATA_DIR" in os.environ:
            cfg["data_dir"] = os.environ["DATA_DIR"]

        return cls(cfg)

    @staticmethod
    def _deep_update(base: dict, update: dict) -> None:
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                Config._deep_update(base[k], v)
            else:
                base[k] = v

    @property
    def host(self) -> str:
        return self._config.get("host", "0.0.0.0")

    @property
    def port(self) -> int:
        return int(self._config.get("port", 8001))

    @property
    def data_dir(self) -> Path:
        d = Path(self._config.get("data_dir", "data"))
        if not d.is_absolute():
            d = Path(__file__).resolve().parent.parent / d
        return d

    @property
    def esp32_config(self) -> Dict[str, Any]:
        return dict(self._config.get("esp32", DEFAULT_CONFIG["esp32"]))

    @property
    def stage_config(self) -> Dict[str, Any]:
        return dict(self._config.get("stage", DEFAULT_CONFIG["stage"]))

    def validate_auth(self, role: str, pin_or_code: str) -> bool:
        auth_cfg = self._config.get("auth", {})
        if role not in auth_cfg:
            return False

        role_cfg = auth_cfg[role]
        expected_pin = role_cfg.get("pin")
        expected_code = role_cfg.get("pairing_code")

        if role == "display":
            # Display is allowed if pin is empty or pin matches
            return not expected_pin or (pin_or_code == expected_pin)

        if expected_pin is not None:
            return pin_or_code == expected_pin
        if expected_code is not None:
            return pin_or_code == expected_code

        return False
