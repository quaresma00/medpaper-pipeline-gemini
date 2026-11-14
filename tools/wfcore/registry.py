"""Loads pipeline.toml (the SSOT) plus per-project config overrides.

Stdlib only: tomllib requires Python >= 3.11.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths


@dataclass
class Stage:
    id: str
    title: str
    card: str
    outputs: list[str] = field(default_factory=list)
    gate: list[dict] = field(default_factory=list)
    needs_user: bool = False
    loopable: bool = False
    index: int = 0

    def card_path(self) -> Path:
        return paths.pipeline_dir() / self.card


@dataclass
class Pipeline:
    meta: dict
    layout: dict
    policy: dict
    targets: dict
    freeform: list[str]
    stages: list[Stage]
    raw: dict

    # ---- lookups -------------------------------------------------------
    def stage(self, sid: str) -> Stage:
        target = "S24_package_human_review" if sid == "S25_submission_audit" else sid
        for s in self.stages:
            if s.id == target:
                return s
        raise KeyError(f"unknown stage: {sid}")

    def resolve(self, stage_ref: str) -> Stage:
        """Accept exact id, index (1-based), or unique prefix/substring."""
        stage_ref = (stage_ref or "").strip()
        if not stage_ref:
            raise KeyError("empty stage token")
        if stage_ref in {"S25_submission_audit", "s25", "S25"}:
            stage_ref = self.stages[-1].id
        for s in self.stages:
            if s.id == stage_ref:
                return s
        if stage_ref.isdigit():
            i = int(stage_ref)
            if 1 <= i <= len(self.stages):
                return self.stages[i - 1]
        low = stage_ref.lower()
        hits = [s for s in self.stages if s.id.lower().startswith(low)]
        if len(hits) == 1:
            return hits[0]
        hits = [s for s in self.stages if low in s.id.lower()]
        if len(hits) == 1:
            return hits[0]
        raise KeyError(f"stage token '{stage_ref}' matched {len(hits)} stages")

    def next_of(self, sid: str) -> Stage | None:
        s = self.stage(sid)
        if s.index + 1 < len(self.stages):
            return self.stages[s.index + 1]
        return None

    def stages_after(self, sid: str) -> list[Stage]:
        return self.stages[self.stage(sid).index + 1 :]

    def first(self) -> Stage:
        return self.stages[0]

    def target(self, key: str, default=None):
        return self.targets.get(key, default)

    def all_declared_outputs(self) -> set[str]:
        out: set[str] = set()
        for s in self.stages:
            out.update(s.outputs)
        return out


def load(config_overrides: dict | None = None) -> Pipeline:
    pf = paths.pipeline_file()
    if not pf.exists():
        raise SystemExit(f"pipeline definition missing: {pf}")
    data = tomllib.loads(pf.read_text(encoding="utf-8"))

    stages: list[Stage] = []
    for i, raw in enumerate(data.get("stage", [])):
        stages.append(
            Stage(
                id=raw["id"],
                title=raw.get("title", raw["id"]),
                card=raw.get("card", f"stages/{raw['id']}.md"),
                outputs=list(raw.get("outputs", [])),
                gate=list(raw.get("gate", [])),
                needs_user=bool(raw.get("needs_user", False)),
                loopable=bool(raw.get("loopable", False)),
                index=i,
            )
        )
    if not stages:
        raise SystemExit("pipeline.toml declares no stages")

    targets = dict(data.get("targets", {}))
    if config_overrides:
        targets.update(config_overrides.get("targets", {}))

    return Pipeline(
        meta=data.get("meta", {}),
        layout=data.get("layout", {}),
        policy=data.get("policy", {}),
        targets=targets,
        freeform=list(data.get("freeform", {}).get("globs", [])),
        stages=stages,
        raw=data,
    )
