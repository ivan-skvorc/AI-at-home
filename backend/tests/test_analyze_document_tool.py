"""Tests for the `analyze_document` tool (fork feature).

The tool is the seam where a large document meets a small model: it resolves
the file, converts it, notices when the text layer is missing, routes a scan
through OCR, and only then runs the map-reduce pass.

The properties under test:
- containment — the tool reads uploads and nothing else, whatever path it is
  handed;
- a scanned PDF is transcribed rather than summarised into nothing, and a
  missing prerequisite is reported as an actionable message instead of an
  empty answer;
- transcription and summarisation stay separate steps;
- the answer entering the agent's context is bounded, and the full working is
  written to a file.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.documents_config import DocumentsConfig
from deerflow.tools.builtins.analyze_document_tool import _analyze_document_impl, _filename_from

THREAD = "thread-1"


class _Response:
    def __init__(self, content):
        self.content = content


class _Model:
    def __init__(self, reply="a finding", fail=False):
        self.reply = reply
        self.fail = fail
        self.prompts: list = []

    async def ainvoke(self, messages):
        self.prompts.append(messages[0].content)
        if self.fail:
            raise RuntimeError("model failed")
        return _Response(self.reply)


class _Paths:
    def __init__(self, root: Path):
        self.root = root

    def sandbox_uploads_dir(self, thread_id, *, user_id=None):
        path = self.root / thread_id / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sandbox_outputs_dir(self, thread_id, *, user_id=None):
        path = self.root / thread_id / "outputs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sandbox_work_dir(self, thread_id, *, user_id=None):
        path = self.root / thread_id / "workspace"
        path.mkdir(parents=True, exist_ok=True)
        return path


def _app_config(documents: DocumentsConfig | None = None, vision: bool = False):
    models = [SimpleNamespace(name="default-model", supports_vision=False)]
    if vision:
        models.append(SimpleNamespace(name="vision-model", supports_vision=True))
    return SimpleNamespace(documents=documents or DocumentsConfig(), models=models)


def _runtime():
    return SimpleNamespace(context={"thread_id": THREAD}, config={}, state={})


@pytest.fixture
def uploads(tmp_path: Path):
    return _Paths(tmp_path)


class TestPathContainment:
    def test_a_virtual_upload_path_resolves_to_its_filename(self):
        assert _filename_from("/mnt/user-data/uploads/report.pdf") == "report.pdf"

    def test_a_bare_filename_is_accepted(self):
        assert _filename_from("report.pdf") == "report.pdf"

    def test_traversal_is_rejected(self):
        assert _filename_from("../../etc/passwd") is None
        assert _filename_from("/mnt/user-data/uploads/../../etc/passwd") is None

    def test_a_nested_path_is_rejected(self):
        assert _filename_from("sub/dir/report.pdf") is None

    def test_an_absolute_path_outside_uploads_is_rejected(self):
        assert _filename_from("/etc/passwd") is None

    def test_an_empty_path_is_rejected(self):
        assert _filename_from("   ") is None


class TestReadingTheDocument:
    @pytest.mark.anyio
    async def test_a_missing_file_is_reported(self, uploads, monkeypatch):
        out = await _analyze_document_impl("nope.pdf", "q", runtime=_runtime(), _paths=uploads, _app_config=_app_config())
        assert "not in this thread's uploads" in out

    @pytest.mark.anyio
    async def test_a_markdown_companion_is_used_when_present(self, uploads, monkeypatch):
        up = uploads.sandbox_uploads_dir(THREAD)
        (up / "report.pdf").write_bytes(b"%PDF-1.4")
        (up / "report.pdf.md").write_text("# Report\n\n" + ("finding " * 500), encoding="utf-8")
        model = _Model()
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool._model_for", lambda name, cfg: model)
        out = await _analyze_document_impl("report.pdf", "what is here?", runtime=_runtime(), _paths=uploads, _app_config=_app_config())
        assert "a finding" in out
        assert "converted Markdown" in out
        assert model.prompts

    @pytest.mark.anyio
    async def test_the_answer_names_its_source_and_coverage(self, uploads, monkeypatch):
        up = uploads.sandbox_uploads_dir(THREAD)
        (up / "notes.md").write_text("# Notes\n\n" + ("content " * 500), encoding="utf-8")
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool._model_for", lambda name, cfg: _Model())
        out = await _analyze_document_impl("notes.md", "q", runtime=_runtime(), _paths=uploads, _app_config=_app_config())
        assert "— source: notes.md" in out
        assert "read" in out and "parts" in out

    @pytest.mark.anyio
    async def test_the_per_part_notes_are_written_to_outputs(self, uploads, monkeypatch):
        up = uploads.sandbox_uploads_dir(THREAD)
        (up / "notes.md").write_text("# Notes\n\n" + ("content " * 800), encoding="utf-8")
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool._model_for", lambda name, cfg: _Model())
        out = await _analyze_document_impl("notes.md", "q", runtime=_runtime(), _paths=uploads, _app_config=_app_config())
        notes = uploads.sandbox_outputs_dir(THREAD) / "document-analysis" / "notes.md.notes.md"
        assert notes.is_file()
        assert "per-part notes:" in out

    @pytest.mark.anyio
    async def test_the_answer_is_bounded_before_it_enters_context(self, uploads, monkeypatch):
        up = uploads.sandbox_uploads_dir(THREAD)
        (up / "notes.md").write_text("# Notes\n\n" + ("content " * 500), encoding="utf-8")
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool._model_for", lambda name, cfg: _Model(reply="z" * 50_000))
        config = _app_config(DocumentsConfig(answer_max_chars=1_000))
        out = await _analyze_document_impl("notes.md", "q", runtime=_runtime(), _paths=uploads, _app_config=config)
        assert "[answer truncated]" in out
        assert len(out) < 3_000

    @pytest.mark.anyio
    async def test_no_thread_context_is_reported_rather_than_guessed(self, uploads):
        runtime = SimpleNamespace(context={}, config={}, state={})
        out = await _analyze_document_impl("x.pdf", "q", runtime=runtime, _paths=uploads, _app_config=_app_config())
        assert "no thread context" in out


class TestScannedDocuments:
    def _scanned(self, uploads):
        up = uploads.sandbox_uploads_dir(THREAD)
        (up / "scan.pdf").write_bytes(b"%PDF-1.4")
        # A converted scan: page anchors, no text.
        (up / "scan.pdf.md").write_text("\n".join(f"<!-- page: {n} -->" for n in range(1, 41)), encoding="utf-8")
        return up

    @pytest.mark.anyio
    async def test_an_empty_text_layer_routes_through_ocr(self, uploads, monkeypatch):
        self._scanned(uploads)
        transcript = "\n\n".join(f"<!-- page: {n} -->\nTranscribed body text for page {n}. " + ("word " * 100) for n in range(1, 6))

        async def fake_ocr(*args, **kwargs):
            return SimpleNamespace(text=transcript, pages_transcribed=5, pages_failed=0, cache_path=None, complete=True)

        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool.ocr_pdf_to_markdown", fake_ocr)
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool._model_for", lambda name, cfg: _Model())
        out = await _analyze_document_impl("scan.pdf", "q", runtime=_runtime(), _paths=uploads, _app_config=_app_config(vision=True))
        assert "text layer was empty" in out
        assert "5 page(s) were transcribed" in out
        assert "OCR transcript" in out

    @pytest.mark.anyio
    async def test_summarising_happens_after_transcription_not_during_it(self, uploads, monkeypatch):
        # The vision pass must not be asked for an answer: it transcribes, and a
        # separate map-reduce pass over the transcript does the analysis.
        self._scanned(uploads)
        transcript = "\n\n".join(f"<!-- page: {n} -->\n" + ("word " * 300) for n in range(1, 4))

        async def fake_ocr(source, model, **kwargs):
            return SimpleNamespace(text=transcript, pages_transcribed=3, pages_failed=0, cache_path=None, complete=True)

        analysis_model = _Model()
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool.ocr_pdf_to_markdown", fake_ocr)
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool._model_for", lambda name, cfg: analysis_model)
        await _analyze_document_impl("scan.pdf", "what is the total?", runtime=_runtime(), _paths=uploads, _app_config=_app_config(vision=True))
        assert analysis_model.prompts, "the transcript was never analysed"
        assert any("what is the total?" in prompt for prompt in analysis_model.prompts)

    @pytest.mark.anyio
    async def test_no_vision_model_is_an_actionable_message(self, uploads, monkeypatch):
        self._scanned(uploads)
        out = await _analyze_document_impl("scan.pdf", "q", runtime=_runtime(), _paths=uploads, _app_config=_app_config(vision=False))
        assert "supports_vision" in out
        assert "image-based" in out

    @pytest.mark.anyio
    async def test_ocr_disabled_says_so(self, uploads, monkeypatch):
        self._scanned(uploads)
        config = _app_config(DocumentsConfig(ocr={"enabled": False}), vision=True)
        out = await _analyze_document_impl("scan.pdf", "q", runtime=_runtime(), _paths=uploads, _app_config=config)
        assert "documents.ocr.enabled" in out

    @pytest.mark.anyio
    async def test_a_failed_transcription_reports_rather_than_answering(self, uploads, monkeypatch):
        self._scanned(uploads)

        async def fake_ocr(*args, **kwargs):
            return SimpleNamespace(text="", pages_transcribed=0, pages_failed=3, cache_path=None, complete=False)

        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool.ocr_pdf_to_markdown", fake_ocr)
        out = await _analyze_document_impl("scan.pdf", "q", runtime=_runtime(), _paths=uploads, _app_config=_app_config(vision=True))
        assert "image-based" in out

    @pytest.mark.anyio
    async def test_max_pages_is_capped_by_the_configured_limit(self, uploads, monkeypatch):
        self._scanned(uploads)
        seen: dict[str, object] = {}

        async def fake_ocr(source, model, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(text="<!-- page: 1 -->\n" + ("w " * 200), pages_transcribed=1, pages_failed=0, cache_path=None, complete=True)

        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool.ocr_pdf_to_markdown", fake_ocr)
        monkeypatch.setattr("deerflow.tools.builtins.analyze_document_tool._model_for", lambda name, cfg: _Model())
        config = _app_config(DocumentsConfig(ocr={"max_pages": 10}), vision=True)
        await _analyze_document_impl("scan.pdf", "q", max_pages=500, runtime=_runtime(), _paths=uploads, _app_config=config)
        assert seen["max_pages"] == 10
