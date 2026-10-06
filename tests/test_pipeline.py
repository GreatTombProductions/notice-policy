#!/usr/bin/env python3
"""Tests for the notice-policy pipeline (parser + compliance math). Run: pytest tests/"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from parser import parse_anthropic, parse_openai  # noqa: E402
from generate import _add_months, _floor_days, _notice_days, _compute_models  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

def test_anthropic_policy_extraction():
    records, policy = parse_anthropic(load("anthropic-fixture.html"))
    assert policy["vendor"] == "Anthropic"
    assert len(policy["floors"]) == 1
    assert policy["floors"][0]["min"] == 60
    assert policy["floors"][0]["unit"] == "days"


def test_anthropic_lifecycle_table():
    records, _ = parse_anthropic(load("anthropic-fixture.html"))
    by_id = {r["model_id"]: r for r in records}
    # Active model: availability guarantee, no retirement
    assert by_id["claude-opus-5"]["status"] == "active"
    assert by_id["claude-opus-5"]["retirement_not_before"] == "2027-07-24"
    # Retired model in lifecycle table
    assert by_id["claude-opus-4-20250514"]["status"] == "retired"
    assert by_id["claude-opus-4-20250514"]["announced"] == "2026-04-14"
    assert by_id["claude-opus-4-20250514"]["retirement"] == "2026-06-15"


def test_anthropic_history_announced_dates():
    """History section ids supply announced dates for retired models — the
    gap the original Model Lifecycle Watch parser never closed."""
    records, _ = parse_anthropic(load("anthropic-fixture.html"))
    by_id = {r["model_id"]: r for r in records}
    rec = by_id["claude-opus-4-1-20250805"]
    assert rec["status"] == "retired"
    assert rec["announced"] == "2026-06-05"
    assert rec["retirement"] == "2026-08-05"
    assert rec["replacement"] == "claude-opus-4-8"  # merged from history table


def test_anthropic_dedupe_lifecycle_and_history():
    records, _ = parse_anthropic(load("anthropic-fixture.html"))
    ids = [r["model_id"] for r in records]
    assert ids.count("claude-opus-4-1-20250805") == 1
    assert ids.count("claude-3-haiku-20240307") == 1


def test_anthropic_mythos_deprecated_no_retirement():
    records, _ = parse_anthropic(load("anthropic-fixture.html"))
    mythos = [r for r in records if r["model_id"] == "claude-mythos-preview"]
    assert len(mythos) == 1
    assert mythos[0]["status"] == "deprecated"
    assert mythos[0]["retirement"] is None


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def test_openai_policy_extraction():
    records, policy = parse_openai(load("openai-fixture.html"))
    floors = {f["class"]: f for f in policy["floors"]}
    assert floors["ga"]["min"] == 6 and floors["ga"]["unit"] == "months"
    assert floors["specialized"]["min"] == 3
    assert floors["preview"]["min"] == 2 and floors["preview"]["unit"] == "weeks"
    assert policy["escape_hatch"] is not None
    assert "safety or compliance" in policy["escape_hatch"]


def test_openai_us_and_iso_dates():
    """Both US-form ('January 20, 2027') and ISO ('2026-02-17') shutdown dates
    must parse — the original parser dropped every ISO-dated retirement."""
    records, _ = parse_openai(load("openai-fixture.html"))
    by_id = {r["model_id"]: r for r in records}
    assert by_id["gpt-audio"]["retirement"] == "2027-01-20"
    assert by_id["chatgpt-4o-latest"]["retirement"] == "2026-02-17"
    assert by_id["text-ada-001"]["retirement"] == "2024-01-04"


def test_openai_substitute_model_table():
    records, _ = parse_openai(load("openai-fixture.html"))
    by_id = {r["model_id"]: r for r in records}
    assert by_id["gpt-5-chat-latest"]["announced"] == "2026-04-22"
    assert by_id["gpt-5-chat-latest"]["retirement"] == "2026-07-23"
    # Pipe-separated multi-model cells split correctly
    assert by_id["gpt-4o-2024-05-13"]["retirement"] == "2026-07-23"
    assert by_id["gpt-4o-2024-08-06"]["retirement"] == "2026-07-23"


def test_openai_system_rows_excluded():
    """API/system deprecations (Assistants API, OpenAI-Beta:, descriptive
    cells) must not appear as model records."""
    records, _ = parse_openai(load("openai-fixture.html"))
    ids = {r["model_id"] for r in records}
    assert "Assistants API" not in ids
    assert "OpenAI-Beta" not in ids
    assert "Realtime API" not in ids
    assert "text-ada-001" in ids  # real models survive


def test_openai_announced_dates_per_section():
    records, _ = parse_openai(load("openai-fixture.html"))
    by_id = {r["model_id"]: r for r in records}
    assert by_id["chatgpt-4o-latest"]["announced"] == "2025-11-18"
    assert by_id["text-ada-001"]["announced"] == "2023-07-06"
    assert by_id["gpt-audio"]["announced"] == "2026-07-20"


# ---------------------------------------------------------------------------
# Compliance math
# ---------------------------------------------------------------------------

def test_add_months_calendar_arithmetic():
    assert _add_months("2026-05-08", 6).isoformat() == "2026-11-08"
    assert _add_months("2026-11-18", 6).isoformat() == "2027-05-18"
    # month-end clamp
    assert _add_months("2026-08-31", 1).isoformat() == "2026-09-30"


def test_notice_days():
    assert _notice_days("2026-05-08", "2026-08-10") == 94
    assert _notice_days("2026-02-19", "2026-04-20") == 60


def test_floor_days_units():
    assert _floor_days("2026-05-08", {"min": 6, "unit": "months"}) == 184
    assert _floor_days("2026-05-08", {"min": 2, "unit": "weeks"}) == 14
    assert _floor_days("2026-05-08", {"min": 60, "unit": "days"}) == 60


def _policy(vendor):
    return {
        "OpenAI": {
            "floors": [
                {"class": "ga", "min": 6, "unit": "months", "quote": "GA"},
                {"class": "specialized", "min": 3, "unit": "months", "quote": "spec"},
                {"class": "preview", "min": 2, "unit": "weeks", "quote": "prev"},
            ]
        },
        "Anthropic": {
            "floors": [{"class": "publicly released models", "min": 60, "unit": "days", "quote": "60d"}]
        },
    }


def test_verdict_short_vs_ga_floor():
    recs = [{
        "vendor": "OpenAI", "model_id": "gpt-5.2-chat-latest", "family": "gpt-5.2",
        "status": "retired", "announced": "2026-05-08", "retirement": "2026-08-10",
        "replacement": "x", "source_url": "u",
    }]
    out = _compute_models(recs, _policy("OpenAI"))
    assert out[0]["notice_days"] == 94
    assert out[0]["verdicts"]["ga"]["verdict"] == "SHORT"
    assert out[0]["verdicts"]["specialized"]["verdict"] == "PASS"
    assert out[0]["primary_floor"] == "ga"
    assert out[0]["primary_verdict"] == "SHORT"


def test_verdict_pass_at_floor():
    recs = [{
        "vendor": "Anthropic", "model_id": "claude-3-haiku-20240307", "family": "Haiku",
        "status": "retired", "announced": "2026-02-19", "retirement": "2026-04-20",
        "replacement": "x", "source_url": "u",
    }]
    out = _compute_models(recs, _policy("Anthropic"))
    assert out[0]["notice_days"] == 60
    assert out[0]["primary_verdict"] == "PASS"


def test_preview_model_uses_preview_floor():
    recs = [{
        "vendor": "OpenAI", "model_id": "gpt-4o-realtime-preview-2024-10-01", "family": "preview",
        "status": "retired", "announced": "2025-09-15", "retirement": "2026-05-12",
        "replacement": "x", "source_url": "u",
    }]
    out = _compute_models(recs, _policy("OpenAI"))
    assert out[0]["is_preview"] is True
    assert out[0]["primary_floor"] == "preview"
    assert out[0]["primary_verdict"] == "PASS"  # 239 days >> 14


def test_missing_announced_is_null_never_assumed():
    recs = [{
        "vendor": "Anthropic", "model_id": "claude-1-0", "family": "Claude 1.0",
        "status": "retired", "announced": None, "retirement": "2024-11-06",
        "replacement": "x", "source_url": "u",
    }]
    out = _compute_models(recs, _policy("Anthropic"))
    assert out[0]["notice_days"] is None
    assert out[0]["primary_verdict"] is None
    assert "not computable" in out[0]["note"]
