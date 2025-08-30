# runners/run_mem0_strict_hit_miss.py
import os, sys, time, json, argparse
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from mem0 import MemoryClient
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# 仅在 paged 模式需要（与 Letta 一致的外部分页工具）
try:
    from tools.mega_facts import MegaFactsBackend
except Exception:
    MegaFactsBackend = None  # fat 可不依赖

VERSION = "v2"

def canonical_fact_text(q: str) -> str:
    q = (q or "").strip()
    if not q.endswith("."):
        q += "."
    return q

def parse_items_from_search(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("results", "items", "memories"):
            if k in resp and isinstance(resp[k], list):
                return resp[k]
    return []

def is_true_hit(q: str, text: str) -> bool:
    parts = (q or "").split()
    if len(parts) < 3:
        return False
    subj, obj = parts[0].lower(), parts[-1].lower()
    t = (text or "").lower()
    return (subj in t) and (obj in t)

def fact_to_text(f) -> str:
    subj = f.get("subject", "")
    pred = f.get("predicate", "")
    obj  = f.get("object", "")
    return f"{subj} {pred} {obj}."

def safe_add(client: MemoryClient, text: str, user_id: str, max_retries=5, base_delay=0.4):
    """
    写入带指数退避，避免 429/5xx 导致“卡住”。
    """
    delay = base_delay
    for i in range(max_retries + 1):
        try:
            client.add(messages=[{"role": "user", "content": text}],
                       user_id=user_id, version=VERSION)
            return True
        except Exception as e:
            msg = str(e)
            # 命中限流/后端抖动 → 退避重试
            if any(code in msg for code in ("429", "502", "503", "504")) and i < max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 6.0)
            else:
                # 其他错误/已到达最大重试 → 不中断整体流程
                print(f"[WARN] add failed (attempt {i+1}/{max_retries+1}): {e}")
                return False

def run(out="outputs/logs_mem0_strict_hit_miss.jsonl",
        namespace=None,
        mode="fat",            # "fat" | "paged"
        pages=3,
        page_size=50,
        cap_per_page=2,        # 每页写入上限（小一点更稳）；None/-1 表示不限制（可能很慢）
        n_facts=10000,
        n_gold=500,
        seed=42):
    """
    两阶段 strict hit/miss：
      - pass1：检索，未命中→按模式写入；记录 latency、items_written
      - pass2：立刻再次检索；记录 latency
    输出字段保持不变：
      pass1: framework/phase/query/used_memory/items_written/latency_ms/namespace
      pass2: framework/phase/query/used_memory/latency_ms/namespace
    """
    # 1) 初始化 client/namespace
    api_key = os.getenv("MEM0_API_KEY")
    assert api_key, "请设置 MEM0_API_KEY"
    client = MemoryClient(api_key=api_key)
    ns = namespace or os.getenv("MEM0_NAMESPACE", "mem-eval-fixed")
    print(f"[INFO] namespace={ns}  mode={mode}")

    # 2) paged 需要外部工具
    backend = None
    if mode == "paged":
        assert MegaFactsBackend is not None, "paged 模式需要 tools.mega_facts.MegaFactsBackend"
        backend = MegaFactsBackend.from_synthetic(
            n_facts=n_facts,
            n_gold=n_gold,
            gold_entities=50,
            seed=seed,
        )

    # 3) 50 条 query（与你的评测一致）
    questions = [f"gold.entity.{i} is associated with gold.topic.{i%10}" for i in range(1, 51)]

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as log:

        # ---------- Pass 1 ----------
        for q in questions:
            t0 = time.time()
            resp = client.search(q, version=VERSION, filters={"AND":[{"user_id": ns}]})
            hits = parse_items_from_search(resp)
            hit = any(is_true_hit(q, h.get("text","")) for h in hits)

            wrote = 0
            if not hit:
                if mode == "fat":
                    text = canonical_fact_text(q)
                    safe_add(client, text, ns)
                    wrote = 1
                else:
                    # paged：分页写少量，带退避重试，避免卡住
                    total_written = 0
                    for p in range(1, pages + 1):
                        resp_tool = backend.query(q, mode="paged", page=p, page_size=page_size)
                        page_items = resp_tool.get("items", [])
                        # 控制每页写入上限（默认 2；太大会慢/被限流）
                        if cap_per_page is not None and cap_per_page >= 0:
                            page_items = page_items[:cap_per_page]
                        for f in page_items:
                            if safe_add(client, fact_to_text(f), ns):
                                total_written += 1
                        # 轻微节流，避免连续打爆
                        time.sleep(0.05)
                    wrote = total_written

            latency_ms = int((time.time() - t0) * 1000)
            rec = {
                "framework": "Mem0",
                "phase": "pass1",
                "query": q,
                "used_memory": hit,
                "items_written": wrote,
                "latency_ms": latency_ms,
                "namespace": ns
            }
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(rec)

        # ---------- Pass 2 ----------
        for q in questions:
            t0 = time.time()
            resp = client.search(q, version=VERSION, filters={"AND":[{"user_id": ns}]})
            hits = parse_items_from_search(resp)
            hit = any(is_true_hit(q, h.get("text","")) for h in hits)
            latency_ms = int((time.time() - t0) * 1000)
            rec = {
                "framework": "Mem0",
                "phase": "pass2",
                "query": q,
                "used_memory": hit,
                "latency_ms": latency_ms,
                "namespace": ns
            }
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(rec)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/logs_mem0_strict_hit_miss.jsonl")
    ap.add_argument("--namespace", default=None,
                    help="固定 user_id（默认为 mem-eval-fixed），第二轮自然命中")
    ap.add_argument("--mode", choices=["fat","paged"], default="paged",
                    help="fat=未命中写1条canonical；paged=分页少量写入（更稳）")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page_size", type=int, default=50)
    ap.add_argument("--cap_per_page", type=int, default=2,
                    help="paged时每页最多写入多少条；None/-1=不限制（可能很慢）")
    ap.add_argument("--n_facts", type=int, default=10000)
    ap.add_argument("--n_gold", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ns = ap.parse_args()

    run(out=ns.out,
        namespace=ns.namespace,
        mode=ns.mode,
        pages=ns.pages,
        page_size=ns.page_size,
        cap_per_page=ns.cap_per_page,
        n_facts=ns.n_facts,
        n_gold=ns.n_gold,
        seed=ns.seed)
