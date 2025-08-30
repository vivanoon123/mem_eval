# tools/mega_facts.py
from __future__ import annotations
import random
from typing import List, Dict, Any, Optional

class MegaFactsBackend:
    """
    合成事实工具：
      - 精确生成与 queries 对齐的 golden facts（如 gold.entity.i ↔ gold.topic.(i%10)）
      - 支持 fat / paged 两种查询模式
      - 查询时将匹配的 golden facts 排到前面，再拼接噪声

    记录结构（示例）：
    {
      "subject": "gold.entity.1",
      "predicate": "is associated with",
      "object": "gold.topic.1",
      "ts": "2024-06-01T00:00:00",
      "tags": ["gold"],
      "source": "synthetic"
    }
    """

    def __init__(self, facts: List[Dict[str, Any]], gold: List[Dict[str, Any]], rng: random.Random):
        self.facts = facts              # 全部事实（gold + noise）
        self.gold = gold                # gold 子集
        self.rng = rng

    # ---------------- 工厂方法：最稳的对齐生成 ----------------
    @classmethod
    def from_synthetic(
        cls,
        n_facts: int = 10_000,
        n_gold: int = 200,
        seed: int = 42,
        *,
        gold_entities: int = 50,      # 与你的 queries 对齐：生成 gold.entity.1..gold.entity.50
        topic_mod: int = 10,          # gold.topic.(i % topic_mod)
    ) -> "MegaFactsBackend":
        """
        最稳：显式覆盖 gold.entity.1..gold.entity.<gold_entities>，确保与 queries 对齐。
        其余补足为噪声 facts 到 n_facts。
        """
        rng = random.Random(seed)
        gold: List[Dict[str, Any]] = []

        # 1) 生成与 queries 对齐的 gold
        for i in range(1, gold_entities + 1):
            gold.append({
                "subject": f"gold.entity.{i}",
                "predicate": "is associated with",
                "object": f"gold.topic.{i % topic_mod}",
                "ts": "2024-06-01T00:00:00",
                "tags": ["gold"],
                "source": "synthetic"
            })

        # 如需更多 gold（>gold_entities），再补齐一些随机 gold（可选）
        extra_gold = max(0, n_gold - gold_entities)
        for j in range(extra_gold):
            x = rng.randint(1, gold_entities * 5)  # 随机更多实体空间
            gold.append({
                "subject": f"gold.entity.{x}",
                "predicate": "is associated with",
                "object": f"gold.topic.{x % topic_mod}",
                "ts": "2024-07-{:02d}T00:00:00".format(rng.randint(1, 28)),
                "tags": ["gold", "extra"],
                "source": "synthetic"
            })

        # 2) 生成噪声 facts（不严格匹配 queries）
        facts: List[Dict[str, Any]] = list(gold)
        remaining = max(0, n_facts - len(facts))
        verbs = [
            "mentions", "is unrelated to", "conflicts with", "precedes", "follows",
            "uses", "depends on", "is similar to", "replaces", "is replaced by"
        ]
        for _ in range(remaining):
            a = rng.randint(1, gold_entities * 5)
            b = rng.randint(0, topic_mod - 1)
            verb = rng.choice(verbs)
            facts.append({
                "subject": f"noise.entity.{a}",
                "predicate": verb,
                "object": f"noise.topic.{b}",
                "ts": "2023-{:02d}-{:02d}T00:00:00".format(rng.randint(1, 12), rng.randint(1, 28)),
                "tags": ["noise"],
                "source": "synthetic"
            })

        rng.shuffle(facts)
        return cls(facts=facts, gold=gold, rng=rng)

    # ---------------- 查询接口 ----------------
    def query(
        self,
        q: str,
        *,
        mode: str = "fat",
        page: int = 1,
        page_size: int = 50
    ) -> Dict[str, Any]:
        """
        返回 {"items": [...]}。
        - 将与查询 q 强匹配的 gold 放在前面
        - 再拼接若干噪声（可选）
        - mode="paged" 时再切片
        """
        # 简单解析：从 query 中提取 entity 与 topic
        # 期望格式：gold.entity.X is associated with gold.topic.Y
        entity = None
        topic = None
        parts = q.strip().split()
        # 防御式解析
        try:
            # 固定模板："gold.entity.{i} is associated with gold.topic.{j}"
            entity = parts[0]                  # gold.entity.X
            topic = parts[-1]                  # gold.topic.Y
        except Exception:
            pass

        def is_gold_match(rec: Dict[str, Any]) -> bool:
            return (
                rec.get("subject") == entity and
                rec.get("predicate") == "is associated with" and
                rec.get("object") == topic
            )

        # 1) 取出强匹配的 gold（放前面）
        gold_hits = [g for g in self.gold if is_gold_match(g)]

        # 2) 追加一些与 query “弱相关/无关”的噪声（保持足量）
        #    这里简单随机抽样，也可以做基于关键词的打分
        noise_candidates = [f for f in self.facts if f not in gold_hits]
        self.rng.shuffle(noise_candidates)

        # FAT 模式：先“金”后“噪”，不分页（由调用方自行截断/限流）
        if mode == "fat":
            items = gold_hits + noise_candidates
            return {"items": items}

        # PAGED 模式：先拼满，再分页
        items_full = gold_hits + noise_candidates
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        page_items = items_full[start:end]
        return {"items": page_items}
