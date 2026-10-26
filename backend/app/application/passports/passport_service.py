from io import BytesIO
from pathlib import Path
import zipfile

from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository
from backend.app.infrastructure.exporters.word_passport_exporter import WordPassportExporter
from backend.app.security.file_encryption import FileEncryptionService


class PassportService:
    def __init__(
        self,
        pipeline_repo: PipelineRepository,
        template_path: Path,
        output_dir: Path,
        encryption_service: FileEncryptionService,
        remove_source_after_processing: bool = False,
    ):
        self.repo = pipeline_repo
        self.exporter = WordPassportExporter(template_path)
        self.output_dir = output_dir
        self.encryption = encryption_service
        self.remove_source_after_processing = remove_source_after_processing

    async def generate_passport(self, name: str) -> tuple[bytes, str]:
        pipeline = await self.repo.get_by_name(name)
        if not pipeline:
            raise KeyError(name)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{name}.docx"
        encrypted_path = self.output_dir / f"{name}.docx.enc"
        try:
            self.exporter.export(pipeline, path)
            plaintext = path.read_bytes()
            encrypted_payload = self.encryption.encrypt(plaintext)
            encrypted_path.write_bytes(encrypted_payload)
            decrypted = self.encryption.decrypt(encrypted_payload)
            return decrypted, path.name
        finally:
            # Никогда не оставляем незашифрованный docx на диске после отдачи в память.
            path.unlink(missing_ok=True)
            if self.remove_source_after_processing:
                encrypted_path.unlink(missing_ok=True)

    async def get_all_pipelines_names(self) -> list[str]:
        return await self.repo.list_names()

    async def generate_passports_zip(self, names: list[str]) -> tuple[bytes, str]:
        unique_names: list[str] = []
        seen: set[str] = set()
        for name in names:
            key = (name or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_names.append(key)

        if not unique_names:
            raise ValueError("No pipeline names provided")

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for pipeline_name in unique_names:
                payload, filename = await self.generate_passport(pipeline_name)
                archive.writestr(filename, payload)

        return buffer.getvalue(), "passports.zip"

