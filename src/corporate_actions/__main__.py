"""CLI: python -m corporate_actions [--variant A|B|C|D|E|F|G|H] [--documents DIR] [--golden CSV] [--out DIR]

Variantes C, D, E e F leem LLM_PROVIDER / LLM_MODEL / LLM_EFFORT / chave do provedor do ambiente ou do .env.
"""
import argparse
import json
from pathlib import Path

from .audit import new_run_id
from .pipeline import SemanticContext, run_batch

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "case" / "Case AI Dev - Envio"


def main():
    parser = argparse.ArgumentParser(description="Extração de avisos de eventos corporativos (variantes A/B/C do E-003; D do E-004; E do E-005; F do E-006)")
    parser.add_argument("--variant", choices=["A", "B", "C", "D", "E", "F", "G", "H"], default="A")
    parser.add_argument("--documents", type=Path, default=CASE / "documents")
    parser.add_argument("--golden", type=Path, default=CASE / "golden_records" / "golden records.csv")
    parser.add_argument("--out", type=Path, default=None, help="default: outputs/runs/<run_id>")
    parser.add_argument("--llm-cache", type=Path, default=None, help="variantes C/D/E/F: diretório de cache/replay das respostas")
    parser.add_argument("--no-cache-read", action="store_true", help="variantes C/D/E/F: sempre chama o LLM (mas grava no cache)")
    args = parser.parse_args()
    run_id = new_run_id()
    out = args.out or ROOT / "outputs" / "runs" / run_id
    ctx = None
    if args.variant in ("C", "D", "E", "F", "G", "H"):
        from .llm.cache import ResponseCache
        from .llm.config import llm_config_from_env
        from .llm.registry import get_provider
        provider = get_provider(llm_config_from_env())
        cache = ResponseCache(args.llm_cache or out / "llm_cache", read=not args.no_cache_read)
        ctx = SemanticContext(provider=provider, cache=cache)
    manifest = run_batch(args.documents, args.golden, out, run_id, variant=args.variant, semantic_ctx=ctx)
    print(json.dumps({"run_id": run_id, "variant": args.variant, "out": str(out), **manifest["summary"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
