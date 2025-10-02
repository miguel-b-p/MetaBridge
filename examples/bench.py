from __future__ import annotations


import os
import time
import threading
import statistics as stats

import metabridge as meta
import service_daemon

def bench_latency(n=200):
    c = meta.connect("demo-service", argumento="ping", timeout=3.0)

    # warmup
    for _ in range(20):
        c.get()
    
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        c.get()
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
            c.get()
            counts[i] += 1

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    total = sum(counts)
    return {"concurrency": concurrency, "duration_s": duration, "ops": total, "ops_per_sec": total / duration}

if __name__ == "__main__":
    os.environ.setdefault("SYNAPSE_WORKERS", "16")
    lat = bench_latency()
    thr = bench_throughput()
    print("Latency (ms):", lat)
    print("Throughput:", thr)