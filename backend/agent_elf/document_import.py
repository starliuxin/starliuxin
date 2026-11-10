from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1024 * 1024


class DocumentImportError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    file_type: str
    content: str
    source_metadata: dict[str, str | int]


def extract_document(filename: str, payload: bytes) -> ExtractedDocument:
    if not filename or "\x00" in filename or "/" in filename or "\\" in filename:
        raise DocumentImportError("文件名无效。", 400)
    if len(filename) > 255:
        raise DocumentImportError("文件名不能超过 255 个字符。", 400)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise DocumentImportError("单个文档不能超过 20 MiB。", 413)
    if not payload:
        raise DocumentImportError("文件为空。")

    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        content, details = _extract_pdf(payload)
        file_type = "pdf"
        extraction_method = "pypdf-text"
    elif suffix == ".docx":
        content, details = _extract_docx(payload)
        file_type = "docx"
        extraction_method = "python-docx-text"
    else:
        raise DocumentImportError("仅支持 PDF 与 DOCX 文档。", 415)

    extracted_bytes = len(content.encode("utf-8"))
    if extracted_bytes > MAX_EXTRACTED_BYTES:
        raise DocumentImportError("提取文本不能超过 1 MiB。", 413)
    if not content.strip():
        raise DocumentImportError("未找到可提取的文本；扫描件 OCR 尚不支持。")

    metadata: dict[str, str | int] = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source_size_bytes": len(payload),
        "extraction_method": extraction_method,
        "extracted_bytes": extracted_bytes,
        **details,
    }
    return ExtractedDocument(filename, file_type, content, metadata)


def _extract_pdf(payload: bytes) -> tuple[str, dict[str, int]]:
    if not payload.startswith(b"%PDF-"):
        raise DocumentImportError("文件扩展名与 PDF 文件签名不匹配。")

    try:
        reader = PdfReader(BytesIO(payload), strict=False)
        if reader.is_encrypted:
            raise DocumentImportError("不支持加密 PDF，请先在本地解密后重新导入。")
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise DocumentImportError("PDF 不能超过 500 页。", 413)

        pages: list[str] = []
        extracted_size = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            extracted_size = _append_limited(pages, text, extracted_size)
        return "\n\n".join(pages).strip(), {"page_count": page_count}
    except DocumentImportError:
        raise
    except (PdfReadError, ValueError, OSError, KeyError, NotImplementedError) as exc:
        raise DocumentImportError("PDF 无法解析或已损坏。") from exc


def _extract_docx(payload: bytes) -> tuple[str, dict[str, int]]:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise DocumentImportError("DOCX 压缩包不能超过 2,000 个文件条目。", 413)
            if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocumentImportError("DOCX 解压后内容不能超过 50 MiB。", 413)
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise DocumentImportError("不支持加密 DOCX 文件。")
            if any(stat.S_ISLNK(entry.external_attr >> 16) for entry in entries):
                raise DocumentImportError("DOCX 中不允许包含符号链接。")
            required_entries = {"[Content_Types].xml", "word/document.xml"}
            if not required_entries.issubset(archive.namelist()):
                raise DocumentImportError("文件扩展名与 DOCX 文档结构不匹配。")

        document = Document(BytesIO(payload))
    except DocumentImportError:
        raise
    except (BadZipFile, PackageNotFoundError, XMLSyntaxError, KeyError, ValueError, OSError) as exc:
        raise DocumentImportError("DOCX 无法解析或已损坏。") from exc

    parts: list[str] = []
    extracted_size = 0
    try:
        for paragraph in document.paragraphs:
            extracted_size = _append_limited(parts, paragraph.text, extracted_size)
        for table in document.tables:
            for row in table.rows:
                extracted_size = _append_limited(
                    parts,
                    "\t".join(cell.text for cell in row.cells),
                    extracted_size,
                )
    except DocumentImportError:
        raise
    except ValueError as exc:
        raise DocumentImportError("提取文本不能超过 1 MiB。", 413) from exc

    return "\n".join(parts).strip(), {"archive_entries": len(entries)}


def _append_limited(parts: list[str], text: str, current_size: int) -> int:
    if not text:
        return current_size
    separator = 1 if parts else 0
    text_size = len(text.encode("utf-8"))
    if current_size + separator + text_size > MAX_EXTRACTED_BYTES:
        raise DocumentImportError("提取文本不能超过 1 MiB。", 413)
    parts.append(text)
    return current_size + separator + text_size
