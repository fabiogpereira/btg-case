"""Transcrição por modelo multimodal (E-009, braço B). Só percepção: imagem da página -> texto.

O modelo recebe apenas a imagem renderizada e um prompt de transcrição literal. Não recebe golden records, nomes de
emissores, tickers, campos esperados nem regras. Não decide nada: a saída vira um TextLayer que segue exatamente a
mesma pipeline congelada (extração determinística, semântica, validação, roteamento), pelo hook `text_fallback`.

Configuração congelada: um único modelo (`claude-opus-5`), prompt e schema fixos (fingerprint na auditoria), saída
estruturada (linhas transcritas + trechos incertos), sem ferramentas, sem fallback. O modelo não aceita parâmetro de
temperatura; a aleatoriedade residual é registrada como limitação. Página renderizada a 200 DPI (resolução nativa da
imagem do scan; abaixo do limite de 2576 px no lado longo, sem redução).

Replay: a resposta é gravada em `cache_dir` com chave SHA-256(modelo | fingerprint | imagem). Com o arquivo presente,
nenhuma chamada é feita (reprodutibilidade dos testes de regressão). A execução oficial usa um diretório novo.
"""
import base64
import hashlib
import io
import json
import os
import time
from decimal import Decimal
from pathlib import Path

from corporate_actions.ingestion import MIN_ALNUM_CHARS_PER_PAGE, TextLayer, normalize_whitespace

from .ocr_local import _display, _sha

MODEL = "claude-opus-5"
MAX_TOKENS = 4000
DPI = 200
SYSTEM = (
    "You are a transcription engine for images of printed documents. Your only task is to reproduce the visible "
    "text exactly as printed. You never interpret, validate, summarize, correct or complete anything.")
INSTRUCTIONS = (
    "Transcribe every piece of text visible on this page, in reading order, one output line per printed line.\n"
    "Rules:\n"
    "- Copy characters exactly as printed: letters, accents, case, digits, punctuation, separators (e.g. keep a comma "
    "as the decimal separator if that is what is printed), symbols such as R$ and %, and parentheses.\n"
    "- Table rows: transcribe label and value on the same line, in the order they appear. Rows of dots used as table "
    "fillers may be copied as a run of dots.\n"
    "- Do not correct, normalize, reformat, translate or complete any text. Do not fix apparent typos.\n"
    "- Do not use outside knowledge about companies, tickers, identifiers, laws, dates or amounts.\n"
    "- Never add text that is not visible. If something is not legible, do not guess a value: write what you can see "
    "and list it in `uncertain`.\n"
    "- If you are not fully sure about a character or word, keep your best literal reading in the line AND list that "
    "exact token in `uncertain` with a short reason.\n"
    "- Signatures, stamps or handwriting: transcribe only if legible as text; otherwise count them in "
    "`illegible_regions`.")
SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {"type": "array", "items": {"type": "string"}},
        "uncertain": {"type": "array", "items": {
            "type": "object", "properties": {"token": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["token", "reason"], "additionalProperties": False}},
        "illegible_regions": {"type": "integer"},
    },
    "required": ["lines", "uncertain", "illegible_regions"],
    "additionalProperties": False,
}


