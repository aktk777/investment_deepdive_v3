#!/usr/bin/env bash
# One-time setup for the deep-dive-system Full mode scripts.
# Run from project root: bash scripts/setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "[setup] Installing Python dependencies..."
pip install -r requirements.txt

echo ""
echo "[setup] Done. The system works without any API keys (WebFetch fallback path)."
echo ""
echo "OPTIONAL: For EDINET regulated-filings direct access (faster + more reliable"
echo "than WebFetch for older 有報 / 大量保有報告書), get a free API key at:"
echo "  https://api.edinet-fsa.go.jp/api/auth/index.aspx"
echo "  export EDINET_API_KEY=your_key_here"
echo "  (add to ~/.zshrc or ~/.bashrc to persist)"
echo ""
echo "Without the key, the system still works — it just skips EDINET-direct."
echo ""
echo "Test the toolkit:"
echo "  python scripts/fetch_company_pdf.py --help"
echo "  python scripts/fetch_tdnet.py --help"
echo "  python scripts/fetch_edinet.py --help"
echo "  python scripts/parse_pdf.py --help"
