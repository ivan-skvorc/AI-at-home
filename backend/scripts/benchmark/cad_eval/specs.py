"""The eval's fixed requests, read from ``specs/<id>/``.

Each spec directory holds ``spec.json`` (the request a user would type, its band
and the ground truth) and, for every part the allow-list can express,
``reference.py``: a script in the dialect ``cad_build`` reads, from which the
truth was derived (``derive_truth.py``). The truth never reaches the model.

Stdlib only: the CAD package's own test (``test_eval_specs.py``) loads this file
by path in an environment without DeerFlow.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SPECS_DIR = Path(__file__).with_name("specs")

#: Part bands, in the order results are reported.
BANDS = ("prismatic", "holes", "fits")
#: The one spec that is run with the CAD module turned off, and only then.
NO_MODULE_BAND = "no-module"
#: How a truth bounding box is compared: every side as stated, the height as stated and
#: the footprint in either order, or the three sides in any order.
ORIENTATIONS = ("fixed", "z", "free")

#: Appended to every request, so a run measures the part and not a round of questions.
#: It is part of the spec-set hash: change it and earlier rows stop being comparable.
PREAMBLE = "This is a test request: do not ask me questions. Where a detail is missing, choose a sensible value and say which you chose."


@dataclass(frozen=True)
class Need:
    """Work that lands outside this harness and that a spec waits for."""

    item: str
    why: str
    #: Allow-list methods the reference script calls that today's table may not have.
    operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Spec:
    id: str
    band: str
    title: str
    request: str
    directory: Path
    #: How the truth bounding box is compared (ORIENTATIONS).
    orientation: str = "z"
    #: Derived from the reference script; None until ``derive_truth.py`` has run for it.
    truth: dict[str, Any] | None = None
    needs: tuple[Need, ...] = ()
    #: The construct the allow-list refuses for this request, when it cannot express it at all.
    expected_refused: str | None = None
    #: For the no-module spec: phrases the final answer must contain.
    reply_mentions: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def reference(self) -> Path:
        return self.directory / "reference.py"

    @property
    def has_reference(self) -> bool:
        return self.reference.is_file()

    def missing_operations(self, available: Iterable[str]) -> dict[str, list[str]]:
        """The needed operations the given allow-list lacks, by the item that adds them."""
        names = set(available)
        missing: dict[str, list[str]] = {}
        for need in self.needs:
            absent = [operation for operation in need.operations if operation not in names]
            if absent:
                missing.setdefault(need.item, []).extend(absent)
        return missing

    def prompt(self) -> str:
        return f"{self.request}\n\n{PREAMBLE}"


class SpecError(ValueError):
    """A spec file that does not say what the harness needs."""


def _need(value: Any, where: str) -> Need:
    if not isinstance(value, dict) or not isinstance(value.get("item"), str) or not isinstance(value.get("why"), str):
        raise SpecError(f"{where}: each need is {{'item': str, 'why': str, 'operations': [str]}}")
    operations = value.get("operations", [])
    if not isinstance(operations, list) or not all(isinstance(name, str) for name in operations):
        raise SpecError(f"{where}: needs[].operations is a list of method names")
    return Need(value["item"], value["why"], tuple(operations))


def _check_truth(truth: Any, where: str) -> None:
    if truth is None:
        return
    if not isinstance(truth, dict):
        raise SpecError(f"{where}: truth is an object")
    if not isinstance(truth.get("solids"), int) or truth["solids"] < 1:
        raise SpecError(f"{where}: truth.solids is a whole number of at least one")
    box = truth.get("bbox_mm")
    if not isinstance(box, list) or len(box) != 3 or not all(isinstance(side, (int, float)) and side > 0 for side in box):
        raise SpecError(f"{where}: truth.bbox_mm is three positive numbers")
    if not isinstance(truth.get("volume_mm3"), (int, float)) or truth["volume_mm3"] <= 0:
        raise SpecError(f"{where}: truth.volume_mm3 is a positive number")
    holes = truth.get("hole_diameters_mm")
    if holes is not None and (not isinstance(holes, list) or not all(isinstance(d, (int, float)) and d > 0 for d in holes)):
        raise SpecError(f"{where}: truth.hole_diameters_mm lists positive diameters")


def load_spec(directory: Path) -> Spec:
    where = f"{directory.name}/spec.json"
    try:
        raw = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"{where}: {exc}") from None
    for key in ("id", "band", "title", "request"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise SpecError(f"{where}: {key} is a non-empty string")
    if raw["id"] != directory.name:
        raise SpecError(f"{where}: id {raw['id']!r} is not the directory's name")
    if raw["band"] not in (*BANDS, NO_MODULE_BAND):
        raise SpecError(f"{where}: band is one of {', '.join((*BANDS, NO_MODULE_BAND))}")
    if raw.get("orientation", "z") not in ORIENTATIONS:
        raise SpecError(f"{where}: orientation is one of {', '.join(ORIENTATIONS)}")
    _check_truth(raw.get("truth"), where)
    mentions = raw.get("reply_mentions", [])
    if not isinstance(mentions, list) or not all(isinstance(text, str) and text for text in mentions):
        raise SpecError(f"{where}: reply_mentions is a list of phrases")
    return Spec(
        id=raw["id"],
        band=raw["band"],
        title=raw["title"],
        request=raw["request"],
        directory=directory,
        orientation=raw.get("orientation", "z"),
        truth=raw.get("truth"),
        needs=tuple(_need(value, where) for value in raw.get("needs", [])),
        expected_refused=raw.get("expected_refused"),
        reply_mentions=tuple(mentions),
        raw=raw,
    )


def load_specs(root: Path = SPECS_DIR, *, band: str | None = None, ids: Iterable[str] | None = None) -> list[Spec]:
    """Every spec under *root*, by band and id; the no-module spec only when asked for by its band."""
    specs = [load_spec(directory) for directory in root.iterdir() if (directory / "spec.json").is_file()]
    order = {name: index for index, name in enumerate((*BANDS, NO_MODULE_BAND))}
    specs.sort(key=lambda spec: (order[spec.band], spec.id))
    if band is None:
        specs = [spec for spec in specs if spec.band != NO_MODULE_BAND]
    else:
        specs = [spec for spec in specs if spec.band == band]
    if ids is not None:
        wanted = set(ids)
        unknown = wanted - {spec.id for spec in specs}
        if unknown:
            raise SpecError(f"no spec named {', '.join(sorted(unknown))}" + (f" in band {band}" if band else ""))
        specs = [spec for spec in specs if spec.id in wanted]
    return specs


def spec_set_hash(specs: Iterable[Spec]) -> str:
    """Twelve hex digits over the requests, the truth, the references and the preamble.

    Two result rows are comparable only when this matches: a reworded request or a
    moved truth is another test.
    """
    digest = hashlib.sha256(PREAMBLE.encode("utf-8"))
    for spec in sorted(specs, key=lambda spec: spec.id):
        digest.update(json.dumps(spec.raw, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if spec.has_reference:
            digest.update(spec.reference.read_bytes())
    return digest.hexdigest()[:12]


def write_truth(spec: Spec, truth: dict[str, Any]) -> None:
    """Store *truth* in the spec's file, keeping every other key and their order."""
    raw = dict(spec.raw)
    raw["truth"] = truth
    (spec.directory / "spec.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
