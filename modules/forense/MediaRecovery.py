from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import math
import mmap
import os
import re
import stat
import struct
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, BinaryIO, Callable, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

_BLKGETSIZE64: int = 0x80081272

LengthStrategy = Literal["footer", "capped", "riff_declared_size", "iso_bmff_boxwalk"]

HashAlgorithmFactory = Callable[[], Any]
ProgressCallback = Callable[[int, Optional[int]], Awaitable[None]]


class WorkspaceManagerInterface(ABC):

    @abstractmethod
    def get_active_project_path(self) -> Optional[Path]:
        raise NotImplementedError


class OrchestratorModuleInterface(ABC):
    needs_sentinel: bool = False

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@dataclass(frozen=True)
class SignatureDefinition:
    name: str
    extension: str
    header: bytes
    footer: Optional[bytes] = None
    max_size_bytes: int = 100 * 1024 * 1024
    start_offset_adjustment: int = 0
    secondary_marker_offset: Optional[int] = None
    secondary_marker_bytes: Optional[bytes] = None
    length_strategy: LengthStrategy = "footer"
    compiled_header: "re.Pattern[bytes]" = field(init=False, repr=False)
    compiled_footer: Optional["re.Pattern[bytes]"] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "compiled_header", re.compile(re.escape(self.header)))
        if self.footer is not None:
            object.__setattr__(self, "compiled_footer", re.compile(re.escape(self.footer)))


@dataclass(frozen=True)
class CarvedFileResult:
    signature_name: str
    output_path: Path
    size_bytes: int
    source_offset: int
    sha256: str
    truncated: bool


@dataclass
class _OpenCarveJob:
    signature: SignatureDefinition
    start_offset: int
    output_path: Path
    handle: BinaryIO
    hasher: Any
    bytes_written: int = 0
    search_offset: int = 0
    resolved_length: Optional[int] = None
    box_probe_offset: Optional[int] = None
    dynamic_resolution_failed: bool = False


