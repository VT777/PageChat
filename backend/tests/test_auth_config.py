from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import auth
from app.core import config


def test_jwt_secret_is_configured_and_stable() -> None:
    assert isinstance(config.JWT_SECRET, str)
    assert len(config.JWT_SECRET) >= 32
    assert auth.JWT_SECRET == config.JWT_SECRET
