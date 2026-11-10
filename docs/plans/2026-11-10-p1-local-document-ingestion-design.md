# P1 Local Document Ingestion Design

## Goal

Extend the P0 local knowledge shelf to accept text-based PDF and DOCX documents while keeping the existing TXT, Markdown, and CSV import API unchanged.

## Scope and limits

- Accept `.pdf` and `.docx` files through a multipart upload endpoint.
- Extract embedded text only; do not run OCR, follow links, or execute document content.
- Limit uploaded files to 20 MiB, PDFs to 500 pages, DOCX archives to 2,000 entries and 50 MiB total uncompressed size, and extracted UTF-8 text to 1 MiB.
- Validate file signatures and required DOCX package entries rather than trusting browser-supplied MIME types.
- Reject encrypted, malformed, unsupported, or text-empty documents with a clear error and do not create a knowledge item.
- Store extracted text, not the original file. Record source filename, format, source byte size, SHA-256, extraction method, and extracted byte count.
- Keep synchronous parsing for this bounded local-only P1 slice. It is not an OS-level sandbox.

## Implementation

Add a document extraction module using `pypdf` and `python-docx`. The upload route reads the multipart file with a strict size bound, validates the extension and signature, applies PDF page or DOCX ZIP limits, then stores extracted text and provenance through the existing SQLite knowledge store. Add a backward-compatible metadata column for existing databases; existing text imports continue to work without changing their API contract.

The knowledge UI accepts PDF and DOCX alongside current text formats, displays import errors, and exposes extraction provenance for imported documents. The raw document is discarded after extraction.

## Verification

Test valid PDF/DOCX extraction, legacy text imports, forged extensions/signatures, encrypted or malformed PDFs, scanned/text-empty documents, oversized uploads, PDF page overflow, DOCX archive entry and decompressed-size overflow, persistence of provenance, and migration from the existing knowledge schema. Run backend tests and Ruff; run frontend tests, build, and dependency audit.
