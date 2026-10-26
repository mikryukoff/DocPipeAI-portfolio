from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.application.exceptions import ValidationError
from backend.app.application.ocr.ocr_recognition_service import OcrRecognitionService


class OcrBatchService:
    def __init__(self, recognition_service: OcrRecognitionService):
        self.recognition_service = recognition_service

    @staticmethod
    def _norm_batch_stats(
        *,
        files_processed: int,
        files_total: int,
        current_file: str | None = None,
        inner: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Поля для панели job (совместимо с renderJob: files_processed / files_total)."""
        out: dict[str, Any] = {
            "source": "ocr_pdf",
            "files_processed": files_processed,
            "files_total": files_total,
            "processed_files": files_processed,
            "total_files": files_total,
        }
        if current_file:
            out["current_file"] = current_file
        if inner:
            for k, v in inner.items():
                if v is not None:
                    out[k] = v
        return out

    @staticmethod
    def _scale_inner_progress(
        file_index: int,
        total_files: int,
        inner_percent: int,
    ) -> int:
        if total_files <= 0:
            return inner_percent
        lo = (file_index - 1) * 100.0 / total_files
        hi = file_index * 100.0 / total_files
        return int(lo + (inner_percent / 100.0) * (hi - lo))

    def _wrap_file_progress(
        self,
        *,
        file_index: int,
        total_files: int,
        files_done_before: int,
        files_total_counter: int,
        current_file: str,
        outer: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None,
    ) -> Callable[[int, dict[str, Any] | None], Awaitable[None]] | None:
        if outer is None:
            return None

        async def wrapped(inner_p: int, inner_ex: dict[str, Any] | None = None) -> None:
            overall = self._scale_inner_progress(file_index, total_files, inner_p)
            merged = self._norm_batch_stats(
                files_processed=files_done_before,
                files_total=files_total_counter,
                current_file=current_file,
                inner=inner_ex,
            )
            await outer(min(99, overall), merged)

        return wrapped

    async def process_pdf_paths(
        self,
        *,
        kind: str,
        pdf_paths: list[Path],
        pages_limit: int,
        on_progress: Callable[[int, dict[str, Any] | None], Awaitable[None]] | None = None,
    ) -> list[dict[str, Any]]:
        # Порядок только как в multipart/архиве — без сортировки по имени.
        pdf_paths = list(pdf_paths)
        results: list[dict[str, Any]] = []
        if kind == "passport_compensators":
            if len(pdf_paths) % 2 != 0:
                raise ValidationError(
                    "Для passport_compensators требуется четное количество PDF-файлов: "
                    "первый в паре — diameter, второй — gost/materials."
                )
            total_pairs = len(pdf_paths) // 2
            for idx in range(0, len(pdf_paths), 2):
                diameter_path = pdf_paths[idx]
                gost_materials_path = pdf_paths[idx + 1]
                pair_index = (idx // 2) + 1
                if on_progress is not None:
                    await on_progress(
                        min(90, int((pair_index - 1) / max(total_pairs, 1) * 100)),
                        self._norm_batch_stats(
                            files_processed=pair_index - 1,
                            files_total=total_pairs,
                            current_file=f"{diameter_path.name} + {gost_materials_path.name}",
                            inner={"stage": "batch_compensators", "ocr_kind": kind},
                        ),
                    )
                inner_cb = self._wrap_file_progress(
                    file_index=pair_index,
                    total_files=total_pairs,
                    files_done_before=pair_index - 1,
                    files_total_counter=total_pairs,
                    current_file=f"{diameter_path.name} + {gost_materials_path.name}",
                    outer=on_progress,
                )
                raw = await self.recognition_service.recognize_passport_compensators(
                    diameter_file_name=diameter_path.name,
                    diameter_pdf_bytes=diameter_path.read_bytes(),
                    gost_materials_file_name=gost_materials_path.name,
                    gost_materials_pdf_bytes=gost_materials_path.read_bytes(),
                    on_progress=inner_cb,
                )
                merged = dict(raw) if isinstance(raw, dict) else {}
                merged["source_file"] = [diameter_path.name, gost_materials_path.name]
                results.append(merged)
                if on_progress is not None:
                    await on_progress(
                        min(95, int((pair_index / max(total_pairs, 1)) * 100)),
                        self._norm_batch_stats(
                            files_processed=pair_index,
                            files_total=total_pairs,
                            current_file=f"{diameter_path.name} + {gost_materials_path.name}",
                            inner={"stage": "batch_compensators", "ocr_kind": kind},
                        ),
                    )
            if on_progress is not None:
                await on_progress(
                    100,
                    self._norm_batch_stats(
                        files_processed=total_pairs,
                        files_total=total_pairs,
                        inner={"stage": "batch_done", "ocr_kind": kind},
                    ),
                )
            return results

        total_files = len(pdf_paths)
        for index, pdf_path in enumerate(pdf_paths, start=1):
            if on_progress is not None:
                await on_progress(
                    min(90, int((index - 1) / max(total_files, 1) * 100)),
                    self._norm_batch_stats(
                        files_processed=index - 1,
                        files_total=total_files,
                        current_file=pdf_path.name,
                        inner={"stage": "batch_files", "ocr_kind": kind},
                    ),
                )
            inner_cb = self._wrap_file_progress(
                file_index=index,
                total_files=total_files,
                files_done_before=index - 1,
                files_total_counter=total_files,
                current_file=pdf_path.name,
                outer=on_progress,
            )
            if kind == "instrument_drawings":
                raw = await self.recognition_service.recognize_drawing(
                    file_name=pdf_path.name,
                    pdf_bytes=pdf_path.read_bytes(),
                    pages_limit=pages_limit,
                    on_progress=inner_cb,
                )
            elif kind == "passport_rngs":
                raw = await self.recognition_service.recognize_passport_rngs(
                    file_name=pdf_path.name,
                    pdf_bytes=pdf_path.read_bytes(),
                    pages_limit=pages_limit,
                    on_progress=inner_cb,
                )
            elif kind == "passport_vik":
                raw = await self.recognition_service.recognize_passport_vik(
                    file_name=pdf_path.name,
                    pdf_bytes=pdf_path.read_bytes(),
                    pages_limit=pages_limit,
                    on_progress=inner_cb,
                )
            elif kind == "pipelines_tests":
                raw = await self.recognition_service.recognize_pipelines_tests(
                    file_name=pdf_path.name,
                    pdf_bytes=pdf_path.read_bytes(),
                    pages_limit=pages_limit,
                    on_progress=inner_cb,
                )
            else:
                raw = {}
            merged = dict(raw) if isinstance(raw, dict) else {}
            merged["source_file"] = pdf_path.name
            results.append(merged)
            if on_progress is not None:
                await on_progress(
                    min(95, int((index / max(total_files, 1)) * 100)),
                    self._norm_batch_stats(
                        files_processed=index,
                        files_total=total_files,
                        current_file=pdf_path.name,
                        inner={"stage": "batch_files", "ocr_kind": kind},
                    ),
                )
        if on_progress is not None:
            await on_progress(
                100,
                self._norm_batch_stats(
                    files_processed=total_files,
                    files_total=total_files,
                    inner={"stage": "batch_done", "ocr_kind": kind},
                ),
            )
        return results
