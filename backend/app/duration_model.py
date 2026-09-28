"""
duration_model.py

Learns from past task completion data to predict how long a task will
actually take, given its category and original estimated duration.

Design
------
- Features: [estimated_duration, category_encoded]
  ``category`` is label-encoded so the model sees a numeric value.
  Unknown categories at prediction time map to a dedicated "unknown" bucket.

- Target: actual_duration

- Model: GradientBoostingRegressor
  Handles non-linear relationships and small, noisy datasets well.
  Falls back to LinearRegression if GBR is overkill for tiny logs.

- Persistence: joblib dump to backend/data/duration_model.joblib
  The artefact includes the trained model AND the label-encoder so
  prediction is self-contained.

Cold start
----------
When no trained model exists (or fewer than MIN_SAMPLES log entries
are available), predict_duration() returns estimated_duration * FALLBACK_RATIO.
The ratio is 1.0 (identity) by default but can be tuned if historical data
shows tasks consistently take longer than estimated.

Usage
-----
    from app.duration_model import train_duration_model, predict_duration

    # Train (call after enough log entries accumulate)
    train_duration_model()

    # Predict
    est = predict_duration(category="reading", estimated_duration=60)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR   = Path(__file__).parent.parent / "data"
MODEL_FILE = DATA_DIR / "duration_model.joblib"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum number of log entries required to train a model.
# Below this threshold predict_duration() returns the fallback.
MIN_SAMPLES: int = 5

# Fallback multiplier applied to estimated_duration when no model is available.
# 1.0 = return estimated_duration unchanged.
FALLBACK_RATIO: float = 1.0

# Category assigned to tasks whose category string is empty or unseen.
UNKNOWN_CATEGORY = "__unknown__"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_log() -> list[dict]:
    """Read completion_log.json and return the raw list of dicts."""
    from app.persistence import read_all_completions
    entries = read_all_completions()
    return [e.model_dump() for e in entries]


def _encode_categories(
    categories: list[str],
    existing_map: dict[str, int] | None = None,
) -> tuple[list[int], dict[str, int]]:
    """
    Label-encode a list of category strings.

    Parameters
    ----------
    categories    : raw category strings from the log
    existing_map  : mapping from a previously trained model (for inference)

    Returns
    -------
    (encoded_list, category_map)
    """
    if existing_map is not None:
        # Inference path: map unknowns to the UNKNOWN_CATEGORY bucket
        encoded = [
            existing_map.get(c, existing_map.get(UNKNOWN_CATEGORY, 0))
            for c in categories
        ]
        return encoded, existing_map

    # Training path: build mapping from scratch
    unique = sorted(set(categories)) + [UNKNOWN_CATEGORY]
    cat_map: dict[str, int] = {cat: i for i, cat in enumerate(unique)}
    encoded = [cat_map[c] for c in categories]
    return encoded, cat_map


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def train_duration_model() -> str:
    """
    Train a regression model on all completion log entries and save it to disk.

    Returns a human-readable status string (useful for logging / CLI output).

    Raises
    ------
    ValueError   If fewer than MIN_SAMPLES entries exist in the log.
    """
    import joblib
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import cross_val_score
    import numpy as np

    entries = _load_log()

    if len(entries) < MIN_SAMPLES:
        raise ValueError(
            f"Not enough data to train: {len(entries)} entries found, "
            f"need at least {MIN_SAMPLES}. Complete more tasks first."
        )

    categories        = [e.get("category") or UNKNOWN_CATEGORY for e in entries]
    estimated         = [e["estimated_duration"] for e in entries]
    actual            = [e["actual_duration"]    for e in entries]

    encoded_cats, cat_map = _encode_categories(categories)

    X = [[est, cat] for est, cat in zip(estimated, encoded_cats)]
    y = actual

    model = GradientBoostingRegressor(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.1,
        random_state=42,
    )
    model.fit(X, y)

    # Cross-val score for a quick sanity check (only meaningful with ≥10 samples)
    cv_note = ""
    if len(entries) >= 10:
        scores = cross_val_score(model, X, y, cv=min(5, len(entries)), scoring="r2")
        cv_note = f" | CV R²={np.mean(scores):.3f}"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    artefact = {"model": model, "category_map": cat_map}
    joblib.dump(artefact, MODEL_FILE)

    status = (
        f"Model trained on {len(entries)} samples"
        f"{cv_note} → saved to {MODEL_FILE}"
    )
    log.info(status)
    return status


def predict_duration(category: str, estimated_duration: int) -> int:
    """
    Predict how long a task will actually take.

    Parameters
    ----------
    category           : task category string (may be empty)
    estimated_duration : planned duration in minutes

    Returns
    -------
    Predicted duration in minutes (rounded to nearest integer).

    Cold-start behaviour
    --------------------
    If no trained model file exists, returns
    ``round(estimated_duration * FALLBACK_RATIO)`` — by default this is
    just ``estimated_duration`` unchanged, since FALLBACK_RATIO = 1.0.
    """
    import joblib

    if not MODEL_FILE.exists():
        log.debug(
            "No trained model found at %s — returning fallback prediction.", MODEL_FILE
        )
        return round(estimated_duration * FALLBACK_RATIO)

    try:
        artefact   = joblib.load(MODEL_FILE)
        model      = artefact["model"]
        cat_map: dict[str, int] = artefact["category_map"]

        norm_cat = category or UNKNOWN_CATEGORY
        encoded_cats, _ = _encode_categories([norm_cat], existing_map=cat_map)

        X = [[estimated_duration, encoded_cats[0]]]
        raw = model.predict(X)[0]

        # Clamp: prediction must be at least 1 minute and at most 8 hours
        predicted = max(1, min(round(float(raw)), 480))
        return predicted

    except Exception as exc:  # corrupted file, version mismatch, etc.
        log.warning("Failed to load/use trained model (%s) — using fallback.", exc)
        return round(estimated_duration * FALLBACK_RATIO)


# ---------------------------------------------------------------------------
# __main__ — quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print("predict_duration (cold start):", predict_duration("reading", 60))

    try:
        status = train_duration_model()
        print("Training:", status)
        print("predict_duration (model):", predict_duration("reading", 60))
    except ValueError as e:
        print(f"Training skipped: {e}")
        sys.exit(0)
