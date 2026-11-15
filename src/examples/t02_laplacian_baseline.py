"""Global Laplacian-variance baseline for T02 Raw QC Triage."""
from __future__ import annotations

import pandas as pd

from ..common.contact_sheet import render_contact_sheet
from ..common.decision import Decision, write_decision
from ..common.image_ops import laplacian_variance, load_rgb
from ..common.review import make_review_queue, write_review_queue
from ..metrics.tracks import get_track
from ..pipeline import _image_path, load


def run(ctx) -> None:
    if ctx.track != "t02":
        raise ValueError(f"T02 Laplacian baseline cannot run track {ctx.track!r}")

    spec = get_track(ctx.track)
    images = load(ctx)["images"]
    rows = []
    for row in images.itertuples(index=False):
        sharpness = laplacian_variance(load_rgb(_image_path(ctx, str(row.path))))
        rows.append(
            {
                "image_id": row.image_id,
                "score": 1.0 / (sharpness + 1e-6),
                "reason": "low_sharpness",
                "pred_action": "REVIEW",
                "path": str(row.path),
                "camera_id": row.camera_id,
                "light": row.light,
                "split": row.split,
            }
        )
    scored = pd.DataFrame(rows)
    ctx.stats["n_items"] = len(scored)
    queue = make_review_queue(
        scored,
        id_col="image_id",
        score_col="score",
        budget=int(ctx.param("budget", 20)),
        reason_col="reason",
        action_col="pred_action",
        slice_col="light",
        evidence_col="path",
    )
    write_review_queue(queue, ctx.out("review_queue.csv"))
    render_contact_sheet(
        queue,
        ctx.out("contact_sheet.html"),
        image_root=ctx.input_dir,
        title="T02 Laplacian baseline review queue",
    )
    scored[spec.pred_columns + ["reason", "pred_action"]].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(
        Decision(
            status="HOLD",
            reason_code="BASELINE_ONLY",
            reason="Baseline rankings require human review before any release decision.",
            owner="baseline",
            scope=ctx.track,
            evidence=[str(ctx.out(spec.pred_file))],
        ),
        ctx.out("decision.json"),
        ctx.out("decision_log.csv"),
    )
