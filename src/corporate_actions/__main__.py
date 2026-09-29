"""CLI: python -m corporate_actions [--documents DIR] [--golden CSV] [--out DIR]"""
import argparse
import json
from pathlib import Path

from .audit import new_run_id
from .pipeline import run_batch

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "case" / "Case AI Dev - Envio"


def main():
    parser = argparse.ArgumentParser(description="Baseline A — extração determinística de avisos de eventos corporativos")
    parser.add_argument("--documents", type=Path, default=CASE / "documents")
    parser.add_argument("--golden", type=Path, default=CASE / "golden_records" / "golden records.csv")
    parser.add_argument("--out", type=Path, default=None, help="default: outputs/runs/<run_id>")
    args = parser.parse_args()
    run_id = new_run_id()
    out = args.out or ROOT / "outputs" / "runs" / run_id
    manifest = run_batch(args.documents, args.golden, out, run_id)
    print(json.dumps({"run_id": run_id, "out": str(out), **manifest["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
