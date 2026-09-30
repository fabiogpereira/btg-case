"""Harness do E-004 exercitado offline (dataset original apenas; nenhum run da D no challenge set)."""
import json

from conftest import DOCS, GOLDEN
from test_hybrid_variant_d import Fake, v2

from corporate_actions.pipeline import SemanticContext, run_batch
from evaluation.e004 import efficiency, invocation_consistency, need_oracle_challenge, need_oracle_original, quality
from evaluation.llm_metrics import expected_ids_original

DOC06_DATES = [{"role": "record_date", "status": "FOUND", "value_as_written": "26/06/2026", "evidence": "Data-base do grupamento 26/06/2026"},
               {"role": "ex_date", "status": "FOUND", "value_as_written": "29/06/2026", "evidence": "Início da negociação grupada 29/06/2026"}]


class DevFake(Fake):
    def structured_call(self, system, user_text, tools, output_schema, max_tool_rounds=3):
        self.parsed = v2("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], DOC06_DATES)
        resp = super().structured_call(system, user_text, tools, output_schema, max_tool_rounds)
        args = {"identifier": "BRPQLTACNOR8", "identifier_type": "ISIN"}
        resp.tool_calls = [type(resp.tool_calls[0])("lookup_security", args, tools[0].handler(args), 10)]
        return resp


def test_need_oracle_is_computed_from_frozen_b_outputs():
    orig = {v["document"][:2] for v in need_oracle_original().values() if v["needed"]}
    assert orig == {"03", "06"}
    assert len([v for v in need_oracle_challenge().values() if v["needed"]]) == 7


def test_efficiency_and_quality_on_a_fake_d_run(tmp_path):
    run1, run2 = tmp_path / "d1", tmp_path / "d2"
    run_batch(DOCS, GOLDEN, run1, "d1", "D", SemanticContext(DevFake(None)))
    run_batch(DOCS, GOLDEN, run2, "d2", "D", SemanticContext(DevFake(None)))
    e = efficiency(run1, need_oracle_original(), expected_ids_original())
    assert e["invoked_documents"] == 1 and e["eligible_documents"] == 7
    assert e["false_negative_invocations"] == ["03_siderurgica_paranaense_proventos.pdf"]
    assert e["false_positive_invocations"] == []
    assert e["function_calling_invoked_docs"]["correct_calls"] == 1
    assert e["latency_end_to_end_with_llm"]["n"] == 1 and e["latency_end_to_end_without_llm"]["n"] == 7
    q = quality({"D": run1}, {})
    assert q["original"]["D"]["unsafe_auto_approvals"] == []
    c = invocation_consistency(run1, run2)
    assert c["invocation_decision_consistent"] == 8 and c["routing_decision_consistent"] == 8
    json.dumps(e)
