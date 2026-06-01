import sys

from loguru import logger

from netbuddy.core.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        backtrace=settings.debug,
        diagnose=settings.debug,
    )
