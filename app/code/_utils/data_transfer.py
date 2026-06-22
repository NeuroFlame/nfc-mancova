import logging
import os

import numpy as np


def file_to_bytes(file_path: str) -> bytes:
    """Reads any file as bytes."""
    try:
        with open(file_path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        return b""


def bytes_to_file(file_path: str, file_data: bytes):
    """Writes bytes to a file."""
    with open(file_path, "wb") as f:
        f.write(file_data)


def save_binary(path, arr):
    with open(path, "wb+") as fh:
        header = "%s" % str(arr.dtype)
        for index in arr.shape:
            header += " %d" % index
        header += "\n"
        fh.write(header.encode())
        fh.write(arr.data.tobytes())
        os.fsync(fh)


def load_binary(path):
    with open(path, "rb") as fh:
        header = fh.readline().decode().split()
        dtype = header.pop(0)
        arrayDimensions = tuple(int(d) for d in header)
        return np.frombuffer(fh.read(), dtype=dtype).reshape(arrayDimensions)
