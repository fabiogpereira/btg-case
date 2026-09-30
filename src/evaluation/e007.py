"""E-007 — hardening determinístico pré-OCR (variante G × F). PRÉ-REGISTRADO antes da regressão oficial.

python -m evaluation.e007 run   --out outputs/experiments/E-007_pre_ocr     (regressão da G por replay, sem API)
python -m evaluation.e007 eval  --out outputs/experiments/E-007_pre_ocr/evaluation

Conjuntos (todos regression sets; nenhum é blind para a G): original (desenvolvimento), challenge, blind-derived,
BT-002 (deixa de ser blind a partir daqui). F = registros oficiais congelados (E-006 e BT-002).

Replay: a G usa exatamente as respostas do LLM gravadas nos runs oficiais da F (mesmo prompt, mesmo texto). Onde a G
pedir o LLM num documento em que a F não pediu, o replay não tem resposta: o provedor de replay devolve erro (sem rede),
o documento vai para revisão por `SEMANTIC_INTERPRETER_FAILED` e é listado em `cache_misses`. Nenhuma chamada de API.

Métricas pré-registradas:
- segurança: enhanced (D-025, `e006.enhanced_components`), com componentes separados; aprovações com identidade errada;
  bindings errados (valor final vindo de regra de rótulo, diferente do gabarito); omissões; aprovações falsas;
- identidade (G): contagem por método; não resolvidas; conflitos; identidade errada = linha casada com ISIN/ticker/CNPJ
  diferente do gabarito (onde o gabarito tem identidade: original, blind-derived, BT-002);
- binding (G): associações mantidas, rejeitadas (por motivo), bindings errados evitados (candidato rejeitado com valor
  diferente do gabarito), bindings corretos perdidos (rejeitado com valor igual ao gabarito);
- utilidade: acurácia de roteamento, taxa de revisão, aprovações corretas, false reviews.
Critérios de sucesso (seção `success_criteria`), fixados antes da regressão.
"""
import argparse
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

from .blind import value_match as blind_value_match
from .bt002 import evaluate as evaluate_bt002, load_truth as load_truth_bt002
from .e006 import E_RUNS, _field, evaluate_run, truth_blind, truth_challenge, truth_original

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "case" / "Case AI Dev - Envio"
E6 = ROOT / "outputs" / "experiments" / "E-006_hardened"
B2 = ROOT / "outputs" / "experiments" / "BT-002_blind_F"
DATASETS = {
    "original": (CASE / "documents", CASE / "golden_records" / "golden records.csv", E6 / "llm_cache_run1", E6 / "original_F"),
    "challenge": (ROOT / "tests" / "challenge_set" / "cases", CASE / "golden_records" / "golden records.csv",
                  E6 / "llm_cache_run1", E6 / "challenge_F"),
    "blind_derived": (ROOT / "tests" / "blind_set" / "documents", ROOT / "tests" / "blind_set" / "golden_records.csv",
                      E6 / "llm_cache_run1", E6 / "blind_derived_F"),
    "bt002": (ROOT / "tests" / "blind_set_v2" / "documents", ROOT / "tests" / "blind_set_v2" / "golden_records.csv",
              B2 / "llm_cache_run1", B2 / "blind_F"),
}
DATE_FIELDS = {"approval_date", "record_date", "ex_date", "payment_date", "share_credit_date"}


# --- regressão por replay ----------------------------------------------------------------------------

class ReplayProvider:
    """Mesma configuração dos runs oficiais; sem rede. Cache miss -> resposta com erro (registrada)."""
    name = "replay-only"

    def __init__(self):
        from corporate_actions.llm.config import LLMConfig
        self.config = LLMConfig("anthropic", "claude-opus-5", "medium", 8000, "off", 120)
        self.misses = 0

    def structured_call(self, *args, **kwargs):
        from corporate_actions.llm.base import LLMResponse
        self.misses += 1
        resp = LLMResponse("replay-only", self.config.model, None, None, None, None, 0)
        resp.errors.append("replay_cache_miss: no recorded response for this request (no API call made)")
        return resp


