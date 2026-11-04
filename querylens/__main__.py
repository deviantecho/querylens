import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="QueryLens revenue analytics workbench")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(os.environ.get("QUERYLENS_DATA_DIR", ".querylens"))
    )
    parser.add_argument(
        "--eval", action="store_true", help="Run the deterministic query regression suite"
    )
    parser.add_argument(
        "--train-ml",
        action="store_true",
        help="Fit and evaluate the calibrated local intent classifier",
    )
    parser.add_argument(
        "--ai-eval",
        action="store_true",
        help="Benchmark examples, trained intent, and local LLM with/without retrieval",
    )
    parser.add_argument(
        "--skip-llm", action="store_true", help="Evaluate only inexpensive local baselines"
    )
    parser.add_argument(
        "--eval-limit",
        type=int,
        default=None,
        help="Limit benchmark cases; final reports disclose the count",
    )
    args = parser.parse_args()
    if args.train_ml:
        from querylens.ai.intent import train

        _, report = train(args.data_dir.resolve() / "ai")
        print(
            {
                k: v
                for k, v in report["evaluation"].items()
                if k not in {"predictions", "ood_predictions", "per_class", "confusion_matrix"}
            }
        )
        return
    from querylens.service import Workbench

    workbench = Workbench(args.data_dir.resolve())
    if args.ai_eval:
        from querylens.ai.evaluate import run as ai_evaluate

        report = ai_evaluate(workbench, include_local=not args.skip_llm, limit=args.eval_limit)
        print(
            [
                {k: v for k, v in r.items() if k not in {"predictions", "refusals"}}
                for r in report["variants"]
            ]
        )
        return
    if args.eval:
        from querylens.evaluation import run

        result = run(workbench)
        print(result)
        raise SystemExit(0 if result["passed"] == result["total"] else 1)
    from querylens.server import make_server

    server = make_server(workbench, args.port)
    print(f"QueryLens is running at http://127.0.0.1:{server.server_port}", flush=True)
    print("Synthetic data: January - December 2025. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
