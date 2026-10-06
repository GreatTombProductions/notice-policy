#!/usr/bin/env python3
"""
generate.py — Compute notice-policy compliance from parsed vendor records.

For every model with an announcement date and a retirement (shutdown) date:
  notice_days = retirement - announced
Compared against the vendor's OWN stated minimum-notice floors:
  OpenAI:  GA 6 months | specialized 3 months | preview ~2 weeks
           (calendar-month arithmetic for month floors; the page's own
            preview criterion — "preview" in the model name — selects the
            preview floor as the model's primary floor)
  Anthropic: 60 days for publicly released models

Honesty rules (S119 discipline):
  - A model without an announcement date on the page gets notice_days=null and
    verdicts=null, labeled "no announcement date on page" — never assumed.
  - A vendor with no parseable policy is listed as a documented gap, never clean.
  - The safety/compliance escape hatch in OpenAI's policy is quoted verbatim
    in the output; the tool reports the record, not the excuse.

Output: data/compliance.json
{
  "generated_at", "as_of",
  "sources": [{"vendor", "url", "status", "fetched_at", "bytes", "note"}],
  "policies": {"Anthropic": {...}, "OpenAI": {...}, "DeepSeek": {...}},
  "models": [ {...compliance records...} ],
  "track_records": {"OpenAI": {...}, "Anthropic": {...}}
}
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import (  # noqa: E402
    ANTHROPIC_URL,
    OPENAI_URL,
    parse_anthropic,
    parse_openai,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_PATH = DATA_DIR / "compliance.json"

DEEPSEEK_NOTE = (
    "DeepSeek publishes no model deprecation page and no notice policy, so no "
    "notice interval or floor is computable. Listed as a documented gap, not hidden."
)
PIN = Path(__file__).resolve().parent / "expected_semantics.json"


# ---------------------------------------------------------------------------
# floor math
# ---------------------------------------------------------------------------

def _add_months(iso_date: str, months: int) -> date:
    """Calendar-month arithmetic: 2026-05-08 + 6 months = 2026-11-08.
    Day is clamped to the target month's last day when needed."""
    y, m, d = (int(x) for x in iso_date.split("-"))
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    nd = min(d, calendar.monthrange(ny, nm)[1])
    return date(ny, nm, nd)


def _floor_days(announced: str, floor: dict) -> int:
    """Concrete minimum-notice days for a floor given the announcement date.
    Month floors use calendar arithmetic (the truest reading of '6 months');
    week/day floors are flat."""
    unit = floor.get("unit")
    if unit == "months":
        return (_add_months(announced, floor["min"]) - date.fromisoformat(announced)).days
    if unit == "weeks":
        return floor["min"] * 7
    return floor["min"]


def _notice_days(announced: str, retirement: str) -> int:
    return (date.fromisoformat(retirement) - date.fromisoformat(announced)).days


# ---------------------------------------------------------------------------
# compliance records
# ---------------------------------------------------------------------------

def _compute_models(records: list, policies: dict) -> list:
    out = []
    for rec in records:
        status = rec["status"]
        if status == "active":
            continue  # no retirement obligation yet
        ann, ret = rec.get("announced"), rec.get("retirement")
        compliance = {
            "vendor": rec["vendor"],
            "model_id": rec["model_id"],
            "family": rec.get("family") or rec["model_id"],
            "status": status,
            "announced": ann,
            "retirement": ret,
            "replacement": rec.get("replacement"),
            "source_url": rec.get("source_url"),
        }
        if not (ann and ret):
            compliance.update({
                "notice_days": None,
                "floors": [],
                "verdicts": {},
                "primary_floor": None,
                "primary_verdict": None,
                "note": ("No retirement date published — notice interval not computable" if ann
                         else "No announcement date on vendor page — notice interval not computable"),
            })
            out.append(compliance)
            continue

        notice = _notice_days(ann, ret)
        floors = policies[rec["vendor"]]["floors"]
        is_preview = "preview" in rec["model_id"].lower()
        verdicts = {}
        for fl in floors:
            floor_days = _floor_days(ann, fl)
            verdicts[fl["class"]] = {
                "floor_days": floor_days,
                "verdict": "PASS" if notice >= floor_days else "SHORT",
            }
        # Primary floor: preview-named models are judged on the preview floor
        # (the vendor's own criterion), everything else on the GA floor.
        if is_preview and "preview" in verdicts:
            primary = "preview"
        else:
            primary = "ga" if "ga" in verdicts else ("publicly released models" if "publicly released models" in verdicts else None)
        compliance.update({
            "notice_days": notice,
            "floors": [{"class": fl["class"], "floor_days": _floor_days(ann, fl)} for fl in floors],
            "verdicts": verdicts,
            "primary_floor": primary,
            "primary_verdict": verdicts.get(primary, {}).get("verdict") if primary else None,
            "is_preview": is_preview,
            "note": None,
        })
        out.append(compliance)
    return out


