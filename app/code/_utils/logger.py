import logging
import os


class NvFlareLogger:
    """Per-site logger that writes to a named file and prefixes stdout output with the site name.

    Two sites running in the same process get independent loggers with independent
    handlers, so heartbeat and GIFT output lines in Docker logs are always tagged
    with which site produced them.
    """

    def __init__(self, log_name: str, output_path: str, log_level: str = "info"):
        level = getattr(logging, log_level.upper(), logging.INFO)
        # Use id(self) in the logger name so two instances never share handlers.
        self._logger = logging.getLogger(f"nfc.{log_name}.{id(self)}")
        self._logger.setLevel(level)
        self._logger.propagate = False

        os.makedirs(output_path, exist_ok=True)
        fmt = logging.Formatter(f"%(asctime)s [{log_name}] %(levelname)s - %(message)s")

        file_handler = logging.FileHandler(os.path.join(output_path, log_name))
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        self._logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(fmt)
        self._logger.addHandler(stream_handler)

        self._file_handler = file_handler

    def _msg(self, *args) -> str:
        return " ".join(str(a) for a in args)

    def info(self, *args) -> None:
        self._logger.info(self._msg(*args))

    def warning(self, *args) -> None:
        self._logger.warning(self._msg(*args))

    def error(self, *args) -> None:
        self._logger.error(self._msg(*args))

    def debug(self, *args) -> None:
        self._logger.debug(self._msg(*args))

    def close(self) -> None:
        self._file_handler.close()
        self._logger.removeHandler(self._file_handler)
