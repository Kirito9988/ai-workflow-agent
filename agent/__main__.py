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
    web = sub.add_parser("serve")
    web.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        engine = Engine(DemoLLM() if args.mode == "demo" else LiveLLM())
        if args.command == "serve":
            from .web import serve
            serve(engine, args.port)
        elif args.command == "catalog":
            print(json.dumps([d["source"] for d in engine.catalog.workflows.values()], indent=2))
        elif args.command == "examples":
            outputs = [engine.run(e["request"], e["inputs"]) for e in json.loads((ROOT / "examples/requests.json").read_text())]
            target = ROOT / "examples" / ("live_results.json" if args.mode == "live" else "demo_results.json")
            target.write_text(json.dumps(outputs, indent=2, ensure_ascii=False))
            for result in outputs:
                print(result["workflow_id"], result["status"], result.get("message", ""))
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
