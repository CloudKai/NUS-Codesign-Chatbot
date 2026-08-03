from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .settings import settings


TEXT_SUFFIXES = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".py", ".js", ".ts", ".tsx",
    ".jsx", ".html", ".css", ".xml", ".yaml", ".yml", ".sql", ".r",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | IMAGE_SUFFIXES | {".pdf", ".docx", ".pptx", ".xlsx"}


@dataclass(frozen=True)
class StoredUpload:
    name: str
    path: Path
    mime: str
    size: int
    supported: bool
    extracted_text: str = ""

    @property
    def is_image(self) -> bool:
        return self.path.suffix.lower() in IMAGE_SUFFIXES


def _safe_name(name: str) -> str:
    safe = Path(name).name.replace("\x00", "").strip()
    return safe[:180] or "upload"


def _upload_root(thread_id: str) -> Path:
    safe_id = "".join(character for character in thread_id if character.isalnum() or character in "-_")
    root = (settings.files_dir / "threads" / safe_id / "uploads").resolve()
    if settings.files_dir not in root.parents:
        raise ValueError("Unsafe chat identifier")
    root.mkdir(parents=True, exist_ok=True)
    return root


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        from docx import Document

        document = Document(path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    if suffix == ".pptx":
        from pptx import Presentation

        presentation = Presentation(path)
        values: list[str] = []
        for index, slide in enumerate(presentation.slides, start=1):
            values.append(f"Slide {index}")
            values.extend(
                shape.text for shape in slide.shapes if hasattr(shape, "text") and shape.text
            )
        return "\n".join(values)
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        output = io.StringIO()
        writer = csv.writer(output)
        for sheet in workbook.worksheets:
            writer.writerow([f"Sheet: {sheet.title}"])
            for row in sheet.iter_rows(values_only=True):
                writer.writerow(["" if value is None else value for value in row])
        return output.getvalue()
    return ""


def save_uploads(
    thread_id: str,
    uploads: Iterable[tuple[str, bytes, str | None]],
    *,
    max_file_size_mb: int | None = None,
) -> list[StoredUpload]:
    """Validate and store uploads using the user-upload limit by default."""
    items = list(uploads)
    if len(items) > settings.max_files:
        raise ValueError(f"Upload at most {settings.max_files} files per message.")
    root = _upload_root(thread_id)
    size_limit_mb = max_file_size_mb or settings.max_file_size_mb
    stored: list[StoredUpload] = []
    for name, content, supplied_mime in items:
        if len(content) > size_limit_mb * 1024 * 1024:
            raise ValueError(f"{name} exceeds the {size_limit_mb} MB limit.")
        safe_name = _safe_name(name)
        candidate = root / safe_name
        counter = 2
        while candidate.exists():
            candidate = root / f"{Path(safe_name).stem}-{counter}{Path(safe_name).suffix}"
            counter += 1
        candidate.write_bytes(content)
        mime = supplied_mime or mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        supported = candidate.suffix.lower() in SUPPORTED_SUFFIXES
        extracted = ""
        if supported and candidate.suffix.lower() not in IMAGE_SUFFIXES:
            try:
                extracted = extract_text(candidate)
            except Exception as exc:
                extracted = f"[Could not extract {candidate.name}: {type(exc).__name__}]"
        stored.append(
            StoredUpload(
                name=candidate.name,
                path=candidate,
                mime=mime,
                size=len(content),
                supported=supported,
                extracted_text=extracted[:120_000],
            )
        )
    return stored


def image_input(upload: StoredUpload) -> dict[str, str]:
    encoded = base64.b64encode(upload.path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{upload.mime};base64,{encoded}",
        "detail": "auto",
    }


def document_context(uploads: Iterable[StoredUpload], limit: int = 160_000) -> str:
    sections: list[str] = []
    remaining = limit
    for upload in uploads:
        if not upload.extracted_text:
            continue
        text = upload.extracted_text[:remaining]
        sections.append(f"--- {upload.name} ---\n{text}")
        remaining -= len(text)
        if remaining <= 0:
            break
    return "\n\n".join(sections)
