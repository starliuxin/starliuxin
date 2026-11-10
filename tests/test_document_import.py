from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from agent_elf.app import create_app
from agent_elf.document_import import (
    MAX_DOCX_ENTRIES,
    MAX_DOCX_UNCOMPRESSED_BYTES,
    MAX_EXTRACTED_BYTES,
    MAX_PDF_PAGES,
    MAX_UPLOAD_BYTES,
    DocumentImportError,
    extract_document,
)
from agent_elf.provider import DemoProvider
from agent_elf.store import StateStore
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter


def make_pdf(text: str = "Local PDF knowledge", page_count: int = 1) -> bytes:
    font_number = page_count + 3
    content_start = font_number + 1
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    kids = " ".join(f"{index + 3} 0 R" for index in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    for index in range(page_count):
        content_number = content_start + index
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
                f"/Contents {content_number} 0 R >>"
            ).encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    for index in range(page_count):
        page_text = escaped if index == 0 else ""
        stream = f"BT /F1 12 Tf 72 720 Td ({page_text}) Tj ET".encode()
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, content in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(content)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def make_docx(text: str = "Local DOCX knowledge") -> bytes:
    document = Document()
    document.add_paragraph(text)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "topic"
    table.rows[0].cells[1].text = "local"
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def add_docx_entry(payload: bytes, name: str, content: bytes) -> bytes:
    return add_docx_entries(payload, [(name, content)])


def add_docx_entries(payload: bytes, extra_entries: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(payload)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for entry in source.infolist():
            target.writestr(entry.filename, source.read(entry.filename))
        for name, content in extra_entries:
            target.writestr(name, content)
    return output.getvalue()


def test_extracts_pdf_and_docx_text_with_provenance() -> None:
    pdf = extract_document("notes.pdf", make_pdf())
    docx = extract_document("notes.docx", make_docx())

    assert pdf.content == "Local PDF knowledge"
    assert pdf.file_type == "pdf"
    assert pdf.source_metadata["page_count"] == 1
    assert len(str(pdf.source_metadata["sha256"])) == 64
    assert docx.content == "Local DOCX knowledge\ntopic\tlocal"
    assert docx.file_type == "docx"
    assert docx.source_metadata["archive_entries"] > 0


def test_rejects_mismatched_names_encrypted_and_text_empty_files() -> None:
    with pytest.raises(DocumentImportError, match="签名"):
        extract_document("forged.pdf", make_docx())

    with pytest.raises(DocumentImportError, match="PDF 无法解析"):
        extract_document("broken.pdf", b"%PDF-1.4\nnot a valid PDF")

    encrypted = PdfWriter()
    encrypted.add_blank_page(width=100, height=100)
    encrypted.encrypt("secret")
    stream = BytesIO()
    encrypted.write(stream)
    with pytest.raises(DocumentImportError, match="加密 PDF"):
        extract_document("encrypted.pdf", stream.getvalue())

    with pytest.raises(DocumentImportError, match="扫描件 OCR 尚不支持"):
        extract_document("image-only.pdf", make_pdf(text=""))

    fake_archive = BytesIO()
    with ZipFile(fake_archive, "w") as archive:
        archive.writestr("not-a-docx.txt", "fake")
    with pytest.raises(DocumentImportError, match="DOCX 文档结构"):
        extract_document("fake.docx", fake_archive.getvalue())


def test_rejects_size_page_and_extracted_text_overflows() -> None:
    with pytest.raises(DocumentImportError) as upload_error:
        extract_document("large.pdf", b"%PDF-" + b"0" * MAX_UPLOAD_BYTES)
    assert upload_error.value.status_code == 413

    with pytest.raises(DocumentImportError) as pages_error:
        extract_document("many-pages.pdf", make_pdf(page_count=MAX_PDF_PAGES + 1))
    assert pages_error.value.status_code == 413

    with pytest.raises(DocumentImportError) as text_error:
        extract_document(
            "large-text.pdf",
            make_pdf(text="x" * (MAX_EXTRACTED_BYTES + 1)),
        )
    assert text_error.value.status_code == 413

    with pytest.raises(DocumentImportError) as docx_text_error:
        extract_document(
            "large-text.docx",
            make_docx(text="x" * (MAX_EXTRACTED_BYTES + 1)),
        )
    assert docx_text_error.value.status_code == 413


def test_rejects_docx_archive_entry_and_uncompressed_size_overflows() -> None:
    many_entries = add_docx_entries(
        make_docx(),
        [(f"extra/{index}.txt", b"") for index in range(MAX_DOCX_ENTRIES)],
    )
    with pytest.raises(DocumentImportError, match="2,000 个文件条目"):
        extract_document("too-many-entries.docx", many_entries)

    oversized_archive = add_docx_entry(
        make_docx(),
        "extra/large.txt",
        b"0" * (MAX_DOCX_UNCOMPRESSED_BYTES + 1),
    )
    assert len(oversized_archive) < MAX_UPLOAD_BYTES
    with pytest.raises(DocumentImportError, match="解压后内容不能超过"):
        extract_document("zip-bomb.docx", oversized_archive)


def test_upload_endpoint_persists_extracted_text_and_source_metadata(tmp_path: Path) -> None:
    app = create_app(tmp_path / "knowledge.sqlite3", DemoProvider())
    with TestClient(app) as client:
        response = client.post(
            "/api/knowledge/upload",
            files={"file": ("reference.pdf", make_pdf(), "application/pdf")},
        )
        assert response.status_code == 201
        imported = response.json()
        assert imported["source_metadata"]["source_size_bytes"] > 0

        listed = client.get("/api/knowledge").json()
        assert listed[0]["source_metadata"] == imported["source_metadata"]
        stored = app.state.store.enabled_knowledge()
        assert stored[0]["content"] == "Local PDF knowledge"

        oversized = client.post(
            "/api/knowledge/upload",
            files={
                "file": (
                    "too-large.pdf",
                    b"%PDF-" + b"0" * MAX_UPLOAD_BYTES,
                    "application/pdf",
                )
            },
        )
        assert oversized.status_code == 413
        assert len(client.get("/api/knowledge").json()) == 1


def test_existing_knowledge_database_migrates_metadata_column(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE knowledge_items (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )

    store = StateStore(database)
    item = store.add_knowledge("notes.md", "md", "old API")
    assert item["source_metadata"] is None
    assert store.list_knowledge()[0]["source_metadata"] is None
