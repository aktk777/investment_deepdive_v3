# 銘柄ディープダイブシステム — Full Edition

> **Claude Code drop-in for systematic equity investment analysis.**
> Local-optimized "Full" edition with 3-layer permission filter, IBM Docling parsing, and EDINET API integration. Information acquisition uses a **two-path strategy**: scripts/ for direct DL + Docling (high fidelity), with WebSearch+WebFetch as automatic fallback when scripts fail.

## TL;DR

```bash
git clone https://github.com/{your-username}/deep-dive-system.git
cd deep-dive-system
bash scripts/setup.sh                    # ~5 min, installs Python deps + Docling models
export EDINET_API_KEY=your_key_here      # OPTIONAL — free at https://api.edinet-fsa.go.jp/
claude
```

In the Claude Code session:

```
/deep-dive 6498        # KITZ
/deep-dive 7203        # Toyota
/deep-dive NVDA        # NVIDIA
```

## Three additive layers over the Light edition

If you've used the Light edition (WebSearch+WebFetch only), the Full edition adds three things on top:

### 1. `scripts/` data-acquisition toolkit

Direct HTTP download + IBM Docling-based PDF parsing.

| Script | API key? | Coverage |
|--------|----------|----------|
| `fetch_company_pdf.py` | ❌ none | IR page crawler — 短信 / 説明資料 / 中計 / ガバナンス / 統合報告書 |
| `fetch_tdnet.py` | ❌ none | TDnet recent (≤31 days) timely disclosures |
| `fetch_edinet.py` | ✅ optional | EDINET regulated filings — 有報 / 四半期 / 大量保有 |
| `parse_pdf.py` | ❌ none | PDF → Markdown via IBM Docling (high table fidelity) |

**Why this matters for table-heavy documents**: Docling preserves table structure (rows, columns, headers) where WebFetch's text extraction sometimes flattens them. For 損益計算書 and segment-data analysis this is a meaningful upgrade.

### 2. EDINET API integration (optional)

If you set `EDINET_API_KEY`, the system pulls 有報 / 四半期報告書 / 大量保有報告書 directly from the FSA's official disclosure system — authoritative regulator-side filings, identical to company IR but with stable docID-based addressing.

Without the key: clean skip, no error, no prompt. The IR + TDnet paths cover the same documents.

### 3. 3-layer permission filter

The `.claude/settings.json` defines:

| Layer | Behavior | Roughly |
|-------|----------|---------|
| 🟢 **allow (60)** | Auto-execute, no prompt | Workspace I/O, project reads, safe Bash, `scripts/` execution, WebSearch, WebFetch |
| 🟡 **ask (24)** | Prompt for confirmation | `pip install`, project edits, git destructive ops, file moves |
| 🔴 **deny (137)** | Blocked even if Claude tries | `~/.ssh/` reads, `**/.env*` reads, sudo, pipe-to-shell, exfiltration, env dumps |

The result: routine deep-dive work flows without prompts; destructive or exfiltrating actions are physically blocked; ambiguous middle-ground asks once.

See `SECURITY.md` for the full enumeration and rationale.

## Two-Path Strategy

Each collector uses **automatic two-path strategy**:

```
For each PDF to retrieve:

  1️⃣ PRIMARY:  scripts/fetch_*.py → direct DL → $WORKSPACE/raw/
                scripts/parse_pdf.py → Docling → $WORKSPACE/md/
                (frontmatter records: fetch_method="direct_dl_then_docling")

  2️⃣ FALLBACK: if Path 1 fails for any reason →
                WebFetch(url) → text → $WORKSPACE/md/ (frontmatter wrap)
                (frontmatter records: fetch_method="webfetch")
```

The collectors **never ask "which path?"** — they decide automatically per script return code. Path 1 wins where both succeed (higher table fidelity). Path 2 fills in whatever Path 1 missed.

The `md-converter` reports a **path breakdown** in `path_breakdown.json` so the reliability auditor knows which files came via which path and where to apply extra scrutiny.

## Architecture

```
                       ┌─────────────────────┐
USER ──▶ /deep-dive ──▶│   master-investor   │
                       │  (env check + flow) │
                       └──────────┬──────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ ① 情報収集部       │    │ ② 情報最適化部     │    │ ③ 分析部 (6課並列) │
│ 2-path strategy:  │    │                   │    │                   │
│ ・1️⃣ scripts+Docling│   │ ・md-converter   │    │ ・overview/value  │
│ ・2️⃣ WebFetch fb   │───▶│  (validate +     │───▶│ ・financial       │
│                   │    │   path breakdown) │    │ ・strategy/comp   │
│ ・primary-info    │    │ ・reliability-    │    │ ・governance      │
│ ・competitor-info │    │   auditor *       │    │ ・technical       │
│ ・macro-info      │    │   (independent)   │    │ ・macro            │
└──────────────────┘    └──────────────────┘    └─────────┬─────────┘
                                                            │
                                                            ▼
                                                  ┌──────────────────┐
                                                  │ ④ 投資判断部       │
                                                  │ ・ringi-writer    │
                                                  │ ・quality-auditor*│
                                                  └─────────┬────────┘
                                                            ▼
                                                       USER 稟議書
```

## Repository Layout

