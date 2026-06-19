import argparse
import json
import os
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from redis.exceptions import RedisError

from performance.distributed_locks import (
    LOCK_BUSY,
    checkout_user_lock_key,
    daily_sales_report_lock_key,
    get_lock_redis_client,
    redis_distributed_lock,
)
from reports.models import DailySalesBatchRun
from reports.tasks import process_daily_sales_report_task


THREAD_LOCK_NAME = "lock:task7:threaded-proof"
CHECKOUT_USER_ID = 7007
REPORT_DATE = date(2001, 7, 7)


class DistributedLockTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 7 Redis distributed lock proof.")
    parser.add_argument("--attempts", type=int, default=8, help="Concurrent attempts for the generic lock proof.")
    parser.add_argument("--hold-seconds", type=float, default=1.0, help="How long the winning lock holder sleeps.")
    return parser.parse_args()


def cleanup_lock_keys(lock_keys):
    client = get_lock_redis_client()
    if lock_keys:
        client.delete(*lock_keys)


def run_threaded_lock_proof(attempts, hold_seconds):
    if attempts < 2:
        raise DistributedLockTestError("--attempts must be at least 2.")

    cleanup_lock_keys([THREAD_LOCK_NAME])
    barrier = threading.Barrier(attempts)
    results = []
    results_lock = threading.Lock()

    def worker(index):
        barrier.wait()
        with redis_distributed_lock(THREAD_LOCK_NAME, timeout=10, blocking_timeout=0) as lock:
            if lock.acquired:
                time.sleep(hold_seconds)
            with results_lock:
                results.append(
                    {
                        "attempt": index,
                        "acquired": lock.acquired,
                        "status": lock.status,
                        "lock_key": lock.key,
                    }
                )

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    acquired_count = sum(1 for result in results if result["acquired"])
    blocked_count = sum(1 for result in results if not result["acquired"] and result["status"] == LOCK_BUSY)
    return {
        "name": "threaded_single_lock",
        "total_attempts": attempts,
        "acquired_count": acquired_count,
        "blocked_count": blocked_count,
        "lock_keys_used": [THREAD_LOCK_NAME],
        "attempts": sorted(results, key=lambda item: item["attempt"]),
        "passed": acquired_count == 1 and blocked_count == attempts - 1,
    }


def run_checkout_duplicate_lock_simulation():
    lock_key = checkout_user_lock_key(CHECKOUT_USER_ID)
    cleanup_lock_keys([lock_key])

    with redis_distributed_lock(lock_key, timeout=10, blocking_timeout=0) as first_lock:
        with redis_distributed_lock(lock_key, timeout=10, blocking_timeout=0) as second_lock:
            blocked = not second_lock.acquired and second_lock.status == LOCK_BUSY
            return {
                "name": "checkout_duplicate_submission",
                "total_attempts": 2,
                "acquired_count": int(first_lock.acquired) + int(second_lock.acquired),
                "blocked_count": int(blocked),
                "lock_keys_used": [lock_key],
                "first_status": first_lock.status,
                "second_status": second_lock.status,
                "expected_busy_code": "checkout_lock_busy",
                "passed": first_lock.acquired and blocked,
            }


def run_daily_sales_lock_skip_proof():
    lock_key = daily_sales_report_lock_key(REPORT_DATE)
    cleanup_lock_keys([lock_key])
    DailySalesBatchRun.objects.filter(report_date=REPORT_DATE).delete()
    batch_run = DailySalesBatchRun.objects.create(report_date=REPORT_DATE, chunk_size=2)

    with redis_distributed_lock(lock_key, timeout=10, blocking_timeout=0) as held_lock:
        result = process_daily_sales_report_task.apply(
            kwargs={
                "report_date": str(REPORT_DATE),
                "batch_run_id": batch_run.id,
                "chunk_size": 2,
            }
        ).get()

    batch_run.refresh_from_db()
    skipped = result.get("status") == "skipped" and result.get("reason") == "distributed_lock_busy"
    return {
        "name": "daily_sales_same_date_task",
        "total_attempts": 2,
        "acquired_count": int(held_lock.acquired),
        "blocked_count": int(skipped),
        "lock_keys_used": [lock_key],
        "held_lock_status": held_lock.status,
        "task_result": result,
        "batch_run_status": batch_run.status,
        "passed": held_lock.acquired and skipped,
    }


def build_summary(proofs):
    total_attempts = sum(proof["total_attempts"] for proof in proofs)
    acquired_count = sum(proof["acquired_count"] for proof in proofs)
    blocked_count = sum(proof["blocked_count"] for proof in proofs)
    lock_keys_used = sorted({key for proof in proofs for key in proof["lock_keys_used"]})
    passed = all(proof["passed"] for proof in proofs)
    return {
        "total_attempts": total_attempts,
        "acquired_count": acquired_count,
        "blocked_count": blocked_count,
        "lock_keys_used": lock_keys_used,
        "result": "PASSED" if passed else "FAILED",
    }


def save_results(result):
    results_dir = BASE_DIR / "results" / "locks"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / f"task7_distributed_lock_{timestamp}.json"
    latest_path = results_dir / "task7_distributed_lock_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(summary, latest_path):
    print("\nTask 7 - Redis Distributed Lock Proof\n")
    print(f"Total attempts: {summary['total_attempts']}")
    print(f"Acquired count: {summary['acquired_count']}")
    print(f"Blocked count: {summary['blocked_count']}")
    print("Lock keys used:")
    for key in summary["lock_keys_used"]:
        print(f"- {key}")
    print(f"Result: {summary['result']}")
    print(f"\nSaved latest result: {latest_path}")


def main():
    args = parse_args()
    lock_keys = [
        THREAD_LOCK_NAME,
        checkout_user_lock_key(CHECKOUT_USER_ID),
        daily_sales_report_lock_key(REPORT_DATE),
    ]

    try:
        cleanup_lock_keys(lock_keys)
        proofs = [
            run_threaded_lock_proof(args.attempts, args.hold_seconds),
            run_checkout_duplicate_lock_simulation(),
            run_daily_sales_lock_skip_proof(),
        ]
        summary = build_summary(proofs)
        result = {
            **summary,
            "proofs": proofs,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        timestamped_path, latest_path = save_results(result)
        print_summary(summary, latest_path)
        print(f"Saved timestamped result: {timestamped_path}")
        return 0 if summary["result"] == "PASSED" else 1
    except RedisError as exc:
        print(f"\nTask 7 distributed lock proof could not reach Redis: {exc}", file=sys.stderr)
        return 2
    except DistributedLockTestError as exc:
        print(f"\nTask 7 distributed lock proof could not run: {exc}", file=sys.stderr)
        return 2
    finally:
        try:
            cleanup_lock_keys(lock_keys)
        except RedisError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
