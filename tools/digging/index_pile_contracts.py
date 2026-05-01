#!/usr/bin/env python3
"""Index old pile material into private module/asset contracts.

This tool is deliberately read-only against the source pile. It scans known
ChewGum project folders and writes private planning artifacts under
`_Internal/digging/`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
DEFAULT_PILE_ROOT = Path("/Volumes/SSD/00_Pile_For_Digging")
DEFAULT_OUTPUT_ROOT = REPO / "_Internal" / "digging"
SKIP_DIRS = {
    ".git",
    ".DS_Store",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".tmp",
    "tmp",
}


@dataclass(frozen=True)
class ModuleSeed:
    id: str
    label: str
    source_paths: tuple[str, ...]
    contract_boundary: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    tests: tuple[str, ...]
    dependency_boundary: str
    asset_boundary: str
    public_status: str
    extraction_status: str
    first_fixture: str
    first_public_proof: str
    score: int
    notes: tuple[str, ...]


MODULE_SEEDS: tuple[ModuleSeed, ...] = (
    ModuleSeed(
        id="chewgum-scenescript",
        label="ChewGumSceneScript",
        source_paths=(
            "01_ChewGumOS-main/gamelogic/animation",
            "01_ChewGumOS-main/gamelogic/scene",
            "01_ChewGumOS-main/gamelogic/director",
        ),
        contract_boundary="Validated renderer-neutral animation cue JSON.",
        inputs=("natural-language or hand-authored scene intent", "spatial presets", "dialog IDs"),
        outputs=("SceneScript JSON", "validation report", "readable timeline plan"),
        tests=("01_ChewGumOS-main/gamelogic/__tests__/*.test.ts",),
        dependency_boundary="Core validation should not require Motion Canvas; current director CLI must be isolated from model-specific calls.",
        asset_boundary="No direct art/audio assets required for validation fixtures.",
        public_status="candidate_private_first",
        extraction_status="highest_priority_after_lipservice",
        first_fixture="simple-walk-and-speak.scenescript.json",
        first_public_proof="Timeline inspector that renders cue order, warnings, and frame counts.",
        score=96,
        notes=(
            "Already has schema helpers, validator, director examples, and viseme stamping.",
            "Best bridge between AI-assisted authoring and deterministic animation contracts.",
        ),
    ),
    ModuleSeed(
        id="chewgum-bg",
        label="ChewGumBG / TileRuleset V2",
        source_paths=(
            "03_BG_Generation/src/backgrounds",
            "01_ChewGumOS-main/bg-gen/backgrounds",
        ),
        contract_boundary="BackgroundSource frame contract plus semantic object descriptors.",
        inputs=("seed/config", "tile ruleset", "raster grid"),
        outputs=("RasterCommand frames", "BackgroundObjectDescriptor metadata", "validation/self-check report"),
        tests=("01_ChewGumOS-main/scripts/check-tileset-v2.ts",),
        dependency_boundary="Mostly authored TypeScript; image-derived modes need asset provenance.",
        asset_boundary="Use synthetic/minimal tile fixtures for public v0.",
        public_status="candidate_private_first",
        extraction_status="strong_repo_candidate_after_visual_proof",
        first_fixture="minimal-room.ruleset.json",
        first_public_proof="Seeded background viewer with semantic-object overlay.",
        score=91,
        notes=(
            "A separate 03_BG_Generation package-shaped copy already exists.",
            "Needs canonical source decision between 03_BG_Generation and ChewGumOS bg-gen.",
        ),
    ),
    ModuleSeed(
        id="chewgum-rooms",
        label="ChewGumRooms",
        source_paths=("01_ChewGumOS-main/Interior_Generation",),
        contract_boundary="Interior room grammar and generative source contract.",
        inputs=("room type", "props", "dimensions"),
        outputs=("appendable interior source", "room raster/geometry", "constraint report"),
        tests=("01_ChewGumOS-main/Interior_Generation/tests/*.test.ts",),
        dependency_boundary="Authored TypeScript; can probably stay renderer-neutral at the core.",
        asset_boundary="Public v0 should use abstract room fixtures or authored safe sprites.",
        public_status="candidate_private_first",
        extraction_status="strong_candidate_maybe_submodule_of_bg",
        first_fixture="bedroom.v0.json",
        first_public_proof="Bedroom proof with rule/debug overlays.",
        score=88,
        notes=(
            "Has its own package shape and strong test density.",
            "May be more useful folded into ChewGumBG than as a separate repo.",
        ),
    ),
    ModuleSeed(
        id="chewgum-lipservice",
        label="ChewGumLipService",
        source_paths=(
            "02_Lip_Assignment",
            "00_Assets/00_Raw_Audio",
            "01_ChewGumOS-main/src/api/characters/lipSync.ts",
        ),
        contract_boundary="Dialogue audio/transcript to mouth-shape timing exports.",
        inputs=("audio file", "transcript/word timings", "mouth-shape profile", "manual overrides"),
        outputs=("viseme timeline", "export adapters", "review report"),
        tests=("02_Lip_Assignment/**/*.py", "01_ChewGumOS-main/src/__tests__/lipSync.test.ts"),
        dependency_boundary="Python audio tooling plus optional external aligners; public v0 needs documented install boundaries.",
        asset_boundary="Requires public-safe sample audio and mouth-shape profile before release.",
        public_status="active_product_direction",
        extraction_status="already_selected_serious_tool",
        first_fixture="synthetic-dialogue-lipservice-project.json",
        first_public_proof="Tiny browser preview plus JSON/CSV export.",
        score=95,
        notes=(
            "Most practically valuable outside ChewGum.",
            "Needs clean project format and export adapters before repo push.",
        ),
    ),
    ModuleSeed(
        id="chewgum-char-runtime",
        label="ChewGumCharacterRuntime",
        source_paths=("01_ChewGumOS-main/src/api/characters",),
        contract_boundary="Layered sprite state, mouth lookup, clip playback, and lip-sync sampling.",
        inputs=("character profile", "body/emotion/viseme state", "LipSyncTimeline"),
        outputs=("resolved frame/layer state", "sampled viseme", "runtime sprite instruction"),
        tests=("01_ChewGumOS-main/src/__tests__/characterPipeline.test.ts", "01_ChewGumOS-main/src/__tests__/lipSync.test.ts"),
        dependency_boundary="Core can be renderer-neutral; Aseprite import and runtime adapters need separation.",
        asset_boundary="Needs public-safe sample character profile; Gum mouths are not complete enough yet.",
        public_status="pair_with_lipservice",
        extraction_status="hold_until_sample_profile",
        first_fixture="one-character-mouth-profile.json",
        first_public_proof="LipService output drives one sample sprite mouth layer.",
        score=82,
        notes=(
            "Very valuable as LipService proof infrastructure.",
            "Too asset-dependent to lead as a standalone repo.",
        ),
    ),
    ModuleSeed(
        id="chewgum-genfx",
        label="ChewGumGenFX",
        source_paths=("01_ChewGumOS-main/genfx",),
        contract_boundary="Procedural effect specs, generator registry, and prefab catalog.",
        inputs=("effect spec", "seed/time", "palette"),
        outputs=("palette-index or raster frames", "prefab metadata", "visual proof"),
        tests=("01_ChewGumOS-main/genfx/__tests__/*.test.ts",),
        dependency_boundary="Mostly authored TypeScript; adapter/render boundaries need trimming.",
        asset_boundary="Can start with no external assets if first slice is purely procedural.",
        public_status="candidate_later",
        extraction_status="narrow_slice_first",
        first_fixture="fire-material-source.v0.json",
        first_public_proof="One physically truthful effect with deterministic seed and params.",
        score=78,
        notes=(
            "High identity value, but too broad to publish whole.",
            "Use CREATIVE_RULES.md as the taste gate.",
        ),
    ),
    ModuleSeed(
        id="chewgum-raster",
        label="ChewGumRaster",
        source_paths=(
            "01_ChewGumOS-main/src/api/raster.ts",
            "01_ChewGumOS-main/src/api/effects",
            "01_ChewGumOS-main/src/api/captureAdapter.ts",
            "01_ChewGumOS-main/src/api/nonOverlapCoverage.ts",
        ),
        contract_boundary="Renderer-neutral pixel/raster command utilities and memory buffers.",
        inputs=("raster grid", "commands", "coverage policy", "capture target"),
        outputs=("projected commands", "history/accumulation snapshots", "coverage-filtered commands"),
        tests=("01_ChewGumOS-main/src/__tests__/runtime.test.ts",),
        dependency_boundary="Some browser canvas paths; pure command transforms can be isolated.",
        asset_boundary="No authored assets required.",
        public_status="shared_core",
        extraction_status="dependency_core_not_headline",
        first_fixture="tiny-8x8-raster-commands.json",
        first_public_proof="Command transform test report, not a flashy page.",
        score=73,
        notes=(
            "Important backbone for BG, Rooms, and GenFX.",
            "Not compelling enough as the first public repo by itself.",
        ),
    ),
    ModuleSeed(
        id="chewgum-voicebox",
        label="ChewGumVoiceBox",
        source_paths=("00_Assets/00_Raw_Audio/clips", "00_Assets/00_Raw_Audio/*_labeled.json"),
        contract_boundary="Sentence-level character performance clip index.",
        inputs=("sentence clips", "transcripts", "speaker labels", "public-use flags"),
        outputs=("playable line index", "random/call-response sequences", "clip provenance report"),
        tests=(),
        dependency_boundary="Audio playback can be browser-native; corpus builder likely Python.",
        asset_boundary="Public output must carry per-clip approval/provenance; incidental game audio is a recorded risk posture.",
        public_status="private_first",
        extraction_status="playful_sibling_to_lipservice",
        first_fixture="ten-approved-sentence-clips.voicebox.json",
        first_public_proof="Local voice-box toy with approved sample clips only.",
        score=74,
        notes=(
            "The raw corpus is large and useful.",
            "Should not publish raw clips until public-use flags exist.",
        ),
    ),
    ModuleSeed(
        id="gooey-capability-manifest",
        label="Gooey Capability Manifest",
        source_paths=("07_GOOEY/src/manifest.ts", "07_GOOEY/README.md"),
        contract_boundary="Visible capability inventory for tools, scenes, characters, effects, and servers.",
        inputs=("module contract status", "test/proof paths", "tool readiness"),
        outputs=("capabilities.v0.json", "Gooey dashboard panels", "agent-readable skill map"),
        tests=(),
        dependency_boundary="UI is vanilla/Vite; reusable part is the manifest schema.",
        asset_boundary="No public assets required for manifest v0.",
        public_status="internal_backbone",
        extraction_status="extract_schema_not_ui",
        first_fixture="capabilities.v0.json",
        first_public_proof="Private dashboard reads generated capability JSON.",
        score=80,
        notes=(
            "This is how Chew/Gum remember what they can actually do.",
            "Avoid turning a quick UI into a framework too early.",
        ),
    ),
    ModuleSeed(
        id="z-shared-toy-backlog",
        label="z_shared Toy Backlog",
        source_paths=("z_shared",),
        contract_boundary="Standalone HTML studies promoted only after source trail and taxonomy pass.",
        inputs=("single HTML study", "public explanation", "source trail"),
        outputs=("toy note", "demo parameters", "related terms"),
        tests=(),
        dependency_boundary="Mostly browser-native; each HTML file needs individual check.",
        asset_boundary="Usually asset-light; still inspect embedded references.",
        public_status="toy_backlog",
        extraction_status="selective_promotion",
        first_fixture="displacement-modes-wiki.html",
        first_public_proof="Displacement Modes toy note.",
        score=62,
        notes=(
            "Fast public material, but not all future work should be toys.",
            "Good source for idea breadth while serious tools harden.",
        ),
    ),
    ModuleSeed(
        id="cdp-external-reference",
        label="CDP External Reference",
        source_paths=("12_CDP",),
        contract_boundary="External audio software; reference/integration only.",
        inputs=("installed CDP tools", "audio files"),
        outputs=("processed audio artifacts", "integration notes"),
        tests=(),
        dependency_boundary="Third-party LGPL project; do not repackage or claim authorship.",
        asset_boundary="No ChewGum authored assets in this source tree.",
        public_status="external_reference_only",
        extraction_status="blocked_as_chewgum_repo",
        first_fixture="none",
        first_public_proof="External tool citation, not extraction.",
        score=12,
        notes=("Useful influence or integration target, not ChewGum raw material.",),
    ),
)


ASSET_GROUPS: tuple[dict[str, str], ...] = (
    {
        "id": "raw-audio-corpus",
        "source_path": "00_Assets/00_Raw_Audio",
        "asset_role": "audio_corpus",
        "owner": "Shane Curry",
        "provenance_class": "authored_voice_with_incidental_external_game_audio",
        "public_status": "private_index_first",
        "rights_note": "Creator accepts risk for selected noncommercial clips, but public use must be flagged per clip.",
    },
    {
        "id": "character-assets",
        "source_path": "00_Assets/01_CHARACTERS",
        "asset_role": "character_source_art",
        "owner": "Shane Curry",
        "provenance_class": "authored_asset",
        "public_status": "candidate_after_indexing",
        "rights_note": "Gum character source/sprites; confirm per file before public sample use.",
    },
    {
        "id": "mouth-assets",
        "source_path": "00_Assets/01_MOUTHS",
        "asset_role": "mouth_shape_profile",
        "owner": "Shane Curry",
        "provenance_class": "authored_asset",
        "public_status": "candidate_after_indexing",
        "rights_note": "Chew mouth shapes are strong LipService sample candidates.",
    },
    {
        "id": "chewgumos-ui-assets",
        "source_path": "00_Assets/z_ChewGumOS Assets",
        "asset_role": "os_ui_identity",
        "owner": "Shane Curry",
        "provenance_class": "authored_asset",
        "public_status": "candidate_after_indexing",
        "rights_note": "Internal OS visual identity; useful for Gooey/ChewGumOS pages.",
    },
    {
        "id": "legacy-sprites",
        "source_path": "00_Assets/zmore sprites",
        "asset_role": "legacy_sprite_archive",
        "owner": "Shane Curry",
        "provenance_class": "mixed_authored_archive",
        "public_status": "curate_before_use",
        "rights_note": "Old ChewGum/MVP/Godot/Blender material; quality and context pass required.",
    },
    {
        "id": "line-art-reference",
        "source_path": "00_Assets/line_art_examples",
        "asset_role": "visual_reference",
        "owner": "external_reference",
        "provenance_class": "external_reference",
        "public_status": "do_not_publish_as_asset",
        "rights_note": "Reference images only unless original source terms are verified.",
    },
    {
        "id": "ai-image-lab-reference",
        "source_path": "00_Assets/AI image laboratory inspo",
        "asset_role": "internal_inspiration_reference",
        "owner": "mixed_or_generated",
        "provenance_class": "ai_generated_reference",
        "public_status": "internal_only",
        "rights_note": "Do not present as authored ChewGum art.",
    },
    {
        "id": "standalone-html-studies",
        "source_path": "z_shared",
        "asset_role": "toy_source_material",
        "owner": "Shane Curry",
        "provenance_class": "authored_or_mixed_code_study",
        "public_status": "promote_selectively",
        "rights_note": "Each HTML study needs source-trail and embedded-asset check before promotion.",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pile-root",
        default=os.environ.get("DIGGING_PILE_ROOT", str(DEFAULT_PILE_ROOT)),
        help="source pile root; read-only",
    )
    parser.add_argument(
        "--output-root",
        default=os.environ.get("DIGGING_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT)),
        help="private output root under _Internal/",
    )
    args = parser.parse_args()

    pile_root = Path(args.pile_root).expanduser().resolve()
    output_root = _resolve_output_root(args.output_root)

    if not pile_root.exists():
        print(f"pile root not found: {pile_root}", file=sys.stderr)
        return 2
    if not pile_root.is_dir():
        print(f"pile root is not a directory: {pile_root}", file=sys.stderr)
        return 2

    output_root.mkdir(parents=True, exist_ok=True)

    generated = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    modules = sorted(
        (_build_module(seed, pile_root) for seed in MODULE_SEEDS),
        key=lambda item: item["rank_score"],
        reverse=True,
    )
    assets = [_build_asset_group(group, pile_root) for group in ASSET_GROUPS]
    summary = _build_summary(pile_root, modules, assets)

    module_doc = {
        "schema": "chewgum.module-contracts.v0",
        "generated_at": generated,
        "source_root": str(pile_root),
        "read_only": True,
        "summary": summary["modules"],
        "modules": modules,
    }
    asset_doc = {
        "schema": "chewgum.asset-atlas.v0",
        "generated_at": generated,
        "source_root": str(pile_root),
        "read_only": True,
        "summary": summary["assets"],
        "asset_groups": assets,
    }

    _write_json(output_root / "module-contracts.json", module_doc)
    _write_json(output_root / "asset-atlas.json", asset_doc)
    (output_root / "extraction-candidates.md").write_text(
        _render_markdown(generated, pile_root, modules, assets, summary),
        encoding="utf-8",
    )

    print(f"wrote {output_root / 'module-contracts.json'}")
    print(f"wrote {output_root / 'asset-atlas.json'}")
    print(f"wrote {output_root / 'extraction-candidates.md'}")
    print(
        "summary: "
        f"{summary['modules']['candidate_count']} candidate modules, "
        f"{summary['assets']['asset_group_count']} asset groups",
    )
    return 0


def _resolve_output_root(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = REPO / path
    resolved = path.expanduser().resolve()
    internal = (REPO / "_Internal").resolve()
    if resolved != internal and internal not in resolved.parents:
        raise SystemExit(f"output root must be under {internal}: {resolved}")
    return resolved


def _build_module(seed: ModuleSeed, pile_root: Path) -> dict[str, Any]:
    sources = []
    file_count = 0
    line_count = 0
    ext_counts: Counter[str] = Counter()
    existing_paths: list[str] = []

    for rel in seed.source_paths:
        path = pile_root / rel
        exists = path.exists()
        if exists:
            existing_paths.append(rel)
            metrics = _scan_path(path)
            file_count += metrics["file_count"]
            line_count += metrics["line_count"]
            ext_counts.update(metrics["extension_counts"])
        sources.append(
            {
                "path": rel,
                "exists": exists,
                "kind": "directory" if path.is_dir() else "file" if path.is_file() else "missing",
            }
        )

    test_files = _expand_globs(seed.tests, pile_root)
    package_files = _package_files_for_sources(seed.source_paths, pile_root)

    return {
        "id": seed.id,
        "label": seed.label,
        "rank_score": seed.score,
        "source_paths": sources,
        "source_exists": bool(existing_paths),
        "contract_boundary": seed.contract_boundary,
        "inputs": list(seed.inputs),
        "outputs": list(seed.outputs),
        "tests": {
            "patterns": list(seed.tests),
            "matched_files": test_files,
            "matched_count": len(test_files),
        },
        "metrics": {
            "file_count": file_count,
            "line_count": line_count,
            "extension_counts": dict(sorted(ext_counts.items())),
            "package_files": package_files,
        },
        "dependency_boundary": seed.dependency_boundary,
        "asset_boundary": seed.asset_boundary,
        "public_status": seed.public_status,
        "extraction_status": seed.extraction_status,
        "first_fixture": seed.first_fixture,
        "first_public_proof": seed.first_public_proof,
        "notes": list(seed.notes),
    }


def _build_asset_group(group: dict[str, str], pile_root: Path) -> dict[str, Any]:
    rel = group["source_path"]
    path = pile_root / rel
    metrics = _scan_path(path) if path.exists() else _empty_metrics_serializable()
    samples = _sample_files(path, limit=24) if path.exists() else []
    signals = _asset_signals(group["id"], path)
    size_label = _du_sh(path) if path.exists() else "missing"

    return {
        **group,
        "exists": path.exists(),
        "kind": "directory" if path.is_dir() else "file" if path.is_file() else "missing",
        "size": size_label,
        "metrics": metrics,
        "signals": signals,
        "sample_files": samples,
    }


def _asset_signals(group_id: str, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    if group_id == "raw-audio-corpus":
        clips = path / "clips"
        return {
            "labeled_episode_files": _count_glob(path, "*_labeled.json"),
            "manual_override_files": _count_glob(path, "*_manual.json"),
            "viseme_files": _count_glob(path, "*_visemes.json"),
            "phoneme_files": _count_glob(path, "*_phonemes.json"),
            "transcript_files": _count_glob(clips, "*_transcript.json"),
            "sentence_clip_dirs": _count_dirs(clips),
            "clip_wav_files": _count_glob(clips, "**/*.wav"),
            "review_bucket_wav_files": {
                "CHEW": _count_glob(path / "CHEW", "*.wav"),
                "GUM": _count_glob(path / "GUM", "*.wav"),
                "BOTH": _count_glob(path / "BOTH", "*.wav"),
                "TRASH": _count_glob(path / "TRASH", "*.wav"),
            },
        }

    if group_id == "mouth-assets":
        return {
            "chew_full_shapes": sorted(p.stem for p in (path / "CHEW_SNES_FULL").glob("*.png")),
            "chew_test_shapes": sorted(p.stem for p in (path / "CHEW_SNES_TEST").glob("*.png")),
        }

    if group_id == "standalone-html-studies":
        return {
            "html_files": _count_glob(path, "**/*.html"),
            "mp3_files": _count_glob(path, "**/*.mp3"),
            "likely_toy_candidates": [
                p.name
                for p in sorted(path.glob("*.html"))
                if any(token in p.name for token in ("sine", "noise", "windows", "displacement", "path", "fourier"))
            ][:40],
        }

    return {}


def _scan_path(path: Path) -> dict[str, Any]:
    metrics = _empty_metrics()
    if not path.exists():
        return metrics

    paths = [path] if path.is_file() else list(_iter_files(path))
    for file_path in paths:
        metrics["file_count"] += 1
        try:
            metrics["total_bytes"] += file_path.stat().st_size
        except OSError:
            pass
        ext = file_path.suffix.lower().lstrip(".") or "[noext]"
        metrics["extension_counts"][ext] += 1
        if ext in {"ts", "tsx", "js", "jsx", "py", "md", "json", "html", "css"}:
            metrics["line_count"] += _safe_line_count(file_path)

    metrics["extension_counts"] = dict(sorted(metrics["extension_counts"].items()))
    return metrics


def _empty_metrics() -> dict[str, Any]:
    return {
        "file_count": 0,
        "line_count": 0,
        "total_bytes": 0,
        "extension_counts": Counter(),
    }


def _empty_metrics_serializable() -> dict[str, Any]:
    return {
        "file_count": 0,
        "line_count": 0,
        "total_bytes": 0,
        "extension_counts": {},
    }


def _iter_files(root: Path):
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name in SKIP_DIRS:
                continue
            yield Path(current) / name


def _safe_line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _expand_globs(patterns: tuple[str, ...], pile_root: Path) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(
            str(path.relative_to(pile_root))
            for path in sorted(pile_root.glob(pattern))
            if path.is_file()
        )
    return matches


def _package_files_for_sources(source_paths: tuple[str, ...], pile_root: Path) -> list[str]:
    package_files: set[str] = set()
    for rel in source_paths:
        path = pile_root / rel
        candidates = [path] + list(path.parents)
        for candidate in candidates:
            if candidate == pile_root.parent:
                break
            package = candidate / "package.json"
            if package.exists() and pile_root in package.resolve().parents:
                package_files.add(str(package.relative_to(pile_root)))
                break
    return sorted(package_files)


def _sample_files(path: Path, limit: int) -> list[str]:
    files = sorted(_iter_files(path), key=lambda p: str(p).lower())
    return [str(p.relative_to(path)) for p in files[:limit]]


def _count_glob(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.glob(pattern) if p.is_file())


def _count_dirs(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.iterdir() if p.is_dir())


def _du_sh(path: Path) -> str:
    result = subprocess.run(
        ["du", "-sh", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.split()[0]


def _build_summary(
    pile_root: Path,
    modules: list[dict[str, Any]],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    module_candidates = [m for m in modules if m["rank_score"] >= 70 and m["source_exists"]]
    return {
        "modules": {
            "module_count": len(modules),
            "candidate_count": len(module_candidates),
            "top_candidates": [m["id"] for m in sorted(module_candidates, key=lambda m: m["rank_score"], reverse=True)[:6]],
            "source_root_exists": pile_root.exists(),
        },
        "assets": {
            "asset_group_count": len(assets),
            "existing_group_count": sum(1 for a in assets if a["exists"]),
            "private_first_groups": [a["id"] for a in assets if "private" in a["public_status"]],
            "blocked_or_external_groups": [
                a["id"]
                for a in assets
                if a["public_status"] in {"do_not_publish_as_asset", "internal_only"}
            ],
        },
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_markdown(
    generated: str,
    pile_root: Path,
    modules: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# Extraction Candidates",
        "",
        f"Generated: {generated}",
        f"Source root: `{pile_root}`",
        "Mode: read-only scan; outputs are private.",
        "",
        "## Short Read",
        "",
        "ChewGumOS is best treated as an internal proving room. The public-grade",
        "opportunities are the smaller contracts inside it, especially SceneScript,",
        "LipService, BG/Rooms, and the capability manifest.",
        "",
        "## Top Module Candidates",
        "",
        "| Rank | Module | Score | Status | First proof |",
        "| ---: | --- | ---: | --- | --- |",
    ]

    ranked = sorted(modules, key=lambda item: item["rank_score"], reverse=True)
    for index, module in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | {module['label']} | {module['rank_score']} | "
            f"{module['extraction_status']} | {module['first_public_proof']} |"
        )

    lines.extend(
        [
            "",
            "## Asset / Corpus Groups",
            "",
            "| Group | Size | Public status | Provenance | Key signal |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for asset in assets:
        signal = _short_signal(asset)
        lines.append(
            f"| {asset['id']} | {asset['size']} | {asset['public_status']} | "
            f"{asset['provenance_class']} | {signal} |"
        )

    lines.extend(
        [
            "",
            "## Recommended Next Build",
            "",
            "Build the private ModuleContract + AssetAtlas layer into a repeatable",
            "Chew/Gum memory source:",
            "",
            "1. Promote `chewgum-scenescript` to the first extraction packet.",
            "2. Generate one good SceneScript fixture and one bad fixture.",
            "3. Isolate renderer-neutral validation from Motion Canvas execution.",
            "4. Feed the result into Gooey's future `capabilities.v0.json`.",
            "5. Use `asset-atlas.json` to choose safe sample assets for later visual proofs.",
            "",
            "## Files Written By This Pass",
            "",
            "- `_Internal/digging/module-contracts.json`",
            "- `_Internal/digging/asset-atlas.json`",
            "- `_Internal/digging/extraction-candidates.md`",
            "",
            "## Summary",
            "",
            f"- Modules scanned: {summary['modules']['module_count']}",
            f"- Strong module candidates: {summary['modules']['candidate_count']}",
            f"- Asset groups scanned: {summary['assets']['asset_group_count']}",
            f"- Existing asset groups: {summary['assets']['existing_group_count']}",
            "",
        ]
    )
    return "\n".join(lines)


def _short_signal(asset: dict[str, Any]) -> str:
    signals = asset.get("signals", {})
    if asset["id"] == "raw-audio-corpus":
        return (
            f"{signals.get('labeled_episode_files', 0)} labeled JSON, "
            f"{signals.get('clip_wav_files', 0)} clip WAV"
        )
    if asset["id"] == "mouth-assets":
        return f"{len(signals.get('chew_full_shapes', []))} Chew full mouth PNG"
    if asset["id"] == "standalone-html-studies":
        return f"{signals.get('html_files', 0)} HTML studies"
    return f"{asset['metrics']['file_count']} files"


if __name__ == "__main__":
    raise SystemExit(main())
