"""Avaliação do challenge set sintético (E-003). Métricas próprias, nunca misturadas com as do dataset original."""
import json
from collections import defaultdict
from pathlib import Path

from .compare import load_run

CATEGORY_METRICS = {
    "negation": "negation_accuracy",
    "conditional_tax": "conditional_expression_accuracy",
    "alternative_date_labels": "date_role_mapping_accuracy",
    "misleading_keywords": "misleading_keywords_accuracy",
    "event_description": "event_description_accuracy",
}


def _ratio(n, d):
    return {"correct": n, "total": d, "pct": None if d == 0 else round(100 * n / d, 1)}


def _target_result(target: dict, rec: dict) -> dict:
    if target["target"] == "event_type":
        got = (rec.get("classification") or {}).get("event_type")
        return {"target": "event_type", "expected": target["expected"], "got": got, "correct": got == target["expected"]}
    fields = {**(rec.get("fields") or {}), **(rec.get("event_specific_fields") or {})}
    f = fields.get(target["field"])
    got_status = f["status"] if f else "ABSENT"
    got_value = f["value"] if f else None
    correct = got_status == target["expected_status"] and got_value == target["expected_value"]
    return {"target": target["field"], "expected": target["expected_value"], "got": got_value,
            "got_status": got_status, "correct": correct}


def evaluate_challenge(cs_dir: Path, run_dir: Path) -> dict:
    gt = json.loads((cs_dir / "ground_truth.json").read_text(encoding="utf-8"))
    records, manifest = load_run(run_dir)
    rows, per_category = [], defaultdict(lambda: [0, 0])
    for case in gt["cases"]:
        rec = records.get(case["sha256"], {})
        decision = (rec.get("routing") or {}).get("decision", "ABSENT")
        targets = [_target_result(t, rec) for t in case["targets"]]
        all_correct = all(t["correct"] for t in targets)
        exp = case["routing"]
        unsafe = decision == "AUTO_APPROVE" and (not all_correct or exp["decision"] != "AUTO_APPROVE")
        for cat in case["categories"]:
            per_category[cat][0] += sum(t["correct"] for t in targets)
            per_category[cat][1] += len(targets)
        rows.append({"case": case["id"], "categories": case["categories"], "targets": targets,
                     "decision": decision, "reason_codes": (rec.get("routing") or {}).get("reason_codes", []),
                     "expected_routing": exp, "routing_match": decision == exp["decision"],
                     "false_confident": [t["target"] for t in targets if not t["correct"]] if decision == "AUTO_APPROVE" else [],
                     "wrong_but_flagged": [t["target"] for t in targets if not t["correct"]] if decision != "AUTO_APPROVE" else [],
                     "unsafe_auto_approval": unsafe})
    all_targets = [t for r in rows for t in r["targets"]]
    defined = [r for r in rows if r["expected_routing"]["expectation_status"] == "DEFINED"]
    return {
        "run_id": manifest["run_id"], "pipeline_version": manifest["pipeline_version"],
        "challenge_set_version": gt["challenge_set_version"],
        "semantic_accuracy": _ratio(sum(t["correct"] for t in all_targets), len(all_targets)),
        **{metric: _ratio(*per_category[cat]) for cat, metric in CATEGORY_METRICS.items()},
        "false_confident_interpretations": sum(len(r["false_confident"]) for r in rows),
        "wrong_but_flagged": sum(len(r["wrong_but_flagged"]) for r in rows),
        "unsafe_auto_approvals": [r["case"] for r in rows if r["unsafe_auto_approval"]],
        "routing_defined": _ratio(sum(r["routing_match"] for r in defined), len(defined)),
        "review_rate": _ratio(sum(r["decision"] != "AUTO_APPROVE" for r in rows), len(rows)),
        "llm": manifest["summary"].get("llm"),
        "cases": rows,
    }
