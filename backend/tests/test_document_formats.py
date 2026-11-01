"""Tests for ``deerflow.documents.formats`` (fork feature, roadmap item 33).

A book rarely arrives as a PDF. Project Gutenberg ships HTML, EPUB, plain text
and zips of those, and none of them is converted on upload — so before this
module the agent saw a file name and a byte count, and ``analyze_document`` read
an HTML book as raw markup and a zip as compressed bytes.

The properties under test:
- a size estimate comes from the file size or the archive listing, and never
  decompresses anything;
- an archive is bounded before any member is opened — member count, total
  uncompressed size, nested archives, encrypted members and paths that leave
  the archive are refusals with a reason the agent can pass on;
- HTML and EPUB are read as Markdown, and a zip's documents are read in order
  and named, with everything else skipped rather than guessed at.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from deerflow.documents import formats
from deerflow.documents.formats import UnreadableDocument, estimate_extent, read_container_text, survey_archive


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _epub(path: Path, chapters: list[tuple[str, str]]) -> Path:
    container = '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(len(chapters)))
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">'
        f"<metadata><dc:title>Cookery</dc:title></metadata><manifest>{items}</manifest><spine>{spine}</spine></package>"
    )
    members = {"mimetype": b"application/epub+zip", "META-INF/container.xml": container.encode(), "OEBPS/content.opf": opf.encode()}
    for i, (title, body) in enumerate(chapters):
        members[f"OEBPS/c{i}.xhtml"] = f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>{title}</h1><p>{body}</p></body></html>'.encode()
    return _zip(path, members)


class TestArchiveSurvey:
    def test_a_book_zip_lists_its_documents_and_skips_everything_else(self, tmp_path: Path):
        survey = survey_archive(_zip(tmp_path / "book.zip", {"book.html": b"<p>soup</p>" * 100, "images/cover.jpg": b"\xff\xd8" * 50}))
        assert survey.refusal is None
        assert survey.documents == (("book.html", 1100),)
        assert survey.skipped == 1

    @pytest.mark.parametrize(
        ("members", "reason"),
        [
            ({"book.html": b"<p>x</p>", "extra.zip": b"PK\x05\x06" + b"\0" * 18}, "another archive"),
            ({"../escape.txt": b"x"}, "outside the archive"),
            ({"/etc/escape.txt": b"x"}, "outside the archive"),
            ({"images/cover.jpg": b"\xff\xd8"}, "no text or HTML documents"),
        ],
    )
    def test_an_unsafe_or_empty_archive_is_refused_with_a_reason(self, tmp_path: Path, members, reason):
        assert reason in survey_archive(_zip(tmp_path / "x.zip", members)).refusal

    def test_an_encrypted_member_is_refused(self, tmp_path: Path):
        # zipfile cannot write an encrypted member, so set bit 0 of the
        # general-purpose flag in the central directory, which is what a reader
        # sees before opening anything.
        data = bytearray(_zip(tmp_path / "locked.zip", {"secret.txt": b"x"}).read_bytes())
        flag = data.index(b"PK\x01\x02") + 8
        data[flag] |= 0x1
        (tmp_path / "locked.zip").write_bytes(bytes(data))
        assert "encrypted" in survey_archive(tmp_path / "locked.zip").refusal

    def test_the_bounds_come_from_the_listing_without_decompressing(self, tmp_path: Path, monkeypatch):
        path = _zip(tmp_path / "big.zip", {"a.txt": b"a" * 5_000, "b.txt": b"b" * 5_000})

        def decompressed(*args, **kwargs):
            raise AssertionError("a member was opened while surveying")

        monkeypatch.setattr(zipfile.ZipFile, "open", decompressed)
        monkeypatch.setattr(formats, "MAX_ARCHIVE_UNCOMPRESSED", 6_000)
        assert "unpacks to" in survey_archive(path).refusal
        monkeypatch.setattr(formats, "MAX_ARCHIVE_UNCOMPRESSED", 64 * 1024 * 1024)
        monkeypatch.setattr(formats, "MAX_ARCHIVE_MEMBERS", 1)
        assert "holds 2 files" in survey_archive(path).refusal

    def test_a_file_that_is_not_a_zip_is_refused_rather_than_raised(self, tmp_path: Path):
        (tmp_path / "fake.zip").write_bytes(b"not a zip at all")
        assert "not a readable zip" in survey_archive(tmp_path / "fake.zip").refusal


class TestReadingContainers:
    def test_html_is_read_as_markdown_not_markup(self, tmp_path: Path):
        path = tmp_path / "book.html"
        path.write_text("<html><body><h1>Sauces</h1><p>Melt the <b>butter</b>.</p></body></html>", encoding="utf-8")
        text, origin = read_container_text(path)
        assert "# Sauces" in text and "**butter**" in text
        assert "<p>" not in text
        assert origin == "HTML converted to Markdown"

    def test_an_epub_is_read_through_its_chapters_in_spine_order(self, tmp_path: Path):
        text, origin = read_container_text(_epub(tmp_path / "book.epub", [("Sauces", "Roux first."), ("Soups", "Stock next.")]))
        assert text.index("Sauces") < text.index("Soups")
        assert "Roux first." in text and "<p>" not in text
        assert origin == "EPUB converted to Markdown"

    def test_a_zip_reads_its_documents_in_order_and_names_them(self, tmp_path: Path):
        path = _zip(tmp_path / "book.zip", {"part1.html": b"<h1>Eggs</h1><p>Boil.</p>", "cover.jpg": b"\xff\xd8", "part2.txt": b"Fish: poach gently."})
        text, origin = read_container_text(path)
        assert text.index("## File: part1.html") < text.index("# Eggs") < text.index("## File: part2.txt") < text.index("poach gently")
        assert "<p>" not in text
        assert origin == "2 documents inside the archive (part1.html, part2.txt); 1 other file not read"

    def test_a_refused_archive_raises_its_reason_before_reading(self, tmp_path: Path, monkeypatch):
        path = _zip(tmp_path / "nested.zip", {"book.html": b"<p>x</p>", "inner.epub": b"PK"})
        monkeypatch.setattr(zipfile.ZipFile, "read", lambda *a, **k: pytest.fail("a member was read from a refused archive"))
        with pytest.raises(UnreadableDocument, match="another archive"):
            read_container_text(path)

    def test_an_unsafe_epub_is_refused_like_a_zip(self, tmp_path: Path, monkeypatch):
        path = _epub(tmp_path / "book.epub", [("Sauces", "Roux.")])
        monkeypatch.setattr(formats, "MAX_ARCHIVE_UNCOMPRESSED", 10)
        with pytest.raises(UnreadableDocument, match="unpacks to"):
            read_container_text(path)


class TestExtentEstimate:
    def test_a_text_file_is_estimated_from_its_size(self, tmp_path: Path):
        path = tmp_path / "book.txt"
        path.write_text("word " * 50_000, encoding="utf-8")
        estimate = estimate_extent(path)
        assert estimate.chars == 250_000
        assert estimate.describe() == "up to 250,000 characters (~62,500 tokens), estimated from the file size"

    def test_an_html_file_is_estimated_from_its_size_markup_included(self, tmp_path: Path):
        # read_file returns the raw markup, so the byte count is what a linear read costs.
        path = tmp_path / "book.html"
        path.write_bytes(b"<p>soup</p>" * 1_000)
        assert estimate_extent(path).chars == 11_000

    def test_a_zip_counts_its_documents_only(self, tmp_path: Path):
        path = _zip(tmp_path / "book.zip", {"book.html": b"x" * 4_000, "cover.jpg": b"y" * 90_000})
        estimate = estimate_extent(path)
        assert estimate.chars == 4_000
        assert estimate.describe().endswith("estimated from the archive listing")

    def test_a_refused_archive_carries_its_reason_and_no_size(self, tmp_path: Path):
        estimate = estimate_extent(_zip(tmp_path / "x.zip", {"inner.zip": b"PK"}))
        assert estimate.chars == 0
        assert "another archive" in estimate.archive.refusal

    @pytest.mark.parametrize("name", ["photo.png", "report.pdf", "deck.pptx", "noext"])
    def test_files_it_cannot_size_get_no_estimate(self, tmp_path: Path, name):
        (tmp_path / name).write_bytes(b"\x00\x01" * 100)
        assert estimate_extent(tmp_path / name) is None
