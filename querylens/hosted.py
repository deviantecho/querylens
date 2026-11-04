"""Entry point for the free, CPU-only public portfolio demo."""

import os
import shutil
from pathlib import Path


def main():
    # Set before importing scientific libraries; the free instance has limited RAM/CPU.
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    os.environ["QUERYLENS_MODE"] = "intent"
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME") or os.environ.get("QUERYLENS_PUBLIC_HOST")
    if not hostname or any(c in hostname for c in "/\\@ \t\r\n"):
        raise SystemExit(
            "Set RENDER_EXTERNAL_HOSTNAME or QUERYLENS_PUBLIC_HOST to the public hostname."
        )
    data_dir = Path(os.environ.get("QUERYLENS_DATA_DIR", ".querylens")).resolve()
    report = Path("reports/ai-evaluation.json")
    if report.is_file():
        (data_dir / "reports").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(report, data_dir / "reports/ai-evaluation.json")

    from querylens.server import make_server
    from querylens.service import Workbench

    workbench = Workbench(data_dir, memory_limit="128MB", threads=1)
    workbench.prune_history()
    server = make_server(
        workbench,
        int(os.environ.get("PORT", "10000")),
        public_demo=True,
        allowed_hosts={hostname},
    )
    print(f"QueryLens public demo listening on port {server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
