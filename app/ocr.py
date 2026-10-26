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


def _pdf_text(path: Path) -> str:
    try:
        return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True, timeout=20)
    except Exception:
        return ""


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


def read_document(path: Path) -> dict:
    """Prefer born-digital PDF text. OCR images and scanned PDFs. Do not invent text."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        text = _docx_text(path)
        return {
            "text": text,
            "method": "docx",
            "confidence": 100.0 if text.strip() else None,
            "ocr_used": False,
            "unreadable": not bool(text.strip()),
        }
    if suffix == ".pdf":
        native = _pdf_text(path)
        if len(native.strip()) >= NATIVE_MIN:
            return {
                "text": native,
                "method": "pdftotext",
                "confidence": 100.0,
                "ocr_used": False,
                "unreadable": False,
            }
        if not shutil.which("tesseract"):
            return {
                "text": native,
                "method": "pdftotext_thin",
                "confidence": None,
                "ocr_used": False,
                "unreadable": len(native.strip()) < 20,
            }
        ocr_text, conf = _ocr_pdf_pages(path)
        if ocr_text.strip():
            return {
                "text": ocr_text,
                "method": "tesseract_pdf",
                "confidence": conf,
                "ocr_used": True,
                "unreadable": False,
            }
        return {
            "text": native,
            "method": "pdftotext_thin",
            "confidence": conf,
            "ocr_used": False,
            "unreadable": len(native.strip()) < 20,
        }
    text, conf = _ocr_tsv(path)
    return {
        "text": text,
        "method": "tesseract",
        "confidence": conf,
        "ocr_used": True,
        "unreadable": not bool(text.strip()),
    }


def low_confidence(read: dict) -> bool:
    conf = read.get("confidence")
    return bool(read.get("ocr_used")) and conf is not None and conf < LOW_CONF