def run_regression(out: Path):
    from corporate_actions.llm.cache import ResponseCache
    from corporate_actions.pipeline import SemanticContext, run_batch
    for name, (docs, golden, cache, _) in DATASETS.items():
        provider = ReplayProvider()
        manifest = run_batch(docs, golden, out / f"{name}_G", run_id=f"e007-replay-{name}", variant="G",
                             semantic_ctx=SemanticContext(provider, ResponseCache(cache)))
        print(name, manifest["summary"]["decisions"], "cache_misses:", provider.misses)


# --- gabarito comum para binding/identidade -------------------------------------------------------------

def _records(run_dir: Path, key: str) -> dict:
    return {r["document"][key]: r for r in
            (json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "records").glob("*.json")))}


def truths(dataset):
    if dataset == "original":
        return truth_original(), "sha256"
    if dataset == "challenge":
        return truth_challenge(), "sha256"
    if dataset == "blind_derived":
        return truth_blind(), "file_name"
    return load_truth_bt002(ROOT / "tests" / "blind_set_v2" / "ground_truth.json")[0], "file_name"


def _gt_value(truth, name):
    """Valor do gabarito normalizado para comparação com candidatos: data ISO, Decimal, alíquota Decimal."""
    gf = truth["fields"].get(name)
    if not gf or gf["status"] != "found":
        return None
    if "raw" in gf:
        raw = gf["raw"]
        v = raw.get("rate") if name == "withholding_tax" else raw.get("value")
    else:
        v = gf["value"]["rate"] if name == "withholding_tax" and isinstance(gf["value"], dict) else gf["value"]
    if v is None or isinstance(v, dict):
        return None
    return v if name in DATE_FIELDS else Decimal(str(v))


def _norm_raw(name, raw):
    from corporate_actions.normalization import parse_date
    from corporate_actions.numeric import parse_br_decimal, parse_br_percent
    from corporate_actions.profiles import DETERMINISTIC_PROFILE
    token = DETERMINISTIC_PROFILE.set("v2")
    try:
        if name in DATE_FIELDS:
            return parse_date(raw).isoformat()
        if name == "withholding_tax":
            return parse_br_percent(raw)
        return parse_br_decimal(raw)
    except Exception:
        return None
    finally:
        DETERMINISTIC_PROFILE.reset(token)


def _field_ok(truth, name, got):
    gf = truth["fields"][name]
    if "raw" in gf:
        return blind_value_match(name, gf["raw"], got)
    return bool(got) and got["status"] == "found" and got["value"] == gf["value"]


def wrong_bindings(rec, truth) -> list[str]:
    """Campo cujo valor final veio de regra de rótulo e difere do gabarito. Para o IR, o binding é a alíquota
    associada ao rótulo (a base vem de outra regra e é avaliada na semântica, não aqui)."""
    out = []
    for name, gf in truth["fields"].items():
        got = _field(rec, name)
        if gf["status"] != "found" or not got or got["status"] != "found":
            continue
        if not any(".label" in r and not r.startswith("llm.") for r in got.get("extraction_rules", [])):
            continue
        if name == "withholding_tax":
            gtv = _gt_value(truth, name)
            wrong = gtv is not None and Decimal(str(got["value"]["rate"])) != gtv
        else:
            wrong = not _field_ok(truth, name, got)
        if wrong:
            out.append(name)
    return out


def identity_truth(dataset, truth, rec):
    if dataset == "original":
        return {k: truth["fields"][k]["value"] for k in ("isin", "ticker", "cnpj")
                if k in truth["fields"] and truth["fields"][k]["status"] == "found"}
    if dataset in ("blind_derived", "bt002"):
        return {k: truth["fields"][k]["value"] for k in ("isin", "ticker", "cnpj") if k in truth["fields"]}
    return None


def matched_row(rec):
    if rec.get("identity"):
        return rec["identity"].get("matched_reference")
    return (rec.get("reference_check") or {}).get("golden_row")


