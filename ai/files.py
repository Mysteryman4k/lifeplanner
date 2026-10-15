"""Text from study material the student attaches: PDF, PowerPoint (.pptx), Word (.docx), text and Markdown.

Everything happens on this PC; only the text goes with a question. Files are read defensively, because a
downloaded file can be built to cause trouble:
- Word and PowerPoint files are zip archives of XML. Their size is checked before anything is unpacked (a
  small zip can expand enormously), and XML with a DOCTYPE is refused (entity tricks).
- PDFs are read with pypdf, page by page, up to a page limit. Password-protected ones are refused.
- A file with no text at all (a scanned PDF is pictures of pages) is reported, not sent empty.

The text comes back in parts (pages, slides, or sections of a Word file) so the student can choose which
parts to send when the whole file is too long.
"""
import io
import re
import time
import zipfile
import zlib
from pathlib import PurePath
from xml.etree import ElementTree

MAX_UPLOAD = 30 * 1024 * 1024       # bytes of file
MAX_UNZIPPED = 80 * 1024 * 1024     # bytes unpacked from a Word or PowerPoint file, in all
MAX_MEMBER = 30 * 1024 * 1024       # bytes unpacked from one part of it
MAX_PARTS = 1000                    # pages or slides read
MAX_TEXT = 2_000_000                # characters kept from one file
SECTION = 4000                      # characters per part of a Word or text file
PDF_SECONDS = 60                    # reading a PDF's pages stops after this long
KINDS = {".pdf": "PDF", ".pptx": "PowerPoint", ".docx": "Word", ".txt": "Text", ".md": "Markdown",
         ".markdown": "Markdown"}
OLD = {".doc": "Word 97-2003 (.doc)", ".ppt": "PowerPoint 97-2003 (.ppt)", ".rtf": "Rich Text (.rtf)",
       ".odt": "OpenDocument (.odt)", ".pages": "Pages", ".key": "Keynote"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class FileError(Exception):
    """A problem with the file, in words for the student."""


def extract(name: str, data: bytes) -> dict:
    """{"name", "kind", "parts": [{"label", "text"}], "chars", "words"} for an attached file."""
    ext = PurePath(name).suffix.lower()
    if len(data) > MAX_UPLOAD:
        raise FileError("That file is over 30 MB. Attach a smaller file, or just the part you need.")
    if ext in OLD:
        raise FileError(f"{OLD[ext]} files can't be read. Save it as PDF, .docx or .pptx and attach that.")
    if ext not in KINDS:
        raise FileError("Attach a PDF, PowerPoint (.pptx), Word (.docx), text or Markdown file.")
    if not data:
        raise FileError("That file is empty.")
    if ext == ".pdf":
        parts = _pdf(data)
    elif ext == ".pptx":
        parts = _pptx(data)
    elif ext == ".docx":
        parts = _sections(_docx(data), "Section")
    else:
        parts = _sections(_decode(data), "Section")
    parts = [p for p in parts if p["text"].strip()]
    if not parts:
        raise FileError("There's no text in that file to read. If it's scanned pages (pictures), EasyUniTrack "
                        "can't read them yet: copy the text in, or use a version with real text.")
    total, kept = 0, []
    for p in parts:
        if total >= MAX_TEXT:
            break
        p = {**p, "text": p["text"][:MAX_TEXT - total]}
        total += len(p["text"])
        kept.append(p)
    text = " ".join(p["text"] for p in kept)
    return {"name": PurePath(name).name[:200], "kind": KINDS[ext], "parts": kept, "chars": total,
            "words": len(text.split())}


# ── PDF ──
def _pdf(data: bytes) -> list:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:                                  # pragma: no cover - part of the app's requirements
        raise FileError("PDF reading isn't available in this copy of EasyUniTrack.") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")              # "" opens files that only restrict printing or copying
            except Exception:                            # some protection needs a library the app doesn't include
                opened = 0
            if not opened:
                raise FileError("That PDF is password-protected or locked, so its text can't be read. If it's your "
                                "own file, save a copy without the protection and attach that.")
        parts, deadline = [], time.monotonic() + PDF_SECONDS
        for i, page in enumerate(reader.pages):
            if i >= MAX_PARTS:
                break
            if time.monotonic() > deadline:              # a huge or oddly built PDF: stop, and say what to do instead
                raise FileError(f"That PDF is taking too long to read (it got to page {i}). Save the pages you need "
                                "as a smaller PDF and attach that.")
            try:
                text = page.extract_text() or ""
            except Exception:                            # one damaged page doesn't stop the rest
                text = ""
            parts.append({"label": f"Page {i + 1}", "text": _tidy(text)})
        return parts
    except FileError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as e:
        raise FileError(f"That PDF couldn't be read ({type(e).__name__}). It may be damaged.") from None


# ── Word and PowerPoint (zip archives of XML) ──
def _zip(data: bytes) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise FileError("That file couldn't be opened. It may be damaged, or not really that kind of file.") from None
    total = 0
    for info in z.infolist():                           # checked before anything is unpacked
        if info.file_size > MAX_MEMBER:
            raise FileError("That file has a part that's far too big to read safely.")
        total += info.file_size
    if total > MAX_UNZIPPED:
        raise FileError("That file unpacks to far too much to read safely.")
    return z


def _xml(z: zipfile.ZipFile, member: str):
    try:
        raw = z.read(member)
    except KeyError:
        return None
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, ValueError):
        # a wrong checksum, an unsupported or encrypted part: damaged as far as the student can tell
        raise FileError("Part of that file is damaged, so it couldn't be read.") from None
    # Office writes UTF-8. Anything else (UTF-16 has zero bytes) could hide a DOCTYPE from the check below
    upper = raw.upper()
    if b"\x00" in raw[:512] or b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise FileError("That file contains XML EasyUniTrack won't read, for safety.")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise FileError("Part of that file is damaged, so it couldn't be read.") from None


