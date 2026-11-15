import json

import numpy as np
import pandas as pd
import pytest

from src import main as runner
from src.common.context import RunContext
from src.pipeline import process


FIXTURE = "fixtures/t02_raw_qc"


def test_t02_pipeline_runs_and_applies_human_review(tmp_path):
    output = tmp_path / "poc"
    args = [
        "--track",
        "t02",
        "--input",
        FIXTURE,
        "--output",
        str(output),
        "--offline",
        "--seed",
        "42",
    ]
    assert runner.main(args) == 0

    predictions = pd.read_csv(output / "ranked_review.csv")
    queue = pd.read_csv(output / "review_queue.csv")
    assert len(predictions) == 96
    assert {"image_id", "score", "pred_action"}.issubset(predictions.columns)
    assert np.isfinite(predictions["score"]).all()
    assert len(queue) == 20
    assert (output / "contact_sheet.html").is_file()
    assert json.loads((output / "decision.json").read_text())["status"] == "HOLD"

    for column in ["reviewer", "reviewer_decision", "review_note"]:
        queue[column] = queue[column].astype(object)
    queue.loc[0, ["reviewer", "reviewer_decision", "review_note"]] = [
        "Test Reviewer", "approve", "Image checked and usable"
    ]
    queue.to_csv(output / "review_queue_reviewed.csv", index=False)
    assert runner.main(args) == 0

    predictions = pd.read_csv(output / "ranked_review.csv").set_index("image_id")
    reviewed_id = queue.loc[0, "item_id"]
    assert predictions.loc[reviewed_id, "pred_action"] == "KEEP"
    assert (output / "audit_log.jsonl").is_file()
    assert json.loads((output / "decision.json").read_text())["reason_code"] == "HUMAN_REVIEW_INCOMPLETE"


def test_t02_go_requires_all_priority_items_to_be_kept(tmp_path):
    output = tmp_path / "poc"
    args = [
        "--track",
        "t02",
        "--input",
        FIXTURE,
        "--output",
        str(output),
        "--offline",
        "--seed",
        "42",
    ]
    assert runner.main(args) == 0
    queue_path = output / "review_queue.csv"
    queue = pd.read_csv(queue_path)
    for column in ["reviewer", "reviewer_decision", "review_note"]:
        queue[column] = queue[column].astype(object)
    queue["reviewer"] = "Test Reviewer"
    queue["reviewer_decision"] = "approve"
    queue["review_note"] = "Checked and usable"
    queue.to_csv(output / "review_queue_reviewed.csv", index=False)

    assert runner.main(args) == 0
    decision = json.loads((output / "decision.json").read_text())
    assert decision["status"] == "GO"
    assert decision["reason_code"] == "PRIORITY_QUEUE_KEPT"


def test_t02_pipeline_rejects_paths_outside_input(tmp_path):
    ctx = RunContext(
        track="t02",
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        config={},
        seed=42,
        rng=np.random.default_rng(42),
    )
    images = pd.DataFrame(
        [
            {
                "image_id": "sample",
                "path": "../outside.jpg",
                "camera_id": "cam_A",
                "light": "day",
                "split": "dev",
            }
        ]
    )
    with pytest.raises(ValueError, match="escapes input directory"):
        process(ctx, {"images": images})


def test_t02_laplacian_baseline_writes_prediction_contract(tmp_path):
    output = tmp_path / "baseline"
    assert runner.main(
        [
            "--track",
            "t02",
            "--input",
            FIXTURE,
            "--pipeline",
            "src.examples.t02_laplacian_baseline",
            "--output",
            str(output),
            "--offline",
            "--seed",
            "42",
        ]
    ) == 0
    predictions = pd.read_csv(output / "ranked_review.csv")
    assert len(predictions) == 96
    assert {"image_id", "score"}.issubset(predictions.columns)
    assert np.isfinite(predictions["score"]).all()
