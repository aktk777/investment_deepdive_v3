#!/usr/bin/env python3
"""
Crawl a company IR page (or any URL) and download relevant PDFs.

Local-only Full mode tool. Requires direct HTTP egress to the company IR domain.
If your environment blocks egress (e.g., remote Claude Code sandbox), use
WebSearch + WebFetch from the agent layer instead — this script is for local use.

What this covers (vs EDINET):
  - 決算短信 (earnings briefing)        — usually only on company IR
  - 決算説明資料 (presentation deck)     — only on company IR
  - 中期経営計画 (mid-term plan)         — only on company IR
  - 統合報告書 (integrated report)       — only on company IR

Usage:
    # discover PDFs on an IR page (no download)
    python scripts/fetch_company_pdf.py discover \\
        --url "https://www.example.co.jp/ir/library.html"

    # discover with keyword filter
    python scripts/fetch_company_pdf.py discover \\
        --url "https://www.example.co.jp/ir/library.html" \\
        --keyword 決算短信 --keyword 決算説明

    # download specific URLs
    python scripts/fetch_company_pdf.py download \\
        --url https://www.example.co.jp/ir/2025q3.pdf \\
        --url https://www.example.co.jp/ir/2025q2.pdf \\
        --output-dir workspace/.../raw/

    # discover + download in one shot
    python scripts/fetch_company_pdf.py harvest \\
        --url "https://www.example.co.jp/ir/library.html" \\
        --keyword 決算短信 \\
        --max 4 \\
        --output-dir workspace/.../raw/

Requires:
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; DeepDiveBot/1.0; investment-research) "
    "deep-dive-system"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.9"}


@dataclass
class PdfLink:
    url: str
    text: str
    score: int
    detected_at: str


# ---------------- Discovery ----------------

def discover_pdfs(url: str, keywords: list[str] | None = None, follow_indices: int = 1) -> list[PdfLink]:
    """Fetch a page, find PDF links, optionally follow 1 hop deeper for index pages."""
    visited: set[str] = set()
    found: dict[str, PdfLink] = {}

    def visit(u: str, depth: int):
        if u in visited:
            return
        visited.add(u)
        try:
            r = requests.get(u, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[warn] {u}: {e}", file=sys.stderr)
            return
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            return
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(u, href)
            text = a.get_text(strip=True) or ""
            if full.lower().split("?")[0].endswith(".pdf"):
                score = _score_match(full, text, keywords)
                if keywords and score == 0:
                    continue
                if full not in found:
                    found[full] = PdfLink(
                        url=full,
                        text=text[:200],
                        score=score,
                        detected_at=datetime.now().isoformat(timespec="seconds"),
                    )
            elif depth < follow_indices and _looks_like_ir_index(full, text, base_url=url):
                visit(full, depth + 1)

    visit(url, depth=0)
    out = list(found.values())
    out.sort(key=lambda x: (-x.score, x.url))
    return out


def _score_match(url: str, text: str, keywords: list[str] | None) -> int:
    if not keywords:
        return 1
    s = 0
    blob = (url + " " + text).lower()
    for kw in keywords:
        if kw.lower() in blob:
            s += 1
    return s


def _looks_like_ir_index(url: str, text: str, base_url: str) -> bool:
    try:
        same_host = urlparse(url).netloc == urlparse(base_url).netloc
    except Exception:
        return False
    if not same_host:
        return False
    haystack = (url + " " + text).lower()
    needles = ["library", "disclosure", "ir", "決算", "investors", "investor", "適時", "資料"]
    return any(n in haystack for n in needles)


# ---------------- Download ----------------

def download_pdf(url: str, output_dir: Path, fname: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if fname is None:
        fname = _safe_filename_from_url(url)
    target = output_dir / fname
    with requests.get(url, headers=HEADERS, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(target, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return target


def _safe_filename_from_url(url: str) -> str:
    base = os.path.basename(urlparse(url).path) or "download.pdf"
    base = re.sub(r"[^\w.\-]+", "_", base)
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base


# ---------------- subcommands ----------------

def cmd_discover(args):
    links = discover_pdfs(args.url, keywords=args.keyword or None, follow_indices=args.follow)
    if args.max:
        links = links[: args.max]
    print(json.dumps([asdict(x) for x in links], ensure_ascii=False, indent=2))


def cmd_download(args):
    output_dir = Path(args.output_dir)
    manifest = []
    for u in args.url:
        try:
            t = download_pdf(u, output_dir)
            manifest.append({
                "filename": str(t),
                "source_url": u,
                "source_authority": "company_ir",
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "size_bytes": t.stat().st_size,
            })
            print(f"[fetch] {u} → {t}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[error] {u}: {e}", file=sys.stderr)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def cmd_harvest(args):
    """discover + download in one go."""
    links = discover_pdfs(args.url, keywords=args.keyword or None, follow_indices=args.follow)
    if args.max:
        links = links[: args.max]

    output_dir = Path(args.output_dir)
    manifest = []
    for ln in links:
        try:
            t = download_pdf(ln.url, output_dir)
            manifest.append({
                "filename": str(t),
                "source_url": ln.url,
                "anchor_text": ln.text,
                "source_authority": "company_ir",
                "match_score": ln.score,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "size_bytes": t.stat().st_size,
            })
            print(f"[fetch] {ln.url} → {t}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[error] {ln.url}: {e}", file=sys.stderr)

    manifest_path = output_dir / "company_pdf_fetch_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[done] {len(manifest)} files. manifest: {manifest_path}", file=sys.stderr)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


# ---------------- CLI ----------------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="List PDF links on a page (and optionally one hop deeper)")
    d.add_argument("--url", required=True)
    d.add_argument("--keyword", action="append", help="Filter PDFs whose link/text contains keyword (repeatable)")
    d.add_argument("--follow", type=int, default=1, help="Follow this many hops into IR sub-pages (default 1)")
    d.add_argument("--max", type=int, default=20)
    d.set_defaults(func=cmd_discover)

    dl = sub.add_parser("download", help="Download specific PDF URLs")
    dl.add_argument("--url", action="append", required=True, help="PDF URL (repeatable)")
    dl.add_argument("--output-dir", required=True)
    dl.set_defaults(func=cmd_download)

    h = sub.add_parser("harvest", help="discover + download in one go")
    h.add_argument("--url", required=True)
    h.add_argument("--keyword", action="append")
    h.add_argument("--follow", type=int, default=1)
    h.add_argument("--max", type=int, default=10)
    h.add_argument("--output-dir", required=True)
    h.set_defaults(func=cmd_harvest)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