def _paragraphs(root, para_tag: str, text_tag: str) -> list:
    out = []
    for p in root.iter(para_tag):
        line = "".join(t.text or "" for t in p.iter(text_tag)).strip()
        if line:
            out.append(line)
    return out


def _docx(data: bytes) -> str:
    z = _zip(data)
    root = _xml(z, "word/document.xml")
    if root is None:
        raise FileError("That doesn't look like a Word (.docx) file.")
    lines = []
    for p in root.iter(f"{W}p"):
        line = ""
        for node in p.iter():
            if node.tag == f"{W}t":
                line += node.text or ""
            elif node.tag == f"{W}tab":
                line += "\t"
            elif node.tag in (f"{W}br", f"{W}cr"):
                line += "\n"
        if line.strip():
            lines.append(line.strip())
    return "\n".join(lines)


def _pptx(data: bytes) -> list:
    z = _zip(data)
    names = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    if not names:
        raise FileError("That doesn't look like a PowerPoint (.pptx) file.")
    order = sorted(names, key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    parts = []
    for i, member in enumerate(order[:MAX_PARTS]):
        root = _xml(z, member)
        lines = _paragraphs(root, f"{A}p", f"{A}t") if root is not None else []
        notes = _slide_notes(z, member)
        text = "\n".join(lines) + (f"\nSpeaker notes: {notes}" if notes else "")
        parts.append({"label": f"Slide {i + 1}", "text": _tidy(text)})
    return parts


def _slide_notes(z: zipfile.ZipFile, slide: str) -> str:
    """The speaker notes linked to a slide (through its relationships file), if any."""
    rels = _xml(z, slide.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels")
    if rels is None:
        return ""
    for rel in rels.iter(f"{REL}Relationship"):
        if rel.get("Type", "").endswith("/notesSlide"):
            target = rel.get("Target", "")              # "../notesSlides/notesSlide1.xml", or from the package root
            member = "ppt/" + target[3:] if target.startswith("../") else target.lstrip("/")
            root = _xml(z, member)
            if root is not None:
                lines = [ln for ln in _paragraphs(root, f"{A}p", f"{A}t") if not ln.isdigit()]   # not the slide number
                return " ".join(lines)
    return ""


# ── text ──
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _sections(text: str, label: str) -> list:
    """Text without pages, in parts of about SECTION characters, split between paragraphs."""
    text = _tidy(text)
    parts, current = [], ""
    for para in text.split("\n"):
        if current and len(current) + len(para) > SECTION:
            parts.append(current)
            current = ""
        current += ("\n" if current else "") + para
    if current:
        parts.append(current)
    return [{"label": f"{label} {i + 1}", "text": p} for i, p in enumerate(parts[:MAX_PARTS])]


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def readers() -> dict:
    """Which readers this copy of the app has: the packaged app's smoke test checks PDF reading made it in."""
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return {"pdf": False}
    return {"pdf": True}


CLOUD_CHARS = 150_000              # characters of a file sent with one question to a cloud provider
LOCAL_CHARS = 90_000               # ... to Ollama, when its context allows
LOCAL_SLOW = 30_000                # over this, say a local model will take a while
CHARS_PER_TOKEN = 3.2              # English prose is about 3.7; maths and code use more tokens
RESERVE_TOKENS = 8000              # the instructions, recent messages and the reply


def budget(provider: str, context: int = None) -> dict:
    """How much attached text goes with one question (it's sent again with each one). Cloud providers bill
    for it every time. Ollama reads only as much as its context length allows (see OllamaProvider.context_length),
    and reads slowly: about 8 minutes for 80,000 characters on a PC without a graphics card."""
    if provider != "ollama":
        return {"chars": CLOUD_CHARS, "slow_over": None, "context": None}
    chars = LOCAL_CHARS
    if context:
        reserve = min(RESERVE_TOKENS, context // 2)
        chars = min(chars, int((context - reserve) * CHARS_PER_TOKEN))
    return {"chars": chars, "slow_over": LOCAL_SLOW, "context": context}
