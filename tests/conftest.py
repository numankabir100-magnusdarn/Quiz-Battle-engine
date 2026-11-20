import os
import sys
import tempfile
import shutil
from pathlib import Path
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.engine.game_engine import GameEngine
from server.engine.questions import SampleQuestionProvider
from server.persistence import PersistenceManager
from server.config import Config


@pytest.fixture
def temp_data_dir():
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def clean_engine():
    """Provides a fresh game engine with 12 teams initialized."""
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
