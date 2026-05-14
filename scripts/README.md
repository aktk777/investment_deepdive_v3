# scripts/ — Full mode data acquisition toolkit

Local-only Python toolkit for high-fidelity information retrieval. Used by collector sub-agents as the **primary path**, with WebSearch + WebFetch as fallback when these scripts fail (network restrictions, sandbox limits, transient errors).

## When this layer applies

| Environment | Behavior |
|-------------|----------|
| **Local Claude Code** (your laptop) | Scripts work — direct HTTP egress is unrestricted. Collectors use this path first for higher fidelity (Docling table extraction). |
| **Remote Claude Code sandbox** | Scripts return 403 (`host_not_allowed` from egress proxy). Collectors detect this and fall back to WebSearch + WebFetch. |

The collectors auto-detect environment by trying the scripts first; if they fail, they switch paths cleanly. You don't manage modes manually.

## Tools

| Script | API key? | What it gets |
|--------|----------|-------------|
| `fetch_company_pdf.py` | ❌ none | IR page crawler — downloads 短信 / 説明資料 / 中計 / ガバナンス報告書 |
| `fetch_tdnet.py` | ❌ none | TDnet recent (≤31 days) timely disclosures |
| `fetch_edinet.py` | ✅ optional | EDINET regulated filings (有報 / 四半期 / 大量保有). Cleanly skips if no key. |
| `parse_pdf.py` | ❌ none | PDF → Markdown via IBM Docling (with pdftotext fallback) |

## Setup (one-time)

```bash
bash scripts/setup.sh
```

That installs the Python deps (`requests`, `bs4`, `lxml`, `docling`). Docling downloads model weights on first run (~300 MB), then caches them.

**Optional**: set `EDINET_API_KEY` for direct regulator-side access:

```bash
# Get a free key at https://api.edinet-fsa.go.jp/api/auth/index.aspx
export EDINET_API_KEY=your_key
# (add to ~/.zshrc / ~/.bashrc to persist)
```

## Quick reference

### Company IR harvest

```bash
python scripts/fetch_company_pdf.py harvest \
    --url "https://www.kitz.co.jp/ir/library/" \
    --keyword 決算短信 --keyword 決算説明 --keyword 中期 --keyword 統合報告 \
    --max 12 \
    --output-dir workspace/6498_20260510/raw/
```

### TDnet recent disclosures

```bash
python scripts/fetch_tdnet.py download \
    --ticker 6498 \
    --keyword 決算短信 --keyword 業績予想 --keyword 自己株式 \
    --days-back 31 \
    --output-dir workspace/6498_20260510/raw/
```

### EDINET (optional)

```bash
python scripts/fetch_edinet.py download \
    --ticker 6498 \
    --doc-type yuho --doc-type shihanki \
    --output-dir workspace/6498_20260510/raw/ \
    --keep-yuho 2 --keep-shihanki 4
# exit code 78 = no API key, fall back to other paths
```

### PDF → Markdown

```bash
# manifest-driven (preserves source attribution)
python scripts/parse_pdf.py \
    --manifest workspace/6498_20260510/manifest.json \
    --output-dir workspace/6498_20260510/md/ \
    --ticker 6498
```

The parser tries **Docling first**, falls back to pdftotext if Docling fails or isn't installed. Engine used is recorded in each output's frontmatter.

## Output frontmatter contract

Every Markdown produced by `parse_pdf.py` starts with:

```yaml
---
source_file: "/abs/path/to/original.pdf"
source_url: "https://api.edinet-fsa.go.jp/api/v2/documents/S100XXXX?type=1"
source_authority: "edinet"      # company_ir | tdnet | edinet | sec_edgar | tier1_media
document_type: "yuho"            # yuho | shihanki | tanshin | setsumei | mid_term | governance
period: "2024-03-31"
ticker: "6498"
language_original: "ja"
converted_at: "2026-05-10T10:23:11"
parser_engine: "docling"         # docling | pdftotext
fetch_method: "direct_dl_then_docling"
---
```

When the collector took the WebFetch fallback path instead, the frontmatter shows `fetch_method: "webfetch"` and `parser_engine: "anthropic_pdf_extract"`.

## Failure handling

If a script fails (network error, corrupt PDF), it writes errors to `conversion_errors.json` and exits non-zero. Collector sub-agents catch this and fall back to WebFetch — they should NOT silently summarize from memory.

## Direct vs fallback — which wins?

When both paths succeed for the same document, the **direct DL + Docling** result wins (higher table fidelity). The collector skips the WebFetch fallback in that case. If you want to compare results, check `parser_engine` and `fetch_method` in the frontmatter.
