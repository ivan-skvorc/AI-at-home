"""Books that do not arrive as PDFs: HTML, EPUB, plain text and zips of those.

Fork feature (roadmap item 33). Upload conversion covers PDF and Office files
only, and it is off by default (``uploads.auto_convert_documents``) because it
runs third-party parsers on the host before sandbox isolation applies. So an
HTML, EPUB, text or zipped book reached the agent as a name and a byte count:
no outline, no extent, no routing to ``analyze_document``. And
``analyze_document`` read whatever it did not convert as plain text — an HTML
book as raw markup, a zip as compressed bytes.

Two jobs, kept apart:

* :func:`estimate_extent` tells the uploads prompt how big a file is **without
  parsing it**: the byte count for text-like files (an upper bound on their
  characters, and exactly what ``read_file`` would return for HTML, markup
  included), and the declared sizes in the central directory for EPUB and zip.
* :func:`read_container_text` is what ``analyze_document`` calls when the agent
  explicitly asks to read one of these files: HTML and EPUB become Markdown, and
  a zip's text and HTML members are read in order and named.

**Archives are bounded from their listing before any member is opened.**
MarkItDown's ``ZipConverter`` ``read()``s every member into memory and recurses
into nested archives, and its ``EpubConverter`` streams every chapter, with no
bound on count, size or depth — fine for a trusted file, a decompression bomb
for an untrusted upload. ``zipfile`` stops a member at the size its central
directory declares (a member that inflates past it fails its CRC check rather
than growing), so checking the declared sizes first bounds what reading can
cost. A zip is never handed to ``ZipConverter``.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from deerflow.utils.context_budget import CHARS_PER_TOKEN

# Bounds on what one archive may hold. A Gutenberg zip is a handful of files
# and a few megabytes; these leave room for an EPUB with hundreds of chapters
# and images while refusing anything that unpacks past what a 50 MiB upload
# could legitimately hold.
MAX_ARCHIVE_MEMBERS = 1_000
MAX_ARCHIVE_UNCOMPRESSED = 64 * 1024 * 1024

# Files whose bytes are their text: the size is an upper bound on what a
# linear read pulls into context.
TEXT_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".log", ".yaml", ".yml"})
# HTML is text to ``read_file`` (markup and all) but Markdown to
# ``analyze_document``, which strips the markup before splitting.
MARKUP_SUFFIXES = frozenset({".html", ".htm", ".xhtml"})
ARCHIVE_SUFFIXES = frozenset({".zip", ".epub"})
# What ``analyze_document`` reads through this module rather than as plain text.
CONTAINER_SUFFIXES = MARKUP_SUFFIXES | ARCHIVE_SUFFIXES
# Zip members that are read; everything else (images, fonts, PDFs) is skipped
# and counted, never guessed at.
_ARCHIVE_DOCUMENT_SUFFIXES = TEXT_SUFFIXES | MARKUP_SUFFIXES
# A member with one of these suffixes is an archive inside the archive.
_NESTED_ARCHIVE_SUFFIXES = frozenset({".zip", ".epub", ".jar", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst"})
_LISTED_DOCUMENTS = 5


class UnreadableDocument(Exception):
    """A file the reader refuses to open; the message is fit to show the agent."""


def _human_size(size: int) -> str:
    kb = size / 1024
    return f"{kb:.1f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


@dataclass(frozen=True)
class ArchiveSurvey:
    """What an archive's central directory says it holds, decided before opening it."""

    documents: tuple[tuple[str, int], ...] = ()
    skipped: int = 0
    refusal: str | None = None

    @property
    def document_chars(self) -> int:
        """Declared uncompressed bytes of the readable members: an upper bound on their text."""
        return sum(size for _, size in self.documents)

    def _names(self) -> str:
        shown = ", ".join(name for name, _ in self.documents[:_LISTED_DOCUMENTS])
        hidden = len(self.documents) - _LISTED_DOCUMENTS
        return f"{shown}, and {_plural(hidden, 'more document')}" if hidden > 0 else shown

    def describe_contents(self) -> str:
        """One line naming the documents the agent can ask for, and what is skipped."""
        listed = ", ".join(f"{name} ({_human_size(size)})" for name, size in self.documents[:_LISTED_DOCUMENTS])
        hidden = len(self.documents) - _LISTED_DOCUMENTS
        if hidden > 0:
            listed += f", and {_plural(hidden, 'more document')}"
        return f"{listed}; {_plural(self.skipped, 'other file')} not read" if self.skipped else listed

    def describe_origin(self) -> str:
        origin = f"{_plural(len(self.documents), 'document')} inside the archive ({self._names()})"
        return f"{origin}; {_plural(self.skipped, 'other file')} not read" if self.skipped else origin


