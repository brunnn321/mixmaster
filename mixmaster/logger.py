"""Logging centralizado: todo va a logs/app.log, nunca rompe la app."""

import logging
from logging.handlers import RotatingFileHandler

from .app_paths import LOG_FILE, ensure_app_dirs


def get_logger(name: str = "mixmaster") -> logging.Logger:
    """Devuelve un logger con handler a app.log (rotativo, 1 MB x 3)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    ensure_app_dirs()
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    # Consola solo para errores (útil al desarrollar)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.WARNING)
    logger.addHandler(ch)

    return logger
