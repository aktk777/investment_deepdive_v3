#!/usr/bin/env python3
"""
PDF → Markdown converter with layout-aware parsing.

PRIMARY ENGINE: IBM Docling
  - Recognizes tables, headings, lists, footnotes
  - Outputs clean Markdown with table structure preserved
  - Critical for financial documents (P&L, B/S, segment tables)

FALLBACK: pdftotext (poppler) — last-resort plain-text extraction

Usage:
    # single file
    python scripts/parse_pdf.py input.pdf -o output.md

    # batch a directory
    python scripts/parse_pdf.py --batch workspace/.../raw/ -o workspace/.../md/

    # batch using a manifest (preferred — preserves source attribution)
    python scripts/parse_pdf.py --manifest workspace/.../manifest.json \\
        --output-dir workspace/.../md/ --ticker 6498

    # specify engine explicitly
    python scripts/parse_pdf.py input.pdf -o output.md --engine docling
    python scripts/parse_pdf.py input.pdf -o output.md --engine pdftotext

Output Markdown includes a YAML frontmatter block with source attribution.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path


def parse_with_docling(pdf_path: Path) -> str:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        raise RuntimeError("docling not installed. Run: pip install docling")
    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()


def parse_with_pdftotext(pdf_path: Path) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError(
            "pdftotext not found. Install poppler "
            "(apt-get install poppler-utils, or brew install poppler)"
        )
    proc = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


ENGINES = {
    "docling": parse_with_docling,
    "pdftotext": parse_with_pdftotext,
}

ENGINE_FALLBACK_ORDER = ["docling", "pdftotext"]


def parse_pdf(pdf_path: Path, engine: str = "auto") -> tuple[str, str]:
    """Parse PDF, returning (markdown, engine_used)."""
    if engine == "auto":
        last_err: Exception | None = None
        for e in ENGINE_FALLBACK_ORDER:
            try:
                return ENGINES[e](pdf_path), e
            except Exception as err:
                print(f"[warn] engine {e} failed for {pdf_path.name}: {err}", file=sys.stderr)
                last_err = err
        raise RuntimeError(f"All engines failed. Last error: {last_err}")
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine: {engine}. Allowed: {list(ENGINES)}")
    return ENGINES[engine](pdf_path), engine


def build_frontmatter(
    source_file: str,
    source_url: str | None = None,
    source_authority: str | None = None,
    document_type: str | None = None,
    period: str | None = None,
    ticker: str | None = None,
    engine: str | None = None,
    extra: dict | None = None,
) -> str:
    fm = {
        "source_file": source_file,
        "source_url": source_url or "unknown",
        "source_authority": source_authority or "unknown",
        "document_type": document_type or "unknown",
        "period": period or "unknown",
        "ticker": ticker or "unknown",
        "language_original": "ja",
        "converted_at": datetime.now().isoformat(timespec="seconds"),
        "parser_engine": engine or "unknown",
        "fetch_method": "direct_dl_then_docling",
    }
    if extra:
        fm.update({k: v for k, v in extra.items() if k not in fm})
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, str):
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def cmd_single(args):
    pdf_path = Path(args.input)
    out_path = Path(args.output)
    md, engine_used = parse_pdf(pdf_path, engine=args.engine)
    fm = build_frontmatter(
        source_file=str(pdf_path),
        source_url=args.source_url,
        source_authority=args.authority,
        document_type=args.doc_type,
        period=args.period,
        ticker=args.ticker,
        engine=engine_used,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(fm + md, encoding="utf-8")
    print(f"[ok] {pdf_path} → {out_path}  (engine={engine_used}, {out_path.stat().st_size} bytes)")


def cmd_batch_dir(args):
    src = Path(args.batch)
    dst = Path(args.output)
    pdfs = sorted(src.rglob("*.pdf"))
    if not pdfs:
        print(f"[info] no PDFs found in {src}", file=sys.stderr)
        return
    summary = {"converted": [], "failed": []}
    for p in pdfs:
        rel = p.relative_to(src)
        out = dst / rel.with_suffix(".md")
        try:
            md, engine_used = parse_pdf(p, engine=args.engine)
            fm = build_frontmatter(
                source_file=str(p),
                ticker=args.ticker,
                engine=engine_used,
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(fm + md, encoding="utf-8")
            summary["converted"].append({"in": str(p), "out": str(out), "engine": engine_used})
            print(f"[ok] {p.name} → {out}  ({engine_used})")
        except Exception as e:
            summary["failed"].append({"in": str(p), "error": str(e)})
            print(f"[error] {p.name}: {e}", file=sys.stderr)
    err_log = dst / "conversion_errors.json"
    err_log.parent.mkdir(parents=True, exist_ok=True)
    err_log.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] converted={len(summary['converted'])}, failed={len(summary['failed'])}, log={err_log}")


def cmd_batch_manifest(args):
    """Convert PDFs listed in a manifest JSON, preserving rich attribution per file."""
    manifest_path = Path(args.manifest)
    out_dir = Path(args.output_dir)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = raw if isinstance(raw, list) else raw.get("files", [])
    if not entries:
        print(f"[info] manifest empty: {manifest_path}", file=sys.stderr)
        return
    summary = {"converted": [], "failed": []}
    md_index = []
    for ent in entries:
        f = Path(ent.get("filename", ""))
        if not f.exists() or f.suffix.lower() != ".pdf":
            continue
        out = out_dir / (f.stem + ".md")
        try:
            md, engine_used = parse_pdf(f, engine=args.engine)
            fm = build_frontmatter(
                source_file=str(f),
                source_url=ent.get("source_url"),
                source_authority=ent.get("source_authority"),
                document_type=ent.get("type"),
                period=ent.get("period"),
                ticker=args.ticker or ent.get("ticker"),
                engine=engine_used,
                extra={k: v for k, v in ent.items() if k not in {
                    "filename", "source_url", "source_authority", "type", "period", "ticker"
                }},
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(fm + md, encoding="utf-8")
            md_index.append({
                "md_file": str(out),
                "source_pdf": str(f),
                "type": ent.get("type"),
                "period": ent.get("period"),
                "engine": engine_used,
            })
            summary["converted"].append({"in": str(f), "out": str(out), "engine": engine_used})
            print(f"[ok] {f.name} → {out}  ({engine_used})")
        except Exception as e:
            summary["failed"].append({"in": str(f), "error": str(e), "trace": traceback.format_exc(limit=2)})
            print(f"[error] {f.name}: {e}", file=sys.stderr)
    idx_path = out_dir / "md_index.json"
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(json.dumps(md_index, ensure_ascii=False, indent=2), encoding="utf-8")
    err_log = out_dir / "conversion_errors.json"
    err_log.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] converted={len(summary['converted'])}, failed={len(summary['failed'])}")
    print(f"       index={idx_path}, errors={err_log}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", nargs="?", help="Single PDF input (for single-file mode)")
    p.add_argument("-o", "--output", help="Output .md path (single-file mode)")
    p.add_argument("--batch", help="Directory containing PDFs (batch-dir mode); also pass -o for output dir")
    p.add_argument("--manifest", help="Manifest JSON listing PDFs with metadata (batch-manifest mode)")
    p.add_argument("--output-dir", help="Output dir for batch-manifest mode")
    p.add_argument("--engine", default="auto", choices=["auto", *ENGINES.keys()],
                   help="Parser engine (default: auto = try docling, fallback pdftotext)")
    p.add_argument("--ticker", help="Ticker for frontmatter")
    p.add_argument("--source-url", help="Source URL for frontmatter (single-file mode)")
    p.add_argument("--authority", help="Source authority tag (single-file mode)")
    p.add_argument("--doc-type", help="Document type tag (single-file mode)")
    p.add_argument("--period", help="Period tag (single-file mode)")
    args = p.parse_args()

    if args.manifest:
        if not args.output_dir:
            sys.exit("--manifest requires --output-dir")
        cmd_batch_manifest(args)
    elif args.batch:
        if not args.output:
            sys.exit("--batch requires -o (output directory)")
        cmd_batch_dir(args)
    else:
        if not args.input or not args.output:
            sys.exit("single-file mode requires INPUT and -o OUTPUT")
        cmd_single(args)


if __name__ == "__main__":
    main()