def survey_archive(path: Path) -> ArchiveSurvey:
    """Bound an archive from its central directory, without decompressing a member."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError):
        return ArchiveSurvey(refusal="it is not a readable zip archive")
    files = [info for info in infos if not info.is_dir()]
    if len(files) > MAX_ARCHIVE_MEMBERS:
        return ArchiveSurvey(refusal=f"it holds {len(files):,} files; the limit is {MAX_ARCHIVE_MEMBERS:,}")
    total = sum(info.file_size for info in files)
    if total > MAX_ARCHIVE_UNCOMPRESSED:
        return ArchiveSurvey(refusal=f"it unpacks to {_human_size(total)}; the limit is {_human_size(MAX_ARCHIVE_UNCOMPRESSED)}")
    for info in files:
        name = PurePosixPath(info.filename)
        if info.flag_bits & 0x1:
            return ArchiveSurvey(refusal=f"it contains encrypted files ({info.filename})")
        if name.is_absolute() or ".." in name.parts:
            return ArchiveSurvey(refusal=f"a file inside it points outside the archive ({info.filename})")
        if name.suffix.lower() in _NESTED_ARCHIVE_SUFFIXES:
            return ArchiveSurvey(refusal=f"it contains another archive ({info.filename}); nested archives are not opened")
    documents = tuple((info.filename, info.file_size) for info in files if PurePosixPath(info.filename).suffix.lower() in _ARCHIVE_DOCUMENT_SUFFIXES)
    skipped = len(files) - len(documents)
    if not documents:
        return ArchiveSurvey(skipped=skipped, refusal=f"it holds no text or HTML documents ({_plural(skipped, 'other file')})")
    return ArchiveSurvey(documents=documents, skipped=skipped)


@dataclass(frozen=True)
class ExtentEstimate:
    """An upper bound on what reading a file end to end pulls into context."""

    chars: int
    basis: str
    archive: ArchiveSurvey | None = None

    def describe(self) -> str:
        return f"up to {self.chars:,} characters (~{self.chars // CHARS_PER_TOKEN:,} tokens), estimated from the {self.basis}"


def estimate_extent(path: Path) -> ExtentEstimate | None:
    """Size a text-like, HTML, EPUB or zip file without parsing it; ``None`` for anything else."""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES or suffix in MARKUP_SUFFIXES:
        try:
            return ExtentEstimate(chars=path.stat().st_size, basis="file size")
        except OSError:
            return None
    if suffix in ARCHIVE_SUFFIXES:
        survey = survey_archive(path)
        return ExtentEstimate(chars=0 if survey.refusal else survey.document_chars, basis="archive listing", archive=survey)
    return None


def _markitdown(path: Path) -> str:
    from markitdown import MarkItDown

    return MarkItDown().convert(str(path)).text_content


def read_container_text(path: Path) -> tuple[str, str]:
    """Return Markdown for an HTML file, an EPUB or a zip's documents, and where it came from.

    Raises :class:`UnreadableDocument` for an archive that fails its bounds;
    nothing inside it has been decompressed by then.
    """
    suffix = path.suffix.lower()
    if suffix in MARKUP_SUFFIXES:
        return _markitdown(path), "HTML converted to Markdown"
    if suffix not in ARCHIVE_SUFFIXES:
        raise ValueError(f"not a container format: {suffix}")
    survey = survey_archive(path)
    if survey.refusal:
        raise UnreadableDocument(survey.refusal)
    if suffix == ".epub":
        return _markitdown(path), "EPUB converted to Markdown"

    from markitdown.converters import HtmlConverter

    converter = HtmlConverter()
    sections: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name, _ in survey.documents:
            text = archive.read(name).decode("utf-8", errors="replace")
            if PurePosixPath(name).suffix.lower() in MARKUP_SUFFIXES:
                text = converter.convert_string(text).markdown
            sections.append(f"## File: {name}\n\n{text.strip()}")
    return "\n\n".join(sections), survey.describe_origin()
