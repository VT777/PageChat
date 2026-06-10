"""Shared logging configuration helpers."""

from __future__ import annotations

import logging


NOISY_HTTP_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "openai._base_client",
)


def silence_noisy_http_loggers(level: int = logging.WARNING) -> None:
    for logger_name in NOISY_HTTP_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)
