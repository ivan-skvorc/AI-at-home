"""Tests for deerflow.config.yaml_guard — duplicate-key-detecting YAML loading.

Motivation: a user's config.yaml ended up with two top-level ``sandbox:`` keys;
PyYAML's last-key-wins silently reverted them to LocalSandboxProvider. The guard
turns that silent misconfiguration into a loud, precise error.
"""

from __future__ import annotations

import io
import textwrap

import pytest
import yaml

from deerflow.config.yaml_guard import DuplicateKeyError, safe_load_guarded

# ---------------------------------------------------------------------------
# Clean documents load exactly like yaml.safe_load
# ---------------------------------------------------------------------------


class TestCleanDocuments:
    def test_clean_mapping_loads_normally(self):
        text = textwrap.dedent(
            """\
            config_version: 3
            sandbox:
              use: deerflow.sandbox.local:LocalSandboxProvider
            models:
              - name: gpt
                model: gpt-4o
            """
        )
        assert safe_load_guarded(text) == yaml.safe_load(text)

    def test_empty_document_returns_none(self):
        assert safe_load_guarded("") is None

    def test_scalar_document(self):
        assert safe_load_guarded("42") == 42

    def test_accepts_stream(self):
        stream = io.StringIO("a: 1\nb: 2\n")
        assert safe_load_guarded(stream) == {"a": 1, "b": 2}

    def test_anchors_and_aliases_do_not_false_positive(self):
        text = textwrap.dedent(
            """\
            defaults: &defaults
              temperature: 0.7
            other: *defaults
            """
        )
        data = safe_load_guarded(text)
        assert data["other"] == {"temperature": 0.7}


# ---------------------------------------------------------------------------
# Merge keys (<<:) keep working and never false-positive
# ---------------------------------------------------------------------------


class TestMergeKeys:
    def test_merge_key_with_anchor_loads(self):
        text = textwrap.dedent(
            """\
            base: &base
              a: 1
              b: 2
            child:
              <<: *base
              c: 3
            """
        )
        data = safe_load_guarded(text)
        assert data["child"] == {"a": 1, "b": 2, "c": 3}

    def test_merge_key_override_does_not_false_positive(self):
        """Overriding a merged-in key is the whole point of <<: — not a duplicate."""
        text = textwrap.dedent(
            """\
            base: &base
              a: 1
              b: 2
            child:
              <<: *base
              a: 10
            """
        )
        data = safe_load_guarded(text)
        assert data["child"] == {"a": 10, "b": 2}

    def test_multiple_merge_keys_do_not_false_positive(self):
        text = textwrap.dedent(
            """\
            one: &one
              a: 1
            two: &two
              b: 2
            child:
              <<: *one
              <<: *two
            """
        )
        data = safe_load_guarded(text)
        assert data["child"] == {"a": 1, "b": 2}

    def test_duplicate_explicit_key_next_to_merge_key_still_raises(self):
        text = textwrap.dedent(
            """\
            base: &base
              a: 1
            child:
              <<: *base
              c: 3
              c: 4
            """
        )
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded(text)
        assert excinfo.value.key == "c"


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_top_level_duplicate_raises(self):
        text = textwrap.dedent(
            """\
            sandbox:
              use: deerflow.community.aio_sandbox:AioSandboxProvider
            models: []
            sandbox:
              use: deerflow.sandbox.local:LocalSandboxProvider
            """
        )
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded(text, source="config.yaml")
        err = excinfo.value
        assert err.key == "sandbox"
        assert err.first_line == 1
        assert err.duplicate_line == 4
        assert err.source == "config.yaml"
        assert str(err) == "duplicate top-level key 'sandbox' in config.yaml: first defined at line 1, duplicated at line 4"

    def test_top_level_duplicate_exact_line_numbers(self):
        lines = ["a: 1", "b: 2", "c: 3", "b: 4"]
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded("\n".join(lines) + "\n")
        err = excinfo.value
        assert (err.key, err.first_line, err.duplicate_line) == ("b", 2, 4)

    def test_message_without_source(self):
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded("a: 1\na: 2\n")
        assert str(excinfo.value) == "duplicate top-level key 'a': first defined at line 1, duplicated at line 2"

    def test_nested_duplicate_raises_with_plain_key_wording(self):
        text = textwrap.dedent(
            """\
            sandbox:
              use: provider-a
              image: img
              use: provider-b
            """
        )
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded(text, source="config.yaml")
        err = excinfo.value
        assert err.key == "use"
        assert err.first_line == 2
        assert err.duplicate_line == 4
        assert str(err) == "duplicate key 'use' in config.yaml: first defined at line 2, duplicated at line 4"

    def test_duplicate_inside_list_entry_raises(self):
        text = textwrap.dedent(
            """\
            models:
              - name: one
                model: gpt-4o
                name: two
            """
        )
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded(text)
        err = excinfo.value
        assert err.key == "name"
        assert err.first_line == 2
        assert err.duplicate_line == 4

    def test_deeply_nested_duplicate_raises(self):
        text = textwrap.dedent(
            """\
            a:
              b:
                c:
                  x: 1
                  x: 2
            """
        )
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded(text)
        assert excinfo.value.key == "x"

    def test_same_key_in_sibling_mappings_is_fine(self):
        text = textwrap.dedent(
            """\
            one:
              use: a
            two:
              use: b
            """
        )
        assert safe_load_guarded(text) == {"one": {"use": "a"}, "two": {"use": "b"}}

    def test_source_defaults_to_stream_name(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("a: 1\na: 2\n", encoding="utf-8")
        with open(path, encoding="utf-8") as f, pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded(f)
        assert excinfo.value.source == str(path)

    def test_is_a_yaml_error(self):
        with pytest.raises(yaml.YAMLError):
            safe_load_guarded("a: 1\na: 2\n")

    def test_non_string_duplicate_key(self):
        with pytest.raises(DuplicateKeyError) as excinfo:
            safe_load_guarded("1: a\n1: b\n")
        assert excinfo.value.key == 1
