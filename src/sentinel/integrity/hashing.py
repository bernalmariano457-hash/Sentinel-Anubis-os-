from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Final

DEFAULT_CHUNK_SIZE: Final[int] = 1024 * 1024

_SHA256_HEX_LEN: Final[int] = 64


def hash_stream(stream: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:

    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")

    hasher = hashlib.sha256()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        hasher.update(chunk)
    return hasher.hexdigest()


def hash_file(path: Path | str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:

    with open(path, "rb") as f:
        return hash_stream(f, chunk_size)


class HashWriter:

    __slots__ = ("_stream", "_hasher")

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._hasher = hashlib.sha256()

    def write(self, data: bytes) -> int:

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"HashWriter.write() requires bytes-like, got {type(data).__name__}"
            )
        self._hasher.update(data)
        return self._stream.write(data)

    def digest(self) -> str:
        return self._hasher.hexdigest()


class HashingFile:

    __slots__ = ("path", "_file", "_writer")

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._file: BinaryIO | None = None
        self._writer: HashWriter | None = None

    def __enter__(self) -> HashingFile:
        self._file = open(self.path, "wb")
        self._writer = HashWriter(self._file)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._file is not None:
            self._file.close()

    def write(self, data: bytes) -> int:
        if self._writer is None:
            raise RuntimeError("HashingFile used outside its context manager")
        return self._writer.write(data)

    @property
    def digest(self) -> str:
        if self._writer is None:
            raise RuntimeError("HashingFile used outside its context manager")
        return self._writer.digest()


def canonical_json(obj: Any) -> bytes:

    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_canonical(obj: Any) -> str:

    return hashlib.sha256(canonical_json(obj)).hexdigest()


def verify_file_hash(
    path: Path | str,
    expected: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> bool:

    expected_norm = expected.strip().lower()
    if len(expected_norm) != _SHA256_HEX_LEN:
        raise ValueError(
            f"expected must be {_SHA256_HEX_LEN} hex chars, got {len(expected_norm)}"
        )
    actual = hash_file(path, chunk_size)
    return hmac.compare_digest(actual, expected_norm)
