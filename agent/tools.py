"""Reusable tools. Tools do not route requests or know workflow IDs."""
import csv
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from decimal import Decimal

import openpyxl

from .core import Clarification, WorkflowError, normalize, number, tool


def rows_from_file(ctx, filename):
    path = ctx.path(filename)
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise WorkflowError("Missing or duplicate file headers")
            rows = list(reader)
            if any(None in r for r in rows):
                raise WorkflowError("Row contains more fields than headers")
            return rows
    if path.suffix.lower() == ".xlsx":
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            iterator = book.active.values
            headers = next(iterator, None)
            if not headers or any(h is None for h in headers) or len(headers) != len(set(headers)):
                raise WorkflowError("Missing or duplicate spreadsheet headers")
            return [dict(zip(headers, row)) for row in iterator if any(v is not None for v in row)]
        finally:
            book.close()
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text())
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise WorkflowError("JSON data must be an array of objects")
        return rows
    raise WorkflowError("Only CSV, XLSX and JSON data files are supported")


@tool("read_rows")
def read_rows(ctx, args):
    return rows_from_file(ctx, ctx.inputs.get(args.get("input", "file")) or args["default"])


@tool("normalize_columns")
def normalize_columns(ctx, args):
    aliases = {"product_sku": "sku", "item_code": "sku", "stock_code": "sku", "product": "product_name", "name": "product_name", "product_title": "product_name"}
    out = []
    for row in ctx.state[args["source"]]:
        normalized = {}
        for k, v in row.items():
            key = re.sub(r"[^a-z0-9]+", "_", normalize(k)).strip("_")
            key = aliases.get(key, key)
            if key in normalized:
                raise WorkflowError("Columns normalize to duplicate field: " + key)
            normalized[key] = v.strip() if isinstance(v, str) else v
        out.append(normalized)
    return out


@tool("validate_rows")
def validate_rows(ctx, args):
    clean, invalid = [], []
    rows = ctx.state[args["source"]]
    if rows and not set(args["required"]).issubset(rows[0]):
        raise WorkflowError("Vendor file is missing required columns: " + ", ".join(args["required"]))
    for n, row in enumerate(rows, start=2):
        missing = [key for key in args["required"] if not str(row.get(key) or "").strip()]
        if missing:
            invalid.append({"row_number": n, "missing_fields": missing, "data": row})
        else:
            clean.append(row)
    return {"cleaned": clean, "invalid_rows": invalid, "total_rows": len(rows), "valid_count": len(clean), "invalid_count": len(invalid)}