def evaluate_variant(dataset, run_dir) -> dict:
    tr, key = truths(dataset)
    recs = _records(run_dir, key)
    base = evaluate_bt002(run_dir) if dataset == "bt002" else evaluate_run(dataset, run_dir)
    rows = []
    for k, truth in tr.items():
        rec = recs[k]
        auto = rec["routing"]["decision"] == "AUTO_APPROVE"
        idt = identity_truth(dataset, truth, rec)
        row = matched_row(rec)
        wrong_id = bool(row and idt and any(row.get(f) != v for f, v in idt.items() if v))
        wb = wrong_bindings(rec, truth)
        prevented, lost, bound, rejected = [], [], 0, {}
        for b in rec.get("binding", []):
            if b["decision"] == "BOUND":
                bound += 1
                continue
            rejected[b["reason"]] = rejected.get(b["reason"], 0) + 1
            gtv = _gt_value(truth, b["field"])
            if gtv is not None:
                (lost if _norm_raw(b["field"], b["raw"]) == gtv else prevented).append(f"{b['field']}={b['raw']}")
        ident = rec.get("identity") or {}
        rows.append({"id": truth["id"], "decision": rec["routing"]["decision"], "reasons": rec["routing"]["reason_codes"],
                     "identity_method": ident.get("identity_method"), "identity_reason": ident.get("reason_code"),
                     "identity_conflicts": ident.get("conflicts", []), "wrong_identity": wrong_id,
                     "wrong_identity_approved": auto and wrong_id, "wrong_bindings": wb,
                     "wrong_bindings_approved": wb if auto else [], "bindings_bound": bound, "bindings_rejected": rejected,
                     "wrong_bindings_prevented": prevented, "correct_bindings_lost": lost,
                     "llm_errors": (rec.get("llm") or {}).get("errors", [])})
    count = lambda m: sum(r["identity_method"] == m for r in rows)
    safety = base["safety_enhanced"] if dataset != "bt002" else {
        "unsafe_auto_approvals_enhanced": base["safety"]["unsafe_auto_approvals_enhanced"],
        "material_omissions_approved": base["safety"]["material_omissions_approved"],
        "hallucinations_approved": base["safety"]["hallucinations_approved"],
        "unresolved_ambiguity_approved": base["safety"]["unresolved_ambiguity_approved"],
        "validation_failures_approved": base["safety"]["validation_failures_approved"],
        "contradictions_approved": base["safety"]["semantic_contradictions_approved"]}
    routing = base["routing"]
    if dataset == "bt002":
        routing = {"accuracy_defined": routing["accuracy"], "false_approvals": routing["false_approvals"],
                   "false_reviews": routing["false_reviews"], "review_rate": routing["review_rate"],
                   "correct_auto_approvals": routing["correct_auto_approvals"]}
    else:
        routing = {**routing, "correct_auto_approvals": [r["id"] for r in base["per_document"] if r["routing_kind"] == "correct_auto"]}
    return {
        "safety": {**{k: v for k, v in safety.items() if k != "detail"},
                   "wrong_identity_approvals": [r["id"] for r in rows if r["wrong_identity_approved"]],
                   "wrong_bindings_approved": {r["id"]: r["wrong_bindings_approved"] for r in rows if r["wrong_bindings_approved"]},
                   "false_approvals": routing["false_approvals"]},
        "identity": {"ISIN_EXACT": count("ISIN_EXACT"), "TICKER_AND_CNPJ_EXACT": count("TICKER_AND_CNPJ_EXACT"),
                     "TICKER_AND_ISSUER_EXACT": count("TICKER_AND_ISSUER_EXACT"), "UNRESOLVED": count("UNRESOLVED"),
                     "conflicts_detected": {r["id"]: r["identity_conflicts"] for r in rows if r["identity_conflicts"]},
                     "unresolved_reasons": {r["id"]: r["identity_reason"] for r in rows if r["identity_method"] == "UNRESOLVED"},
                     "wrong_identity_any_routing": [r["id"] for r in rows if r["wrong_identity"]]},
        "binding": {"bound": sum(r["bindings_bound"] for r in rows),
                    "rejected": {k: sum(r["bindings_rejected"].get(k, 0) for r in rows)
                                 for k in sorted({k for r in rows for k in r["bindings_rejected"]})},
                    "wrong_bindings_any_routing": {r["id"]: r["wrong_bindings"] for r in rows if r["wrong_bindings"]},
                    "wrong_bindings_prevented": {r["id"]: r["wrong_bindings_prevented"] for r in rows if r["wrong_bindings_prevented"]},
                    "correct_bindings_lost": {r["id"]: r["correct_bindings_lost"] for r in rows if r["correct_bindings_lost"]}},
        "utility": routing,
        "cache_misses": [r["id"] for r in rows if any("replay_cache_miss" in e for e in r["llm_errors"])],
        "per_document": rows,
    }