class MediaRecoveryEngine(OrchestratorModuleInterface):

    needs_sentinel: bool = True

    CHUNK_SIZE: int = 4 * 1024 * 1024
    OVERLAP_SIZE: int = 64 * 1024
    FALLBACK_OUTPUT_PATH: Path = Path("data/evidence/recovered_media")

    _FTYP_MIN_BOX_SIZE: int = 16
    _FTYP_MAX_BOX_SIZE: int = 4096

    _FOURCC_PATTERN: "re.Pattern[bytes]" = re.compile(rb"[\x20-\x7e]{4}")

    ENTROPY_PROBE_SIZE: int = 128
    ENTROPY_MIN_PROBE_SIZE: int = 128
    STATIC_NOISE_ENTROPY_THRESHOLD: float = 6.0

    _DEFAULT_CONFIG_FILENAME: str = "config.json"

    def __init__(
        self,
        workspace_manager: Optional[WorkspaceManagerInterface] = None,
        hash_algorithm: HashAlgorithmFactory = hashlib.sha256,
        config_path: Optional[Path] = None,
    ) -> None:
        self._workspace_manager = workspace_manager
        self._hash_algorithm_factory = hash_algorithm
        self._default_config_path = config_path or (Path(__file__).resolve().parent / self._DEFAULT_CONFIG_FILENAME)

    async def execute(
        self,
        source: Path,
        hash_algorithm: Optional[HashAlgorithmFactory] = None,
        on_progress: Optional[ProgressCallback] = None,
        config_path: Optional[Path] = None,
    ) -> list[CarvedFileResult]:
        return await self.scan(source, hash_algorithm=hash_algorithm, on_progress=on_progress, config_path=config_path)

    async def scan(
        self,
        source: Path,
        hash_algorithm: Optional[HashAlgorithmFactory] = None,
        on_progress: Optional[ProgressCallback] = None,
        config_path: Optional[Path] = None,
    ) -> list[CarvedFileResult]:
        signatures = await asyncio.to_thread(self._load_signatures, config_path)
        if not signatures:
            logger.error("No hay firmas disponibles para el analisis, se aborta el escaneo de %s", source)
            return []

        hash_factory = hash_algorithm or self._hash_algorithm_factory

        output_dir = self._resolve_output_directory()
        try:
            await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
        except (PermissionError, OSError, FileNotFoundError) as error:
            logger.error("No fue posible preparar el directorio de salida %s: %s", output_dir, error)
            return []

        results: list[CarvedFileResult] = []
        estimated_size = await asyncio.to_thread(self._resolve_source_size, source)
        logger.info(
            "Iniciando file carving sobre %s, tamano estimado: %s",
            source,
            estimated_size if estimated_size is not None else "desconocido",
        )

        if not estimated_size:
            logger.error("No fue posible determinar el tamano de %s para el mapeo en memoria", source)
            return results

        try:
            fd, mm = await asyncio.to_thread(self._open_mapped_source, source, estimated_size)
        except (PermissionError, FileNotFoundError, OSError, ValueError) as error:
            logger.error("No fue posible mapear la fuente %s en memoria: %s", source, error)
            return results

        mv = memoryview(mm)
        total_size = len(mv)

        active_jobs: list[_OpenCarveJob] = []
        opened_offsets: set[int] = set()
        last_scanned_offset = 0
        job_counter = 0
        interrupted = False
        position = 0

        try:
            while position < total_size:
                window_start = max(0, position - self.OVERLAP_SIZE)
                window_end = min(total_size, position + self.CHUNK_SIZE)

                def _process_window() -> int:
                    self._advance_active_jobs(active_jobs, mv, window_end, results)
                    search_start = max(window_start, last_scanned_offset)
                    updated_counter = self._detect_and_open_jobs(
                        mv,
                        search_start,
                        window_end,
                        output_dir,
                        opened_offsets,
                        job_counter,
                        active_jobs,
                        results,
                        signatures,
                        hash_factory,
                    )
                    self._advance_active_jobs(active_jobs, mv, window_end, results)
                    return updated_counter

                job_counter = await asyncio.to_thread(_process_window)

                if window_end - self.OVERLAP_SIZE > last_scanned_offset:
                    last_scanned_offset = window_end - self.OVERLAP_SIZE

                position = window_end

                if on_progress is not None:
                    await on_progress(position, total_size)

                await asyncio.sleep(0)
        except asyncio.CancelledError:
            interrupted = True
            logger.warning("Carving cancelado durante el analisis de %s", source)
            raise
        except (PermissionError, OSError, FileNotFoundError) as error:
            interrupted = True
            logger.error("Fallo de E/S durante el analisis de %s: %s", source, error)
        finally:
            for job in active_jobs:
                if interrupted:
                    self._abort_job(job)
                else:
                    self._discard_incomplete_job(job, results)
            try:
                mv.release()
            except BufferError as error:
                logger.warning("No fue posible liberar la vista de memoria de %s: %s", source, error)
            await asyncio.to_thread(self._close_mapped_source, fd, mm)

        logger.info("Carving finalizado sobre %s, archivos recuperados: %d", source, len(results))
        return results

    def _load_signatures(self, config_path: Optional[Path]) -> dict[str, SignatureDefinition]:
        resolved_path = config_path or self._default_config_path
        try:
            raw_text = resolved_path.read_text(encoding="utf-8")
        except (PermissionError, FileNotFoundError, OSError) as error:
            logger.error("No fue posible leer el archivo de firmas %s: %s", resolved_path, error)
            return {}

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as error:
            logger.error("El archivo de firmas %s contiene JSON invalido: %s", resolved_path, error)
            return {}

        raw_signatures = payload.get("signatures", {})
        if not isinstance(raw_signatures, dict):
            logger.error("El archivo de firmas %s no contiene un objeto 'signatures' valido", resolved_path)
            return {}

        signatures: dict[str, SignatureDefinition] = {}
        for key, entry in raw_signatures.items():
            try:
                signatures[key] = SignatureDefinition(
                    name=entry["name"],
                    extension=entry["extension"],
                    header=bytes.fromhex(entry["header"]),
                    footer=bytes.fromhex(entry["footer"]) if entry.get("footer") else None,
                    max_size_bytes=int(entry.get("max_size_bytes", 100 * 1024 * 1024)),
                    start_offset_adjustment=int(entry.get("start_offset_adjustment", 0)),
                    secondary_marker_offset=(
                        int(entry["secondary_marker_offset"])
                        if entry.get("secondary_marker_offset") is not None
                        else None
                    ),
                    secondary_marker_bytes=(
                        bytes.fromhex(entry["secondary_marker_bytes"])
                        if entry.get("secondary_marker_bytes")
                        else None
                    ),
                    length_strategy=entry.get("length_strategy", "footer"),
                )
            except (KeyError, ValueError, TypeError) as error:
                logger.error("Definicion de firma invalida para '%s' en %s: %s", key, resolved_path, error)
        return signatures

    def _resolve_output_directory(self) -> Path:
        if self._workspace_manager is not None:
            try:
                active_project_path = self._workspace_manager.get_active_project_path()
            except Exception as error:
                logger.warning("El gestor de workspaces fallo al resolver el proyecto activo: %s", error)
                active_project_path = None
            if active_project_path is not None:
                return Path(active_project_path) / "evidence" / "recovered_media"
        return self.FALLBACK_OUTPUT_PATH

    def _resolve_source_size(self, source: Path) -> Optional[int]:
        try:
            file_descriptor = os.open(source, os.O_RDONLY)
        except (PermissionError, FileNotFoundError, OSError) as error:
            logger.warning("No fue posible determinar el tamano de %s: %s", source, error)
            return None
        try:
            mode = os.fstat(file_descriptor).st_mode
            if stat.S_ISBLK(mode):
                try:
                    raw = fcntl.ioctl(file_descriptor, _BLKGETSIZE64, struct.pack("L", 0))
                    return struct.unpack("L", raw)[0]
                except OSError as error:
                    logger.warning("ioctl BLKGETSIZE64 fallo sobre %s: %s", source, error)
                    return None
            return os.fstat(file_descriptor).st_size
        finally:
            os.close(file_descriptor)

    def _open_mapped_source(self, source: Path, size: int) -> Tuple[int, mmap.mmap]:
        fd = os.open(source, os.O_RDONLY)
        try:
            mm = mmap.mmap(fd, size, prot=mmap.PROT_READ)
        except Exception:
            os.close(fd)
            raise
        try:
            mm.madvise(mmap.MADV_SEQUENTIAL)
        except (AttributeError, OSError):
            pass
        return fd, mm

    def _close_mapped_source(self, fd: int, mm: Optional[mmap.mmap]) -> None:
        if mm is not None:
            try:
                mm.close()
            except (BufferError, OSError) as error:
                logger.warning("No fue posible cerrar el mapeo en memoria: %s", error)
        try:
            os.close(fd)
        except OSError as error:
            logger.warning("No fue posible cerrar el descriptor de la fuente: %s", error)

    @staticmethod
    def _shannon_entropy(data: Any) -> float:
        length = len(data)
        if length == 0:
            return 0.0
        counts = [0] * 256
        for byte in data:
            counts[byte] += 1
        inverse_length = 1.0 / length
        entropy = 0.0
        for count in counts:
            if count:
                probability = count * inverse_length
                entropy -= probability * math.log2(probability)
        return entropy

    def _looks_like_static_noise(self, mv: memoryview, match_index: int, up_to_offset: int) -> bool:
        probe_end = min(up_to_offset, match_index + self.ENTROPY_PROBE_SIZE)
        probe = mv[match_index:probe_end]
        if len(probe) < self.ENTROPY_MIN_PROBE_SIZE:
            return False
        return self._shannon_entropy(probe) >= self.STATIC_NOISE_ENTROPY_THRESHOLD

    def _find_pattern(self, mv: memoryview, compiled_pattern: "re.Pattern[bytes]", start: int, end: int) -> int:
        if start >= end:
            return -1
        view = mv[start:end]
        match = compiled_pattern.search(view)
        if match is None:
            return -1
        return start + match.start()

    def _validate_secondary_marker(
        self,
        mv: memoryview,
        signature: SignatureDefinition,
        absolute_index: int,
        up_to_offset: int,
    ) -> bool:
        if signature.secondary_marker_offset is None or signature.secondary_marker_bytes is None:
            return True
        start = absolute_index + signature.secondary_marker_offset
        end = start + len(signature.secondary_marker_bytes)
        if end > up_to_offset or start < 0:
            return False
        return bytes(mv[start:end]) == signature.secondary_marker_bytes

    def _validate_initial_ftyp_box(self, mv: memoryview, absolute_start: int, up_to_offset: int) -> bool:
        if absolute_start < 0 or absolute_start + 8 > up_to_offset:
            return False
        raw_size = int.from_bytes(mv[absolute_start:absolute_start + 4], "big")
        return self._FTYP_MIN_BOX_SIZE <= raw_size <= self._FTYP_MAX_BOX_SIZE

    def _passes_signature_validation(
        self,
        mv: memoryview,
        signature: SignatureDefinition,
        absolute_index: int,
        up_to_offset: int,
    ) -> bool:
        if not self._validate_secondary_marker(mv, signature, absolute_index, up_to_offset):
            return False
        if signature.length_strategy == "iso_bmff_boxwalk":
            adjusted_start = max(0, absolute_index + signature.start_offset_adjustment)
            if not self._validate_initial_ftyp_box(mv, adjusted_start, up_to_offset):
                return False
        return True

    def _resolve_riff_declared_length(self, mv: memoryview, absolute_start: int, up_to_offset: int) -> Optional[int]:
        if absolute_start < 0 or absolute_start + 8 > up_to_offset:
            return None
        declared_size = int.from_bytes(mv[absolute_start + 4:absolute_start + 8], "little")
        return declared_size + 8

    def _advance_iso_bmff_resolution(self, job: _OpenCarveJob, mv: memoryview, up_to_offset: int) -> None:
        if job.resolved_length is not None or job.dynamic_resolution_failed or job.box_probe_offset is None:
            return
        while True:
            probe_offset = job.box_probe_offset
            if probe_offset + 8 > up_to_offset:
                return
            raw_size = int.from_bytes(mv[probe_offset:probe_offset + 4], "big")
            box_type = bytes(mv[probe_offset + 4:probe_offset + 8])
            if raw_size == 0:
                job.dynamic_resolution_failed = True
                job.box_probe_offset = None
                return
            if not self._FOURCC_PATTERN.fullmatch(box_type):
                job.resolved_length = probe_offset - job.start_offset
                job.box_probe_offset = None
                return
            header_length = 8
            box_size = raw_size
            if raw_size == 1:
                if probe_offset + 16 > up_to_offset:
                    return
                box_size = int.from_bytes(mv[probe_offset + 8:probe_offset + 16], "big")
                header_length = 16
            if box_size < header_length:
                job.resolved_length = probe_offset - job.start_offset
                job.box_probe_offset = None
                return
            next_probe_offset = probe_offset + box_size
            if next_probe_offset - job.start_offset > job.signature.max_size_bytes:
                job.dynamic_resolution_failed = True
                job.box_probe_offset = None
                return
            job.box_probe_offset = next_probe_offset

    def _build_output_path(
        self,
        output_dir: Path,
        signature: SignatureDefinition,
        absolute_start: int,
        job_counter: int,
    ) -> Path:
        timestamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        seed = f"{signature.name}:{absolute_start}:{job_counter}:{time.time_ns()}".encode("utf-8")
        digest = hashlib.md5(seed).hexdigest()[:12]
        filename = f"{signature.name.lower()}_{timestamp}_{digest}{signature.extension}"
        return output_dir / filename

    def _cleanup_partial_file(self, output_path: Path, handle: BinaryIO) -> None:
        try:
            handle.close()
        except (PermissionError, OSError):
            pass
        try:
            output_path.unlink(missing_ok=True)
        except (PermissionError, OSError) as error:
            logger.warning("No fue posible eliminar el archivo parcial %s: %s", output_path, error)

    def _abort_job(self, job: _OpenCarveJob) -> None:
        self._cleanup_partial_file(job.output_path, job.handle)

    def _write_to_job(self, job: _OpenCarveJob, data: Any) -> bool:
        try:
            job.handle.write(data)
        except (PermissionError, OSError) as error:
            logger.error("Fallo al escribir en %s: %s", job.output_path, error)
            self._cleanup_partial_file(job.output_path, job.handle)
            return False
        job.hasher.update(data)
        job.bytes_written += len(data)
        return True

    def _close_and_finalize(self, job: _OpenCarveJob, results: list[CarvedFileResult], truncated: bool) -> None:
        try:
            job.handle.close()
        except (PermissionError, OSError) as error:
            logger.error("Fallo al cerrar %s, se descarta el resultado: %s", job.output_path, error)
            try:
                job.output_path.unlink(missing_ok=True)
            except (PermissionError, OSError) as unlink_error:
                logger.warning("No fue posible eliminar %s: %s", job.output_path, unlink_error)
            return
        results.append(
            CarvedFileResult(
                signature_name=job.signature.name,
                output_path=job.output_path,
                size_bytes=job.bytes_written,
                source_offset=job.start_offset,
                sha256=job.hasher.hexdigest(),
                truncated=truncated,
            )
        )

    def _finalize_job(
        self,
        job: _OpenCarveJob,
        payload: Any,
        results: list[CarvedFileResult],
        truncated: bool,
    ) -> None:
        if len(payload) > 0 and not self._write_to_job(job, payload):
            return
        self._close_and_finalize(job, results, truncated)

    def _discard_incomplete_job(self, job: _OpenCarveJob, results: list[CarvedFileResult]) -> None:
        self._close_and_finalize(job, results, truncated=True)

    def _process_job_against_buffer(
        self,
        job: _OpenCarveJob,
        mv: memoryview,
        up_to_offset: int,
        results: list[CarvedFileResult],
    ) -> bool:
        write_cursor = job.start_offset + job.bytes_written
        if write_cursor >= up_to_offset:
            return True

        if job.signature.length_strategy == "iso_bmff_boxwalk":
            self._advance_iso_bmff_resolution(job, mv, up_to_offset)

        if job.resolved_length is not None:
            new_data = mv[write_cursor:up_to_offset]
            remaining = job.resolved_length - job.bytes_written
            if remaining <= len(new_data):
                payload = new_data[:max(0, remaining)]
                self._finalize_job(job, payload, results, truncated=False)
                return False
            if not self._write_to_job(job, new_data):
                return False
            return True

        if job.signature.footer is not None:
            footer_len = len(job.signature.footer)
            search_from = max(write_cursor, job.search_offset)
            match_index = self._find_pattern(mv, job.signature.compiled_footer, search_from, up_to_offset)
            if match_index != -1:
                payload_end = match_index + footer_len
                payload = mv[write_cursor:payload_end]
                self._finalize_job(job, payload, results, truncated=False)
                return False

            safe_flush_to = max(write_cursor, up_to_offset - (footer_len - 1))
            allowed_new_bytes = job.signature.max_size_bytes - job.bytes_written
            pending = safe_flush_to - write_cursor

            if pending >= allowed_new_bytes:
                payload = mv[write_cursor:write_cursor + max(0, allowed_new_bytes)]
                self._finalize_job(job, payload, results, truncated=True)
                return False

            if pending > 0:
                new_data = mv[write_cursor:safe_flush_to]
                if not self._write_to_job(job, new_data):
                    return False

            job.search_offset = safe_flush_to
            return True

        new_data = mv[write_cursor:up_to_offset]
        allowed_new_bytes = job.signature.max_size_bytes - job.bytes_written
        if len(new_data) >= allowed_new_bytes:
            payload = new_data[:max(0, allowed_new_bytes)]
            self._finalize_job(job, payload, results, truncated=True)
            return False

        if not self._write_to_job(job, new_data):
            return False
        return True

    def _open_new_job(
        self,
        signature: SignatureDefinition,
        mv: memoryview,
        match_index: int,
        up_to_offset: int,
        output_dir: Path,
        job_counter: int,
        results: list[CarvedFileResult],
        active_jobs: list[_OpenCarveJob],
        hash_factory: HashAlgorithmFactory,
    ) -> None:
        absolute_start = match_index + signature.start_offset_adjustment
        if absolute_start < 0:
            absolute_start = 0
        output_path = self._build_output_path(output_dir, signature, absolute_start, job_counter)

        try:
            handle: BinaryIO = open(output_path, "wb")
        except (PermissionError, OSError, FileNotFoundError) as error:
            logger.error("No fue posible crear el archivo de salida %s: %s", output_path, error)
            return

        job = _OpenCarveJob(
            signature=signature,
            start_offset=absolute_start,
            output_path=output_path,
            handle=handle,
            hasher=hash_factory(),
            search_offset=absolute_start,
        )

        if signature.length_strategy == "riff_declared_size":
            declared_length = self._resolve_riff_declared_length(mv, absolute_start, up_to_offset)
            if declared_length is not None and declared_length <= signature.max_size_bytes:
                job.resolved_length = declared_length
        elif signature.length_strategy == "iso_bmff_boxwalk":
            job.box_probe_offset = absolute_start

        if self._process_job_against_buffer(job, mv, up_to_offset, results):
            active_jobs.append(job)

    def _detect_and_open_jobs(
        self,
        mv: memoryview,
        search_start: int,
        up_to_offset: int,
        output_dir: Path,
        opened_offsets: set[int],
        job_counter: int,
        active_jobs: list[_OpenCarveJob],
        results: list[CarvedFileResult],
        signatures: dict[str, SignatureDefinition],
        hash_factory: HashAlgorithmFactory,
    ) -> int:
        for signature in signatures.values():
            cursor = search_start
            while True:
                match_index = self._find_pattern(mv, signature.compiled_header, cursor, up_to_offset)
                if match_index == -1:
                    break
                cursor = match_index + 1
                if match_index in opened_offsets:
                    continue
                if not self._passes_signature_validation(mv, signature, match_index, up_to_offset):
                    continue
                if self._looks_like_static_noise(mv, match_index, up_to_offset):
                    continue
                opened_offsets.add(match_index)
                job_counter += 1
                self._open_new_job(
                    signature, mv, match_index, up_to_offset, output_dir, job_counter, results, active_jobs, hash_factory
                )
        return job_counter

    def _advance_active_jobs(
        self,
        active_jobs: list[_OpenCarveJob],
        mv: memoryview,
        up_to_offset: int,
        results: list[CarvedFileResult],
    ) -> None:
        still_active: list[_OpenCarveJob] = []
        for job in active_jobs:
            if self._process_job_against_buffer(job, mv, up_to_offset, results):
                still_active.append(job)
        active_jobs[:] = still_active