def write_csv(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            # Prevent spreadsheet formula injection in exported untrusted text.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in row.items()})


@tool("export_validation")
def export_validation(ctx, args):
    result = dict(ctx.state[args["source"]])
    clean_path = ctx.run_dir / "cleaned.csv"
    invalid_path = ctx.run_dir / "invalid_rows.json"
    write_csv(clean_path, result["cleaned"], list(result["cleaned"][0]) if result["cleaned"] else ["sku", "product_name"])
    invalid_path.write_text(json.dumps(result["invalid_rows"], indent=2))
    result["files"] = [str(clean_path), str(invalid_path)]
    return result


@tool("restock")
def restock(ctx, args):
    out = []
    for row in ctx.state[args["source"]]:
        current = number(row.get("current_stock"), "current_stock")
        minimum = number(ctx.inputs.get("minimum_stock", row.get("minimum_stock")), "minimum_stock")
        if current < minimum:
            out.append({"sku": row["sku"], "product_name": row["product_name"], "current_stock": current,
                        "threshold": minimum, "reorder_quantity": minimum - current})
    return {"products_requiring_restock": out, "reorder_policy": "Top up to minimum stock; no supplier pack size assumed"}


@tool("compare_prices")
def compare_prices(ctx, args):
    vendor = {}
    for row in ctx.state[args["vendor"]]:
        sku = normalize(row.get("sku"))
        if not sku or sku in vendor:
            raise WorkflowError("Vendor SKUs must be present and unique")
        vendor[sku] = Decimal(str(number(row.get("price"), "vendor price")))
    report = []
    for row in ctx.state[args["products"]]:
        sku = normalize(row["sku"])
        price = Decimal(str(number(row.get("price"), "internal price")))
        if sku not in vendor:
            report.append({"sku": row["sku"], "status": "unmatched", "exception": True})
            continue
        base = vendor[sku]
        if base == 0:
            report.append({"sku": row["sku"], "status": "zero_vendor_price", "exception": True, "percentage_difference": None})
            continue
        difference = abs(price - base) / base * 100
        report.append({"sku": row["sku"], "internal_price": float(price), "vendor_price": float(base),
                       "percentage_difference": round(float(difference), 4), "exception": difference > Decimal("10"), "status": "matched"})
    return {"products": report, "exception_count": sum(r["exception"] for r in report), "denominator": "vendor price", "rule": "absolute difference > 10%"}


@tool("prepare_content")
def prepare_content(ctx, args):
    fields = ["product_name", "category", "attributes", "material", "color", "target_audience"]
    return {"facts": {k: ctx.inputs[k] for k in fields if ctx.inputs.get(k) not in (None, "", [], {})},
            "missing_information": [k for k in fields if ctx.inputs.get(k) in (None, "", [], {})]}


@tool("generate_content")
def generate_content(ctx, args):
    prepared = ctx.state[args["source"]]
    properties = {k: {"type": "string"} for k in ["description", "short_description", "seo_title", "meta_description"]}
    out = ctx.backend.generate("product_content", prepared["facts"], {"type": "object", "properties": properties, "required": list(properties)})
    if not isinstance(out, dict) or any(not isinstance(out.get(k), str) or not out[k].strip() for k in properties):
        raise WorkflowError("Generated product content has missing or invalid fields")
    if len(out["seo_title"]) > 60 or len(out["meta_description"]) > 160:
        raise WorkflowError("Generated SEO title/meta exceed 60/160 character limits")
    out["missing_information"] = prepared["missing_information"]
    out["review_note"] = "Review generated prose for factual accuracy before publishing"
    return out


@tool("validate_identifier")
def validate_identifier(ctx, args):
    order_id, email = ctx.inputs.get("order_id"), ctx.inputs.get("customer_email")
    if not order_id and not email:
        raise Clarification("Provide order_id or customer_email")
    if order_id and not re.fullmatch(r"ORD-[A-Za-z0-9-]+", str(order_id), re.I):
        raise Clarification("Order ID must look like ORD-1001")
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(email)):
        raise Clarification("Provide a valid customer email")
    return {"order_id": order_id, "customer_email": email}


@tool("lookup_orders")
def lookup_orders(ctx, args):
    identifiers = ctx.state[args["identifier"]]
    rows = rows_from_file(ctx, "orders.json")
    found = [r for r in rows if (not identifiers["order_id"] or normalize(r["order_id"]) == normalize(identifiers["order_id"])) and (not identifiers["customer_email"] or normalize(r["customer_email"]) == normalize(identifiers["customer_email"]))]
    if not found:
        raise Clarification("No order found. Please provide another order ID or email")
    return found


@tool("lookup_shipments")
def lookup_shipments(ctx, args):
    shipments = {r["order_id"]: r for r in rows_from_file(ctx, "shipments.json")}
    return [{**order, "shipment": shipments.get(order["order_id"], {"status": "Not shipped", "tracking": None})} for order in ctx.state[args["source"]]]


@tool("summarize_orders")
def summarize_orders(ctx, args):
    return {"orders": [{k: r[k] for k in ["order_id", "status", "items", "shipment"]} for r in ctx.state[args["source"]]], "source": "simulated order/shipment API fixtures"}


@tool("normalize_products")
def normalize_products(ctx, args):
    return [{**r, "normalized_sku": normalize(r.get("sku")), "normalized_name": normalize(r.get("product_name"))} for r in ctx.state[args["source"]]]


