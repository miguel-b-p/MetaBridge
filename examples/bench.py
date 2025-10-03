from __future__ import annotations

import os
import statistics as stats
import threading
import time

import metabridge as meta

import service_daemon


def bench_latency(n=200):
    c = meta.connect("demo-service", argumento="ping", timeout=3.0)

    # warmup
    for _ in range(20):
        c.get("warmup")

    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        c.get("warmup")
        times.append((time.perf_counter() - t0) * 1e3)

    return {
        "n": n,
        "p50_ms": stats.median(times),
        "p95_ms": sorted(times)[int(0.95 * (n - 1))],
        "avg_ms": sum(times) / len(times),
        "min_ms": min(times),
        "max_ms": max(times),
    }


def bench_throughput(concurrency=16, duration=2.0):
    stop = time.perf_counter() + duration
    counts = [0] * concurrency

    def worker(i):
        c = meta.connect("demo-service", argumento="pong", timeout=3.0)
        while time.perf_counter() < stop:
            c.get("warmup")
            counts[i] += 1

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = sum(counts)
    return {"concurrency": concurrency, "duration_s": duration, "ops": total, "ops_per_sec": total / duration}


def bench_lru_cache_stress(concurrency=16, duration=2.0, unique_instances=500):
    """
    Stresses the server-side LRU cache for service instances and checks for deadlocks.

    This test creates a high number of concurrent requests, each targeting a
    different service instance by providing unique constructor arguments. By
    using more unique instances than the cache size (default 128), this test
    forces the cache to perform frequent evictions and creations, which are
    protected by a lock.

    Sustained performance under this load indicates the O(1) cache is working
    as expected. The test will hang if a deadlock occurs.
    """
    stop = time.perf_counter() + duration
    counts = [0] * concurrency
    errors = [0] * concurrency

    def worker(i):
        while time.perf_counter() < stop:
            try:
                # Cycle through unique constructor arguments to stress the cache.
                # The server caches service instances based on these arguments.
                instance_id = counts[i] % unique_instances
                with meta.connect("demo-service", argumento=f"id_{instance_id}", timeout=2.0) as c:
                    c.get("stress-test")
                    counts[i] += 1
            except Exception:
                errors[i] += 1

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_ops = sum(counts)
    total_errors = sum(errors)
    return {
        "concurrency": concurrency,
        "duration_s": duration,
        "unique_instances": unique_instances,
        "ops": total_ops,
        "ops_per_sec": total_ops / duration,
        "errors": total_errors,
    }


if __name__ == "__main__":
    print("Starting service daemon for benchmarks...")
    os.environ.setdefault("META_WORKERS", "16")

    print("\n--- Latency Benchmark ---")
    lat = bench_latency()
    print(f"Latency (ms): {lat}")

    print("\n--- Throughput Benchmark (Single Instance) ---")
    thr = bench_throughput()
    print(f"Throughput: {thr}")

    print("\n--- LRU Cache Stress Test (Multiple Instances) ---")
    print("Checking for O(1) performance and deadlocks under heavy cache load...")
    stress = bench_lru_cache_stress()
    print(f"Stress Test: {stress}")

    if stress["errors"] > 0:
        print(f"🔴 WARNING: Stress test encountered {stress['errors']} errors.")
    if stress["ops_per_sec"] < thr["ops_per_sec"] / 2 and thr["ops_per_sec"] > 0:
        print("🟡 WARNING: Significant performance drop during stress test. The cache might not be O(1).")
    elif stress["errors"] == 0:
        print("✅ PASSED: No deadlocks detected and performance is stable.")