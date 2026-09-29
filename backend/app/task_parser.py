"""
task_parser.py

Parse a free-text task description into a structured FlexibleTask-shaped dict.

Two modes
---------
LLM mode (when GROQ_API_KEY env var is set)
    Calls the Groq chat completions API (qwen/qwen3.8-27b) with a
    strict JSON-only prompt.  Returns a dict with only the fields the LLM
    can confidently infer.

Heuristic mode (default / cold start / no API key)
    A lightweight rule-based extractor that handles the most common patterns:
    - Time range: "from 11am to 5pm", "10:00am-11:30am"
    - Duration: "30 min", "1 hour", "45 minutes", "2h"
    - Deadline: "today", "tomorrow", "by 3pm", "before 5:30"
    - Priority: "urgent", "important", "low priority", "asap"
    Both modes produce the same output schema.

Output schema
-------------
{
    "title":          str | None,
    "duration":       int | None,   # minutes
    "deadline":       int | None,   # minutes since midnight
    "priority":       int | None,   # 1–10
    "category":       str | None,
    "earliest_start": int | None,
    "latest_end":     int | None,
}

Unknown fields are always null — never guessed.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a task parser for a scheduling app called FlowDay.
Given a free-text task description, extract structured fields and return ONLY
valid JSON — no markdown, no explanation, no code block.

Return ONLY these fields (use null for anything you cannot confidently infer):
{
  "title":          string,       // concise task name
  "duration":       integer|null, // estimated duration in minutes
  "deadline":       integer|null, // minutes since midnight (e.g. 14:00 = 840)
  "priority":       integer|null, // 1 (low) to 10 (urgent)
  "category":       string|null,  // e.g. "reading", "exercise", "admin"
  "earliest_start": integer|null, // minutes since midnight
  "latest_end":     integer|null  // minutes since midnight
}

Rules:
- Convert times to minutes-since-midnight. 9am=540, 3pm=900, 11pm=1380.
- "today" means deadline=end of day (1380). "tomorrow" → null (no same-day deadline).
- "urgent" or "asap" → priority 9. "important" → 7. "low" → 3. Default → null.
- Duration: "30 min"→30, "1 hour"→60, "1.5h"→90. If unclear → null.
- Output ONLY the JSON object, nothing else.
"""


# ---------------------------------------------------------------------------
# Heuristic parser (no API key required)
# ---------------------------------------------------------------------------