@tool("duplicate_groups")
def duplicate_groups(ctx, args):
    rows = ctx.state[args["source"]]
    if len(rows) > 2000:
        raise WorkflowError("Demo similarity tool supports up to 2000 products")
    parent = list(range(len(rows)))
    edges = []
    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for i, a in enumerate(rows):
        for j in range(i + 1, len(rows)):
            b = rows[j]
            fields = [k for k in ["category", "material", "color"] if a.get(k) and b.get(k)]
            matches = [k for k in fields if normalize(a[k]) == normalize(b[k])]
            exact = bool(a["normalized_sku"]) and a["normalized_sku"] == b["normalized_sku"]
            name_similarity = SequenceMatcher(None, a["normalized_name"], b["normalized_name"]).ratio()
            similar = bool(a["normalized_name"] and b["normalized_name"]) and name_similarity >= .85 and len(fields) >= 2 and len(matches) == len(fields)
            if exact or similar:
                parent[find(j)] = find(i)
                edges.append({"rows": [i + 2, j + 2], "matching_fields": (["sku"] if exact else ["product_name"] + matches), "confidence": 1 if exact else round(name_similarity, 3), "level": "definite" if exact else "possible"})
    groups = defaultdict(list)
    for i in range(len(rows)):
        groups[find(i)].append(i)
    out = []
    for indices in groups.values():
        if len(indices) < 2:
            continue
        row_numbers = {i + 2 for i in indices}
        pair_evidence = [e for e in edges if set(e["rows"]).issubset(row_numbers)]
        out.append({"products": [{"row_number": i + 2, "sku": rows[i].get("sku"), "product_name": rows[i].get("product_name")} for i in indices], "pair_evidence": pair_evidence,
                    "confidence": min(e["confidence"] for e in pair_evidence), "level": "definite" if all(e["level"] == "definite" for e in pair_evidence) else "possible"})
    return {"duplicate_groups": out, "note": "Similarity groups are connected candidate pairs; review before merging"}


@tool("prepare_campaign")
def prepare_campaign(ctx, args):
    # Goal and dates are mandatory; optional data is marked missing, never fabricated.
    return {k: ctx.inputs.get(k) for k in ["campaign_goal", "dates", "products", "target_audience", "promotion"]}


@tool("generate_campaign")
def generate_campaign(ctx, args):
    required = ["objective", "audience", "products", "messaging", "channels", "timeline", "checklist"]
    facts = ctx.state[args["source"]]
    schema = {"type": "object", "required": required, "properties": {k: {"type": "array" if k in ["products", "channels", "checklist"] else "string"} for k in required}}
    out = ctx.backend.generate("campaign_brief", facts, schema)
    if not isinstance(out, dict) or any(k not in out for k in required):
        raise WorkflowError("Generated campaign brief has missing fields")
    for k in required:
        if not isinstance(out[k], list if k in ["products", "channels", "checklist"] else str):
            raise WorkflowError("Invalid campaign field type: " + k)
    out["missing_information"] = [k for k, v in facts.items() if v in (None, "", [], {})]
    return out


@tool("deduplicate_keywords")
def deduplicate_keywords(ctx, args):
    seen = set()
    keywords = []
    for row in ctx.state[args["source"]]:
        if "keyword" not in row:
            raise WorkflowError("Keyword file requires a keyword column")
        k = normalize(row["keyword"])
        if k and k not in seen:
            seen.add(k)
            keywords.append(str(row["keyword"]).strip())
    return keywords


