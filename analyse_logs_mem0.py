# mem_eval/scripts/analyze_mem0_logs.py
import json
import argparse
import statistics
from collections import defaultdict

def safe_get(d, *keys, default=None):
    for k in keys:
        if k in d:
            return d[k]
    return default

def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows

def summarize_phase(rows, phase_name):
    xs = [r for r in rows if safe_get(r, "phase") == phase_name]
    n = len(xs)
    if not n:
        return {"count": 0, "hit_rate": 0.0, "avg_latency": None, "p50_latency": None, "p95_latency": None}
    hits = [bool(safe_get(r, "used_memory", default=False)) for r in xs]
    lat = [int(safe_get(r, "latency_ms", default=0)) for r in xs]

    hit_rate = sum(1 for h in hits if h) / n
    avg_latency = sum(lat)/n if n else None
    p50 = statistics.median(lat) if lat else None
    p95 = statistics.quantiles(lat, n=20)[18] if len(lat) >= 20 else max(lat) if lat else None
    return {
        "count": n,
        "hit_rate": hit_rate,
        "avg_latency": avg_latency,
        "p50_latency": p50,
        "p95_latency": p95,
    }

def build_query_pairs(rows):
    """将同一 query 的 pass1 / pass2 配成对"""
    per_query = defaultdict(dict)
    for r in rows:
        q = safe_get(r, "query", default="")
        ph = safe_get(r, "phase", default="")
        per_query[q][ph] = r
    pairs = []
    for q, d in per_query.items():
        p1 = d.get("pass1")
        p2 = d.get("pass2")
        if p1 and p2:
            pairs.append((q, p1, p2))
    return pairs

def print_section(title):
    print("\n" + "="*len(title))
    print(title)
    print("="*len(title))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True, help="JSONL 日志路径（来自 run_mem0_strict_hit_miss.py）")
    ap.add_argument("--topk", type=int, default=5, help="TopK 最快/最慢展示条数（按 pass2）")
    ns = ap.parse_args()

    rows = load_jsonl(ns.log)
    if not rows:
        print("没有读到任何日志行。")
        return

    # 基本信息
    total = len(rows)
    namespace = safe_get(rows[0], "namespace", default="(unknown)")
    framework = safe_get(rows[0], "framework", default="(unknown)")

    print_section("Mem0 日志分析（strict hit/miss）")
    print(f"框架: {framework}")
    print(f"命名空间: {namespace}")
    print(f"总行数: {total}")

    # 分阶段统计
    s1 = summarize_phase(rows, "pass1")
    s2 = summarize_phase(rows, "pass2")

    print_section("分阶段统计")
    for name, s in [("pass1（首次查询）", s1), ("pass2（再次查询）", s2)]:
        print(f"- {name}")
        print(f"  样本数         : {s['count']}")
        print(f"  命中率         : {s['hit_rate']*100:.2f}%")
        if s["avg_latency"] is not None:
            print(f"  平均延迟       : {s['avg_latency']:.2f} ms")
            print(f"  p50 延迟       : {s['p50_latency']:.2f} ms")
            print(f"  p95 延迟       : {s['p95_latency']:.2f} ms")

    # 命中转移矩阵 + 延迟对比
    pairs = build_query_pairs(rows)
    mm = mh = hm = hh = 0
    deltas = []  # pass2 - pass1
    for q, p1, p2 in pairs:
        h1 = bool(safe_get(p1, "used_memory", default=False))
        h2 = bool(safe_get(p2, "used_memory", default=False))
        l1 = int(safe_get(p1, "latency_ms", default=0))
        l2 = int(safe_get(p2, "latency_ms", default=0))
        deltas.append(l2 - l1)
        if not h1 and h2:
            mh += 1
        elif not h1 and not h2:
            mm += 1
        elif h1 and h2:
            hh += 1
        elif h1 and not h2:
            hm += 1

    print_section("命中转移矩阵（以 query 为单位）")
    print(f"miss → hit : {mh}")
    print(f"miss → miss: {mm}")
    print(f"hit  → hit : {hh}")
    print(f"hit  → miss: {hm}")

    if deltas:
        print_section("延迟差（pass2 - pass1）")
        avg_delta = sum(deltas)/len(deltas)
        p50_delta = statistics.median(deltas)
        print(f"平均差值: {avg_delta:.2f} ms （负值表示第二次更快）")
        print(f"p50 差值: {p50_delta:.2f} ms")

    # TopK 最慢/最快（按 pass2）
    pass2_rows = [r for r in rows if safe_get(r, "phase") == "pass2"]
    pass2_rows.sort(key=lambda r: int(safe_get(r, "latency_ms", default=0)), reverse=True)
    worst = pass2_rows[:ns.topk]
    best = list(reversed(pass2_rows[-ns.topk:]))

    print_section(f"Top{ns.topk} 最慢（按 pass2）")
    for r in worst:
        print(f"{safe_get(r, 'latency_ms', default='?')} ms  | hit={bool(safe_get(r, 'used_memory', default=False))} | {safe_get(r, 'query', default='')}")

    print_section(f"Top{ns.topk} 最快（按 pass2）")
    for r in best:
        print(f"{safe_get(r, 'latency_ms', default='?')} ms  | hit={bool(safe_get(r, 'used_memory', default=False))} | {safe_get(r, 'query', default='')}")

if __name__ == "__main__":
    main()