def _heuristic_parse(text: str) -> dict[str, Any]:
    t = text.strip()
    result: dict[str, Any] = {
        "title":          None,
        "duration":       None,
        "deadline":       None,
        "priority":       None,
        "category":       None,
        "earliest_start": None,
        "latest_end":     None,
    }

    lower = t.lower()

    # ── Helper: parse a time expression like "11am", "5pm", "11:30am", "17:00" ──
    def _parse_time_expr(h_str: str, m_str: str | None, mer: str | None) -> int:
        h = int(h_str)
        m = int(m_str) if m_str else 0
        if mer == "pm" and h < 12:
            h += 12
        elif mer == "am" and h == 12:
            h = 0
        return h * 60 + m

    # ── Range: "from 11am to 5pm", "11:00am to 5pm", "11am-5pm" ────────
    range_match = re.search(
        r"(?:from\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|-)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        lower,
    )
    if range_match:
        start_min = _parse_time_expr(
            range_match.group(1), range_match.group(2), range_match.group(3)
        )
        end_min = _parse_time_expr(
            range_match.group(4), range_match.group(5), range_match.group(6)
        )
        if end_min > start_min:
            result["earliest_start"] = start_min
            result["latest_end"]     = end_min
            result["duration"]       = end_min - start_min

    # ── Duration (only if not already set by range) ─────────────────────
    if result["duration"] is None:
        dur_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:hour|hr|h)\b|(\d+)\s*(?:min(?:ute)?s?)\b",
            lower,
        )
        if dur_match:
            if dur_match.group(1):
                result["duration"] = round(float(dur_match.group(1)) * 60)
            else:
                result["duration"] = int(dur_match.group(2))

    # ── Deadline (same-day only) ─────────────────────────────────────────
    # "today", "by 3pm", "before 5:30", "due at 14:00"
    if "today" in lower and not re.search(r"tomorrow", lower):
        result["deadline"] = 1380  # 23:00 default

    time_match = re.search(
        r"(?:by|before|due|at)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        lower,
    )
    if time_match:
        h   = int(time_match.group(1))
        m   = int(time_match.group(2) or 0)
        mer = time_match.group(3)
        if mer == "pm" and h < 12:
            h += 12
        elif mer == "am" and h == 12:
            h = 0
        result["deadline"] = h * 60 + m

    # ── Priority ─────────────────────────────────────────────────────────
    priority_map = {
        "urgent": 9, "asap": 9, "critical": 10, "emergency": 10,
        "important": 7, "high priority": 8,
        "low priority": 2, "low": 3, "whenever": 2,
    }
    for keyword, pval in priority_map.items():
        if keyword in lower:
            result["priority"] = pval
            break

    # ── Category (simple keyword matching) ───────────────────────────────
    category_keywords = {
        "read":      "reading",
        "chapter":   "reading",
        "book":      "reading",
        "exercise":  "exercise",
        "workout":   "exercise",
        "gym":       "exercise",
        "run":       "exercise",
        "email":     "admin",
        "reply":     "admin",
        "call":      "admin",
        "meeting":   "admin",
        "study":     "study",
        "exam":      "study",
        "lecture":   "study",
        "homework":  "study",
        "assignment":"study",
        "code":      "coding",
        "program":   "coding",
        "develop":   "coding",
        "write":     "writing",
        "essay":     "writing",
        "report":    "writing",
    }
    for kw, cat in category_keywords.items():
        if kw in lower:
            result["category"] = cat
            break

    # ── Title (strip the extractable parts, use remainder as title) ──────
    # Simple approach: use the full text trimmed to 80 chars as title
    result["title"] = t[:80] if t else None

    return result


# ---------------------------------------------------------------------------
# LLM parser (Groq)
# ---------------------------------------------------------------------------

def _llm_parse(text: str) -> dict[str, Any]:
    """Call Groq chat completions and parse the JSON response."""
    try:
        from groq import Groq  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "groq package not installed. "
            "Run: pip install groq"
        )

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": text},
        ],
        temperature=0,
        max_tokens=256,
    )

    raw = response.choices[0].message.content or ""
    return _parse_json_response(raw)


def _parse_json_response(raw: str) -> dict[str, Any]:
    """
    Extract and validate a JSON object from the LLM's raw response.
    Handles markdown code fences and trailing text.
    """
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Find the first JSON object in the text
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {raw!r}")

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    # Validate and coerce types — unknown fields silently dropped
    allowed_int  = {"duration", "deadline", "priority", "earliest_start", "latest_end"}
    allowed_str  = {"title", "category"}
    result: dict[str, Any] = {}

    for field in allowed_int:
        val = parsed.get(field)
        if val is None:
            result[field] = None
        else:
            try:
                result[field] = int(val)
            except (TypeError, ValueError):
                result[field] = None

    for field in allowed_str:
        val = parsed.get(field)
        result[field] = str(val).strip() if val is not None else None

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_task_text(text: str) -> dict[str, Any]:
    """
    Parse a free-text task description into structured fields.

    Uses the Groq LLM path when GROQ_API_KEY is set, otherwise falls back
    to the heuristic parser.  Both paths return the same dict schema.

    Raises ValueError with a clear message on malformed LLM responses.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()

    if api_key:
        log.info("parse_task_text: using Groq LLM parser")
        return _llm_parse(text)
    else:
        log.info("parse_task_text: using heuristic parser (no GROQ_API_KEY set)")
        return _heuristic_parse(text)
