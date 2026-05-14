#!/usr/bin/env python3
"""
EDINET API v2 client — download 有価証券報告書 / 四半期報告書 / 半期報告書 etc.
directly from Financial Services Agency's official disclosure system.

OPTIONAL — requires EDINET_API_KEY env var. Without it, this script exits
cleanly with code 78 (EX_CONFIG) and the agent should fall back to other paths.

Why use this when WebFetch is available?
  - Authoritative source (regulator-side filing, identical to company IR)
  - Stable docID-based addressing (no broken IR-page links)
  - Covers all listed Japanese companies uniformly
  - Faster than crawling company IR archives for older 有報

Usage:
    # Find latest 有報 for ticker 6498 (KITZ)
    python scripts/fetch_edinet.py find --ticker 6498 --doc-type yuho

    # Download last 4 quarterly + last 2 annuals
    python scripts/fetch_edinet.py download --ticker 7203 \\
        --doc-type yuho --doc-type shihanki \\
        --output-dir workspace/7203_20260505/raw/

    # Lookup by company name (find ticker / EDINET code)
    python scripts/fetch_edinet.py lookup --name "キッツ"

Requires:
    pip install requests
    Optional: EDINET_API_KEY env var
    (Get one free at https://api.edinet-fsa.go.jp/api/auth/index.aspx)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import requests

API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

DOC_TYPE_CODES = {
    "yuho": "120",         # 有価証券報告書
    "yuho_amend": "130",
    "hanki": "140",        # 半期報告書
    "shihanki": "160",     # 四半期報告書
    "rinji": "180",        # 臨時報告書
    "ooshu": "350",        # 大量保有報告書
    "yuho_kaiji": "030",
}

DOC_TYPE_HUMAN = {v: k for k, v in DOC_TYPE_CODES.items()}


@dataclass
class EdinetDoc:
    doc_id: str
    edinet_code: str
    sec_code: str | None
    filer_name: str
    doc_type_code: str
    doc_description: str
    period_end: str | None
    submit_datetime: str

    @classmethod
    def from_api(cls, r: dict) -> "EdinetDoc":
        return cls(
            doc_id=r.get("docID", ""),
            edinet_code=r.get("edinetCode", "") or "",
            sec_code=r.get("secCode") or None,
            filer_name=r.get("filerName", "") or "",
            doc_type_code=r.get("docTypeCode", "") or "",
            doc_description=r.get("docDescription", "") or "",
            period_end=r.get("periodEnd"),
            submit_datetime=r.get("submitDateTime", "") or "",
        )


def _api_key() -> str:
    k = os.environ.get("EDINET_API_KEY")
    if not k:
        print(
            "[skip] EDINET_API_KEY not set — skipping EDINET fetch.\n"
            "       (Get a free key at https://api.edinet-fsa.go.jp/api/auth/index.aspx)\n"
            "       Agent should fall back to other sources.",
            file=sys.stderr,
        )
        sys.exit(78)  # EX_CONFIG — caller can detect this and fall back
    return k


def list_documents_on_date(d: date) -> list[dict]:
    url = f"{API_BASE}/documents.json"
    params = {"date": d.isoformat(), "type": "2", "Subscription-Key": _api_key()}
    r = requests.get(url, params=params, timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json().get("results", []) or []


def normalize_sec_code(ticker: str) -> str:
    t = ticker.strip()
    if len(t) == 4 and t.isdigit():
        return t + "0"
    return t


def filter_docs(
    raw_docs: Iterable[dict],
    ticker: str | None = None,
    edinet_code: str | None = None,
    doc_type_codes: list[str] | None = None,
) -> list[EdinetDoc]:
    out: list[EdinetDoc] = []
    sec_match = normalize_sec_code(ticker) if ticker else None
    for r in raw_docs:
        d = EdinetDoc.from_api(r)
        if sec_match and (d.sec_code or "").rstrip("0") != sec_match.rstrip("0"):
            if d.sec_code != sec_match:
                continue
        if edinet_code and d.edinet_code != edinet_code:
            continue
        if doc_type_codes and d.doc_type_code not in doc_type_codes:
            continue
        out.append(d)
    return out


def search_documents(
    ticker: str | None,
    edinet_code: str | None,
    doc_types: list[str],
    days_back: int = 400,
) -> list[EdinetDoc]:
    codes = [DOC_TYPE_CODES[dt] for dt in doc_types if dt in DOC_TYPE_CODES]
    if not codes and doc_types:
        sys.exit(f"[fatal] unknown doc-type. allowed: {list(DOC_TYPE_CODES)}")

    today = date.today()
    found: list[EdinetDoc] = []
    seen: set[str] = set()
    for i in range(days_back):
        d = today - timedelta(days=i)
        try:
            raw = list_documents_on_date(d)
        except requests.RequestException as e:
            print(f"[warn] {d}: {e}", file=sys.stderr)
            time.sleep(1)
            continue
        for doc in filter_docs(raw, ticker=ticker, edinet_code=edinet_code, doc_type_codes=codes):
            if doc.doc_id in seen:
                continue
            seen.add(doc.doc_id)
            found.append(doc)
        time.sleep(0.05)
    return found


def download_document(doc_id: str, out_path: Path, fmt: str = "1") -> Path:
    url = f"{API_BASE}/documents/{doc_id}"
    params = {"type": fmt, "Subscription-Key": _api_key()}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, params=params, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return out_path


def cmd_find(args):
    docs = search_documents(
        ticker=args.ticker,
        edinet_code=args.edinet_code,
        doc_types=args.doc_type,
        days_back=args.days_back,
    )
    docs.sort(key=lambda d: d.submit_datetime, reverse=True)
    if args.limit:
        docs = docs[: args.limit]
    print(json.dumps([asdict(d) for d in docs], ensure_ascii=False, indent=2))


def cmd_download(args):
    docs = search_documents(
        ticker=args.ticker,
        edinet_code=args.edinet_code,
        doc_types=args.doc_type,
        days_back=args.days_back,
    )
    docs.sort(key=lambda d: d.submit_datetime, reverse=True)

    if not docs:
        print("[info] no matching documents found.", file=sys.stderr)
        return

    keep_per_type = {
        "120": args.keep_yuho,
        "140": args.keep_hanki,
        "160": args.keep_shihanki,
    }
    bucketed: dict[str, list[EdinetDoc]] = {}
    for d in docs:
        bucketed.setdefault(d.doc_type_code, []).append(d)

    output_dir = Path(args.output_dir)
    manifest_entries = []

    for code, lst in bucketed.items():
        n = keep_per_type.get(code, args.keep_default)
        for d in lst[:n]:
            human = DOC_TYPE_HUMAN.get(d.doc_type_code, d.doc_type_code)
            period = (d.period_end or "unknown").replace("-", "")
            fname = f"{human}_{period}_{d.doc_id}.pdf"
            target = output_dir / fname
            print(f"[fetch] {d.filer_name} / {human} / {d.period_end} → {target}", file=sys.stderr)
            try:
                download_document(d.doc_id, target, fmt="1")
                manifest_entries.append({
                    "filename": str(target),
                    "type": human,
                    "period": d.period_end,
                    "source_url": f"{API_BASE}/documents/{d.doc_id}?type=1",
                    "source_authority": "edinet",
                    "doc_id": d.doc_id,
                    "filer_name": d.filer_name,
                    "edinet_code": d.edinet_code,
                    "sec_code": d.sec_code,
                    "submit_datetime": d.submit_datetime,
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                })
            except requests.RequestException as e:
                print(f"[error] failed to download {d.doc_id}: {e}", file=sys.stderr)

    manifest_path = output_dir / "edinet_fetch_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[done] {len(manifest_entries)} files. manifest: {manifest_path}", file=sys.stderr)
    print(json.dumps(manifest_entries, ensure_ascii=False, indent=2))


def cmd_lookup(args):
    today = date.today()
    matches: dict[str, dict] = {}
    for i in range(args.days_back):
        d = today - timedelta(days=i)
        try:
            raw = list_documents_on_date(d)
        except requests.RequestException:
            continue
        for r in raw:
            name = r.get("filerName", "") or ""
            if args.name and args.name not in name:
                continue
            ec = r.get("edinetCode", "")
            if ec and ec not in matches:
                matches[ec] = {
                    "edinet_code": ec,
                    "filer_name": name,
                    "sec_code": r.get("secCode"),
                }
        time.sleep(0.05)
        if len(matches) >= args.limit:
            break
    print(json.dumps(list(matches.values()), ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    find = sub.add_parser("find", help="Search for matching documents (no download)")
    find.add_argument("--ticker", help="4-digit Japanese ticker (e.g., 6498)")
    find.add_argument("--edinet-code", help="EDINET code (e.g., E01234)")
    find.add_argument("--doc-type", action="append", required=True,
                      choices=list(DOC_TYPE_CODES.keys()),
                      help="Document type (can be repeated)")
    find.add_argument("--days-back", type=int, default=400)
    find.add_argument("--limit", type=int, default=20)
    find.set_defaults(func=cmd_find)

    dl = sub.add_parser("download", help="Search and download matching documents")
    dl.add_argument("--ticker")
    dl.add_argument("--edinet-code")
    dl.add_argument("--doc-type", action="append", required=True,
                    choices=list(DOC_TYPE_CODES.keys()))
    dl.add_argument("--output-dir", required=True)
    dl.add_argument("--days-back", type=int, default=400)
    dl.add_argument("--keep-yuho", type=int, default=2)
    dl.add_argument("--keep-shihanki", type=int, default=4)
    dl.add_argument("--keep-hanki", type=int, default=2)
    dl.add_argument("--keep-default", type=int, default=2)
    dl.set_defaults(func=cmd_download)

    look = sub.add_parser("lookup", help="Find EDINET code by company name substring")
    look.add_argument("--name", required=True)
    look.add_argument("--days-back", type=int, default=180)
    look.add_argument("--limit", type=int, default=20)
    look.set_defaults(func=cmd_lookup)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
