"""Duplicate-key-detecting YAML loading.

PyYAML's ``safe_load`` silently applies last-key-wins when a mapping declares
the same key twice. For ``config.yaml`` this turns user mistakes (for example
a second top-level ``sandbox:`` block appended by hand or by a template
regeneration) into silent misconfigurations — the first block is simply
discarded. This module provides :func:`safe_load_guarded`, a drop-in
replacement that raises :class:`DuplicateKeyError` instead, carrying the key
name, both 1-based line numbers, and the source file name.

YAML merge keys (``<<:``) keep their standard semantics: merging an anchor and
then overriding one of its keys is *not* a duplicate.

IMPORTANT: this module must stay importable with only PyYAML and the standard
library (no pydantic, no other ``deerflow`` imports). Root orchestration
scripts (``scripts/config_upgrade.py``, ``scripts/sync-ollama-models.py``)
load this exact file via ``importlib.util.spec_from_file_location`` so that
one implementation is shared without executing ``deerflow.config.__init__``.
"""

from __future__ import annotations

from typing import IO, Any

import yaml

_MERGE_TAG = "tag:yaml.org,2002:merge"


class DuplicateKeyError(yaml.YAMLError):
    """A YAML mapping declared the same key twice.

    Attributes:
        key: The duplicated key (usually a string).
        first_line: 1-based line number of the first occurrence.
        duplicate_line: 1-based line number of the duplicate occurrence.
        source: File name or label of the YAML source, if known.
        top_level: True when the duplicate is in the document's root mapping.
    """

    def __init__(
        self,
        key: Any,
        first_line: int,
        duplicate_line: int,
        *,
        source: str | None = None,
        top_level: bool = False,
    ) -> None:
        self.key = key
        self.first_line = first_line
        self.duplicate_line = duplicate_line
        self.source = source
        self.top_level = top_level
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        scope = "top-level key" if self.top_level else "key"
        location = f" in {self.source}" if self.source else ""
        return f"duplicate {scope} '{self.key}'{location}: first defined at line {self.first_line}, duplicated at line {self.duplicate_line}"


class GuardedSafeLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that raises :class:`DuplicateKeyError` on duplicate keys.

    Duplicates are detected at every mapping level. The scan runs over the
    *explicit* key nodes of each mapping (merge keys ``<<:`` excluded) before
    PyYAML flattens merges, so ``<<:`` anchors — including overriding a
    merged-in key — never false-positive.
    """

    guard_source: str | None = None
    _root_node: yaml.Node | None = None

    def get_single_data(self) -> Any:
        node = self.get_single_node()
        self._root_node = node
        if node is not None:
            return self.construct_document(node)
        return None

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict:
        if isinstance(node, yaml.MappingNode):
            self._check_duplicate_keys(node)
        # SafeConstructor.construct_mapping flattens merge keys itself.
        return super().construct_mapping(node, deep=deep)

    def _check_duplicate_keys(self, node: yaml.MappingNode) -> None:
        seen: dict[Any, int] = {}
        for key_node, _value_node in node.value:
            if key_node.tag == _MERGE_TAG:
                continue
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError:
                # Unhashable key — let the parent constructor raise its usual error.
                continue
            line = key_node.start_mark.line + 1
            if key in seen:
                raise DuplicateKeyError(
                    key,
                    seen[key],
                    line,
                    source=self.guard_source,
                    top_level=node is self._root_node,
                )
            seen[key] = line


def safe_load_guarded(stream: str | bytes | IO, source: str | None = None) -> Any:
    """Parse a single YAML document, raising :class:`DuplicateKeyError` on duplicate keys.

    Drop-in replacement for ``yaml.safe_load``.

    Args:
        stream: YAML text or an open stream (same as ``yaml.safe_load``).
        source: Label used in error messages (e.g. the file path). Defaults to
            the stream's ``name`` attribute when reading from a file object.

    Returns:
        The parsed document, exactly as ``yaml.safe_load`` would return it.
    """
    if source is None:
        name = getattr(stream, "name", None)
        source = str(name) if name else None
    loader = GuardedSafeLoader(stream)
    loader.guard_source = source
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
