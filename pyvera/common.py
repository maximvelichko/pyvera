"""Common code."""
import logging

_VERA_CONTROLLER = None


def init_logging(logger, logger_level: str) -> None:
    """Initialize the logger."""
    # Set logging level (such as INFO, DEBUG, etc) via an environment variable
    # Defaults to WARNING log level unless PYVERA_LOGLEVEL variable exists
    if logger_level:
        logger.setLevel(logger_level)
        log_handler = logging.StreamHandler()
        log_handler.setFormatter(
            logging.Formatter("%(levelname)s@{%(name)s:%(lineno)d} - %(message)s")
        )
        logger.addHandler(log_handler)
