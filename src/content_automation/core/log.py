"""Application logging that masks every secret value found in Settings."""

import logging
import sys
from collections.abc import Iterable

from pydantic import SecretStr

from content_automation.core.config import Settings

ROOT_LOGGER = "content_automation"
MASK = "***"


def secret_values(settings: Settings) -> list[str]:
    """Return the non-empty secret values held by Settings, longest first."""
    values = {
        value.get_secret_value().strip()
        for name in type(settings).model_fields
        if isinstance(value := getattr(settings, name), SecretStr)
    }
    return sorted((value for value in values if value), key=len, reverse=True)


def mask_secrets(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, MASK)
    return text


class SecretMaskingFormatter(logging.Formatter):
    """Formats records (including tracebacks) and then removes secret values."""

    def __init__(self, secrets: Iterable[str], fmt: str | None = None) -> None:
        super().__init__(fmt)
        self._secrets = list(secrets)

    def format(self, record: logging.LogRecord) -> str:
        return mask_secrets(super().format(record), self._secrets)


def configure_logging(settings: Settings, level: int = logging.INFO) -> logging.Logger:
    """Attach one masking stderr handler to the application logger."""
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in [h for h in logger.handlers if getattr(h, "_ca_handler", False)]:
        logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        SecretMaskingFormatter(secret_values(settings), "%(levelname)s %(name)s: %(message)s")
    )
    handler._ca_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")
