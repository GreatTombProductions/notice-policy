# Notice-Policy Check

Did the AI vendor honor its own stated model-retirement notice window?

Model vendors publish minimum-notice policies for retirements — OpenAI: "Generally available models: At least 6 months"; Anthropic: "at least 60 days' notice" — but nothing cross-checks actual notice given against the stated window. This tool computes the actual notice interval (announcement → retirement) for every model retirement documented on the vendors' own deprecation pages, compares it against the vendors' own stated floors, and flags every shortfall.

**Live:** https://greattombproductions.github.io/notice-policy/

## What it shows

- **The stated policies, verbatim** — quoted from each vendor page, escape hatches included ("Unless safety or compliance concerns require a faster timeline…")
- **Compliance ledgers** — every model with an announcement + retirement date: actual notice days vs the GA floor (6 months), specialized floor (3 months), and preview floor (~2 weeks) for OpenAI; vs the 60-day floor for Anthropic. PASS/SHORT per floor.
- **Track record** — notice days per completed retirement, oldest → newest, with the vendor's own floor as full-width reference
- **Honest coverage** — DeepSeek publishes no deprecation page or notice policy (documented gap, not hidden); models without an announcement or retirement date are marked n/a with the reason, never assumed

## Headline findings (snapshot 2026-10-06)

- **OpenAI:** 72 of 146 models with computable notice get less than the stated 6-month GA floor. 64 fall short of the floor that applies to them under OpenAI's own preview criterion. The 2026-04-22 legacy-snapshot batch gave about 92 days, roughly half the stated floor. gpt-5.4-cyber was announced 2026-09-11 and shut down 2026-10-01: 20 days, short of the GA and specialized floors and above only the preview floor. tts-1, tts-1-hd and two gpt-4o-mini-tts snapshots get 97 days (2026-10-01 to 2027-01-06): short of the GA floor, above the 3-month specialized floor. Boundary cases (182 days against a 183-day floor) and genuine shortfalls (3 days, Codex 2023) both appear.
- **Anthropic:** 20 retirements on record with 60–189 days' notice, **zero below the stated 60-day floor**. Claude Sonnet 4.5 (announced 2026-09-30, retiring 2026-11-30) gets 61 days. The 2026-08-12 snapshot listed 12. Its parser skipped the oldest history section, so the Claude 1.x and Instant retirements (63 days each) were missing.

## Pipeline

```
pipeline/fetch.py     → data/raw/<vendor>-<UTC stamp>.html + .sha256 receipt (multi-transport fetch, 60s hard deadline per source)
pipeline/parser.py    → records + policy   (pure functions; columns mapped by label; unknown states or layouts stop the parse)
pipeline/generate.py  → data/compliance.json (notice computation + verdicts + track records)
```

Run: `python3 pipeline/fetch.py && python3 pipeline/generate.py`

`pipeline/generate.py` builds from the newest captures in `data/raw/`. It stops when a receipt doesn't match its capture, when the newest capture of a page failed, and when anything a vendor states (records, policy text, floors, escape clause) differs from `pipeline/expected_semantics.json`. Inspect the parsed records, then rerun with `--accept-source-change`. Each capture's SHA-256 is shown on the site.

Tests: `python3 -m pytest tests/` (25 tests: offline fixtures for both page layouts seen so far, the captures in `data/raw/`, hand-checked notice intervals, and the build's stop conditions). Browser check: `SMOKE_SITE=. python3 tests/run_browser_smoke.py` (needs Node with Playwright).

## Honesty rules

1. **Announced = the date the vendor's page documents the notification.** Each deprecation section on both pages carries a dated header; the page's own narrative ("On June 5, 2026, Anthropic notified developers…") matches it.
2. **Month floors use calendar-month arithmetic** (announcement + 6 months) — the truest reading of "6 months"; may differ from flat-day counts by 1–2 days at the boundary.
3. **The preview floor applies where the vendor's own criterion says it does** — "preview" in the model name. Everything else is judged on the GA floor; all floors are displayed on every row.
4. **The escape hatch is quoted, not adjudicated.** A SHORT row is the record; whether an exception applied is the vendor's claim to make with evidence.
5. **API/system deprecations are excluded** (Assistants API, legacy endpoints) — the stated floors apply to models.

## Data sources

- Anthropic model-deprecations page: https://docs.claude.com/en/docs/about-claude/model-deprecations
- OpenAI API deprecations page: https://developers.openai.com/api/docs/deprecations

Sibling tool: [Model Lifecycle Watch](https://greattombproductions.github.io/model-lifecycle/) — per-model lifecycle status from the same pages.
