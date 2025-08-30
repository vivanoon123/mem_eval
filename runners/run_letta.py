# runners/run_letta.py
import time, json, argparse, os, sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from tools.mega_facts import MegaFactsBackend
from adapters.letta_adapter import LettaAdapter
from letta_client import Letta

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def run(task_mode="paged", pages=3, page_size=50, out="logs_letta.jsonl",
        n_facts=10000, seed=42):
    # 最稳：gold 覆盖与 queries 对齐（1..50），topic_mod=10
    backend = MegaFactsBackend.from_synthetic(
        n_facts=n_facts,
        n_gold=500,            # 多给点无妨
        gold_entities=50,      # 明确覆盖 1..50
        seed=seed
    )

    sdk_client = Letta(
        token=os.getenv("LETTA_TOKEN"),
        project=os.getenv("LETTA_PROJECT"),
    )
    adapter = LettaAdapter(sdk_client=sdk_client, agent_id=os.getenv("LETTA_AGENT_ID"))

    # 自动生成 50 条查询，与 gold 对齐
    questions = [f"gold.entity.{i} is associated with gold.topic.{i%10}" for i in range(1, 51)]

    # 限制 FAT 模式一次返回的最大 items（避免 5000）
    MAX_FAT_RETURN = 200
    # 实际写入配额
    TOPK_FAT_WRITE = 5
    TOPK_PAGED_WRITE_PER_PAGE = 2

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as log:
        for q in questions:
            t0 = time.time()
            # 1) 先在 Letta 记忆中检索
            mem_hits = adapter.search(q, k=5, page=1, page_size=page_size)
            used_memory = len(mem_hits) > 0
            items_used = 0

            if used_memory:
                # 命中记忆，不需要工具
                pass
            else:
                # 2) 未命中 → 调工具
                if task_mode == "fat":
                    resp = backend.query(q, mode="fat")
                    items = resp["items"][:MAX_FAT_RETURN]         # 限流
                    to_write = items[:TOPK_FAT_WRITE]              # 只写前 K（gold 会优先靠前）
                    adapter.write(to_write, scope="long_term")
                    items_used = len(to_write)                      # 统计写入数量，而非工具返回总量
                else:
                    all_items_written = 0
                    for p in range(1, pages + 1):
                        resp = backend.query(q, mode="paged", page=p, page_size=page_size)
                        page_items = resp["items"]
                        to_write = page_items[:TOPK_PAGED_WRITE_PER_PAGE]
                        if to_write:
                            adapter.write(to_write, scope="long_term")
                            all_items_written += len(to_write)
                    items_used = all_items_written

            latency_ms = int((time.time() - t0) * 1000)
            rec = {
                "framework": "Letta",
                "query": q,
                "mode": task_mode,
                "used_memory": used_memory,
                "items_used": items_used,      # 现在是“写入条数”，不是工具返回条数
                "latency_ms": latency_ms
            }
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(rec)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fat","paged"], default="fat")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page_size", type=int, default=50)
    ap.add_argument("--out", default="logs_letta.jsonl")
    ap.add_argument("--n_facts", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ns = ap.parse_args()
    run(task_mode=ns.mode, pages=ns.pages, page_size=ns.page_size, out=ns.out, n_facts=ns.n_facts, seed=ns.seed)
