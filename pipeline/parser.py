#!/usr/bin/env python3
"""
parser.py — Parse vendor model-deprecation pages into normalized lifecycle records
PLUS the vendor's stated minimum-notice policy (the compliance half).

Extends the Model Lifecycle Watch parser (projects/model-lifecycle/pipeline/parser.py)
with:
  1. Policy extraction — the prose on each page that states minimum notice periods:
       OpenAI: "Generally available models: At least 6 months." (+ specialized 3mo,
               preview ~2wk)
       Anthropic: "providing at least 60 days' notice before model retirement for
               publicly released models"
  2. Anthropic deprecation-history parsing — the h3 section ids carry the
     announcement date ("2026-06-05-claude-opus-4-1-model"), which the original
     parser never captured for retired models. Without announced dates, notice
     intervals cannot be computed; this closes that gap.

Pure functions (HTML string in, (records, policy) out) so tests run offline.

Record shape (one per model family / model snapshot):
{
  "vendor": "Anthropic" | "OpenAI",
  "family": "Claude Opus 4.1",            # human-readable family name
  "model_id": "claude-opus-4-1-20250805",  # vendor model identifier(s)
  "status": "active" | "deprecated" | "retired",
  "announced": "2026-06-05",               # ISO date or None
  "retirement": "2026-08-05",              # ISO date or None
  "replacement": "claude-opus-4-8",        # recommended replacement or None
  "source_url": "https://...",             # vendor page this record came from
  "note": "..."                            # optional human note
}

Policy shape:
{
  "Anthropic": {
    "vendor": "Anthropic",
    "source_url": "...",
    "text": "<full notice-policy prose, verbatim>",
    "floors": [{"class": "publicly released models", "min": 60, "unit": "days",
                "quote": "at least 60 days' notice"}],
    "escape_hatch": "<quoted escape clause or null>"
  },
  "OpenAI": {
    "vendor": "OpenAI",
    "source_url": "...",
    "text": "<full prose>",
    "floors": [{"class": "ga", "min": 6, "unit": "months", "quote": "..."},
               {"class": "specialized", "min": 3, "unit": "months", "quote": "..."},
               {"class": "preview", "min": 2, "unit": "weeks", "quote": "..."}],
    "escape_hatch": "..."
  }
}
"""

from __future__ import annotations

import html as html_mod
import re
from datetime import date
from typing import List, Optional

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}
MONTHS_ABBR = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

