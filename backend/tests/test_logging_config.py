import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.logging_config import NOISY_HTTP_LOGGERS, silence_noisy_http_loggers


def test_silence_noisy_http_loggers_sets_warning_level():
    for logger_name in NOISY_HTTP_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.INFO)

    silence_noisy_http_loggers()

    for logger_name in NOISY_HTTP_LOGGERS:
        assert logging.getLogger(logger_name).level == logging.WARNING