@tool("classify_keywords")
def classify_keywords(ctx, args):
    keywords = ctx.state[args["source"]]
    categories = ctx.inputs.get("categories")
    if not isinstance(categories, dict) or not categories or any(not isinstance(v, list) or not all(isinstance(t, str) and t for t in v) for v in categories.values()):
        raise Clarification("Provide categories as an object mapping category names to keyword arrays")
    if not keywords:
        ctx.state["keyword_generation_attempts"] = 0
        return []
    intents = ["informational", "commercial", "transactional", "navigational"]
    allowed_categories = list(categories) + ["unmapped"]
    schema = {"type": "object", "required": ["keywords"], "properties": {"keywords": {"type": "array", "items": {"type": "object", "required": ["keyword", "intent", "category", "priority", "target_page"], "properties": {"keyword": {"type": "string", "description": "Preserve the input keyword"}, "intent": {"type": "string", "enum": intents}, "category": {"type": "string", "enum": allowed_categories}, "priority": {"type": "string", "enum": ["high", "medium", "low"]}, "target_page": {"type": "string", "pattern": "^/(?!/)", "description": "A suggested relative website path starting with a single slash, for example /categories/clothing or /blog/shirt-care. Never return a page label or full URL."}}}}}}
    facts = {"keywords": keywords, "categories": categories}
    for attempt in range(2):
        ctx.state["keyword_generation_attempts"] = attempt + 1
        out = ctx.backend.generate("keywords", facts, schema)
        rows, errors = validate_keyword_report(out, keywords, allowed_categories, intents)
        if not errors:
            return rows
        # One bounded correction call; do not export malformed model output.
        facts = {"keywords": keywords, "categories": categories,
                 "correction_instruction": "Correct every listed validation error and return the complete report again. Use the exact schema enums and relative paths.",
                 "validation_errors": errors, "previous_report": out}
    raise WorkflowError("Keyword report invalid after 2 generation attempts: " + "; ".join(errors[:3]))


def validate_keyword_report(out, keywords, categories, intents):
    rows = out.get("keywords") if isinstance(out, dict) else None
    if not isinstance(rows, list) or len(rows) != len(keywords):
        return [], ["Return each unique keyword exactly once"]
    if not all(isinstance(r, dict) for r in rows):
        return [], ["Each keyword report row must be an object"]
    errors = []
    if Counter(normalize(r.get("keyword")) for r in rows) != Counter(normalize(k) for k in keywords):
        errors.append("Keyword inputs were changed, omitted or duplicated")
    category_lookup = {normalize(c): c for c in categories}
    for i, original in enumerate(rows, 1):
        r = dict(original)
        rows[i - 1] = r
        # Canonicalize harmless casing/whitespace; unknown labels still fail validation.
        for field in ("intent", "priority"):
            if isinstance(r.get(field), str):
                r[field] = normalize(r[field])
        if isinstance(r.get("category"), str):
            r["category"] = category_lookup.get(normalize(r["category"]), r["category"])
        if isinstance(r.get("target_page"), str):
            r["target_page"] = r["target_page"].strip()
        for field, allowed in [("intent", intents), ("category", categories), ("priority", ["high", "medium", "low"])]:
            if not isinstance(r.get(field), str) or r[field] not in allowed:
                errors.append(f"Row {i} {field} must be one of {allowed}; got {repr(r.get(field))[:80]}")
        if not isinstance(r.get("keyword"), str) or not r["keyword"].strip():
            errors.append(f"Row {i} keyword must be a nonempty string")
        page = r.get("target_page")
        if not isinstance(page, str) or not page.startswith("/") or page.startswith("//"):
            errors.append(f"Row {i} target_page must be a relative path such as /categories/clothing; got {repr(page)[:80]}")
    return rows, errors


@tool("export_keywords")
def export_keywords(ctx, args):
    rows = ctx.state[args["source"]]
    path = ctx.run_dir / "keywords.csv"
    write_csv(path, rows, ["keyword", "intent", "category", "priority", "target_page"])
    return {"keywords": rows, "file": str(path), "generation_attempts": ctx.state.get("keyword_generation_attempts", 1)}


