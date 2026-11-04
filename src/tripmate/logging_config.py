"""Central logging configuration."""

import logging
import sys

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format=LOG_FORMAT,
        stream=sys.stdout,
        force=True,
    )
    # Quiet down noisy third-party loggers.
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