def success_criteria(res) -> dict:
    G, F = res["G"], res["F"]
    ds = list(G)
    return {
        "1_enhanced_unsafe_zero": all(not G[d]["safety"]["unsafe_auto_approvals_enhanced"] for d in ds),
        "2_no_approval_by_ambiguous_or_wrong_identity": all(not G[d]["safety"]["wrong_identity_approvals"] for d in ds) and all(
            r["identity_method"] != "UNRESOLVED" for d in ds for r in G[d]["per_document"] if r["decision"] == "AUTO_APPROVE"),
        "3_no_silent_wrong_binding": all(not G[d]["safety"]["wrong_bindings_approved"] for d in ds) and all(
            len(G[d]["binding"]["wrong_bindings_any_routing"]) <= len(F[d]["binding"]["wrong_bindings_any_routing"]) for d in ds),
        "4_missing_isin_not_absolute_block": any(G[d]["identity"]["TICKER_AND_CNPJ_EXACT"] + G[d]["identity"]["TICKER_AND_ISSUER_EXACT"]
                                                 for d in ds),
        "5_no_material_regression_original": (G["original"]["utility"]["false_reviews"] == F["original"]["utility"]["false_reviews"]
                                              and G["original"]["utility"]["correct_auto_approvals"] == F["original"]["utility"]["correct_auto_approvals"]
                                              and not G["original"]["binding"]["correct_bindings_lost"]),
        "definitions": {"2": "nenhuma aprovação com identidade errada nem com identidade UNRESOLVED",
                        "3": "nenhum binding errado em registro aprovado; bindings errados (qualquer roteamento) da G <= F por conjunto",
                        "4": "pelo menos uma identidade resolvida sem ISIN (nível 2) nos conjuntos; o invariante é provado nos testes unitários",
                        "5": "no original: mesmas aprovações corretas e false reviews da F; nenhum binding correto perdido",
                        "6": "qualitativo (simplicidade e auditabilidade): no log"},
    }


def evaluate_all(g_dir: Path) -> dict:
    res = {"F": {}, "G": {}, "notes": {"F": "registros oficiais congelados (E-006 e BT-002)",
                                       "G": "regressão por replay das respostas do LLM da F (sem API)",
                                       "datasets": "todos regression sets; BT-002 deixa de ser blind"}}
    for name, (_, _, _, f_run) in DATASETS.items():
        res["F"][name] = evaluate_variant(name, f_run)
        res["G"][name] = evaluate_variant(name, g_dir / f"{name}_G")
    res["success_criteria"] = success_criteria(res)
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "eval"])
    p.add_argument("--g-dir", type=Path, default=ROOT / "outputs" / "experiments" / "E-007_pre_ocr")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.cmd == "run":
        run_regression(a.out)
        return
    a.out.mkdir(parents=True, exist_ok=True)
    res = evaluate_all(a.g_dir)
    (a.out / "e007_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    summary = {v: {d: {"unsafe": m["safety"]["unsafe_auto_approvals_enhanced"], "wrong_identity": m["safety"]["wrong_identity_approvals"],
                       "wrong_bindings_approved": m["safety"]["wrong_bindings_approved"], "identity": {k: m["identity"][k] for k in
                       ("ISIN_EXACT", "TICKER_AND_CNPJ_EXACT", "TICKER_AND_ISSUER_EXACT", "UNRESOLVED")},
                       "routing": m["utility"]["accuracy_defined"], "review_rate": m["utility"]["review_rate"],
                       "correct_auto": m["utility"]["correct_auto_approvals"], "false_reviews": m["utility"]["false_reviews"],
                       "cache_misses": m["cache_misses"]} for d, m in res[v].items()} for v in ("F", "G")}
    print(json.dumps({"summary": summary, "success_criteria": res["success_criteria"]}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
