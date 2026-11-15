"""YOUR PoC PIPELINE — this is the file your group owns.

Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      input + provenance check (manifest.csv)
    02 process   your algorithm / model (the research part)
    03 rank      prioritise for a fixed review budget B
    04 review    human-in-the-loop: queue -> reviewer decisions -> overrides + audit log
    05 decide    GO / HOLD / REWORK (or track equivalent) with reason_code + owner, write outputs

Required output: out/<pred_file> with the columns listed for your track in
docs/tracks/TXX.md (also in src/metrics/tracks.py::TRACKS). Then evaluate with
    python -m src.evaluate --track tXX --pred out/<pred_file>

Rules: never read fixtures/*/gt/ here (the GT guard will stop you); seed everything via ctx.rng;
no network calls; fail loudly on missing models instead of downloading.
See src/examples/random_baseline.py for a minimal end-to-end wiring example.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.image_ops import brightness_stats, laplacian_variance, load_rgb
from .common.manifest import verify_manifest
from .common.review import apply_overrides, load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track


_T02_COLUMNS = ["image_id", "path", "camera_id", "light", "split"]
_BLUR_WEIGHT = 0.55
_DARK_WEIGHT = 0.30
_GLARE_WEIGHT = 0.15


def _image_path(ctx: RunContext, value: str) -> Path:
    rel_path = Path(value)
    if not value.strip() or rel_path.is_absolute():
        raise ValueError(f"image path must be relative to input directory: {value!r}")
    root = ctx.input_dir.resolve()
    path = (root / rel_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"image path escapes input directory: {value!r}")
    if not path.is_file():
        raise FileNotFoundError(f"image file not found: {path}")
    return path


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    if ctx.track != "t02":
        spec = get_track(ctx.track)
        raise NotImplementedError(f"PoC pipeline currently implements t02 only, not {spec.track}")

    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    images_path = ctx.input_dir / "images.csv"
    if not images_path.is_file():
        raise FileNotFoundError(f"required input table not found: {images_path}")
    images = pd.read_csv(images_path)
    missing = [column for column in _T02_COLUMNS if column not in images.columns]
    if missing:
        raise ValueError(f"{images_path} missing required columns: {missing}")
    if images["image_id"].isna().any() or images["image_id"].duplicated().any():
        raise ValueError(f"{images_path} must contain unique, non-empty image_id values")
    if images.empty:
        raise ValueError(f"{images_path} contains no images")
    return {"manifest": pd.read_csv(manifest) if manifest.exists() else None, "images": images}


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    if ctx.track != "t02":
        spec = get_track(ctx.track)
        raise NotImplementedError(f"PoC process() currently implements t02 only, not {spec.track}")
    if "images" not in data:
        raise ValueError("load() must provide an `images` table for t02")

    rows = []
    for row in data["images"].itertuples(index=False):
        image = load_rgb(_image_path(ctx, str(row.path)))
        sharpness = laplacian_variance(image)
        brightness = brightness_stats(image)

        blur_risk = 1.0 / (1.0 + sharpness / 100.0)
        dark_risk = min(
            1.0,
            max(
                0.0,
                0.6 * brightness["frac_dark"]
                + 0.4 * (70.0 - brightness["mean"]) / 70.0,
            ),
        )
        glare_risk = min(
            1.0,
            max(
                0.0,
                0.8 * brightness["frac_saturated"]
                + 0.2 * (brightness["p95"] - 245.0) / 10.0,
            ),
        )
        components = {
            "low_sharpness": blur_risk,
            "dark": dark_risk,
            "glare": glare_risk,
        }
        reason = max(components, key=components.get)
        score = (
            _BLUR_WEIGHT * blur_risk
            + _DARK_WEIGHT * dark_risk
            + _GLARE_WEIGHT * glare_risk
        )
        rows.append(
            {
                "image_id": row.image_id,
                "score": float(score),
                "reason": reason,
                "pred_action": "REVIEW",
                "path": str(row.path),
                "camera_id": row.camera_id,
                "light": row.light,
                "split": row.split,
                "sharpness": sharpness,
                "mean_brightness": brightness["mean"],
                "frac_dark": brightness["frac_dark"],
                "frac_saturated": brightness["frac_saturated"],
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Default: top-B by `score`. Adapt id/score/reason columns to your track."""
    budget = int(ctx.param("budget", 20))
    if "image_id" not in scored.columns or "score" not in scored.columns:
        raise ValueError("rank(): t02 process() output needs `image_id` and numeric `score` columns")
    if scored["score"].isna().any():
        raise ValueError("rank(): score values must not be missing")
    q = make_review_queue(
        scored,
        id_col="image_id",
        score_col="score",
        budget=budget,
        reason_col="reason" if "reason" in scored.columns else None,
        action_col="pred_action" if "pred_action" in scored.columns else None,
        slice_col="light" if "light" in scored.columns else None,
        evidence_col="path" if "path" in scored.columns else None,
    )
    ctx.stats["review_item_ids"] = q["item_id"].astype(str).tolist()
    write_review_queue(q, ctx.out("review_queue.csv"))
    render_contact_sheet(
        q,
        ctx.out("contact_sheet.html"),
        image_root=ctx.input_dir,
        title=f"{ctx.track.upper()} review queue",
    )
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Apply reviewer decisions to the suggested KEEP/RECAPTURE action and audit them."""
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if not reviewed_path.exists():
        ctx.stats["n_reviewed"] = 0
        return scored

    reviewed = load_review_decisions(reviewed_path)
    queue_ids = set(queue["item_id"].astype(str))
    reviewed_ids = reviewed["item_id"].astype(str)
    if reviewed_ids.duplicated().any():
        raise ValueError("review file contains duplicate item_id values")
    outside_queue = sorted(set(reviewed_ids) - queue_ids)
    if outside_queue:
        raise ValueError(f"review file contains items not in the current queue: {outside_queue[:5]}")

    overrides = reviewed.copy()
    overrides["item_id"] = overrides["item_id"].astype(str)
    overrides["override_value"] = overrides["override_value"].str.strip().str.upper()
    for row in overrides.itertuples(index=False):
        if row.reviewer_decision == "approve":
            overrides.loc[overrides["item_id"] == row.item_id, "override_value"] = "KEEP"
        elif row.reviewer_decision == "reject":
            overrides.loc[overrides["item_id"] == row.item_id, "override_value"] = "RECAPTURE"
        elif row.reviewer_decision == "edit" and row.override_value not in {"KEEP", "RECAPTURE"}:
            raise ValueError("reviewer_decision=edit requires override_value KEEP or RECAPTURE")
        elif row.reviewer_decision == "edit":
            continue
        else:
            continue
        overrides.loc[overrides["item_id"] == row.item_id, "reviewer_decision"] = "edit"

    final = apply_overrides(
        scored,
        overrides,
        id_col="image_id",
        value_col="pred_action",
    )
    before_actions = scored.set_index("image_id")["pred_action"]
    after_actions = final.set_index("image_id")["pred_action"]
    for row in reviewed.itertuples(index=False):
        item_id = str(row.item_id)
        ctx.audit.log(
            actor=row.reviewer,
            action=f"review:{row.reviewer_decision}",
            item_id=item_id,
            before=before_actions.loc[item_id],
            after=after_actions.loc[item_id],
            reason=row.review_note,
        )
    ctx.stats["n_reviewed"] = len(reviewed)
    return final


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    owner = ctx.config.get("owner")
    if not isinstance(owner, str) or not owner.strip() or owner.strip().upper().startswith("TODO"):
        raise ValueError("Set a real `owner` in configs/lab.yaml before running the T02 pipeline")
    owner = owner.strip()
    queue_ids = set(ctx.stats.get("review_item_ids", []))
    reviewed_queue = final[final["image_id"].astype(str).isin(queue_ids)]
    queue_actions = set(reviewed_queue["pred_action"].astype(str).str.upper())
    if "RECAPTURE" in queue_actions:
        status, code, reason = "REWORK", "RECAPTURE_REQUIRED", "Reviewer marked one or more images for recapture."
    elif not queue_ids or "REVIEW" in queue_actions or len(reviewed_queue) != len(queue_ids):
        status, code, reason = "HOLD", "HUMAN_REVIEW_INCOMPLETE", "Hold until every image in the priority review queue has a decision."
    else:
        status, code, reason = "GO", "PRIORITY_QUEUE_KEPT", "Every image in the priority review queue was reviewed and marked KEEP."
    return Decision(
        status=status,
        reason_code=code,
        reason=reason,
        owner=owner,
        scope=ctx.track,
        evidence=[str(ctx.out("ranked_review.csv")), str(ctx.out("review_queue.csv"))],
        metrics={"n_items": len(final), "n_reviewed": int(ctx.stats.get("n_reviewed", 0))},
    )


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    final[spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