ANTHROPIC_URL = "https://docs.claude.com/en/docs/about-claude/model-deprecations"
OPENAI_URL = "https://developers.openai.com/api/docs/deprecations"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _strip_tags(s: str) -> str:
    """Remove HTML tags, unescape entities, collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _text(html: str) -> str:
    """Whole-document text (scripts/styles stripped) for prose extraction."""
    s = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_us_date(s: str) -> Optional[str]:
    """'August 5, 2026' / 'Aug 5, 2026' / ISO '2026-02-17' -> '2026-02-17'.
    None if not parseable. (Vendor pages mix US-form and ISO dates across
    sections — the original parser accepted only US-form and silently dropped
    every ISO-dated retirement.)"""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", s)
    if m:
        mon = MONTHS.get(m.group(1)) or MONTHS_ABBR.get(m.group(1)[:3])
        if mon is not None:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    return None


def _today_iso() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

def _parse_not_sooner(s: str) -> Optional[str]:
    """'Not sooner than November 24, 2026' -> '2026-11-24'. None if not parseable."""
    if not s or "Not sooner than" not in s:
        return None
    return _parse_us_date(s.replace("Not sooner than", ""))


def _extract_anthropic_policy(text: str) -> dict:
    """Extract the stated minimum-notice policy from the page prose.

    The Notifications section states (verbatim, 2026-08-12):
      "Anthropic notifies customers with active deployments for models with
       upcoming retirements, providing at least 60 days' notice before model
       retirement for publicly released models."
    """
    m = re.search(
        r"Anthropic notifies customers with active deployments for models with "
        r"upcoming retirements, providing at least (\d+) days['\u2019]? notice "
        r"before model retirement for publicly released models",
        text,
    )
    if not m:
        # Broader fallback: any "at least N days' notice" sentence.
        m = re.search(r"at least (\d+) days['\u2019]? notice", text)
    if not m:
        return {
            "vendor": "Anthropic",
            "source_url": ANTHROPIC_URL,
            "text": None,
            "floors": [],
            "escape_hatch": None,
            "note": "No stated minimum-notice policy found on the page.",
        }
    days = int(m.group(1))
    quote = re.search(
        r"Anthropic notifies customers[^.]*", text
    )
    return {
        "vendor": "Anthropic",
        "source_url": ANTHROPIC_URL,
        "text": (quote.group(0).strip() if quote else "at least %d days' notice" % days),
        "floors": [{
            "class": "publicly released models",
            "min": days,
            "unit": "days",
            "quote": "at least %d days' notice" % days,
        }],
        "escape_hatch": None,
        "note": None,
    }


# Dated history headings, two layouts: Aug 2026 nests id="YYYY-MM-DD-<slug>" in a
# div inside the <h3>; Oct 2026 puts the id on the <h3> itself.
_DATED_H3 = re.compile(
    r'<h3\b[^>]*?\bid="(\d{4}-\d{2}-\d{2})-[^"]+"'
    r'|<h3[^>]*>\s*<div class="group relative pt-6 pb-2" id="(\d{4}-\d{2}-\d{2})-[^"]+"'
)
_STATUS_COLUMNS = ["API model name", "Current state", "Deprecated", "Tentative retirement date"]
_STATES = {"Active": "active", "Deprecated": "deprecated", "Retired": "retired"}


def _header(rows: List[str]) -> List[str]:
    return [_strip_tags(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], flags=re.S)] if rows else []


def parse_anthropic(html: str) -> tuple[List[dict], dict]:
    """
    Parse the Anthropic model-deprecations page. Returns (records, policy).

    1. Model status table, columns mapped by label:
         API model name | Current state | Deprecated | Tentative retirement date
       "Deprecated" holds the announcement date. States are Active / Deprecated /
       Retired; any other state, a missing column or a missing table stops the
       parse (fail closed).
    2. Replacement tables (Retirement date | Deprecated model | Recommended
       replacement), one per dated history section; the section's <h3> id is the
       announcement date. Models only found there (Claude 1.x/2.x, Instant,
       early 3.x) are emitted from it.
    """
    text = _text(html)
    policy = _extract_anthropic_policy(text)
    status_rows = None
    replacement_tables = []
    for match in re.finditer(r"<table[^>]*>(.*?)</table>", html, flags=re.S):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(1), flags=re.S)
        header = _header(rows)
        if header and header[0] == "API model name":
            missing = [c for c in _STATUS_COLUMNS if c not in header]
            if missing:
                raise ValueError(f"Anthropic status table: missing column(s) {missing}; header {header}")
            status_rows = (rows[1:], [header.index(c) for c in _STATUS_COLUMNS])
        elif header[:3] == ["Retirement date", "Deprecated model", "Recommended replacement"]:
            heads = list(_DATED_H3.finditer(html, 0, match.start()))
            announced = (heads[-1].group(1) or heads[-1].group(2)) if heads else None
            replacement_tables.append((rows[1:], announced))
    if status_rows is None:
        raise ValueError("Anthropic deprecations page: no model status table ('API model name' header) found")
    if not replacement_tables:
        raise ValueError("Anthropic deprecations page: no replacement tables found")

    records: List[dict] = []
    by_id: dict = {}
    rows, cols = status_rows
    for row in rows:
        cells = [_strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        if not cells:
            continue
        model_id, state, deprecated, retirement = [cells[i] if i < len(cells) else "" for i in cols]
        if not model_id:
            continue
        if state not in _STATES:
            raise ValueError(f"Anthropic status table: unknown state {state!r} for {model_id}")
        ret_iso = _parse_us_date(retirement) if retirement not in ("", "N/A", "To be announced") else None
        bound = _parse_not_sooner(retirement)
        if retirement not in ("", "N/A", "To be announced") and not ret_iso and not bound:
            raise ValueError(f"Anthropic status table: unreadable retirement {retirement!r} for {model_id}")
        rec = {
            "vendor": "Anthropic",
            "model_id": model_id,
            "status": _STATES[state],
            "stated_status": state,
            "announced": _parse_us_date(deprecated) if deprecated not in ("", "N/A") else None,
            "retirement": None if bound else ret_iso,
            "retirement_not_before": bound if state == "Active" else None,
            "replacement": None,
            "source_url": ANTHROPIC_URL,
            "note": None,
        }
        if rec["status"] == "active" and not bound:
            rec["note"] = "No retirement announced"
        elif rec["status"] == "deprecated" and not rec["retirement"]:
            rec["note"] = "Deprecated; retirement date to be announced"
        records.append(rec)
        by_id[model_id] = rec

    for rows, announced in replacement_tables:
        for row in rows:
            cells = [_strip_tags(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S)]
            if len(cells) < 3:
                continue
            ret_iso = _parse_us_date(cells[0])
            if not ret_iso:
                continue
            for old in re.split(r"[,\s]+", cells[1]):
                if not old:
                    continue
                if old in by_id:
                    have = by_id[old]
                    have["replacement"] = have["replacement"] or cells[2] or None
                    have["announced"] = have["announced"] or announced
                    continue
                rec = {
                    "vendor": "Anthropic",
                    "model_id": old,
                    "status": "retired" if ret_iso <= _today_iso() else "deprecated",
                    "announced": announced,
                    "retirement": ret_iso,
                    "retirement_not_before": None,
                    "replacement": cells[2] or None,
                    "source_url": ANTHROPIC_URL,
                    "note": None,
                }
                records.append(rec)
                by_id[old] = rec

    # Aug 2026 layout stated Mythos Preview's deprecation only in prose.
    m = re.search(r"Claude Mythos Preview\s*\(\s*(claude-mythos-preview)\s*\) is deprecated", text)
    if m and m.group(1) not in by_id:
        records.append({
            "vendor": "Anthropic",
            "model_id": m.group(1),
            "status": "deprecated",
            "stated_status": "Deprecated",
            "announced": None,
            "retirement": None,
            "retirement_not_before": None,
            "replacement": "claude-mythos-5",
            "source_url": ANTHROPIC_URL,
            "note": "Deprecated with no retirement date published; migration guide provided",
        })

    # Family name from model id (best effort: strip date suffix + version tail)
    # Model ids end in a compact YYYYMMDD date ("claude-opus-4-1-20250805");
    # the version digits before it are joined back with a dot ("Opus 4.1").
    for rec in records:
        mid = rec["model_id"]
        m = re.match(r"claude-(.+)-(\d{8})$", mid)
        if m:
            base = re.sub(r"\b(\d+)\s+(\d+)\b", r"\1.\2", m.group(1).replace("-", " "))
            rec["family"] = f"Claude {base.title()}"
            continue
        m = re.match(r"claude-(.+)$", mid)
        if m:
            base = re.sub(r"\b(\d+)\s+(\d+)\b", r"\1.\2", m.group(1).replace("-", " "))
            rec["family"] = "Claude " + base.title()
        else:
            rec["family"] = mid

    return records, policy


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def _extract_openai_policy(text: str) -> dict:
    """Extract the stated minimum-notice policy from the page prose.

    The "Model deprecation notice periods" section states (2026-08-12):
      "Generally available models: At least 6 months.
       Specialized variants of generally available models: At least 3 months.
       Preview models: Preview models, identified by preview in the model name,
       may be retired with much shorter notice, such as 2 weeks."
    """
    # Full section prose, verbatim
    m = re.search(
        r"(We provide advance notice before retiring models[^.]*\.)"
        r"(.*?)(?=We use the term)", text, flags=re.S
    )
    prose = m.group(0).strip() if m else None
    if prose:
        # The section's text runs up to the next section's first sentence; drop
        # that section's heading, which would otherwise end the quote.
        prose = re.sub(r"\s*Deprecation vs\. legacy\s*$", "", prose)

    floors = []
    m_ga = re.search(r"Generally available models:\s*At least (\d+) months?", text)
    if m_ga:
        floors.append({
            "class": "ga",
            "min": int(m_ga.group(1)),
            "unit": "months",
            "quote": "Generally available models: At least %s months" % m_ga.group(1),
        })
    m_spec = re.search(r"Specialized variants of generally available models:\s*At least (\d+) months?", text)
    if m_spec:
        floors.append({
            "class": "specialized",
            "min": int(m_spec.group(1)),
            "unit": "months",
            "quote": "Specialized variants of generally available models: At least %s months" % m_spec.group(1),
        })
    m_prev = re.search(r"Preview models[^.]*such as (\d+) weeks?", text)
    if m_prev:
        floors.append({
            "class": "preview",
            "min": int(m_prev.group(1)),
            "unit": "weeks",
            "quote": "Preview models, identified by preview in the model name, may be retired with much shorter notice, such as %s weeks" % m_prev.group(1),
        })

    escape = None
    m_esc = re.search(
        r"(If safety or compliance concerns require us to retire a model sooner[^.]*\.)",
        text,
    )
    if m_esc:
        escape = m_esc.group(1)

    if not floors:
        return {
            "vendor": "OpenAI",
            "source_url": OPENAI_URL,
            "text": prose,
            "floors": [],
            "escape_hatch": escape,
            "note": "No parseable minimum-notice floors found on the page.",
        }
    return {
        "vendor": "OpenAI",
        "source_url": OPENAI_URL,
        "text": prose,
        "floors": floors,
        "escape_hatch": escape,
        "note": None,
    }


def parse_openai(html: str) -> tuple[List[dict], dict]:
    """
    Parse the OpenAI API deprecations page.

    Model deprecation sections have the pattern:
        YYYY-MM-DD: <Title> ... <table>
        where the table has columns: Shutdown date | Model/system | Recommended replacement
    The section header date is the announcement (notification) date.
    """
    text = _text(html)
    policy = _extract_openai_policy(text)
    records: List[dict] = []
    for tbl in re.findall(r"<table[^>]*>(.*?)</table>", html, flags=re.S):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, flags=re.S)
        if not rows:
            continue
        header = [_strip_tags(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], flags=re.S)]
        # Replacement column may be headed "Recommended replacement",
        # "Recommended replacement base model", or "Substitute model"
        if not any(("replacement" in h.lower() or "substitute" in h.lower()) for h in header):
            continue
        try:
            i_date = next(i for i, h in enumerate(header) if "shut" in h.lower() or "retir" in h.lower())
            i_model = next(i for i, h in enumerate(header) if "model" in h.lower() or "system" in h.lower())
            i_repl = next(i for i, h in enumerate(header) if "replacement" in h.lower() or "substitute" in h.lower())
        except StopIteration:
            continue
        tbl_pos = html.find(tbl)
        before = html[max(0, tbl_pos - 30000):tbl_pos]
        m = re.findall(r"(\d{4}-\d{2}-\d{2}):", before)
        ann_date = m[-1] if m else None

        for row in rows[1:]:
            cells = [_strip_tags(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S)]
            if len(cells) <= max(i_date, i_model, i_repl):
                continue
            ret_date = _parse_us_date(cells[i_date])
            if not ret_date:
                continue
            for mid in re.split(r"[|,]+", cells[i_model]):
                mid = mid.strip()
                if not mid:
                    continue
                # Row-level exclusions:
                #  - API/system deprecations are not models (Assistants API,
                #    Videos API, /v1/engines, OpenAI-Beta: ...)
                #  - descriptive cells ("New fine-tuning training on babbage-002")
                #    are not model IDs — model IDs never contain spaces/equals
                if mid.startswith("/") or "api" in mid.lower() or mid.startswith("OpenAI-Beta"):
                    continue
                if " " in mid or "=" in mid or ":" in mid:
                    continue
                status = "retired" if ret_date <= _today_iso() else "deprecated"
                records.append({
                    "vendor": "OpenAI",
                    "family": mid,
                    "model_id": mid,
                    "status": status,
                    "announced": ann_date,
                    "retirement": ret_date,
                    "replacement": cells[i_repl] or None,
                    "source_url": OPENAI_URL,
                    "note": None,
                })

    seen = set()
    out = []
    for rec in records:
        key = (rec["model_id"], rec["retirement"])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out, policy


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import json
    import sys
    from pathlib import Path

    fixture = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if fixture:
        html = fixture.read_text(encoding="utf-8")
        if "claude" in fixture.name.lower():
            records, policy = parse_anthropic(html)
        else:
            records, policy = parse_openai(html)
        print(json.dumps({"records": records, "policy": policy}, indent=2))
        print(f"\n{len(records)} records", file=sys.stderr)
    else:
        print("usage: parser.py <html-fixture>", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
