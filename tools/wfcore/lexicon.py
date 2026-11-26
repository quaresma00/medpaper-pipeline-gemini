"""Cached loader for declarative clinical terminology in reference/clinical_lexicon.toml."""
from __future__ import annotations

import functools
import tomllib
from pathlib import Path

from . import paths


@functools.lru_cache(maxsize=1)
def _raw_lexicon() -> dict:
    lex_path: Path = paths.repo_root() / "reference" / "clinical_lexicon.toml"
    return tomllib.loads(lex_path.read_text(encoding="utf-8"))


def measure_families_map() -> dict[str, dict[str, tuple[str, ...]]]:
    raw = _raw_lexicon().get("measure_families", {})
    return {
        fam: {
            "phrases": tuple(spec.get("phrases", [])),
            "abbr": tuple(spec.get("abbr", [])),
        }
        for fam, spec in raw.items()
    }


def unit_synonyms_map() -> dict[str, tuple[str, ...]]:
    raw = _raw_lexicon().get("unit_synonyms", {})
    return {k: tuple(v) for k, v in raw.items()}


def display_set(name: str) -> set[str]:
    raw = _raw_lexicon().get("display_rules", {})
    return set(raw.get(name, []))
