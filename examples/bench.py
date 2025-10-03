from __future__ import annotations

import os
import statistics as stats
import threading
import time

import metabridge as meta

# A importação inicia o serviço em background e disponibiliza o 'handle'
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


def bench_bottleneck(concurrency=32, duration=5.0):
    """
    Mede a latência e a vazão sob alta carga concorrente para identificar gargalos.
    Este teste envia o máximo de requisições possível de múltiplos threads simultaneamente.
    """
    stop = time.perf_counter() + duration
    # Cada thread terá sua própria lista para armazenar resultados, evitando contenção de locks.
    results = [[] for _ in range(concurrency)]

    def worker(i):
        # Cada thread obtém sua própria conexão de cliente.
        c = meta.connect("demo-service", argumento="stress", timeout=5.0)
        while time.perf_counter() < stop:
            t0 = time.perf_counter()
            c.get("payload")
            # Armazena a latência em milissegundos.
            results[i].append((time.perf_counter() - t0) * 1e3)

    print(f"  Executando com {concurrency} clientes concorrentes por {duration} segundos...")
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Achata a lista de listas em uma única lista com todos os tempos medidos.
    all_times = [t for thread_times in results for t in thread_times]

    n = len(all_times)
    if n == 0:
        return {
            "concurrency": concurrency,
            "duration_s": duration,
            "error": "Nenhuma operação foi concluída a tempo.",
        }

    return {
        "concurrency": concurrency,
        "duration_s": duration,
        "total_ops": n,
        "ops_per_sec": n / duration,
        "p50_ms": stats.median(all_times),
        "p95_ms": sorted(all_times)[int(0.95 * (n - 1))],
        "avg_ms": sum(all_times) / n,
        "min_ms": min(all_times),
        "max_ms": max(all_times),
    }


if __name__ == "__main__":
    print("Iniciando o serviço daemon para os benchmarks...")
    # Define o número de workers do servidor. O benchmark usará mais clientes do que workers para criar estresse.
    os.environ.setdefault("META_WORKERS", "16")

    # Aguarda um instante para garantir que o serviço esteja totalmente iniciado e registrado.
    time.sleep(0.5)

    print("\n--- Benchmark de Latência ---")
    lat = bench_latency()
    print(f"Latência (ms): {lat}")

    print("\n--- Benchmark de Vazão (Instância Única) ---")
    thr = bench_throughput()
    print(f"Vazão: {thr}")

    print("\n--- Benchmark de Gargalo (Alta Concorrência) ---")
    bottle = bench_bottleneck()
    print(f"Gargalo: {bottle}")

    # Encerra o serviço de forma limpa após a conclusão dos benchmarks.
    service_daemon.handle.stop()
    print("\nServiço daemon encerrado.")