def prompt_fingerprint() -> str:
    payload = json.dumps({"model": MODEL, "system": SYSTEM, "instructions": INSTRUCTIONS, "schema": SCHEMA,
                          "max_tokens": MAX_TOKENS, "dpi": DPI}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class VisionTranscriber:
    def __init__(self, cache_dir: Path, artifacts_dir: Path | None = None, allow_api: bool = True):
        self.cache_dir, self.artifacts_dir, self.allow_api = Path(cache_dir), artifacts_dir, allow_api
        self.api_calls = 0

    def describe(self) -> dict:
        import pypdfium2
        return {"extraction_method": "VISION_LLM", "engine": "anthropic", "model": MODEL, "prompt_fingerprint": prompt_fingerprint(),
                "max_tokens": MAX_TOKENS, "dpi": DPI, "renderer": f"pypdfium2 {pypdfium2.version.PYPDFIUM_INFO}",
                "temperature": "not supported by model (not sent)", "tools": None, "fallbacks": "off",
                "reference_data_in_prompt": False}

    def _call(self, png: bytes) -> dict:
        import anthropic

        from corporate_actions.llm.config import load_dotenv
        from corporate_actions.llm.registry import estimate_cost_usd
        load_dotenv()
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        client = anthropic.Anthropic(timeout=300, max_retries=2,
                                     default_headers={"anthropic-workspace-id": workspace} if workspace else None)
        t0 = time.perf_counter()
        msg = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}},
                {"type": "text", "text": INSTRUCTIONS}]}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
        self.api_calls += 1
        text = "".join(b.text for b in msg.content if b.type == "text")
        usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
        return {"id": msg.id, "request_id": getattr(msg, "_request_id", None), "served_model": msg.model,
                "stop_reason": msg.stop_reason, "usage": usage, "latency_ms": int((time.perf_counter() - t0) * 1000),
                "estimated_cost_usd": str(estimate_cost_usd(msg.model, usage)), "output_text": text}

    def __call__(self, doc):
        import pypdfium2 as pdfium
        info = self.describe()
        t0 = time.perf_counter()
        pdf = pdfium.PdfDocument(io.BytesIO(doc.content))
        page_texts, pages_audit, uncertain, usage_total, cost_total, api_ms, replayed = [], [], [], {}, Decimal(0), 0, 0
        for i in range(len(pdf)):
            buf = io.BytesIO()
            image = pdf[i].render(scale=DPI / 72).to_pil()
            image.save(buf, format="PNG")
            png = buf.getvalue()
            key = hashlib.sha256(f"{MODEL}|{prompt_fingerprint()}|{_sha(png)}".encode()).hexdigest()
            cached = self.cache_dir / f"{key}.json"
            if cached.exists():
                resp, replayed = json.loads(cached.read_text(encoding="utf-8")), replayed + 1
            elif not self.allow_api:
                raise RuntimeError("vision replay miss and API not allowed")
            else:
                resp = self._call(png)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(resp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                api_ms += resp["latency_ms"]
            parsed = json.loads(resp["output_text"])
            txt = "\n".join(parsed["lines"])
            page_texts.append(txt)
            uncertain += [{**u, "page": i + 1} for u in parsed["uncertain"]]
            for k, v in resp["usage"].items():
                usage_total[k] = usage_total.get(k, 0) + v
            cost_total += Decimal(resp["estimated_cost_usd"]) if resp["estimated_cost_usd"] not in (None, "None") else Decimal(0)
            artifact = {"page": i + 1, "image_px": list(image.size), "image_sha256": _sha(png), "text_sha256": _sha(txt.encode("utf-8")),
                        "response_cache": _display(cached.resolve()), "message_id": resp["id"], "served_model": resp["served_model"],
                        "stop_reason": resp["stop_reason"], "illegible_regions": parsed["illegible_regions"]}
            if self.artifacts_dir is not None:
                out = Path(self.artifacts_dir).resolve() / doc.sha256
                out.mkdir(parents=True, exist_ok=True)
                (out / f"page-{i + 1}.txt").write_text(txt, encoding="utf-8")
                artifact["raw_text_path"] = _display(out / f"page-{i + 1}.txt")
            pages_audit.append(artifact)
        offsets, parts, cursor = [], [], 0
        for text in page_texts:
            norm = normalize_whitespace(text)
            offsets.append(cursor)
            parts.append(norm)
            cursor += len(norm) + 1
        normalized = " ".join(parts)
        alnum = sum(ch.isalnum() for ch in normalized)
        usable = bool(page_texts) and alnum >= MIN_ALNUM_CHARS_PER_PAGE * len(page_texts)
        tl = TextLayer(usable=usable, pages=len(page_texts), alnum_chars=alnum, min_alnum_chars_per_page=MIN_ALNUM_CHARS_PER_PAGE,
                       page_texts=page_texts, normalized_text=normalized, page_offsets=offsets,
                       reason=None if usable else "VISION_TEXT_NOT_USABLE")
        audit = {**info, "pages": len(page_texts), "duration_ms": {"api": api_ms, "total": int((time.perf_counter() - t0) * 1000)},
                 "api_calls": len(page_texts) - replayed, "replayed_pages": replayed, "usage": usage_total,
                 "estimated_cost_usd": cost_total, "uncertain_tokens": uncertain, "page_artifacts": pages_audit}
        return tl, audit
