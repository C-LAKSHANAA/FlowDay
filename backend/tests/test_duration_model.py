"""
tests/test_duration_model.py

Tests for the duration prediction model.

Each test that touches the filesystem uses a tmp_path fixture so the
real completion_log.json and model file are never affected.
"""

import json
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_log(path: Path, entries: list[dict]) -> None:
    """Write a list of log-entry dicts to a JSON file."""
    path.write_text(json.dumps(entries), encoding="utf-8")


def _make_entry(
    task_id="t1",
    task_title="Test task",
    estimated_duration=60,
    actual_duration=70,
    category="study",
    completed_at="2026-01-01T09:00:00+00:00",
) -> dict:
    return dict(
        task_id=task_id,
        task_title=task_title,
        estimated_duration=estimated_duration,
        actual_duration=actual_duration,
        category=category,
        completed_at=completed_at,
    )


# ---------------------------------------------------------------------------
# 1. test_cold_start_returns_estimated_duration
#    With no model file, predict_duration() returns estimated_duration.
# ---------------------------------------------------------------------------

def test_cold_start_returns_estimated_duration(tmp_path, monkeypatch):
    """
    When no trained model exists, predict_duration must return the
    estimated_duration unchanged (FALLBACK_RATIO = 1.0).
    """
    import app.duration_model as dm
    monkeypatch.setattr(dm, "MODEL_FILE", tmp_path / "no_model.joblib")

    result = dm.predict_duration(category="reading", estimated_duration=45)
    assert result == 45, f"Expected 45 (cold start fallback), got {result}"


def test_cold_start_different_categories(tmp_path, monkeypatch):
    """Cold start must be consistent regardless of category."""
    import app.duration_model as dm
    monkeypatch.setattr(dm, "MODEL_FILE", tmp_path / "no_model.joblib")

    for cat in ("reading", "exercise", "assignment", "", "unknown-cat"):
        result = dm.predict_duration(category=cat, estimated_duration=90)
        assert result == 90, f"Category '{cat}': expected 90, got {result}"


# ---------------------------------------------------------------------------
# 2. test_train_raises_with_too_few_entries
#    Training raises ValueError when fewer than MIN_SAMPLES entries exist.
# ---------------------------------------------------------------------------

def test_train_raises_with_too_few_entries(tmp_path, monkeypatch):
    import app.duration_model as dm
    import app.persistence as pers

    # Point both to tmp files
    log_file   = tmp_path / "completion_log.json"
    model_file = tmp_path / "duration_model.joblib"
    monkeypatch.setattr(dm,   "MODEL_FILE", model_file)
    monkeypatch.setattr(pers, "LOG_FILE",   log_file)
    monkeypatch.setattr(pers, "DATA_DIR",   tmp_path)

    # Write 2 entries — below MIN_SAMPLES (5)
    _write_log(log_file, [_make_entry(f"t{i}") for i in range(2)])

    with pytest.raises(ValueError, match="Not enough data"):
        dm.train_duration_model()


# ---------------------------------------------------------------------------
# 3. test_train_and_predict_with_sufficient_data
#    After training on sufficient entries, predict_duration returns a
#    reasonable value and the model file is created.
# ---------------------------------------------------------------------------

def test_train_and_predict_with_sufficient_data(tmp_path, monkeypatch):
    import app.duration_model as dm
    import app.persistence as pers

    log_file   = tmp_path / "completion_log.json"
    model_file = tmp_path / "duration_model.joblib"
    monkeypatch.setattr(dm,   "MODEL_FILE", model_file)
    monkeypatch.setattr(pers, "LOG_FILE",   log_file)
    monkeypatch.setattr(pers, "DATA_DIR",   tmp_path)

    # 10 entries: reading tasks that consistently overrun by ~10 min
    entries = [
        _make_entry(
            task_id=f"t{i}",
            estimated_duration=60,
            actual_duration=70,
            category="reading",
        )
        for i in range(10)
    ]
    _write_log(log_file, entries)

    status = dm.train_duration_model()

    assert model_file.exists(), "Model file should be created after training"
    assert "trained on 10" in status.lower()

    # Predict for a reading task with est=60 — model should predict ~70
    prediction = dm.predict_duration(category="reading", estimated_duration=60)
    assert isinstance(prediction, int), "Prediction must be an integer"
    # Allow generous range: somewhere between 50 and 90 is reasonable
    assert 50 <= prediction <= 90, (
        f"Prediction {prediction} is outside expected range [50, 90]"
    )


