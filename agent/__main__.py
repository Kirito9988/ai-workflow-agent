import argparse
import json
import os
from pathlib import Path

from .core import Engine, ROOT, WorkflowError
from .llm import DemoLLM, LiveLLM


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def run_examples(engine, examples):
    outputs = []
    blocked = False
    for example in examples:
        if blocked:
            result = {"requested_workflow_id": example["workflow_id"], "workflow_id": None,
                      "request": example["request"], "status": "not_run", "steps": [],
                      "message": "Not attempted: batch paused after Gemini quota/rate-limit response"}
        else:
            result = engine.run(example["request"], example["inputs"])
            result["requested_workflow_id"] = example["workflow_id"]
            blocked = result.get("error_code") == "rate_limited"
        outputs.append(result)
        print(example["workflow_id"], "selected=" + str(result["workflow_id"]), result["status"], result.get("message", ""), flush=True)
    return outputs


def portable_results(value, root=ROOT):
    """Keep captured export paths relative to the project directory."""
    if isinstance(value, dict):
        return {key: portable_results(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_results(item, root) for item in value]
    prefix = str(root) + os.sep
    if isinstance(value, str) and value.startswith(prefix):
        return Path(value).relative_to(root).as_posix()
    return value


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Excel workflow automation agent")
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("request")
    run.add_argument("--inputs", default="{}", help="JSON object or @path/to/file.json")
    sub.add_parser("examples")
    sub.add_parser("catalog")
    sub.add_parser("check", help="Make a minimal Gemini request to diagnose key/model/connectivity")
    web = sub.add_parser("serve")
    web.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        engine = Engine(DemoLLM() if args.mode == "demo" else LiveLLM())
        if args.command == "check":
            if not isinstance(engine.backend, LiveLLM):
                parser.exit(2, "Use --mode live check to test Gemini; demo mode makes no network calls\n")
            print(f"Testing Gemini model {engine.backend.model} (timeout {engine.backend.timeout:g}s)...", flush=True)
            message = engine.backend.complete([{"role": "user", "content": "Reply with only OK."}])
            print("Gemini responded:", message.get("content") or "Response received")
        elif args.command == "serve":
            from .web import serve
            serve(engine, args.port)
        elif args.command == "catalog":
            print(json.dumps([d["source"] for d in engine.catalog.workflows.values()], indent=2))
        elif args.command == "examples":
            outputs = run_examples(engine, json.loads((ROOT / "examples/requests.json").read_text()))
            target = ROOT / "examples" / ("live_results.json" if args.mode == "live" else "demo_results.json")
            target.write_text(json.dumps(portable_results(outputs), indent=2, ensure_ascii=False))
            print("Results:", target)
            if any(r["status"] != "success" for r in outputs):
                raise SystemExit(1)
        else:
            inputs = json.loads(Path(args.inputs[1:]).read_text() if args.inputs.startswith("@") else args.inputs)
            result = engine.run(args.request, inputs)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if result["status"] != "success":
                raise SystemExit(2)
    except (WorkflowError, ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
