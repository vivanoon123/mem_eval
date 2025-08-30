#!/usr/bin/env python3
# analyze_logs.py
# 用法：
#   python analyze_logs.py logs_fat.jsonl logs_paged.jsonl
#   python analyze_logs.py logs_*.jsonl

import argparse
import json
import sys
from collections import defaultdict

def safe_avg(nums):
    return sum(nums) / len(nums) if nums else 0.0

def fmt_pct(n, d):
    return f"{(n/d*100):.2f}%" if d else "NA"

def analyze(records):
    """
    records: list of dict, 每个包含至少：
      - mode: 'fat' or 'paged'
      - used_memory: bool
      - latency_ms: int/float
    """
    # 按模式聚合
    buckets = defaultdict(list)  # key: mode
    for r in records:
        buckets[r.get("mode", "unknown")].append(r)

    def calc_stats(rs):
        total = len(rs)
        hits = [r for r in rs if r.get("used_memory") is True]
        misses = [r for r in rs if r.get("used_memory") is not True]

        hit_rate = fmt_pct(len(hits), total)
        avg_lat_hit = safe_avg([float(r.get("latency_ms", 0)) for r in hits])
        avg_lat_miss = safe_avg([float(r.get("latency_ms", 0)) for r in misses])

        return {
            "total": total,
            "hits": len(hits),
            "hit_rate": hit_rate,
            "avg_latency_hit_ms": avg_lat_hit,
            "avg_latency_miss_ms": avg_lat_miss,
        }

    # 分模式
    per_mode = {mode: calc_stats(rs) for mode, rs in buckets.items()}
    # 总体
    overall = calc_stats(records)

    return per_mode, overall

def load_jsonl(paths):
    recs = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        recs.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"[WARN] 跳过无法解析的行（{p}）: {e}", file=sys.stderr)
        except FileNotFoundError:
            print(f"[WARN] 文件不存在：{p}", file=sys.stderr)
    return recs

def main():
    ap = argparse.ArgumentParser(description="统计命中率与平均延迟（命中/未命中）")
    ap.add_argument("logs", nargs="+", help="一个或多个 JSONL 日志文件")
    args = ap.parse_args()

    records = load_jsonl(args.logs)
    if not records:
        print("未读取到任何记录。请确认日志路径是否正确。")
        return

    per_mode, overall = analyze(records)

    print("\n=== 按模式统计 ===")
    for mode, s in per_mode.items():
        print(f"- mode: {mode}")
        print(f"  总次数: {s['total']}")
        print(f"  命中次数: {s['hits']}  命中率: {s['hit_rate']}")
        print(f"  平均延迟(命中): {s['avg_latency_hit_ms']:.2f} ms")
        print(f"  平均延迟(未命中): {s['avg_latency_miss_ms']:.2f} ms")

    print("\n=== 总体统计（合并所有日志与模式） ===")
    print(f"总次数: {overall['total']}")
    print(f"命中次数: {overall['hits']}  命中率: {overall['hit_rate']}")
    print(f"平均延迟(命中): {overall['avg_latency_hit_ms']:.2f} ms")
    print(f"平均延迟(未命中): {overall['avg_latency_miss_ms']:.2f} ms\n")

if __name__ == "__main__":
    main()
