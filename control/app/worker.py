from __future__ import annotations

import json
import time

from .config import load_settings
from .db import claim_next, complete, event, fail, heartbeat, init_db
from .jobs import execute


def main() -> int:
    init_db()
    while True:
        job = claim_next()
        if not job:
            time.sleep(1.5)
            continue
        job_id = job["id"]
        action = job["action"]
        try:
            # Load operator-editable RDMA settings for every job so API and durable
            # worker processes converge without requiring a service restart.
            settings = load_settings()
            event(job_id, f"Starting {action}")
            heartbeat(job_id, 600)
            result = execute(settings, action)
            complete(job_id, result)
        except Exception as exc:
            # Never expose Python tracebacks or environment content through the API record.
            try:
                detail = json.loads(str(exc))
                message = json.dumps(detail)[:4000]
            except Exception:
                message = str(exc)[:4000]
            fail(job_id, message)
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