def _track_record(models: list, vendor: str, floors: list) -> dict:
    """Per-vendor summary over models with computable notice."""
    vm = [m for m in models if m["vendor"] == vendor and m["notice_days"] is not None]
    days = [m["notice_days"] for m in vm]
    if not days:
        return {
            "with_notice": 0, "min_days": None, "max_days": None,
            "median_days": None, "below_floor": {},
            "by_status": {"retired": 0, "deprecated": 0},
        }
    by_status = {"retired": 0, "deprecated": 0}
    for m in vm:
        by_status[m["status"]] = by_status.get(m["status"], 0) + 1
    below = {}
    for fl in floors:
        n_below = 0
        for m in vm:
            fdays = _floor_days(m["announced"], fl)
            if m["notice_days"] < fdays:
                n_below += 1
        below[fl["class"]] = n_below
    return {
        "with_notice": len(days),
        "min_days": min(days),
        "max_days": max(days),
        "median_days": round(statistics.median(days), 1),
        "below_floor": below,
        "by_status": by_status,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Build data/compliance.json from the pinned captures in data/raw/.")
    ap.add_argument("--accept-source-change", action="store_true",
                    help="replace the semantic pin after inspecting the parsed records and policies")
    args = ap.parse_args()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    sources = []
    policies = {}
    all_models = []
    semantics = {}

    for vendor, url, parser in (
        ("Anthropic", ANTHROPIC_URL, parse_anthropic),
        ("OpenAI", OPENAI_URL, parse_openai),
    ):
        slug = vendor.lower()
        captures = sorted(RAW_DIR.glob(f"{slug}-*.html"))
        failures = sorted(RAW_DIR.glob(f"{slug}-*.failed"))
        if not captures:
            raise RuntimeError(f"no {vendor} capture; run pipeline/fetch.py")
        raw_path = captures[-1]
        if failures and failures[-1].stem > raw_path.stem:
            raise RuntimeError(f"newest {vendor} capture failed ({failures[-1].name}); re-fetch before building")
        receipt = raw_path.with_suffix(".sha256")
        if not receipt.exists():
            raise RuntimeError(f"no receipt for {raw_path.name}")
        body = raw_path.read_bytes()
        sha = hashlib.sha256(body).hexdigest()
        if receipt.read_text(encoding="utf-8").split()[0] != sha:
            raise RuntimeError(f"receipt mismatch for {raw_path.name}")
        fetched = datetime.strptime(raw_path.stem.split("-", 1)[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        records, policy = parser(body.decode("utf-8", errors="replace"))
        sources.append({
            "vendor": vendor, "url": url, "status": "ok",
            "fetched_at": fetched.isoformat(timespec="seconds"), "bytes": len(body),
            "raw_sha256": sha, "note": f"raw={raw_path.name}",
        })
        policies[vendor] = policy
        all_models.extend(records)
        # What the page states; statuses derived from today's date are left out.
        semantics[slug] = {
            "policy": {k: policy.get(k) for k in ("text", "floors", "escape_hatch")},
            "records": sorted(
                ([r["model_id"], r.get("stated_status"), r.get("announced"), r.get("retirement"),
                  r.get("retirement_not_before"), r.get("replacement")] for r in records),
                key=lambda row: [str(v) for v in row]),
        }

    if args.accept_source_change:
        PIN.write_text(json.dumps(semantics, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Accepted semantic pin: {PIN}")
    elif not PIN.exists():
        raise RuntimeError("No semantic pin. Inspect parsed records, then rerun with --accept-source-change.")
    else:
        expected = json.loads(PIN.read_text(encoding="utf-8"))
        changed = sorted(k for k in set(expected) | set(semantics) if expected.get(k) != semantics.get(k))
        if changed:
            raise RuntimeError(f"Vendor statements changed for {changed}. Inspect before --accept-source-change.")
    as_of = max(src["fetched_at"] for src in sources)[:10]

    policies["DeepSeek"] = {
        "vendor": "DeepSeek",
        "source_url": "https://api-docs.deepseek.com/",
        "text": None,
        "floors": [],
        "escape_hatch": None,
        "note": DEEPSEEK_NOTE,
    }
    sources.append({
        "vendor": "DeepSeek", "url": "https://api-docs.deepseek.com/",
        "status": "no-deprecation-page", "fetched_at": None, "bytes": None,
        "note": DEEPSEEK_NOTE,
    })

    models = _compute_models(all_models, policies)
    track_records = {
        vendor: _track_record(models, vendor, policies[vendor]["floors"])
        for vendor in ("OpenAI", "Anthropic")
    }

    payload = {
        "generated_at": generated_at,
        "as_of": as_of,
        "sources": sources,
        "policies": policies,
        "models": models,
        "track_records": track_records,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {OUT_PATH}")
    for vendor in ("OpenAI", "Anthropic"):
        tr = track_records[vendor]
        print(f"  {vendor}: {tr['with_notice']} with notice "
              f"({tr['min_days']}-{tr['max_days']}d, median {tr['median_days']}d) "
              f"below_floor={tr['below_floor']} statuses={tr['by_status']}")
    # Headline findings
    for m in models:
        if m.get("primary_verdict") == "SHORT":
            print(f"  SHORT: {m['vendor']} {m['model_id']} "
                  f"{m['notice_days']}d vs {m['verdicts'][m['primary_floor']]['floor_days']}d "
                  f"({m['primary_floor']} floor)")


if __name__ == "__main__":
    main()