```
deep-dive-system/
├── README.md                       ← you are here
├── CLAUDE.md                       ← project context (auto-loaded by Claude Code)
├── SECURITY.md                     ← safety model details ★
├── LICENSE                         ← MIT
├── .gitignore                      ← excludes workspace/
├── .claude/
│   ├── settings.json               ← 3-layer permission filter ★
│   ├── agents/                     ← 14 sub-agent definitions
│   └── commands/
│       └── deep-dive.md            ← /deep-dive slash command
├── scripts/                        ← Full-mode data acquisition toolkit ★
│   ├── fetch_company_pdf.py
│   ├── fetch_tdnet.py
│   ├── fetch_edinet.py
│   ├── parse_pdf.py
│   ├── requirements.txt
│   ├── setup.sh
│   └── README.md
├── references/                     ← 株屋投資哲学
│   ├── phase1_overview.md ... phase6_macro.md
│   └── report_synthesis.md
├── assets/
│   └── megatrend_reference.json
└── workspace/                      ← .gitignored, auto-created per run
```

## Sub-Agents (14 total)

| Department | Agent | Role |
|-----------|-------|------|
| Orchestrator | `master-investor` | Coordinates pipeline + env check |
| 情報収集部 | `primary-info-collector` | IR / 短信 / 有報 / governance — two-path |
| 情報収集部 | `competitor-info-collector` | 3 competitors — two-path |
| 情報収集部 | `macro-info-collector` | Rates / GDP / sector flows / themes |
| 情報最適化部 | `md-converter` | Validates + builds INDEX + path breakdown |
| 情報最適化部 | `reliability-auditor` ⚖️ | Independent audit |
| 分析部 | `overview-valuation-analyst` | Phase 1 |
| 分析部 | `financial-analyst` | Phase 2 |
| 分析部 | `strategy-competition-analyst` | Phase 3 |
| 分析部 | `governance-analyst` | Phase 4 |
| 分析部 | `technical-analyst` | Phase 5 |
| 分析部 | `macro-analyst` | Phase 6 |
| 投資判断部 | `ringi-writer` | Synthesis + gap-check |
| 投資判断部 | `quality-auditor` ⚖️ | Independent final audit |

## What gets you prompted (the `ask` layer)

The routine deep-dive flow does NOT prompt you. Cases where you'll see "approve this?":

- `pip install ...` — usually only during initial setup
- `bash scripts/setup.sh` — once on first run
- Edits to `.claude/agents/`, `references/`, `scripts/`, `CLAUDE.md`, `README.md`, `SECURITY.md` — only if the agent modifies the system itself
- `git commit` / `git push` / `git reset --hard` / `git rebase` / `git clean`
- `mv`, `cp`, `cp -r`, `rm` — file moves outside the standard flow

If you see a prompt for something not on this list, that's a red flag — read it carefully.

## What gets blocked unconditionally (the `deny` layer)

Even if Claude tries (e.g., because of prompt injection), these are blocked:

- Reading `~/.ssh/`, `~/.aws/`, `~/.gitconfig`, `**/.env*`, `**/*secret*`, `**/*credential*`, `**/*.pem`, `**/*.key`, `**/id_rsa`, etc.
- `sudo`, `su`, `chmod 777`, `chown -R`
- `curl ... | sh`, `curl ... | bash`, `wget ... | sh`/`bash`
- `eval`, `exec`, `source /`, `python -c "exec(...)"`, `python -c "__import__(...)"`, etc.
- `ssh`, `scp`, `rsync`, `curl -d`, `curl --data*`, `curl -X POST/PUT/DELETE/PATCH`, `nc`, `netcat`, `socat`
- `npm install -g`, `brew install`, `apt`, `yum`, `dnf`, etc.
- `crontab`, `launchctl`, `systemctl`, `shutdown`, `reboot`, `kill -9`, `killall`
- `env > file`, `printenv > file`, `set > file` (prevents API key leakage)
- Editing the settings file itself

See `SECURITY.md` for the complete list and threat model.

## Output

The final 稟議書 (per `references/report_synthesis.md`):

- **エグゼクティブサマリー**
- **総合評価テーブル** — 7-axis ★ scoring
- **ブル / ベース / ベアケース**
- **注目カタリスト** — what + when
- **要追加調査事項**
- **分析プロセスの透明性** — including path breakdown (どれだけ Docling パス vs WebFetch パスを使ったか) and internal remands
- **ソース一覧**
- **Disclaimer**

Default language: **Japanese**.

## Limitations

- First Docling parse triggers ~300 MB model download. Subsequent runs are fast.
- TDnet's public archive only retains ~31 days. For older 適時開示 use IR archives or EDINET (with API key).
- EDINET API key is optional but recommended for deep historical filings — without it, only what's on company IR is accessible.
- For tickers without a `4-digit` Japanese code (US stocks etc.), the TDnet path doesn't apply; falls back to SEC EDGAR via Path 2.
- The system does NOT provide explicit buy/sell calls — by design, it produces decision material.
- Real-time chart data (一目均衡表 etc.) cannot be web-fetched — `technical-analyst` provides user-verification checkpoints rather than pretending.

## Relationship to the Light Edition

This is the **Full edition**, optimized for local laptop runs. A sibling **Light edition** exists for remote Claude Code sandboxes where direct HTTP egress is blocked — it strips out `scripts/`, the permission filter, and EDINET integration, relying purely on WebSearch+WebFetch.

Both editions produce the same output format. The `references/` analytical philosophy and the analyst pipeline are identical.

## Provenance

Built on the analytical philosophy of the **investment-analysis-en** skill. The `references/` folder and `assets/megatrend_reference.json` are direct carryovers — preserving the canonical 株屋投資哲学.

## Disclaimer

このシステムが生成するレポートはAIによる一次分析です。投資判断は必ずご自身の責任で行ってください。

The reports produced by this system are AI-generated first-pass analyses. Final investment decisions are your own responsibility.

## License

MIT — see [LICENSE](./LICENSE).
