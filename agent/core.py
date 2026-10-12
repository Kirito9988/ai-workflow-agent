"""Shared catalog, tool registry and bounded workflow runtime."""
from __future__ import annotations

import csv
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {}


class WorkflowError(Exception):
    pass


class Clarification(WorkflowError):
    pass


class TransientError(WorkflowError):
    pass


class QuotaError(WorkflowError):
    """Pause rather than automatically consuming more exhausted provider quota."""
    pass


def tool(name):
    def register(fn):
        if name in TOOLS:
            raise ValueError(f"Duplicate tool: {name}")
        TOOLS[name] = fn
        return fn
    return register


def number(value, field, minimum=0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise WorkflowError(f"{field} must be a number") from None
    if not math.isfinite(result) or result < minimum:
        raise WorkflowError(f"{field} must be finite and >= {minimum}")
    return result


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def clean_inputs(inputs):
    if inputs is None:
        return {}
    if not isinstance(inputs, dict):
        raise WorkflowError("inputs must be an object")
    # Empty template placeholders are not user-supplied facts or overrides.
    return {k: v for k, v in inputs.items()
            if v is not None and v != [] and v != {} and not (isinstance(v, str) and not v.strip())}


class Catalog:
    def __init__(self, excel=None, definitions=None):
        book = openpyxl.load_workbook(excel or ROOT / "data/workflows.xlsx", read_only=True, data_only=True)
        try:
            rows = list(book["Workflows"].values)
        finally:
            book.close()
        required = ["Workflow_ID", "Workflow_Name", "Trigger", "Inputs", "Steps", "Decision_Logic", "Tools_Required", "Expected_Output"]
        if list(rows[0]) != required:
            raise WorkflowError("Unexpected Excel header: expected " + ", ".join(required))
        specs = definitions if definitions is not None else json.loads((ROOT / "data/definitions.json").read_text())
        self.workflows = {}
        for row in rows[1:]:
            if not any(row):
                continue
            source = dict(zip(required, row))
            wid = source["Workflow_ID"]
            if wid in self.workflows or wid not in specs:
                raise WorkflowError(f"Duplicate or unimplemented Excel workflow: {wid}")
            definition = specs[wid]
            # Fail closed when the prose source changes; reviewed bindings must be updated.
            if definition["source"] != source:
                raise WorkflowError(f"Excel source changed for {wid}; review and update its definition")
            if not definition["steps"] or len(definition["steps"]) > 30:
                raise WorkflowError(f"Invalid step count for {wid}")
            self.workflows[wid] = definition


class Context:
    def __init__(self, inputs, backend, data_dir, run_dir):
        self.inputs = inputs
        self.backend = backend
        self.data_dir = Path(data_dir).resolve()
        self.run_dir = Path(run_dir)
        self.state = {}

    def path(self, name):
        p = (self.data_dir / str(name)).resolve()
        if not p.is_relative_to(self.data_dir):
            raise WorkflowError("Input file must be inside the data directory")
        if not p.is_file():
            raise WorkflowError(f"Input file not found: {name}")
        if p.stat().st_size > 5_000_000:
            raise WorkflowError("Input file exceeds 5 MB")
        return p


class Engine:
    def __init__(self, backend, catalog=None, data_dir=None, output_dir=None):
        from . import tools  # noqa: F401; register reusable capabilities
        self.catalog = catalog or Catalog()
        self.backend = backend
        self.data_dir = Path(data_dir or ROOT / "data")
        self.output_dir = Path(output_dir or ROOT / "runs")
        for definition in self.catalog.workflows.values():
            for step in definition["steps"]:
                if step["tool"] not in TOOLS:
                    raise WorkflowError(f"Unknown registered tool: {step['tool']}")

    def input_guide(self, wid, values=None):
        definition = self.catalog.workflows[wid]
        return {"input_template": {**definition.get("input_template", {}), **clean_inputs(values)},
                "input_help": definition.get("input_help", {}),
                "required_fields": definition.get("required", []),
                "input_note": definition.get("input_note", "")}

    def prepare(self, request, inputs=None):
        """Identify intent and show input fields without executing business tools."""
        try:
            if not isinstance(request, str) or not request.strip() or len(request) > 8000:
                raise Clarification("Provide a request of 1–8000 characters")
            supplied = clean_inputs(inputs)
            selection = self.backend.select(request, self.catalog, supplied)
            wid = selection.get("workflow_id")
            confidence = number(selection.get("confidence"), "routing confidence")
            if wid not in self.catalog.workflows or not .65 <= confidence <= 1:
                raise Clarification(selection.get("reason") or "Please specify one supported workflow")
            extracted = clean_inputs(selection.get("inputs", {}))
            guide = self.input_guide(wid, {**extracted, **supplied})
            return {"status": "ready", "workflow_id": wid,
                    "selected_workflow": self.catalog.workflows[wid]["source"]["Workflow_Name"],
                    "selection_reason": selection.get("reason"), **guide}
        except Clarification as exc:
            return {"status": "needs_input", "message": str(exc)}
        except QuotaError as exc:
            return {"status": "error", "error_code": "rate_limited", "message": str(exc)}
        except (WorkflowError, ValueError, TypeError, KeyError) as exc:
            return {"status": "error", "message": str(exc)}

    def run(self, request, inputs=None):
        started = time.perf_counter()
        run_id = uuid.uuid4().hex
        result = {"run_id": run_id, "mode": self.backend.mode, "request": request,
                  "workflow_id": None, "selected_workflow": None, "status": "error", "steps": []}
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            if not isinstance(request, str) or not request.strip() or len(request) > 8000:
                raise Clarification("Provide a request of 1–8000 characters")
            inputs = clean_inputs(inputs)
            for attempt in range(2):
                result["selection_attempts"] = attempt + 1
                try:
                    selection = self.backend.select(request, self.catalog, inputs or {})
                    break
                except TransientError:
                    if attempt == 1:
                        raise
                    time.sleep(.25)
            wid = selection.get("workflow_id")
            confidence = number(selection.get("confidence"), "routing confidence")
            if wid not in self.catalog.workflows or confidence < .65 or confidence > 1:
                raise Clarification(selection.get("reason") or "Please specify one supported workflow")
            definition = self.catalog.workflows[wid]
            result.update(workflow_id=wid, selected_workflow=definition["source"]["Workflow_Name"],
                          selection_reason=selection.get("reason"), confidence=confidence)
            extracted = selection.get("inputs", {})
            if not isinstance(extracted, dict):
                raise WorkflowError("LLM returned invalid input object")
            # Explicit inputs win over inferred values; never populate missing business inputs from fixtures.
            merged = {**clean_inputs(extracted), **inputs}
            result.update(self.input_guide(wid, merged))
            missing = [key for key in definition.get("required", []) if merged.get(key) in (None, "", [], {})]
            if missing:
                raise Clarification("Please provide: " + ", ".join(missing))
            ctx = Context(merged, self.backend, self.data_dir, run_dir)
            for step in definition["steps"]:
                when = step.get("when")
                if when and not ctx.state.get(when):
                    result["steps"].append({"name": step["name"], "tool": step["tool"], "status": "skipped", "duration_ms": 0})
                    continue
                entry = {"name": step["name"], "tool": step["tool"], "status": "running", "attempts": 0}
                result["steps"].append(entry)
                before = time.perf_counter()
                try:
                    for attempt in range(3):
                        entry["attempts"] += 1
                        try:
                            out = TOOLS[step["tool"]](ctx, step.get("args", {}))
                            break
                        except TransientError:
                            if attempt == 2:
                                raise
                            time.sleep(.05 * 2 ** attempt)
                    ctx.state[step["save_as"]] = out
                    entry.update(status="success", output=out)
                except Exception:
                    entry["status"] = "error"
                    raise
                finally:
                    entry["duration_ms"] = round((time.perf_counter() - before) * 1000, 3)
            result.update(status="success", result=ctx.state[definition["output"]])
        except Clarification as exc:
            result.update(status="needs_input", message=str(exc))
        except QuotaError as exc:
            result.update(status="error", error_code="rate_limited", message=str(exc))
        except (WorkflowError, ValueError, KeyError, TypeError, OSError, csv.Error) as exc:
            result.update(status="error", message=str(exc))
        except Exception:
            # Do not leak credentials, stack traces or model responses to the UI.
            result.update(status="error", message="Unexpected tool failure; inspect local application diagnostics")
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        (run_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return result