# ---------------------------------------------------------------------------
# 4. test_predict_unknown_category_does_not_crash
#    An unseen category at prediction time should not crash.
# ---------------------------------------------------------------------------

def test_predict_unknown_category_does_not_crash(tmp_path, monkeypatch):
    import app.duration_model as dm
    import app.persistence as pers

    log_file   = tmp_path / "completion_log.json"
    model_file = tmp_path / "duration_model.joblib"
    monkeypatch.setattr(dm,   "MODEL_FILE", model_file)
    monkeypatch.setattr(pers, "LOG_FILE",   log_file)
    monkeypatch.setattr(pers, "DATA_DIR",   tmp_path)

    # Train on "study" only
    entries = [
        _make_entry(task_id=f"t{i}", category="study",
                    estimated_duration=60, actual_duration=65)
        for i in range(6)
    ]
    _write_log(log_file, entries)
    dm.train_duration_model()

    # Predict with a completely new category — must not raise
    result = dm.predict_duration(category="totally-new-category", estimated_duration=45)
    assert isinstance(result, int)
    assert result >= 1


# ---------------------------------------------------------------------------
# 5. test_prediction_clamped_to_valid_range
#    Predictions are clamped to [1, 480] minutes regardless of model output.
# ---------------------------------------------------------------------------

def test_prediction_clamped_to_valid_range(tmp_path, monkeypatch):
    """Clamp lower bound: model returning a negative raw value → at least 1."""
    import app.duration_model as dm

    # Patch the model file to "exist" and patch joblib.load to return
    # a namespace with a model that produces a negative prediction.
    import types, joblib as _joblib_real

    model_file = tmp_path / "fake.joblib"
    model_file.write_bytes(b"placeholder")  # makes MODEL_FILE.exists() True
    monkeypatch.setattr(dm, "MODEL_FILE", model_file)

    fake_artefact = {
        "model": types.SimpleNamespace(predict=lambda X: [-999.0]),
        "category_map": {"study": 0, dm.UNKNOWN_CATEGORY: 1},
    }
    monkeypatch.setattr(dm, "joblib", types.SimpleNamespace(load=lambda p: fake_artefact),
                        raising=False)

    # The predict function imports joblib locally; patch it in the module
    import importlib
    original_load = None

    def _fake_load(path):
        return fake_artefact

    monkeypatch.setattr("joblib.load", _fake_load)

    result = dm.predict_duration(category="study", estimated_duration=60)
    assert result >= 1, f"Prediction must be clamped to >= 1, got {result}"


def test_prediction_clamped_upper_bound(tmp_path, monkeypatch):
    """Clamp upper bound: model returning a huge raw value → at most 480."""
    import app.duration_model as dm
    import types

    model_file = tmp_path / "fake.joblib"
    model_file.write_bytes(b"placeholder")
    monkeypatch.setattr(dm, "MODEL_FILE", model_file)

    fake_artefact = {
        "model": types.SimpleNamespace(predict=lambda X: [99999.0]),
        "category_map": {"study": 0, dm.UNKNOWN_CATEGORY: 1},
    }
    monkeypatch.setattr("joblib.load", lambda p: fake_artefact)

    result = dm.predict_duration(category="study", estimated_duration=60)
    assert result <= 480, f"Prediction must be clamped to <= 480, got {result}"


# ---------------------------------------------------------------------------
# 6. test_corrupted_model_file_falls_back
#    A corrupted/unreadable model file should fall back gracefully.
# ---------------------------------------------------------------------------

def test_corrupted_model_file_falls_back(tmp_path, monkeypatch):
    import app.duration_model as dm

    corrupt_file = tmp_path / "corrupt.joblib"
    corrupt_file.write_bytes(b"this is not a valid joblib file")
    monkeypatch.setattr(dm, "MODEL_FILE", corrupt_file)

    result = dm.predict_duration(category="reading", estimated_duration=75)
    assert result == 75, (
        f"Corrupted model should fall back to estimated_duration (75), got {result}"
    )
