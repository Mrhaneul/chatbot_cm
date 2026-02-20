#!/usr/bin/env python3
"""
Concurrent user benchmark for chatbot API.

Runs load tests for 5-10 concurrent users, captures:
- request timing (client + server-reported metrics)
- GPU utilization snapshots (nvidia-smi)
- simple answer quality checks (RAG/source + keyword relevance)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import statistics
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
CONCURRENCY_LEVELS = [5, 6, 7, 8, 9, 10]


QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "mindtap_access",
        "text": "I can't access to Cengage MindTap",
        "expected_keywords": ["cengage", "mindtap", "access"],
        "expect_rag": True,
    },
    {
        "id": "return_policy",
        "text": "What are the return policies for textbooks?",
        "expected_keywords": ["return", "policy", "textbook"],
        "expect_rag": True,
    },
    {
        "id": "mcgraw_access",
        "text": "I can't access McGraw Hill Connect",
        "expected_keywords": ["mcgraw", "connect", "access"],
        "expect_rag": True,
    },
    {
        "id": "immediate_access",
        "text": "What is Immediate Access?",
        "expected_keywords": ["immediate access"],
        "expect_rag": True,
    },
    {
        "id": "pearson_access",
        "text": "How do I access Pearson MyLab?",
        "expected_keywords": ["pearson", "mylab"],
        "expect_rag": True,
    },
]


@dataclass
class GPUSample:
    ts: float
    gpu_util: float
    mem_util: float
    mem_used_mb: float
    mem_total_mb: float
    power_w: float


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = (len(ordered) - 1) * p
    low = int(idx)
    high = min(low + 1, len(ordered) - 1)
    frac = idx - low
    return float(ordered[low] * (1 - frac) + ordered[high] * frac)


def safe_mean(values: List[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def run_nvidia_smi_sample() -> GPUSample | None:
    cmd = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        if not out:
            return None
        line = out.splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            return None
        return GPUSample(
            ts=time.time(),
            gpu_util=float(parts[0]),
            mem_util=float(parts[1]),
            mem_used_mb=float(parts[2]),
            mem_total_mb=float(parts[3]),
            power_w=float(parts[4]),
        )
    except Exception:
        return None


def gpu_sampler(stop_event: threading.Event, samples: List[GPUSample], interval_s: float) -> None:
    while not stop_event.is_set():
        sample = run_nvidia_smi_sample()
        if sample:
            samples.append(sample)
        stop_event.wait(interval_s)


def score_quality(question: Dict[str, Any], response_json: Dict[str, Any]) -> Dict[str, Any]:
    reply = (response_json.get("reply") or "").lower()
    source = response_json.get("source") or "UNKNOWN"
    confidence = float(response_json.get("confidence") or 0.0)
    keywords = question["expected_keywords"]

    matched = sum(1 for kw in keywords if kw in reply)
    keyword_score = matched / len(keywords) if keywords else 0.0

    rag_hit = source != "LLM_ONLY" and confidence >= 0.1
    rag_expected = bool(question.get("expect_rag", False))
    rag_score = 1.0 if (rag_hit if rag_expected else True) else 0.0
    quality_score = 0.6 * keyword_score + 0.4 * rag_score

    return {
        "quality_score": round(quality_score, 4),
        "keyword_score": round(keyword_score, 4),
        "rag_hit": rag_hit,
        "quality_pass": quality_score >= 0.65,
    }


def single_request(base_url: str, message: str, session_id: str, timeout_s: int) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat"
    payload = {"message": message, "session_id": session_id}

    start = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=timeout_s)
        end = time.time()
        elapsed_ms = (end - start) * 1000

        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {}

        return {
            "ok": resp.status_code == 200,
            "status_code": resp.status_code,
            "client_total_ms": round(elapsed_ms, 2),
            "response_json": body,
            "error": None if resp.status_code == 200 else resp.text[:500],
        }
    except Exception as exc:
        end = time.time()
        return {
            "ok": False,
            "status_code": 0,
            "client_total_ms": round((end - start) * 1000, 2),
            "response_json": {},
            "error": str(exc),
        }


def run_level(base_url: str, users: int, rounds: int, timeout_s: int) -> Dict[str, Any]:
    requests_out: List[Dict[str, Any]] = []
    level_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=users) as pool:
        for r in range(rounds):
            futs: Dict[concurrent.futures.Future, Dict[str, Any]] = {}
            for u in range(users):
                q = QUESTIONS[(r * users + u) % len(QUESTIONS)]
                session = f"bench-u{u}-lvl{users}-r{r}-{uuid.uuid4().hex[:8]}"
                fut = pool.submit(single_request, base_url, q["text"], session, timeout_s)
                futs[fut] = q
            for fut in concurrent.futures.as_completed(futs):
                res = fut.result()
                q = futs[fut]
                res["question"] = q
                if res["ok"]:
                    res.update(score_quality(q, res.get("response_json", {})))
                else:
                    res.update(
                        {
                            "quality_score": 0.0,
                            "keyword_score": 0.0,
                            "rag_hit": False,
                            "quality_pass": False,
                        }
                    )
                requests_out.append(res)

    level_end = time.time()
    elapsed_s = max(level_end - level_start, 1e-9)

    ok_reqs = [r for r in requests_out if r["ok"]]
    lat_client = [r["client_total_ms"] for r in ok_reqs]

    server_total = [
        float(r["response_json"].get("total_time_ms") or 0.0)
        for r in ok_reqs
        if r.get("response_json")
    ]
    server_retrieval = [
        float(r["response_json"].get("retrieval_time_ms") or 0.0)
        for r in ok_reqs
        if r.get("response_json")
    ]
    server_llm = [
        float(r["response_json"].get("llm_time_ms") or 0.0)
        for r in ok_reqs
        if r.get("response_json")
    ]
    quality_scores = [r["quality_score"] for r in requests_out]
    rag_hits = [1.0 if r["rag_hit"] else 0.0 for r in requests_out]
    quality_passes = [1.0 if r["quality_pass"] else 0.0 for r in requests_out]

    return {
        "users": users,
        "rounds": rounds,
        "window_start_ts": level_start,
        "window_end_ts": level_end,
        "duration_s": round(elapsed_s, 3),
        "total_requests": len(requests_out),
        "successful_requests": len(ok_reqs),
        "success_rate": round((len(ok_reqs) / len(requests_out) * 100.0), 2) if requests_out else 0.0,
        "throughput_rps": round(len(ok_reqs) / elapsed_s, 3),
        "latency_client_ms": {
            "avg": round(safe_mean(lat_client), 2),
            "p50": round(percentile(lat_client, 0.50), 2),
            "p95": round(percentile(lat_client, 0.95), 2),
            "max": round(max(lat_client), 2) if lat_client else 0.0,
        },
        "latency_server_total_ms": {
            "avg": round(safe_mean(server_total), 2),
            "p50": round(percentile(server_total, 0.50), 2),
            "p95": round(percentile(server_total, 0.95), 2),
            "max": round(max(server_total), 2) if server_total else 0.0,
        },
        "latency_retrieval_ms_avg": round(safe_mean(server_retrieval), 2),
        "latency_llm_ms_avg": round(safe_mean(server_llm), 2),
        "quality": {
            "quality_score_avg": round(safe_mean(quality_scores), 3),
            "quality_pass_rate_pct": round(safe_mean(quality_passes) * 100.0, 2),
            "rag_hit_rate_pct": round(safe_mean(rag_hits) * 100.0, 2),
        },
        "requests": requests_out,
    }


def summarize_gpu(samples: List[GPUSample], start_ts: float, end_ts: float) -> Dict[str, float]:
    window = [s for s in samples if start_ts <= s.ts <= end_ts]
    if not window:
        return {
            "sample_count": 0,
            "gpu_util_avg": 0.0,
            "gpu_util_peak": 0.0,
            "mem_used_avg_mb": 0.0,
            "mem_used_peak_mb": 0.0,
            "power_avg_w": 0.0,
            "power_peak_w": 0.0,
        }
    return {
        "sample_count": len(window),
        "gpu_util_avg": round(safe_mean([s.gpu_util for s in window]), 2),
        "gpu_util_peak": round(max(s.gpu_util for s in window), 2),
        "mem_used_avg_mb": round(safe_mean([s.mem_used_mb for s in window]), 2),
        "mem_used_peak_mb": round(max(s.mem_used_mb for s in window), 2),
        "power_avg_w": round(safe_mean([s.power_w for s in window]), 2),
        "power_peak_w": round(max(s.power_w for s in window), 2),
    }


def build_markdown_report(result: Dict[str, Any]) -> str:
    ts = result["run_timestamp"]
    lines: List[str] = []
    lines.append(f"# Chatbot Concurrent-User Benchmark Report ({ts})")
    lines.append("")
    lines.append("## Setup")
    lines.append(f"- Base URL: `{result['base_url']}`")
    lines.append(f"- Concurrency levels: `{', '.join(str(x) for x in CONCURRENCY_LEVELS)}` users")
    lines.append(f"- Rounds per level: `{result['rounds_per_level']}`")
    lines.append(f"- Questions tested: `{len(QUESTIONS)}` common RAG queries")
    lines.append("")
    lines.append("## Summary Table")
    lines.append("")
    lines.append("| Users | Success % | Throughput (req/s) | Client p50 (ms) | Client p95 (ms) | Server p50 (ms) | Server p95 (ms) | Retrieval avg (ms) | LLM avg (ms) | GPU avg % | GPU peak % | GPU Mem avg (MB) | Quality avg | Quality pass % | RAG hit % |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for lvl in result["levels"]:
        gpu = lvl["gpu"]
        q = lvl["quality"]
        lines.append(
            f"| {lvl['users']} | {lvl['success_rate']:.2f} | {lvl['throughput_rps']:.3f} | "
            f"{lvl['latency_client_ms']['p50']:.2f} | {lvl['latency_client_ms']['p95']:.2f} | "
            f"{lvl['latency_server_total_ms']['p50']:.2f} | {lvl['latency_server_total_ms']['p95']:.2f} | "
            f"{lvl['latency_retrieval_ms_avg']:.2f} | {lvl['latency_llm_ms_avg']:.2f} | "
            f"{gpu['gpu_util_avg']:.2f} | {gpu['gpu_util_peak']:.2f} | {gpu['mem_used_avg_mb']:.2f} | "
            f"{q['quality_score_avg']:.3f} | {q['quality_pass_rate_pct']:.2f} | {q['rag_hit_rate_pct']:.2f} |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("- `Quality avg` is a lightweight heuristic: 60% keyword relevance + 40% RAG/source hit.")
    lines.append("- `RAG hit` means source was not `LLM_ONLY` and confidence was >= 0.1.")
    lines.append("- Use this as a comparative benchmark across concurrency levels.")
    lines.append("")
    return "\n".join(lines)


def ensure_api_live(base_url: str) -> None:
    health_url = f"{base_url.rstrip('/')}/sessions/stats"
    last_err: Exception | None = None
    for _ in range(5):
        try:
            resp = requests.get(health_url, timeout=30)
            resp.raise_for_status()
            return
        except Exception as exc:
            last_err = exc
            time.sleep(2)
    if last_err:
        raise last_err


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent benchmark for chatbot API")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--gpu-sample-interval", type=float, default=1.0)
    parser.add_argument("--out-json", default="benchmark_concurrency_results.json")
    parser.add_argument("--out-md", default="benchmark_concurrency_report.md")
    args = parser.parse_args()

    ensure_api_live(args.base_url)

    gpu_samples: List[GPUSample] = []
    stop_event = threading.Event()
    sampler_thread = threading.Thread(
        target=gpu_sampler,
        args=(stop_event, gpu_samples, args.gpu_sample_interval),
        daemon=True,
    )
    sampler_thread.start()

    levels: List[Dict[str, Any]] = []
    try:
        for users in CONCURRENCY_LEVELS:
            print(f"[benchmark] Running level: {users} concurrent users")
            level = run_level(
                base_url=args.base_url,
                users=users,
                rounds=args.rounds,
                timeout_s=args.timeout,
            )
            level["gpu"] = summarize_gpu(gpu_samples, level["window_start_ts"], level["window_end_ts"])
            levels.append(level)
            print(
                f"[benchmark] users={users} success={level['success_rate']}% "
                f"p95_client={level['latency_client_ms']['p95']}ms "
                f"gpu_avg={level['gpu']['gpu_util_avg']}%"
            )
    finally:
        stop_event.set()
        sampler_thread.join(timeout=2)

    result = {
        "run_timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "rounds_per_level": args.rounds,
        "questions": QUESTIONS,
        "levels": levels,
    }

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    md = build_markdown_report(result)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"[benchmark] Wrote JSON: {os.path.abspath(args.out_json)}")
    print(f"[benchmark] Wrote report: {os.path.abspath(args.out_md)}")


if __name__ == "__main__":
    main()
