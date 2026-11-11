"""Offline document capture. Store original → native text or OCR. Never a live-call path."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

PACKET_DIR = Path(__file__).resolve().parent.parent / "data" / "packets"
NATIVE_MIN = 80
LOW_CONF = 60.0


def same_file(left: Path, right: Path) -> bool:
    """Skip duplicates by exact bytes. Size first, then a streaming compare — no digest."""
    if not left.exists() or not right.exists():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as first, right.open("rb") as second:
        while True:
            chunk_a, chunk_b = first.read(65536), second.read(65536)
            if chunk_a != chunk_b:
                return False
            if not chunk_a:
                return True


def store_original(case_id: str, source: Path) -> dict:
    if not source.exists():
        raise FileNotFoundError(str(source))
    dest_dir = PACKET_DIR / case_id / "originals"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    shutil.copy2(source, dest)
    return {
        "original_path": str(dest),
        "filename": source.name,
        "bytes": dest.stat().st_size,
    }


def _pdf_text(path: Path, first: int | None = None, last: int | None = None) -> str:
    cmd = ["pdftotext", "-layout"]
    if first is not None:
        cmd.extend(["-f", str(first)])
    if last is not None:
        cmd.extend(["-l", str(last)])
    cmd.extend([str(path), "-"])
    try:
        return subprocess.check_output(cmd, text=True, timeout=20)
    except Exception:
        return ""


def _pdf_page_count(path: Path) -> int | None:
    try:
        raw = subprocess.check_output(["pdfinfo", str(path)], text=True, timeout=10)
    except Exception:
        return None
    for line in raw.splitlines():
        if line.lower().startswith("pages"):
            try:
                return int(line.split(":", 1)[1].strip())
            except (IndexError, ValueError):
                return None
    return None


def _ocr_tsv(path: Path) -> tuple[str, float | None]:
    try:
        raw = subprocess.check_output(["tesseract", str(path), "stdout", "tsv"], text=True, timeout=40)
    except Exception:
        try:
            return subprocess.check_output(["tesseract", str(path), "stdout"], text=True, timeout=40), None
        except Exception:
            return "", None
    words: list[str] = []
    confs: list[float] = []
    for index, line in enumerate(raw.splitlines()):
        if index == 0:
            continue
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            conf = float(parts[10])
        except ValueError:
            continue
        token = (parts[11] or "").strip()
        if not token or conf < 0:
            continue
        words.append(token)
        confs.append(min(conf, 100.0))
    mean = round(sum(confs) / len(confs), 1) if confs else None
    return " ".join(words), mean


def _docx_text(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ET.fromstring(xml)
        parts = []
        for para in root.iter(f"{ns}p"):
            line = "".join((node.text or "") for node in para.iter(f"{ns}t")).strip()
            if line:
                parts.append(line)
        return "\n".join(parts)
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return ""


def _ocr_pdf_pages(path: Path) -> tuple[str, float | None]:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "page"
            subprocess.check_call(
                ["pdftoppm", "-png", "-r", "200", str(path), str(prefix)],
                timeout=300,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            texts = []
            confs = []
            for page in sorted(Path(tmp).glob("page*.png")):
                text, conf = _ocr_tsv(page)
                if text.strip():
                    texts.append(text)
                if conf is not None:
                    confs.append(conf)
            mean = round(sum(confs) / len(confs), 1) if confs else None
            return "\n".join(texts), mean
    except Exception:
        return "", None


def _page_record(page: int, text: str, method: str, confidence: float | None, ocr_used: bool) -> dict:
    stripped = (text or "").strip()
    return {
        "page": page,
        "text": text or "",
        "method": method,
        "confidence": confidence,
        "ocr_used": ocr_used,
        "unreadable": len(stripped) < 20,
        "char_count": len(stripped),
    }


def _ocr_one_pdf_page(path: Path, page: int) -> tuple[str, float | None]:
    if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
        return "", None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "page"
            subprocess.check_call(
                ["pdftoppm", "-png", "-r", "200", "-f", str(page), "-l", str(page), str(path), str(prefix)],
                timeout=60,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            images = sorted(Path(tmp).glob("page*.png"))
            if not images:
                return "", None
            return _ocr_tsv(images[0])
    except Exception:
        return "", None


def _pdf_pages(path: Path) -> list[dict]:
    """Native text per page. OCR only pages that lack readable born-digital text."""
    count = _pdf_page_count(path)
    if not count:
        blob = _pdf_text(path)
        chunks = blob.split("\f") if blob else [""]
        while chunks and not chunks[-1].strip() and len(chunks) > 1:
            chunks.pop()
        count = max(len(chunks), 1)
        pages = []
        for index, chunk in enumerate(chunks or [""], start=1):
            native = chunk or ""
            if len(native.strip()) >= NATIVE_MIN:
                pages.append(_page_record(index, native, "pdftotext", 100.0, False))
                continue
            ocr_text, conf = _ocr_one_pdf_page(path, index)
            if ocr_text.strip():
                pages.append(_page_record(index, ocr_text, "tesseract_pdf", conf, True))
            else:
                pages.append(
                    _page_record(
                        index,
                        native,
                        "pdftotext_thin",
                        conf,
                        False,
                    )
                )
        return pages
    pages = []
    for index in range(1, count + 1):
        native = _pdf_text(path, first=index, last=index)
        if len(native.strip()) >= NATIVE_MIN:
            pages.append(_page_record(index, native, "pdftotext", 100.0, False))
            continue
        ocr_text, conf = _ocr_one_pdf_page(path, index)
        if ocr_text.strip():
            pages.append(_page_record(index, ocr_text, "tesseract_pdf", conf, True))
        else:
            pages.append(_page_record(index, native, "pdftotext_thin", conf, False))
    return pages


def read_pages(path: Path) -> dict:
    """Page-level extraction. A readable cover must not hide scanned attachments."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        text = _docx_text(path)
        pages = [_page_record(1, text, "docx", 100.0 if text.strip() else None, False)]
    elif suffix == ".pdf":
        pages = _pdf_pages(path)
    else:
        text, conf = _ocr_tsv(path)
        pages = [_page_record(1, text, "tesseract", conf, True)]
    confs = [row["confidence"] for row in pages if row.get("confidence") is not None]
    mean = round(sum(confs) / len(confs), 1) if confs else None
    methods = {row["method"] for row in pages}
    method = "mixed" if len(methods) > 1 else next(iter(methods), "unread")
    joined = "\n\f\n".join(row["text"] for row in pages)
    return {
        "pages": pages,
        "text": joined,
        "method": method,
        "confidence": mean,
        "ocr_used": any(row.get("ocr_used") for row in pages),
        "unreadable": all(row.get("unreadable") for row in pages) if pages else True,
        "page_count": len(pages),
    }


def read_document(path: Path) -> dict:
    """Prefer born-digital PDF text. OCR images and thin scanned pages. Do not invent text."""
    return read_pages(path)


def low_confidence(read: dict) -> bool:
    conf = read.get("confidence")
    return bool(read.get("ocr_used")) and conf is not None and conf < LOW_CONF
