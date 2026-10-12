import copy
import io
import json
import ssl
import tempfile
import unittest
from pathlib import Path
import urllib.error
from unittest.mock import patch

from agent.core import Catalog, Engine, ROOT, TOOLS, QuotaError, TransientError, WorkflowError
from agent.llm import DemoLLM, LiveLLM


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = Engine(DemoLLM(), output_dir=self.tmp.name)
        self.examples = json.loads((ROOT / "examples/requests.json").read_text())

    def run_example(self, n, updates=None):
        e = self.examples[n-1]
        return self.engine.run(e["request"], {**e["inputs"], **(updates or {})})

    def fixture(self, name, rows):
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps(rows))
        self.engine.data_dir = Path(self.tmp.name)
        return name

    def test_all_excel_requests_select_and_execute(self):
        for n, e in enumerate(self.examples, 1):
            with self.subTest(workflow=e["workflow_id"]):
                r = self.run_example(n)
                self.assertEqual(r["workflow_id"], e["workflow_id"])
                self.assertEqual(r["status"], "success", r)
                self.assertTrue(all(s["status"] == "success" for s in r["steps"]))

    def test_restock_strict_threshold_and_quantity(self):
        r = self.run_example(1)["result"]["products_requiring_restock"]
        self.assertEqual([x["sku"] for x in r], ["SKU-001"])
        self.assertEqual(r[0]["reorder_quantity"], 16)

    def test_restock_override(self):
        r = self.run_example(1, {"minimum_stock": 5})["result"]["products_requiring_restock"]
        self.assertEqual(r[0]["reorder_quantity"], 1)

    def test_invalid_stock(self):
        for value in [-1, "bad", "NaN", "Infinity"]:
            self.assertEqual(self.run_example(1, {"minimum_stock": value})["status"], "error")

    def test_prices_boundary_and_zero_and_unmatched(self):
        r = self.run_example(2)["result"]["products"]
        self.assertTrue(r[0]["exception"])
        self.assertEqual(r[1]["percentage_difference"], 10)
        self.assertFalse(r[1]["exception"])
        self.assertEqual(r[3]["status"], "zero_vendor_price")
        self.assertEqual(r[4]["status"], "unmatched")

    def test_vendor_invalid_rows_and_exports(self):
        r = self.run_example(3)["result"]
        self.assertEqual((r["valid_count"], r["invalid_count"]), (1, 2))
        self.assertEqual(r["cleaned"][0]["sku"], "V001")
        self.assertTrue(all(Path(p).exists() for p in r["files"]))

    def test_vendor_missing_file_requests_input(self):
        r = self.engine.run(self.examples[2]["request"])
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(r["steps"], [])

    def test_vendor_missing_columns(self):
        filename = self.fixture("bad.json", [{"price": 5}])
        self.assertEqual(self.run_example(3, {"file": filename})["status"], "error")

    def test_vendor_duplicate_normalized_headers(self):
        filename = self.fixture("bad.json", [{"Name": "A", "Product Name": "B", "SKU": "x"}])
        self.assertEqual(self.run_example(3, {"file": filename})["status"], "error")

    def test_file_path_traversal_rejected(self):
        self.assertEqual(self.run_example(3, {"file": "../.env"})["status"], "error")

    def test_missing_file(self):
        self.assertEqual(self.run_example(3, {"file": "absent.csv"})["status"], "error")

    def test_content_missing_attributes_explicit(self):
        r = self.engine.run("Generate product description", {"product_name": "Shirt"})
        self.assertEqual(r["status"], "success")
        self.assertIn("material", r["result"]["missing_information"])
        self.assertNotIn("cotton", r["result"]["description"].lower())

    def test_content_missing_name(self):
        self.assertEqual(self.engine.run("Generate product description")["status"], "needs_input")

    def test_content_malformed_model_output(self):
        with patch.object(self.engine.backend, "generate", return_value={"description": "x"}):
            self.assertEqual(self.run_example(4)["status"], "error")

    def test_order_status_tracking(self):
        r = self.run_example(5)["result"]["orders"][0]
        self.assertEqual(r["order_id"], "ORD-1001")
        self.assertEqual(r["shipment"]["tracking"], "DEMO-TRACK-1001")

    def test_order_unknown_requests_identifier(self):
        self.assertEqual(self.engine.run("Where is order ORD-9999?")["status"], "needs_input")

    def test_order_missing_identifier(self):
        self.assertEqual(self.engine.run("Check order status")["status"], "needs_input")

    def test_order_bad_email(self):
        self.assertEqual(self.engine.run("Check order status", {"customer_email": "invalid"})["status"], "needs_input")

    def test_order_email_multiple_and_not_shipped(self):
        r = self.engine.run("Check order status", {"customer_email": "customer@example.com"})["result"]["orders"]
        self.assertEqual(len(r), 2)
        self.assertIsNone(r[1]["shipment"]["tracking"])

    def test_order_conflicting_identifiers(self):
        r = self.engine.run("Where is order ORD-1001?", {"customer_email": "other@example.com"})
        self.assertEqual(r["status"], "needs_input")

    def test_duplicate_definite_and_possible_evidence(self):
        groups = self.run_example(6)["result"]["duplicate_groups"]
        self.assertEqual(len(groups), 1)
        levels = {p["level"] for p in groups[0]["pair_evidence"]}
        self.assertEqual(levels, {"definite", "possible"})

    def test_empty_sku_not_definite_duplicate(self):
        filename = self.fixture("catalog.json", [{"sku": "", "product_name": "A"}, {"sku": "", "product_name": "A"}])
        self.assertEqual(self.run_example(6, {"file": filename})["result"]["duplicate_groups"], [])

    def test_campaign_missing_goal_and_dates_stops_before_llm(self):
        with patch.object(self.engine.backend, "generate") as generate:
            r = self.engine.run("Create a campaign brief")
            self.assertEqual(r["status"], "needs_input")
            self.assertIn("campaign_goal", r["message"])
            self.assertIn("dates", r["message"])
            generate.assert_not_called()

    def test_campaign_optional_facts_are_missing(self):
        r = self.engine.run("Create a campaign brief", {"campaign_goal": "Launch", "dates": "2026-10-14"})
        self.assertIn("promotion", r["result"]["missing_information"])

    def test_keywords_dedup_and_all_intents(self):
        rows = self.run_example(8)["result"]["keywords"]
        self.assertEqual(len(rows), 5)
        self.assertEqual({r["intent"] for r in rows}, {"informational", "commercial", "transactional", "navigational"})
        self.assertTrue(any(r["priority"] == "high" for r in rows))

    def test_keywords_invalid_model_classification(self):
        with patch.object(self.engine.backend, "generate", return_value={"keywords": []}):
            self.assertEqual(self.run_example(8)["status"], "error")

    def test_keywords_category_input_validation(self):
        self.assertEqual(self.run_example(8, {"categories": {"x": "wrong"}})["status"], "needs_input")

    def test_assignment_all_skills_and_available_capacity(self):
        r = self.run_example(9)["result"]
        self.assertEqual(r["recommended_employee"]["employee_id"], "E04")
        self.assertFalse(r["escalated"])
        self.assertFalse(next(c for c in r["candidates"] if c["employee_id"] == "E02")["eligible"])

    def test_assignment_escalation(self):
        r = self.run_example(9, {"required_skills": ["cobol"]})["result"]
        self.assertTrue(r["escalated"])
        self.assertIsNone(r["recommended_employee"])

    def test_assignment_missing_deadline(self):
        inputs = dict(self.examples[8]["inputs"])
        del inputs["deadline"]
        self.assertEqual(self.engine.run(self.examples[8]["request"], inputs)["status"], "needs_input")

    def test_performance_strict_failure_threshold_and_slow(self):
        rows = {r["workflow_id"]: r for r in self.run_example(10)["result"]["workflows"]}
        self.assertEqual(rows["WF001"]["failure_rate"], .1)
        self.assertFalse(rows["WF001"]["flagged"])
        self.assertTrue(rows["WF002"]["flagged"])
        self.assertTrue(rows["WF004"]["flagged"])
        self.assertTrue(rows["WF002"]["slow_steps"])

    def test_performance_needs_input_excluded(self):
        filename = self.fixture("logs.json", [dict(workflow_id="WF001",status="needs_input",duration_ms=1)])
        r = self.run_example(10, {"file": filename})["result"]["workflows"][0]
        self.assertEqual(r["completed_count"], 0)
        self.assertIsNone(r["success_rate"])

    def test_unknown_request(self):
        self.assertEqual(self.engine.run("What is the weather?")["status"], "needs_input")

    def test_ambiguous_request(self):
        self.assertEqual(self.engine.run("restock and duplicate")["status"], "needs_input")

    def test_empty_request(self):
        self.assertEqual(self.engine.run("")["status"], "needs_input")

    def test_unknown_llm_workflow_rejected(self):
        with patch.object(self.engine.backend, "select", return_value={"workflow_id": "DELETE", "confidence": .99}):
            self.assertEqual(self.engine.run("test")["status"], "needs_input")

    def test_transient_tool_failure_retry(self):
        original = TOOLS["restock"]
        calls = []
        def flaky(ctx, args):
            calls.append(1)
            if len(calls) == 1:
                raise TransientError("Temporary problem")
            return original(ctx, args)
        with patch.dict(TOOLS, {"restock": flaky}):
            r = self.run_example(1)
            self.assertEqual(r["status"], "success")
            self.assertEqual(r["steps"][-1]["attempts"], 2)

    def test_permanent_error_not_retried(self):
        with patch.dict(TOOLS, {"restock": lambda c, a: (_ for _ in ()).throw(WorkflowError("bad input"))}):
            r = self.run_example(1)
            self.assertEqual(r["steps"][-1]["attempts"], 1)
            self.assertEqual(r["status"], "error")

    def test_execution_persisted(self):
        r = self.run_example(1)
        self.assertEqual(json.loads((Path(self.tmp.name) / r["run_id"] / "result.json").read_text()), r)

    def test_excel_source_change_fails_closed(self):
        definitions = copy.deepcopy(self.engine.catalog.workflows)
        definitions["WF001"]["source"]["Decision_Logic"] = "Changed"
        with self.assertRaises(WorkflowError):
            Catalog(definitions=definitions)

    def test_eleventh_workflow_without_engine_changes(self):
        # Supply an additional Excel row and a reviewed definition through a fake workbook.
        source = copy.deepcopy(self.engine.catalog.workflows["WF001"]["source"])
        source.update(Workflow_ID="WF011", Workflow_Name="Warehouse Replenishment")
        definitions = copy.deepcopy(self.engine.catalog.workflows)
        definitions["WF011"] = copy.deepcopy(definitions["WF001"])
        definitions["WF011"].update(source=source, routing_terms=["warehouse replenishment"])
        class Sheet:
            values = [tuple(source)] + [tuple(d["source"].values()) for d in definitions.values()]
        class Book:
            def __getitem__(self, key): return Sheet()
            def close(self): pass
        with patch("agent.core.openpyxl.load_workbook", return_value=Book()):
            engine = Engine(DemoLLM(), catalog=Catalog(definitions=definitions), output_dir=self.tmp.name)
        r = engine.run("warehouse replenishment")
        self.assertEqual(r["workflow_id"], "WF011")
        self.assertEqual(r["status"], "success")

    def test_live_function_call_contract(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only"}):
            live = LiveLLM()
        call = {"tool_calls": [{"function": {"name": "execute_workflow", "arguments": json.dumps({"workflow_id": "WF001", "confidence": .95, "reason": "Restock request", "inputs_json": "{}"})}}]}
        with patch.object(live, "complete", return_value=call) as complete:
            result = live.select("Restock", self.engine.catalog)
        self.assertEqual(result["workflow_id"], "WF001")
        self.assertEqual(complete.call_args.kwargs["tool_choice"], "required")
        self.assertEqual(result["inputs"], {})

    def test_live_bad_tool_call_rejected(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only"}):
            live = LiveLLM()
        with patch.object(live, "complete", return_value={"tool_calls": []}):
            with self.assertRaises(WorkflowError):
                live.select("test", self.engine.catalog)

    def test_gemini_missing_key_is_clear(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(WorkflowError, "GEMINI_API_KEY"):
                LiveLLM()

    def test_gemini_transport_endpoint_key_and_model(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-gemini-key", "GEMINI_MODEL": "configured-model"}):
            live = LiveLLM()
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())
        with patch("agent.llm.urllib.request.urlopen", return_value=response) as opened:
            self.assertEqual(live.complete([{"role": "user", "content": "test"}]), {"content": "{}"})
        req = opened.call_args.args[0]
        self.assertEqual(req.full_url, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer fake-gemini-key")
        self.assertEqual(json.loads(req.data)["model"], "configured-model")

    def test_gemini_bad_extracted_inputs_rejected(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only"}):
            live = LiveLLM()
        for value in ["[]", "not json"]:
            call = {"tool_calls": [{"function": {"name": "execute_workflow", "arguments": json.dumps({"workflow_id": "WF001", "confidence": .9, "reason": "test", "inputs_json": value})}}]}
            with patch.object(live, "complete", return_value=call):
                with self.assertRaises(WorkflowError):
                    live.select("test", self.engine.catalog)

    def test_gemini_empty_completion_rejected(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only"}):
            live = LiveLLM()
        with patch("agent.llm.urllib.request.urlopen", return_value=io.BytesIO(b'{"choices": []}')):
            with self.assertRaisesRegex(WorkflowError, "no usable completion"):
                live.complete([])

    def test_gemini_rate_limit_pauses_instead_of_retrying(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only"}):
            live = LiveLLM()
        error = urllib.error.HTTPError(live.endpoint, 429, "quota", {}, None)
        with patch("agent.llm.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(QuotaError):
                live.complete([])

    def test_gemini_timeout_and_reasoning_are_configurable(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only", "GEMINI_TIMEOUT_SECONDS": "75", "GEMINI_REASONING_EFFORT": "low"}):
            live = LiveLLM()
        response = io.BytesIO(b'{"choices": [{"message": {"content": "OK"}}]}')
        with patch("agent.llm.urllib.request.urlopen", return_value=response) as opened:
            live.complete([])
        self.assertEqual(opened.call_args.kwargs["timeout"], 75)
        self.assertEqual(json.loads(opened.call_args.args[0].data)["reasoning_effort"], "low")

    def test_ssl_read_timeout_is_actionable(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only", "GEMINI_TIMEOUT_SECONDS": "90"}):
            live = LiveLLM()
        with patch("agent.llm.urllib.request.urlopen", side_effect=ssl.SSLError("The read operation timed out")):
            with self.assertRaisesRegex(TransientError, "90 seconds"):
                live.complete([])

    def test_invalid_timeout_is_rejected(self):
        for value in ["NaN", "2", "181", "invalid"]:
            with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only", "GEMINI_TIMEOUT_SECONDS": value}):
                with self.assertRaises(WorkflowError):
                    LiveLLM()

    def test_transient_selection_retry(self):
        selection = {"workflow_id": "WF001", "confidence": .9, "reason": "restock", "inputs": {}}
        with patch.object(self.engine.backend, "select", side_effect=[TransientError("timeout"), selection]):
            r = self.run_example(1)
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["selection_attempts"], 2)

    def test_selection_retry_limit(self):
        with patch.object(self.engine.backend, "select", side_effect=TransientError("timeout")) as select:
            r = self.run_example(1)
        self.assertEqual(r["status"], "error")
        self.assertEqual(select.call_count, 2)
        self.assertEqual(r["steps"], [])

    def test_router_receives_explicit_example_inputs(self):
        with patch.object(self.engine.backend, "select", wraps=self.engine.backend.select) as select:
            self.run_example(4)
        self.assertEqual(select.call_args.args[2]["product_name"], "Cotton T-shirt")

    def test_live_prompt_contains_supplied_inputs_and_delegates_validation(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only"}):
            live = LiveLLM()
        call = {"tool_calls": [{"function": {"name": "execute_workflow", "arguments": json.dumps({"workflow_id": "WF004", "confidence": .95, "reason": "Content request", "inputs_json": "{}"})}}]}
        with patch.object(live, "complete", return_value=call) as complete:
            live.select("Generate SEO content for this product", self.engine.catalog, {"product_name": "Cotton T-shirt"})
        messages = complete.call_args.args[0]
        self.assertEqual(json.loads(messages[1]["content"])["business_inputs"]["product_name"], "Cotton T-shirt")
        self.assertIn("Missing business fields do NOT", messages[0]["content"])

    def test_quota_error_not_retried_by_engine(self):
        with patch.object(self.engine.backend, "select", side_effect=QuotaError("429")) as select:
            r = self.run_example(1)
        self.assertEqual(select.call_count, 1)
        self.assertEqual(r["error_code"], "rate_limited")

    def test_batch_pauses_remaining_examples_after_quota(self):
        from agent.__main__ import run_examples
        with patch.object(self.engine, "run", return_value={"workflow_id": None, "status": "error", "error_code": "rate_limited"}) as run, patch("builtins.print"):
            outputs = run_examples(self.engine, self.examples)
        self.assertEqual(run.call_count, 1)
        self.assertEqual([r["status"] for r in outputs], ["error"] + ["not_run"] * 9)

    def test_requests_are_paced_between_api_calls(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only", "GEMINI_MIN_INTERVAL_SECONDS": "10"}):
            live = LiveLLM()
        responses = [io.BytesIO(b'{"choices": [{"message": {"content": "OK"}}]}') for _ in range(2)]
        with patch("agent.llm.time.monotonic", side_effect=[100, 100, 105, 110]), patch("agent.llm.time.sleep") as sleep, patch("agent.llm.urllib.request.urlopen", side_effect=responses):
            live.complete([])
            live.complete([])
        sleep.assert_called_once_with(5)

    def test_keyword_report_corrects_invalid_page_once(self):
        e = self.examples[7]
        keywords = ["buy cotton shirt", "best cotton shirt", "how to wash cotton shirt", "Brand official website", "blue mug discount"]
        valid = self.engine.backend.generate("keywords", {"keywords": keywords, "categories": e["inputs"]["categories"]}, {})
        invalid = copy.deepcopy(valid)
        invalid["keywords"][0]["target_page"] = "Product page"
        with patch.object(self.engine.backend, "generate", side_effect=[invalid, valid]) as generate:
            r = self.run_example(8)
        self.assertEqual(r["status"], "success")
        self.assertEqual(generate.call_count, 2)
        correction = generate.call_args.args[1]
        self.assertIn("target_page", correction["validation_errors"][0])
        self.assertEqual(r["result"]["generation_attempts"], 2)

    def test_keyword_report_error_identifies_field_after_bounded_correction(self):
        valid = self.run_example(8)["result"]["keywords"]
        invalid = {"keywords": copy.deepcopy(valid)}
        invalid["keywords"][0]["intent"] = "purchase"
        with patch.object(self.engine.backend, "generate", return_value=invalid) as generate:
            r = self.run_example(8)
        self.assertEqual(r["status"], "error")
        self.assertEqual(generate.call_count, 2)
        self.assertIn("Row 1 intent", r["message"])
        self.assertIn("purchase", r["message"])

    def test_keyword_enum_casing_is_normalized(self):
        valid = self.run_example(8)["result"]["keywords"]
        for row in valid:
            row["intent"] = " " + row["intent"].upper() + " "
            row["priority"] = row["priority"].capitalize()
            row["category"] = row["category"].upper()
        with patch.object(self.engine.backend, "generate", return_value={"keywords": valid}) as generate:
            r = self.run_example(8)
        self.assertEqual(r["status"], "success")
        self.assertEqual(generate.call_count, 1)

    def test_keyword_report_rejects_protocol_relative_pages(self):
        rows = self.run_example(8)["result"]["keywords"]
        rows[0]["target_page"] = "//outside.example/page"
        with patch.object(self.engine.backend, "generate", return_value={"keywords": rows}):
            r = self.run_example(8)
        self.assertEqual(r["status"], "error")
        self.assertIn("target_page", r["message"])


if __name__ == "__main__":
    unittest.main()
