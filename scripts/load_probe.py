#!/usr/bin/env python3
"""Deterministic mock-provider load probe for pre-release capacity checks.

This tool never calls paid providers. It exercises the FastAPI surface with the
in-process mock coach against a temporary SQLite store so operators can measure
latency and error rates before student cutover.

Example:

```bash
.venv/bin/python scripts/load_probe.py --users 10 --requests-per-user 5
```

Results are aggregate only (no notebook IDs or message text).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

# Direct script execution places ``scripts/`` on sys.path, not the repository.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import create_app  # noqa: E402
from backend.persistence.factory import reset_file_storage_cache  # noqa: E402
from backend.settings import settings  # noqa: E402
from backend.student_store import StudentStore  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=10, choices=(5, 10, 20, 30))
    parser.add_argument("--requests-per-user", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    latencies_ms: list[float] = []
    errors = 0
    status_429 = 0
    lock = threading.Lock()

    with TemporaryDirectory(prefix="co-design-load-") as tmp:
        database = Path(tmp) / "load.sqlite3"
        # Keep the probe self-contained: uploads stay in memory and each virtual
        # user receives the same owner isolation used by authenticated requests.
        settings.file_storage_provider = "memory"
        reset_file_storage_cache()
        clients = [
            TestClient(
                create_app(
                    StudentStore(database, identifier=f"load-user-{user_index}")
                )
            )
            for user_index in range(args.users)
        ]

        def worker(user_index: int) -> None:
            nonlocal errors, status_429
            client = clients[user_index]
            # Exercise list/create/upload/coach under mock provider.
            list_response = client.get("/api/v1/threads")
            create_response = client.post(
                "/api/v1/threads",
                json={
                    "name": f"load-user-{user_index}",
                    "model_id": "mock",
                    "support_mode": "critical-thinking",
                },
            )
            if list_response.status_code >= 400 or create_response.status_code >= 400:
                with lock:
                    errors += 1
                return
            thread_id = create_response.json()["id"]
            upload_response = client.post(
                f"/api/v1/threads/{thread_id}/sources",
                files=[
                    (
                        "files",
                        ("probe.txt", b"small deterministic upload", "text/plain"),
                    )
                ],
            )
            if upload_response.status_code >= 400:
                with lock:
                    errors += 1
                return
            for index in range(args.requests_per_user):
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/coach/turn",
                    json={
                        "thread_id": thread_id,
                        "student_message": f"Load probe claim {index}",
                        "current_stage": "focus",
                        "response_detail": "short",
                        "idempotency_key": f"load-{user_index}-{index}-{uuid4()}",
                    },
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                with lock:
                    latencies_ms.append(elapsed_ms)
                    if response.status_code == 429:
                        status_429 += 1
                    elif response.status_code >= 400:
                        errors += 1

        started_all = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.users) as executor:
            futures = [
                executor.submit(worker, user_index)
                for user_index in range(args.users)
            ]
            for future in as_completed(futures):
                future.result()
        wall_seconds = time.perf_counter() - started_all

    total = len(latencies_ms)
    ordered = sorted(latencies_ms)
    p50 = ordered[int(0.50 * (total - 1))] if ordered else 0.0
    p95 = ordered[int(0.95 * (total - 1))] if ordered else 0.0
    print(
        {
            "users": args.users,
            "requests": total,
            "requests_per_sec": round(total / wall_seconds, 2) if wall_seconds else 0.0,
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "mean_ms": round(statistics.fmean(latencies_ms), 1) if latencies_ms else 0.0,
            "errors": errors,
            "http_429": status_429,
            "note": "mock provider only; do not claim EC2 sizing without live measurement",
        }
    )


if __name__ == "__main__":
    main()
