from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("apex_sentinel.hash_chain")

CHUNK_SIZE = 65536
GENESIS_HASH = "0" * 64


class ChainIntegrityError(Exception):


class ChainFileError(ChainIntegrityError):


class ChainTamperedError(ChainIntegrityError):


class BlockStatus(str, Enum):
    VALID = "VALID"
    HASH_MISMATCH = "HASH_MISMATCH"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_TAMPERED = "EVIDENCE_TAMPERED"
    CHAIN_BROKEN = "CHAIN_BROKEN"


@dataclass(frozen=True)
class ChainBlock:
    index: int
    previous_hash: str
    file_path: str
    file_hash: str
    file_size_bytes: int
    timestamp: str
    block_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ChainBlock":
        try:
            return ChainBlock(
                index=int(data["index"]),
                previous_hash=str(data["previous_hash"]),
                file_path=str(data["file_path"]),
                file_hash=str(data["file_hash"]),
                file_size_bytes=int(data["file_size_bytes"]),
                timestamp=str(data["timestamp"]),
                block_hash=str(data["block_hash"]),
                metadata=dict(data.get("metadata") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ChainTamperedError(
                f"Bloque con estructura inválida o corrupta: {exc}") from exc


@dataclass
class VerificationResult:
    is_valid: bool
    total_blocks: int
    verified_blocks: int
    first_failure_index: Optional[int]
    failures: list[dict[str, Any]] = field(default_factory=list)
    verified_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HashChainLogger:

    def __init__(self, chain_file_path: str | os.PathLike[str], *, hash_algorithm: str = "sha256") -> None:
        if hash_algorithm not in hashlib.algorithms_guaranteed:
            raise ValueError(
                f"Algoritmo de hash no soportado: '{hash_algorithm}'.")
        self._hash_algorithm = hash_algorithm
        self._chain_file = Path(chain_file_path)
        self._lock = threading.RLock()
        try:
            self._chain_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ChainFileError(
                f"No fue posible crear el directorio '{self._chain_file.parent}': {exc}") from exc
        if not self._chain_file.exists():
            self._initialize_chain_file()

    @property
    def chain_file_path(self) -> Path:
        return self._chain_file

    def _initialize_chain_file(self) -> None:
        try:
            with self._chain_file.open("w", encoding="utf-8") as fh:
                json.dump([], fh)
            logger.info(
                "Archivo de cadena de auditoría inicializado en '%s'.", self._chain_file)
        except OSError as exc:
            raise ChainFileError(
                f"No fue posible inicializar el archivo de cadena '{self._chain_file}': {exc}") from exc

    @staticmethod
    def compute_file_hash(file_path: str | os.PathLike[str], *, algorithm: str = "sha256") -> str:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"El archivo de evidencia no existe: '{path}'.")
        hasher = hashlib.new(algorithm)
        try:
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
        except OSError as exc:
            raise ChainFileError(
                f"No fue posible leer el archivo '{path}' para calcular su hash: {exc}") from exc
        return hasher.hexdigest()

    def _compute_block_hash(self, previous_hash: str, file_hash: str, timestamp: str) -> str:
        payload = f"{previous_hash}{file_hash}{timestamp}".encode("utf-8")
        return hashlib.new(self._hash_algorithm, payload).hexdigest()

    def _read_chain_raw(self) -> list[dict[str, Any]]:
        try:
            with self._chain_file.open("r", encoding="utf-8") as fh:
                content = fh.read().strip()
        except OSError as exc:
            raise ChainFileError(
                f"No fue posible leer el archivo de cadena '{self._chain_file}': {exc}") from exc
        if not content:
            return []
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ChainTamperedError(
                f"El archivo de cadena '{self._chain_file}' contiene JSON inválido o corrupto: {exc}") from exc
        if not isinstance(data, list):
            raise ChainTamperedError(
                f"El archivo de cadena '{self._chain_file}' no contiene una lista de bloques en su raíz.")
        return data

    def load_chain(self) -> list[ChainBlock]:
        with self._lock:
            raw_blocks = self._read_chain_raw()
        return [ChainBlock.from_dict(item) for item in raw_blocks]

    def get_last_block(self) -> Optional[ChainBlock]:
        chain = self.load_chain()
        return chain[-1] if chain else None

    def seal_evidence(self, file_path: str | os.PathLike[str], *, metadata: Optional[dict[str, Any]] = None) -> ChainBlock:

        path = Path(file_path)
        with self._lock:
            file_hash = self.compute_file_hash(
                path, algorithm=self._hash_algorithm)
            file_size = path.stat().st_size
            last_block = self.get_last_block()
            previous_hash = last_block.block_hash if last_block is not None else GENESIS_HASH
            next_index = (last_block.index +
                          1) if last_block is not None else 0
            timestamp = datetime.now(timezone.utc).isoformat()
            block_hash = self._compute_block_hash(
                previous_hash, file_hash, timestamp)

            new_block = ChainBlock(
                index=next_index,
                previous_hash=previous_hash,
                file_path=str(path),
                file_hash=file_hash,
                file_size_bytes=file_size,
                timestamp=timestamp,
                block_hash=block_hash,
                metadata=metadata or {},
            )
            self._append_block(new_block)
            logger.info("Evidencia sellada: bloque #%d -> '%s' (hash=%s...).",
                        new_block.index, path.name, block_hash[:12])
            return new_block

    def _append_block(self, block: ChainBlock) -> None:
        raw_blocks = self._read_chain_raw()
        raw_blocks.append(block.to_dict())
        tmp_path = self._chain_file.with_suffix(
            self._chain_file.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(raw_blocks, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._chain_file)
        except OSError as exc:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    logger.warning(
                        "No fue posible limpiar el archivo temporal '%s' tras un error de escritura.", tmp_path)
            raise ChainFileError(
                f"No fue posible persistir el nuevo bloque en '{self._chain_file}': {exc}") from exc

    def verify_chain(self, *, check_evidence_files: bool = True) -> VerificationResult:

        failures: list[dict[str, Any]] = []
        first_failure_index: Optional[int] = None

        try:
            chain = self.load_chain()
        except ChainIntegrityError as exc:
            return VerificationResult(
                is_valid=False,
                total_blocks=0,
                verified_blocks=0,
                first_failure_index=0,
                failures=[{"index": None, "file_path": None,
                           "status": BlockStatus.CHAIN_BROKEN.value, "reasons": [str(exc)]}],
            )

        expected_previous = GENESIS_HASH
        verified_count = 0

        for expected_index, block in enumerate(chain):
            reasons: list[str] = []
            status = BlockStatus.VALID

            if block.index != expected_index:
                reasons.append(
                    f"Índice fuera de secuencia: esperado {expected_index}, encontrado {block.index}.")
                status = BlockStatus.CHAIN_BROKEN

            if block.previous_hash != expected_previous:
                reasons.append(
                    "El hash del bloque anterior no coincide (bloque insertado, eliminado o reordenado).")
                status = BlockStatus.CHAIN_BROKEN

            recomputed_block_hash = self._compute_block_hash(
                block.previous_hash, block.file_hash, block.timestamp)
            if recomputed_block_hash != block.block_hash:
                reasons.append(
                    "El hash del bloque no es reproducible a partir de sus propios campos (bloque alterado).")
                if status == BlockStatus.VALID:
                    status = BlockStatus.HASH_MISMATCH

            if check_evidence_files:
                evidence_path = Path(block.file_path)
                if not evidence_path.is_file():
                    reasons.append(
                        f"Archivo de evidencia ausente: '{evidence_path}'.")
                    if status == BlockStatus.VALID:
                        status = BlockStatus.EVIDENCE_MISSING
                else:
                    try:
                        current_hash = self.compute_file_hash(
                            evidence_path, algorithm=self._hash_algorithm)
                        if current_hash != block.file_hash:
                            reasons.append(
                                "El hash SHA-256 actual del archivo de evidencia no coincide con el registrado (archivo alterado).")
                            if status == BlockStatus.VALID:
                                status = BlockStatus.EVIDENCE_TAMPERED
                    except ChainFileError as exc:
                        reasons.append(
                            f"No fue posible leer el archivo de evidencia: {exc}")
                        if status == BlockStatus.VALID:
                            status = BlockStatus.EVIDENCE_MISSING

            if reasons:
                if first_failure_index is None:
                    first_failure_index = block.index
                failures.append({
                    "index": block.index,
                    "file_path": block.file_path,
                    "status": status.value,
                    "reasons": reasons,
                })
            else:
                verified_count += 1

            expected_previous = block.block_hash

        result = VerificationResult(
            is_valid=(len(failures) == 0),
            total_blocks=len(chain),
            verified_blocks=verified_count,
            first_failure_index=first_failure_index,
            failures=failures,
        )
        logger.info("Auditoría de cadena completada: %d/%d bloques válidos. Íntegra=%s.",
                    verified_count, len(chain), result.is_valid)
        return result