@tool("rank_employees")
def rank_employees(ctx, args):
    skills = ctx.inputs.get("required_skills")
    if not isinstance(skills, list) or not skills or not all(isinstance(s, str) and s.strip() for s in skills):
        raise Clarification("Provide required_skills as a nonempty array; confirm task skill requirements")
    required = {normalize(s) for s in skills}
    ranked = []
    for row in ctx.state[args["source"]]:
        available = {normalize(s) for s in str(row.get("skills", "")).split(";")}
        workload = number(row.get("workload"), "workload")
        capacity = number(row.get("capacity"), "capacity")
        ranked.append({"employee_id": row["employee_id"], "name": row["name"], "matched_skills": sorted(required & available),
                       "missing_skills": sorted(required - available), "available_capacity": capacity - workload,
                       "eligible": required.issubset(available) and capacity > workload})
    return sorted(ranked, key=lambda r: (r["eligible"], len(r["matched_skills"]), r["available_capacity"], r["employee_id"]), reverse=True)


@tool("recommend_assignment")
def recommend_assignment(ctx, args):
    ranked = ctx.state[args["source"]]
    eligible = [r for r in ranked if r["eligible"]]
    if not eligible:
        return {"escalated": True, "recommended_employee": None, "reason": "No employee has all required skills and available capacity", "candidates": ranked, "priority": ctx.inputs["priority"], "deadline": ctx.inputs["deadline"], "task_summary": ctx.inputs["task_description"]}
    best = eligible[0]
    return {"escalated": False, "recommended_employee": best, "reason": "All required skills match; greatest available capacity among eligible employees", "priority": ctx.inputs["priority"], "deadline": ctx.inputs["deadline"], "task_summary": ctx.inputs["task_description"], "candidates": ranked, "action": "recommendation only; task database not modified"}


@tool("performance_metrics")
def performance_metrics(ctx, args):
    grouped = defaultdict(list)
    for row in ctx.state[args["source"]]:
        if row.get("status") not in ["success", "error", "failure", "needs_input"]:
            raise WorkflowError("Log status must be success, error, failure or needs_input")
        number(row.get("duration_ms"), "duration_ms")
        grouped[row["workflow_id"]].append(row)
    threshold = number(ctx.inputs.get("slow_threshold_ms", 1000), "slow_threshold_ms")
    metrics = []
    for wid, rows in sorted(grouped.items()):
        complete = [r for r in rows if r["status"] != "needs_input"]
        failures = sum(r["status"] in ["error", "failure"] for r in complete)
        avg = sum(number(r["duration_ms"], "duration_ms") for r in complete) / len(complete) if complete else 0
        rate = failures / len(complete) if complete else 0
        errors = Counter(r.get("error", "unspecified") or "unspecified" for r in complete if r["status"] in ["error", "failure"])
        step_times = defaultdict(list)
        for row in complete:
            steps = row.get("steps", [])
            if isinstance(steps, str):
                steps = json.loads(steps or "[]")
            for step in steps:
                step_times[step["name"]].append(number(step["duration_ms"], "step duration"))
        metrics.append({"workflow_id": wid, "execution_count": len(rows), "completed_count": len(complete), "needs_input_count": len(rows) - len(complete), "failure_rate": round(rate, 4), "success_rate": round(1 - rate, 4) if complete else None, "average_execution_ms": round(avg, 3), "frequent_errors": dict(errors.most_common(3)), "slow_steps": [{"name": k, "average_ms": round(sum(v) / len(v), 3)} for k, v in step_times.items() if sum(v) / len(v) > threshold], "flagged": rate > .10 or avg > threshold})
    return {"workflows": metrics, "slow_threshold_ms": threshold, "rule": "Failure rate > 10% OR average duration > threshold; needs_input excluded"}


@tool("performance_recommendations")
def performance_recommendations(ctx, args):
    result = dict(ctx.state[args["source"]])
    result["recommendations"] = [{"workflow_id": r["workflow_id"], "actions": (["Investigate frequent errors: " + ", ".join(r["frequent_errors"])] if r["failure_rate"] > .1 else []) + (["Profile slow tools; consider caching or batching"] if r["average_execution_ms"] > result["slow_threshold_ms"] or r["slow_steps"] else [])} for r in result["workflows"] if r["flagged"] or r["slow_steps"]]
    return result
