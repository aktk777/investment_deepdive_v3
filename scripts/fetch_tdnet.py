#!/usr/bin/env python3
"""
TDnet (Tokyo Stock Exchange Timely Disclosure Network) fetcher.

NO API KEY REQUIRED. Scrapes the public TDnet web archive directly.

Local-only Full mode tool — requires direct HTTP egress to www.release.tdnet.info.
If your environment blocks egress, use WebSearch + WebFetch from the agent layer.

Coverage: ~31 days back from today. TDnet's public archive does NOT keep older
disclosures — for older filings, use company IR pages or EDINET.

Usage:
    # Fetch all 短信 for ticker 6498 in last 31 days
    python scripts/fetch_tdnet.py download \\
        --ticker 6498 \\
        --keyword 決算短信 \\
        --days-back 31 \\
        --output-dir workspace/.../raw/

    # Discover only (no download), see what's there:
    python scripts/fetch_tdnet.py discover --ticker 6498 --days-back 31

Requires:
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.release.tdnet.info/inbs"
USER_AGENT = "Mozilla/5.0 (compatible; DeepDiveBot/1.0; investment-research)"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.9"}


@dataclass
class TdnetEntry:
    submit_time: str
    code: str
    company_name: str
    title: str
    pdf_url: str
    submitted_date: str


def list_disclosures_on_date(d: date) -> list[TdnetEntry]:
    out: list[TdnetEntry] = []
    yyyymmdd = d.strftime("%Y%m%d")
    page = 1
    while page < 50:
        url = f"{BASE}/I_list_{page:03d}_{yyyymmdd}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"[warn] {url}: {e}", file=sys.stderr)
            break
        if r.status_code == 404:
            break
        r.raise_for_status()
        try:
            html = r.content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                html = r.content.decode("shift_jis")
            except UnicodeDecodeError:
                html = r.content.decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "lxml")
        rows = soup.find_all("tr")
        page_entries = []
        for tr in rows:
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            time_text = cells[0].get_text(strip=True)
            code_text = cells[1].get_text(strip=True)
            name_text = cells[2].get_text(strip=True)
            title_cell = cells[3]
            title_text = title_cell.get_text(strip=True)
            pdf_link = None
            for a in title_cell.find_all("a", href=True):
                if a["href"].lower().endswith(".pdf"):
                    pdf_link = urljoin(BASE + "/", a["href"])
                    break
            if not (time_text and code_text and pdf_link):
                continue
            if not re.match(r"^\d{1,2}:\d{2}", time_text):
                continue
            page_entries.append(TdnetEntry(
                submit_time=time_text,
                code=code_text,
                company_name=name_text,
                title=title_text,
                pdf_url=pdf_link,
                submitted_date=d.isoformat(),
            ))
        if not page_entries:
            break
        out.extend(page_entries)
        page += 1
        time.sleep(0.1)
    return out


def search_recent(
    ticker: str | None,
    keywords: list[str] | None,
    days_back: int,
) -> list[TdnetEntry]:
    today = date.today()
    matches: list[TdnetEntry] = []
    sec_short = ticker.strip() if ticker else None
    for i in range(days_back):
        d = today - timedelta(days=i)
        try:
            entries = list_disclosures_on_date(d)
        except requests.RequestException as e:
            print(f"[warn] {d}: {e}", file=sys.stderr)
            continue
        for e in entries:
            if sec_short and not e.code.startswith(sec_short):
                continue
            if keywords:
                if not any(kw in e.title for kw in keywords):
                    continue
            matches.append(e)
    return matches


def download_pdf(url: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    fname = re.sub(r"[^\w.\-]+", "_", url.rsplit("/", 1)[-1])
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    target = output_dir / fname
    with requests.get(url, headers=HEADERS, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(target, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return target


def _classify_title(title: str) -> str:
    if "決算短信" in title:
        return "tanshin"
    if "決算説明" in title or "決算補足" in title:
        return "kessan_setsumei"
    if "業績予想" in title:
        return "guidance_revision"
    if "自己株式" in title or "自社株" in title:
        return "buyback"
    if "中期経営計画" in title or "中計" in title:
        return "mid_term_plan"
    if "ガバナンス" in title:
        return "governance"
    if "M&A" in title or "合併" in title or "買収" in title:
        return "ma"
    return "timely"


def cmd_discover(args):
    entries = search_recent(args.ticker, args.keyword or None, args.days_back)
    entries.sort(key=lambda e: (e.submitted_date, e.submit_time), reverse=True)
    if args.limit:
        entries = entries[: args.limit]
    print(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2))


def cmd_download(args):
    entries = search_recent(args.ticker, args.keyword or None, args.days_back)
    entries.sort(key=lambda e: (e.submitted_date, e.submit_time), reverse=True)
    if args.limit:
        entries = entries[: args.limit]
    if not entries:
        print("[info] no matching TDnet entries", file=sys.stderr)
        return
    output_dir = Path(args.output_dir)
    manifest = []
    for e in entries:
        try:
            t = download_pdf(e.pdf_url, output_dir)
            manifest.append({
                "filename": str(t),
                "type": _classify_title(e.title),
                "title": e.title,
                "company_name": e.company_name,
                "tdnet_code": e.code,
                "period": None,
                "source_url": e.pdf_url,
                "source_authority": "tdnet",
                "submitted_date": e.submitted_date,
                "submitted_time": e.submit_time,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "size_bytes": t.stat().st_size,
            })
            print(f"[fetch] {e.submitted_date} {e.submit_time} {e.title[:60]} → {t.name}", file=sys.stderr)
        except requests.RequestException as err:
            print(f"[error] {e.pdf_url}: {err}", file=sys.stderr)

    manifest_path = output_dir / "tdnet_fetch_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[done] {len(manifest)} files. manifest: {manifest_path}", file=sys.stderr)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="List matching TDnet disclosures (no download)")
    d.add_argument("--ticker", help="4-digit Japanese ticker (e.g., 6498). Matches 5-digit TDnet codes by prefix.")
    d.add_argument("--keyword", action="append", help="Title-substring filter (repeatable; e.g. --keyword 決算短信)")
    d.add_argument("--days-back", type=int, default=31, help="How many days to scan (TDnet keeps ~31)")
    d.add_argument("--limit", type=int, default=50)
    d.set_defaults(func=cmd_discover)

    dl = sub.add_parser("download", help="Search and download matching TDnet disclosures")
    dl.add_argument("--ticker", help="4-digit Japanese ticker")
    dl.add_argument("--keyword", action="append")
    dl.add_argument("--days-back", type=int, default=31)
    dl.add_argument("--limit", type=int, default=20)
    dl.add_argument("--output-dir", required=True)
    dl.set_defaults(func=cmd_download)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
