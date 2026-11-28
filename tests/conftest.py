import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="quizbattle-tests-"))
os.environ["DATA_DIR"] = str(_TEST_RUNTIME_DIR)
os.environ["LOGS_DIR"] = str(_TEST_RUNTIME_DIR / "logs")
atexit.register(shutil.rmtree, _TEST_RUNTIME_DIR, True)

from server.config import Config
from server.engine.game_engine import GameEngine
from server.engine.questions import SampleQuestionProvider
from server.persistence import PersistenceManager


@pytest.fixture(autouse=True)
def isolated_server_runtime():
    from server import main as server_main

    def reset():
        server_main.timer.pause()
        server_main.timer.reset(0)
        server_main.engine.init_default_tournament()
        server_main.engine._undo_stack = []
        server_main.engine._buzzer_arrivals = {}

    reset()
    yield
    reset()


@pytest.fixture
def temp_data_dir():
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def clean_engine():
    """Provides a fresh game engine with 14 teams initialized."""
    engine = GameEngine(question_provider=SampleQuestionProvider(), auto_init_tournament=True)
    return engine


@pytest.fixture
def test_persistence(temp_data_dir):
    return PersistenceManager(data_dir=temp_data_dir)


@pytest.fixture
def test_config(temp_data_dir):
    cfg_dict = {
        "host": "127.0.0.1",
        "port": 8000,
        "data_dir": str(temp_data_dir),
        "auth": {
            "display": {"pin": ""},
            "moderator": {"pin": "1111"},
            "admin": {"pin": "2222"},
            "hub": {"pin": "3333"},
            "buzzer_a": {"pairing_code": "BUZZ_A"},
            "buzzer_b": {"pairing_code": "BUZZ_B"},
        },
    }
    return Config(cfg_dict)
