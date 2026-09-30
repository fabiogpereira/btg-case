import csv, json, re, datetime as dt
from decimal import Decimal
from pathlib import Path
O = Path(".")
norm = lambda s: re.sub(r"\s+", " ", s or "").strip()
gt = json.loads((O / "ground_truth.json").read_text(encoding="utf-8"))
rows = list(csv.DictReader((O / "golden_records.csv").open(encoding="utf-8")))
print("golden header:", list(rows[0].keys()), "rows:", len(rows))
for k in ("isin", "ticker", "cnpj"):
    vals = [r[k] for r in rows]; print(" dup", k, [v for v in set(vals) if vals.count(v) > 1])
bad_id = [r for r in rows if not re.fullmatch(r"BR[A-Z]{4}ACN(OR|PR)\d", r["isin"]) or not re.fullmatch(r"[A-Z]{4}(3|4)", r["ticker"])
          or (r["classe"] == "ON") != r["ticker"].endswith("3") or (r["classe"] == "ON") != (r["isin"][9:11] == "OR")]
print(" identifier/class inconsistencies:", [(r["ticker"], r["isin"], r["classe"]) for r in bad_id])
issues = []
STAT = {"present", "absent", "pending", "not_applicable"}
FIELDS = ["approval_date","record_date","ex_date","payment_date","share_credit_date","gross_amount_per_share","net_amount_per_share","withholding_tax","ratio"]
for c in gt["cases"]:
    cid = c["case_id"]; doc = (O / c["document_file"]).read_text(encoding="utf-8"); nd = norm(doc)
    miss = [f for f in FIELDS if f not in c["fields"]]
    if miss: issues.append((cid, "missing field keys", miss))
    for f, v in c["fields"].items():
        if v.get("status") not in STAT: issues.append((cid, f, "bad status", v.get("status")))
        ev = v.get("evidence")
        if v.get("status") in ("present", "pending"):
            if not ev: issues.append((cid, f, "no evidence"))
            elif ev not in doc: issues.append((cid, f, "evidence not literal" + (" (ok after whitespace norm)" if norm(ev) in nd else ""), ev[:90]))
        if v.get("status") == "present":
            val = v.get("rate") if f == "withholding_tax" else v.get("value")
            if f.endswith("_date"):
                try: dt.date.fromisoformat(val)
                except Exception: issues.append((cid, f, "bad date", val)); continue
        elif f != "withholding_tax" and v.get("value") not in (None, {}):
            issues.append((cid, f, "value with non-present status", v.get("status"), v.get("value")))
    for q in c.get("material_qualifiers", []) + c.get("non_material_context", []):
        if q.get("evidence") and q["evidence"] not in doc:
            issues.append((cid, "qualifier/context evidence not literal" + (" (ok after norm)" if norm(q["evidence"]) in nd else ""), q["evidence"][:90]))
    f = c["fields"]; g, n, w = f["gross_amount_per_share"], f["net_amount_per_share"], f["withholding_tax"]
    if g["status"] == n["status"] == w["status"] == "present" and w.get("rate"):
        calc = Decimal(g["value"]) * (1 - Decimal(w["rate"]))
        if calc != Decimal(n["value"]): issues.append((cid, "arithmetic", g["value"], w["rate"], n["value"], str(calc)))
    iss = c["issuer"]; inref = any(r["ticker"] == iss.get("ticker") and r["isin"] == iss.get("isin") and r["cnpj"] == iss.get("cnpj") for r in rows)
    partial = [r["ticker"] for r in rows if iss.get("ticker") and (r["ticker"] == iss.get("ticker") or r["isin"] == iss.get("isin") or r["cnpj"] == iss.get("cnpj"))]
    if bool(iss.get("in_reference_base")) != inref: issues.append((cid, "in_reference_base mismatch", iss.get("in_reference_base"), inref, partial))
    for k in ("cnpj", "isin", "ticker"):
        if iss.get(k) and iss[k] not in doc: issues.append((cid, "issuer id not in doc", k, iss[k]))
    if not c.get("routing_reason"): issues.append((cid, "no routing_reason"))
    print(cid, c["event_type"], c["expected_routing"], c["case_categories"], "| mq:", [q.get("affects") for q in c.get("material_qualifiers", [])])
print("\nISSUES:", len(issues)); [print(" ", i) for i in issues]
