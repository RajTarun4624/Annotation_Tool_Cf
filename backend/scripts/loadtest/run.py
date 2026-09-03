"""Drive the real API with hundreds of virtual users (asyncio + aiohttp).

    .venv/Scripts/python.exe -m scripts.loadtest.run --base http://127.0.0.1:8011 \
        --annotators 200 --reviewers 30 --admins 2 --duration 120 --think 2

Virtual users run the real flows against the real endpoints:

- annotator: my-queues list -> queue summary -> claim (/next) -> open task ->
  autosave x2 + heartbeat -> submit (5 % skip) -> follow next_task_id ...
- reviewer: my-queues -> QA summary -> claim -> open -> QA draft -> finalize
  (10 % return) -> next ...
- admin: queue list, queue tasks page, task console, dashboard, and one
  XLSX + one JSONL export of a full queue during the run.

``--think`` is the pause between steps in seconds. Real annotators take
minutes per task; a think time of 2 s means every virtual annotator completes
a task roughly every 10 s, i.e. the load of far more than N real people.

Prints per-endpoint-group latency percentiles and error counts; 409s are
reported separately because they are the *expected* outcome of a lost race.

One generator process drives ~120 virtual users comfortably; shard larger
runs across processes with --offset / --rev-offset (disjoint accounts) and
add the reported request counts together.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import defaultdict

import aiohttp

sys.path.insert(0, ".")
from scripts.loadtest.common import ANNOTATION, DEFAULT_BASE_URL, PASSWORD, TAG_PREFIX, ann_email, qa_email  # noqa: E402

API = "/api/v1"


class Metrics:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.status: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.errors: list[str] = []
        self.started = time.perf_counter()
        self.tasks_submitted = 0
        self.tasks_finalized = 0
        self.conflicts = 0
        self.claims_none = 0

    def record(self, group: str, status: int, dt: float, detail: str = "") -> None:
        self.samples[group].append(dt)
        # A 400 "no longer editable" is the pre-lock guard firing because the task
        # filled up while this user held it: the same expected outcome as a 409.
        if status == 400 and "no longer editable" in detail:
            status = 409
        self.status[group][status] += 1
        if status == 409:
            self.conflicts += 1
        elif status >= 400 and len(self.errors) < 50:
            self.errors.append(f"{group} -> {status} {detail[:160]}")

    def report(self) -> dict:
        elapsed = time.perf_counter() - self.started
        total = sum(len(v) for v in self.samples.values())
        rows = []
        for group in sorted(self.samples):
            s = sorted(self.samples[group])
            n = len(s)
            q = lambda p: s[min(n - 1, int(p * n))] * 1000  # noqa: E731
            codes = dict(self.status[group])
            err = sum(c for k, c in codes.items() if k >= 400 and k != 409)
            rows.append({
                "group": group, "n": n, "p50_ms": round(q(0.50), 1), "p95_ms": round(q(0.95), 1),
                "p99_ms": round(q(0.99), 1), "max_ms": round(s[-1] * 1000, 1),
                "errors": err, "conflicts": codes.get(409, 0),
            })
        return {
            "elapsed_s": round(elapsed, 1), "requests": total, "req_per_s": round(total / max(elapsed, 1e-6), 1),
            "tasks_submitted": self.tasks_submitted, "tasks_finalized": self.tasks_finalized,
            "conflicts_409": self.conflicts, "claims_returned_none": self.claims_none,
            "groups": rows, "error_samples": self.errors[:20],
        }


M = Metrics()


class Resp:
    """Minimal response shim (status, text, json()) over an aiohttp response."""

    __slots__ = ("status_code", "text")

    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text

    def json(self):
        try:
            return json.loads(self.text) if self.text else {}
        except ValueError:
            return {}


async def call(client: "aiohttp.ClientSession", group: str, method: str, path: str, **kw) -> Resp | None:
    t = time.perf_counter()
    try:
        async with client.request(method, path, **kw) as r:
            text = await r.text()
            status = r.status
    except Exception as exc:  # noqa: BLE001
        M.record(group, 599, time.perf_counter() - t, repr(exc))
        return None
    M.record(group, status, time.perf_counter() - t, text if status >= 400 else "")
    return Resp(status, text)


def _session(base: str, token: str | None = None, timeout: float = 60) -> "aiohttp.ClientSession":
    headers = {"Authorization": "Bearer " + token} if token else {}
    return aiohttp.ClientSession(
        base_url=base, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout),
        connector=aiohttp.TCPConnector(limit=0, keepalive_timeout=120),
    )


async def login(base: str, email: str, password: str = PASSWORD) -> tuple["aiohttp.ClientSession | None", dict | None]:
    """Log in with a throwaway session; return a keep-alive session carrying the bearer."""
    async with _session(base) as tmp:
        r = await call(tmp, "auth.login", "POST", f"{API}/auth/login", json={"email": email, "password": password})
    if r is None or r.status_code != 200:
        return None, None
    body = r.json()
    return _session(base, body["access_token"]), body["user"]


def _variant() -> dict:
    d = json.loads(json.dumps(ANNOTATION))
    if random.random() < 0.3:
        d["intention"] = random.choice(["adversarial", "hard_to_say"])
    if random.random() < 0.2:
        d["severity"]["J"] = random.choice([3, 4, 5])
    return d


async def annotator(idx: int, base: str, deadline: float, think: float) -> None:
    c, me = await login(base, ann_email(idx))
    if not c:
        return
    async with c:
        uid = me["id"]
        task_id: str | None = None
        queue_id: str | None = None
        while time.perf_counter() < deadline:
            if task_id is None:
                r = await call(c, "queues.my_list", "GET", f"{API}/queues/",
                               params={"assigned_user_id": uid, "hide_exhausted": "true", "page": 1, "page_size": 25})
                items = (r.json().get("items") if r is not None and r.status_code == 200 else None) or []
                prod = [q for q in items if q.get("annotation_type") == "production" and str(q.get("name", "")).startswith(TAG_PREFIX)]
                if not prod:
                    await asyncio.sleep(think)
                    continue
                queue_id = random.choice(prod)["id"]
                await call(c, "ws.summary", "GET", f"{API}/workspace/queues/{queue_id}/summary")
                r = await call(c, "ws.claim", "GET", f"{API}/workspace/queues/{queue_id}/next")
                task_id = r.json().get("task_id") if r is not None and r.status_code == 200 else None
                if not task_id:
                    M.claims_none += 1
                    await asyncio.sleep(think)
                    continue
            r = await call(c, "ws.task", "GET", f"{API}/workspace/tasks/{task_id}")
            if r is None or r.status_code != 200:
                task_id = None
                continue
            elapsed = 0
            await asyncio.sleep(think * random.uniform(0.5, 1.5))
            elapsed += int(think)
            r = await call(c, "ws.draft", "PUT", f"{API}/workspace/tasks/{task_id}/draft",
                           json={"data": {"data_type": "general_text"}, "elapsed_seconds": elapsed})
            if r is not None and r.status_code == 409:
                task_id = None
                continue
            await asyncio.sleep(think * random.uniform(0.5, 1.5))
            elapsed += int(think)
            await call(c, "ws.heartbeat", "POST", f"{API}/workspace/tasks/{task_id}/heartbeat")
            data = _variant()
            r = await call(c, "ws.draft", "PUT", f"{API}/workspace/tasks/{task_id}/draft",
                           json={"data": data, "elapsed_seconds": elapsed})
            if r is not None and r.status_code == 409:
                task_id = None
                continue
            await asyncio.sleep(think * random.uniform(0.3, 0.8))
            if random.random() < 0.05:
                r = await call(c, "ws.skip", "POST", f"{API}/workspace/tasks/{task_id}/skip")
            else:
                r = await call(c, "ws.submit", "POST", f"{API}/workspace/tasks/{task_id}/submit",
                               json={"data": data, "elapsed_seconds": elapsed + 1})
                if r is not None and r.status_code == 200:
                    M.tasks_submitted += 1
            if r is not None and r.status_code == 200:
                task_id = r.json().get("next_task_id")
                if not task_id:
                    M.claims_none += 1
            else:
                task_id = None


async def reviewer(idx: int, base: str, deadline: float, think: float) -> None:
    c, me = await login(base, qa_email(idx))
    if not c:
        return
    async with c:
        uid = me["id"]
        task_id: str | None = None
        qa_id: str | None = None
        while time.perf_counter() < deadline:
            if task_id is None:
                r = await call(c, "queues.my_list", "GET", f"{API}/queues/",
                               params={"assigned_user_id": uid, "hide_exhausted": "true", "page": 1, "page_size": 25})
                items = (r.json().get("items") if r is not None and r.status_code == 200 else None) or []
                qas = [q for q in items if q.get("annotation_type") == "qa" and str(q.get("name", "")).startswith(TAG_PREFIX)
                       and int(q.get("submitted_tasks") or 0) > 0]
                if not qas:
                    await asyncio.sleep(think * 2)
                    continue
                qa_id = random.choice(qas)["id"]
                await call(c, "qa.summary", "GET", f"{API}/workspace/qa/{qa_id}/summary")
                r = await call(c, "qa.claim", "GET", f"{API}/workspace/qa/{qa_id}/next")
                task_id = r.json().get("task_id") if r is not None and r.status_code == 200 else None
                if not task_id:
                    M.claims_none += 1
                    await asyncio.sleep(think * 2)
                    continue
            r = await call(c, "qa.task", "GET", f"{API}/workspace/qa/tasks/{task_id}")
            if r is None or r.status_code != 200:
                task_id = None
                continue
            detail = r.json()
            final = detail.get("final") or _variant()
            await asyncio.sleep(think * random.uniform(0.5, 1.5))
            r = await call(c, "qa.draft", "PUT", f"{API}/workspace/qa/tasks/{task_id}/draft",
                           json={"data": final, "qa_notes": "", "elapsed_seconds": int(think)})
            if r is not None and r.status_code == 409:
                task_id = None
                continue
            await call(c, "qa.heartbeat", "POST", f"{API}/workspace/qa/tasks/{task_id}/heartbeat")
            await asyncio.sleep(think * random.uniform(0.3, 0.8))
            if random.random() < 0.10:
                r = await call(c, "qa.return", "POST", f"{API}/workspace/qa/tasks/{task_id}/return",
                               json={"qa_notes": "Please recheck the subcategory."})
            else:
                r = await call(c, "qa.finalize", "POST", f"{API}/workspace/qa/tasks/{task_id}/finalize",
                               json={"data": final, "qa_notes": "ok"})
                if r is not None and r.status_code == 200:
                    M.tasks_finalized += 1
            if r is not None and r.status_code == 200:
                task_id = r.json().get("next_task_id")
            else:
                task_id = None


async def admin(idx: int, base: str, deadline: float, admin_email: str, admin_password: str) -> None:
    c, _me = await login(base, admin_email, admin_password)
    if not c:
        return
    async with c:
        exported = False
        start = time.perf_counter()
        while time.perf_counter() < deadline:
            r = await call(c, "admin.queues", "GET", f"{API}/queues/", params={"page": 1, "page_size": 25, "search": TAG_PREFIX})
            items = (r.json().get("items") if r is not None and r.status_code == 200 else None) or []
            if items:
                q = random.choice(items)
                await call(c, "admin.queue_tasks", "GET", f"{API}/queues/{q['id']}/tasks", params={"page": 1, "page_size": 25})
            await call(c, "admin.tasks", "GET", f"{API}/tasks/", params={"page": 1, "page_size": 25})
            await call(c, "admin.dashboard", "GET", f"{API}/dashboard/stats")
            await call(c, "admin.dashboard", "GET", f"{API}/dashboard/active-queues")
            if items and not exported and time.perf_counter() - start > 20:
                exported = True
                q = items[0]
                for fmt in ("xlsx", "jsonl"):
                    t = time.perf_counter()
                    try:
                        async with c.get(f"{API}/queues/{q['id']}/export/{fmt}", params={"scope": "all"},
                                         timeout=aiohttp.ClientTimeout(total=300)) as resp:
                            size = 0
                            async for chunk in resp.content.iter_chunked(65536):
                                size += len(chunk)
                            status = resp.status
                        M.record(f"admin.export_{fmt}", status, time.perf_counter() - t)
                        print(f"  [admin {idx}] export {fmt}: {status} {size/1024:.0f} KB in {time.perf_counter()-t:.1f}s")
                    except Exception as exc:  # noqa: BLE001
                        M.record(f"admin.export_{fmt}", 599, time.perf_counter() - t, repr(exc))
            await asyncio.sleep(5)


async def main_async(args) -> dict:
    base = args.base
    async with _session(base, timeout=10) as c:
        async with c.get("/health") as r:
            r.raise_for_status()
    deadline = time.perf_counter() + args.ramp + args.duration
    tasks = []
    # Ramp: stagger starts over --ramp seconds (a shift start, not a thundering herd).
    # --offset / --rev-offset let several generator processes drive disjoint accounts.
    for k in range(args.annotators):
        i = args.offset + k + 1
        delay = args.ramp * k / max(1, args.annotators)
        tasks.append(asyncio.create_task(_delayed(delay, annotator(i, base, deadline, args.think))))
    for k in range(args.reviewers):
        i = args.rev_offset + k + 1
        delay = args.ramp * k / max(1, args.reviewers) + 5
        tasks.append(asyncio.create_task(_delayed(delay, reviewer(i, base, deadline, args.think))))
    for i in range(1, args.admins + 1):
        tasks.append(asyncio.create_task(admin(i, base, deadline, args.admin_email, args.admin_password)))

    async def progress():
        while time.perf_counter() < deadline:
            await asyncio.sleep(15)
            total = sum(len(v) for v in M.samples.values())
            print(f"  t+{time.perf_counter()-M.started:5.0f}s  requests={total:6d}  submitted={M.tasks_submitted:5d}  "
                  f"finalized={M.tasks_finalized:4d}  409={M.conflicts:3d}  errors={len(M.errors):3d}", flush=True)

    tasks.append(asyncio.create_task(progress()))
    await asyncio.gather(*tasks, return_exceptions=True)
    return M.report()


async def _delayed(delay: float, coro):
    await asyncio.sleep(delay)
    await coro


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE_URL)
    ap.add_argument("--annotators", type=int, default=200)
    ap.add_argument("--reviewers", type=int, default=30)
    ap.add_argument("--admins", type=int, default=2)
    ap.add_argument("--offset", type=int, default=0, help="first annotator index - 1 (for sharding)")
    ap.add_argument("--rev-offset", type=int, default=0, help="first reviewer index - 1 (for sharding)")
    ap.add_argument("--duration", type=int, default=120, help="seconds at full load (after ramp)")
    ap.add_argument("--ramp", type=int, default=20)
    ap.add_argument("--think", type=float, default=2.0)
    ap.add_argument("--admin-email", default="admin@gmail.com")
    ap.add_argument("--admin-password", default="Admin@123")
    ap.add_argument("--out", default="loadtest_result.json")
    args = ap.parse_args()
    print(f"load test -> {args.base}: {args.annotators} annotators, {args.reviewers} reviewers, {args.admins} admins, "
          f"ramp {args.ramp}s + {args.duration}s, think {args.think}s")
    report = asyncio.run(main_async(args))
    print()
    print(f"{'group':22s} {'n':>7s} {'p50':>8s} {'p95':>8s} {'p99':>8s} {'max':>8s} {'err':>5s} {'409':>5s}")
    for row in report["groups"]:
        print(f"{row['group']:22s} {row['n']:7d} {row['p50_ms']:8.1f} {row['p95_ms']:8.1f} {row['p99_ms']:8.1f} "
              f"{row['max_ms']:8.1f} {row['errors']:5d} {row['conflicts']:5d}")
    print()
    print(f"requests={report['requests']}  req/s={report['req_per_s']}  elapsed={report['elapsed_s']}s  "
          f"submitted={report['tasks_submitted']}  finalized={report['tasks_finalized']}  "
          f"409={report['conflicts_409']}  claims_none={report['claims_returned_none']}")
    if report["error_samples"]:
        print("error samples:")
        for e in report["error_samples"]:
            print("  ", e)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"written {args.out}")


if __name__ == "__main__":
    main()
