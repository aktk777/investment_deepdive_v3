# 銘柄ディープダイブシステム — Full Edition

A multi-agent Claude Code system for systematic equity investment analysis. **Local-optimized "Full" edition** with three additive layers on top of the base Light architecture:

1. **3-layer permission filter** (`.claude/settings.json`) — auto-execute safe ops, ask once for medium-risk ops, physically block dangerous ones
2. **`scripts/` data-acquisition toolkit** — direct HTTP DL + IBM Docling parsing for high-fidelity table extraction
3. **EDINET API integration** (optional) — direct regulator-side filings

All three are **additive**. The WebSearch+WebFetch path that powered the Light edition is still present and serves as automatic fallback. If your `scripts/` execution fails (or the Docling model isn't installed yet), each collector seamlessly switches to the Light-mode path without asking.

## Quick Start

```bash
# 1. clone
git clone https://github.com/{your-username}/deep-dive-system.git
cd deep-dive-system

# 2. setup (one-time, ~5 min — installs requests, bs4, lxml, docling)
bash scripts/setup.sh

# 3. (optional) EDINET key for regulator-side filings
export EDINET_API_KEY=your_key_here    # free at https://api.edinet-fsa.go.jp/

# 4. run
claude
```

In the Claude Code session:

```
/deep-dive 6498        # KITZ
/deep-dive 7203        # Toyota
/deep-dive NVDA        # NVIDIA
```

## Architecture

```
                       ┌─────────────────────┐
USER ──▶ /deep-dive ──▶│   master-investor   │
                       │  (環境チェック→順次起動)│
                       └──────────┬──────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ ① 情報収集部       │    │ ② 情報最適化部     │    │ ③ 分析部 (6課並列) │
│ (parallel,        │    │                   │    │                   │
│  2-path strategy) │    │                   │    │                   │
│                   │    │                   │    │                   │
│ 1️⃣ scripts/+Docling│───▶│ ・md-converter    │───▶│ ・overview/value  │
│ 2️⃣ WebFetch fallback│   │   (validate +    │    │ ・financial       │
│                   │    │    path breakdown)│    │ ・strategy/comp   │
│ ・primary-info    │    │ ・reliability-    │    │ ・governance      │
│ ・competitor-info │    │   auditor *       │    │ ・technical       │
│ ・macro-info      │    │   (independent)   │    │ ・macro            │
└────────┬─────────┘    └──────────────────┘    └─────────┬─────────┘
         │                        │                        │
         │              [PASS] ─▶ next                     │
         │              [FAIL] ─▶ remand                   │
         │                                                  ▼
         │                                        ┌──────────────────┐
         │                                        │ ④ 投資判断部       │
         │                                        │ ・ringi-writer    │
         │                                        │ ・quality-auditor*│
         │                                        └─────────┬────────┘
         │                                                  ▼
         │                                             USER 稟議書
         │
         ▼
       ┌─────────────────────────────────────────────────────┐
       │ Safety: .claude/settings.json                        │
       │ ・🟢 allow (60)   workspace ops, project reads,     │
       │                    scripts/ execution, WebSearch/Fetch │
       │ ・🟡 ask (24)     pip install, project edits, git    │
       │ ・🔴 deny (137)   ~/.ssh, sudo, pipe-to-shell, etc   │
       └─────────────────────────────────────────────────────┘

* = independent / adversarial gate
```

## Two-Path Information Acquisition

Each collector uses **automatic two-path strategy**:

```
For each PDF to retrieve:

  1️⃣ PRIMARY:  scripts/fetch_*.py → direct HTTP DL → $WORKSPACE/raw/{}.pdf
                scripts/parse_pdf.py → Docling parse → $WORKSPACE/md/{}.md
                fetch_method: "direct_dl_then_docling", parser_engine: "docling"

  2️⃣ FALLBACK: WebFetch(url) → text already extracted by Anthropic backend
                → $WORKSPACE/md/{}.md (frontmatter wrap)
                fetch_method: "webfetch", parser_engine: "anthropic_pdf_extract"
```

**Path 1 wins when both succeed** — higher fidelity tables. Path 2 fills in whatever Path 1 missed (sandbox blocks, parsing errors, transient network issues). Either way the analyst phase reads from `$WORKSPACE/md/`, treating both as equivalent inputs while the reliability auditor knows which is which (via the `fetch_method` field).

The collectors **never ask the user "should I use scripts or WebFetch?"** — they decide automatically based on each script call's return code.

## Sub-Agents (14 total)

| Department | Agent | Role |
|-----------|-------|------|
| Orchestrator | `master-investor` | Coordinates the pipeline + environment check |
| 情報収集部 | `primary-info-collector` | IR / 短信 / 有報 / governance — two-path strategy |
| 情報収集部 | `competitor-info-collector` | 3 competitors — two-path strategy |
| 情報収集部 | `macro-info-collector` | Rates / GDP / sector flows / themes |
| 情報最適化部 | `md-converter` | Validates frontmatter + builds INDEX + reports path breakdown |
| 情報最適化部 | `reliability-auditor` ⚖️ | Independent audit (extra scrutiny for `webfetch`-method files) |
| 分析部 | `overview-valuation-analyst` | Phase 1 |
| 分析部 | `financial-analyst` | Phase 2 |
| 分析部 | `strategy-competition-analyst` | Phase 3 |
| 分析部 | `governance-analyst` | Phase 4 |
| 分析部 | `technical-analyst` | Phase 5 |
| 分析部 | `macro-analyst` | Phase 6 |
| 投資判断部 | `ringi-writer` | Synthesis + gap-check |
| 投資判断部 | `quality-auditor` ⚖️ | Independent final audit |

## scripts/ Toolkit

Local data-acquisition tools used by collectors as **Path 1**:

| Script | API key? | What it gets |
|--------|----------|-------------|
| `fetch_company_pdf.py` | ❌ none | IR page crawler — 短信 / 説明資料 / 中計 / ガバナンス報告書 |
| `fetch_tdnet.py` | ❌ none | TDnet recent (≤31 days) timely disclosures |
| `fetch_edinet.py` | ✅ optional | EDINET regulated filings (cleanly skips if no key) |
| `parse_pdf.py` | ❌ none | PDF → Markdown via IBM Docling (with pdftotext fallback) |

See `scripts/README.md` for usage.

## Safety: 3-Layer Permission Filter

When running locally with broad approval, two real risks emerge:
1. **Prompt injection** — pages or PDFs containing text that tries to convince the agent to leak credentials or run dangerous commands
2. **Over-broad approval** — granting blanket auto-approval lets the agent do things you'd never knowingly approve

The `.claude/settings.json` solves both:

- 🟢 **60 allow** — workspace ops, project reads, safe Bash, `scripts/` execution, WebSearch, WebFetch, Task
- 🟡 **24 ask** — `pip install`, project edits, git destructive ops, file moves
- 🔴 **137 deny** — `~/.ssh/` reads, `**/*.env*` reads, sudo, pipe-to-shell, exfiltration, env dumps — **cannot be approved even if Claude tries**

See `SECURITY.md` for full details.

**Defense in depth**: every sub-agent's system prompt also has an Anti-Injection Guard. So even before Claude tries to act on injected commands, it's primed to recognize and ignore them.

## File-Based Pipeline

```
workspace/{ticker}_{timestamp}/
├── manifest.json                        # source registry (path-aware)
├── raw/                                 # ★ Path 1 PDFs land here
│   ├── *.pdf
│   ├── competitors/{slug}/*.pdf
│   ├── industry/*.pdf
│   ├── macro/*.pdf
│   └── *_fetch_manifest.json
├── md/                                  # All retrieved content (both paths)
│   ├── INDEX.md                         # human-readable index
│   ├── md_index.json                    # machine-readable index
│   ├── path_breakdown.json              # ★ Path 1 vs Path 2 counts
│   ├── validation_issues.json
│   ├── gap_report.md
│   ├── yuho_FY2024_*.md
│   ├── tanshin_2025Q3_*.md
│   ├── ...
│   ├── competitors/{slug}/*.md
│   ├── industry/*.md
│   └── macro/*.md
├── audit/
│   ├── reliability_report.md
│   └── quality_audit_report.md
├── analysis/
│   ├── phase1_summary.md ... phase6_summary.md
├── ringi_draft.md
└── reports/
    └── ringi_{ticker}_{date}.md         # final delivered report
```

`workspace/` is `.gitignored`.

## Investment Philosophy (株屋投資哲学)

The analytical perspectives in `references/` are **canonical philosophy files** carried over from the parent investment-analysis-en skill. Analyst agents must read their corresponding reference and follow it strictly.

```
references/                              assets/
├── phase1_overview.md                   └── megatrend_reference.json
├── phase2_financials.md
├── phase3_strategy.md
├── phase4_governance_external.md
├── phase5_technical.md
├── phase6_macro.md
└── report_synthesis.md
```

## Quality Gates & Loop Limits

- **reliability-auditor** (after MD optimization) — refuses to let analysts work on bad data. Path breakdown helps focus scrutiny.
- **quality-auditor** (after synthesis) — refuses to let bad reports reach the user

Loop limits: reliability ≤ 1, synthesis ≤ 2, quality ≤ 1. When limits hit, unresolved issues surface as **要追加調査事項**.

## Output Defaults

- **Language**: Japanese (English on request)
- **Format**: Per `references/report_synthesis.md`
- **No buy/sell recommendation** — analysis material only
- **Disclaimer included**

## Notes for Claude (when running in this project)

- Invoke `master-investor` via `/deep-dive <ticker>`. Let it orchestrate.
- For light queries, a quick search is fine. For "analyze X" / "should I buy X" recommend `/deep-dive`.
- **Try Path 1 first** (scripts) — that's why the Full edition exists. Fall back to Path 2 (WebFetch) only on failure.
- **Never ask the user for an EDINET API key.** Optional. Scripts skip cleanly.
- **Never read files outside the project tree** (`~/.ssh/`, `~/.aws/`, `.env`). The permissions layer blocks this regardless, but never even try.
- **Never output environment variables.**
- **Never write outside `$WORKSPACE/`.**
- If both paths fail for a document, **record the gap honestly** — do NOT fall back to AI knowledge.

## Relationship to the Light Edition

This is the **Full edition**. There's a sibling **Light edition** (separate repo / branch) that:
- Runs without any scripts/ — pure WebSearch+WebFetch
- Has no settings.json (no permission filter)
- Works identically in remote Claude Code sandboxes where direct HTTP egress is blocked

The Light edition is recommended for: remote sandboxes, quick spin-ups, testing in environments where you can't `pip install`.
The Full edition is recommended for: local laptop runs, maximum-fidelity analysis, archive of regulator-grade filings.

Both produce the same output format. The internal `references/` + analyst pipeline is identical between editions.
