"""CLI: python -m corporate_actions [--variant A|...|K] [--documents DIR] [--golden CSV] [--out DIR]

Solução final: `python -m corporate_actions --variant K` (percepção automática: texto nativo -> OCR local -> vision só
quando faltar campo crítico obrigatório; política de incerteza crítica; mesma pipeline semântica/financeira).

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
    parser.add_argument("--variant", choices=["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"], default="A")
    parser.add_argument("--documents", type=Path, default=CASE / "documents")
    parser.add_argument("--golden", type=Path, default=CASE / "golden_records" / "golden records.csv")
    parser.add_argument("--out", type=Path, default=None, help="default: outputs/runs/<run_id>")
    parser.add_argument("--llm-cache", type=Path, default=None, help="variantes C/D/E/F: diretório de cache/replay das respostas")
    parser.add_argument("--no-cache-read", action="store_true", help="variantes C/D/E/F: sempre chama o LLM (mas grava no cache)")
    parser.add_argument("--perception", choices=["none", "auto"], default=None,
                        help="documentos sem camada de texto: none = revisão; auto = OCR local -> vision (padrão da variante K)")
    parser.add_argument("--vision-cache", type=Path, default=None, help="cache/replay das transcrições de vision (default: <out>/vision_cache)")
    args = parser.parse_args()
    run_id = new_run_id()
    out = args.out or ROOT / "outputs" / "runs" / run_id
    ctx = None
    if args.variant in ("C", "D", "E", "F", "G", "H", "I", "J", "K"):
        from .llm.cache import ResponseCache
        from .llm.config import llm_config_from_env
        from .llm.registry import get_provider
        provider = get_provider(llm_config_from_env())
        cache = ResponseCache(args.llm_cache or out / "llm_cache", read=not args.no_cache_read)
        ctx = SemanticContext(provider=provider, cache=cache)
    text_fallback = None
    if (args.perception or ("auto" if args.variant == "K" else "none")) == "auto":
        from perception.ocr_local import TesseractOCR
        from perception.router import PerceptionRouter
        from perception.vision_transcriber import VisionTranscriber

        from .reference import load_golden_records
        text_fallback = PerceptionRouter(load_golden_records(args.golden), TesseractOCR(artifacts_dir=out / "perception_artifacts" / "ocr"),
                                         VisionTranscriber(cache_dir=args.vision_cache or out / "vision_cache",
                                                           artifacts_dir=out / "perception_artifacts" / "vision"), variant=args.variant)
    manifest = run_batch(args.documents, args.golden, out, run_id, variant=args.variant, semantic_ctx=ctx, text_fallback=text_fallback)
    print(json.dumps({"run_id": run_id, "variant": args.variant, "out": str(out), **manifest["summary"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
