# adapters/mem0_adapter.py
from __future__ import annotations
import os
from typing import List, Dict, Any, Optional


def _fact_to_text(f: Dict[str, Any]) -> str:
    subj = f.get("subject", "")
    pred = f.get("predicate", "")
    obj  = f.get("object", "")
    ts   = f.get("ts")
    tags = f.get("tags", [])
    src  = f.get("source")
    parts = [f"{subj} {pred} {obj}."]
    meta = []
    if src:  meta.append(f"source:{src}")
    if tags: meta.append("tags:" + ",".join(tags))
    if ts:   meta.append(f"ts:{ts}")
    if meta:
        parts.append(f" ({', '.join(meta)})")
    return "".join(parts)


class Mem0Adapter:
    """
    简化版 Mem0 v2 适配器
    - 使用 MEM0_API_KEY 环境变量初始化
    - 支持 write / search / delete
    """

    def __init__(self, *, namespace: Optional[str] = None):
        try:
            from mem0 import MemoryClient
        except Exception as e:
            raise RuntimeError("请先安装 mem0 v2 SDK：`pip install mem0ai`") from e

        api_key = os.getenv("MEM0_API_KEY")
        assert api_key, "请设置 MEM0_API_KEY"

        self.client = MemoryClient(api_key=api_key)
        self.namespace = namespace or os.getenv("MEM0_NAMESPACE", "default")
        self.version = "v2"

    def write(self, facts: List[Dict[str, Any]], scope: str = "long_term") -> List[str]:
        ids: List[str] = []
        for f in facts:
            text = _fact_to_text(f)
            resp = self.client.add(
                messages=[{"role": "user", "content": text}],
                user_id=self.namespace,
                version=self.version,
            )
            if isinstance(resp, dict):
                if "memories" in resp and resp["memories"]:
                    mid = resp["memories"][0].get("id") or resp["memories"][0].get("memory_id")
                    if mid:
                        ids.append(mid)
                else:
                    mid = resp.get("id") or resp.get("memory_id") or resp.get("uuid")
                    if mid:
                        ids.append(mid)
        return ids

    def search(self, query: str, k: int = 5, page: int = 1, page_size: int = 50) -> List[Dict[str, Any]]:
        filters = {"AND": [{"user_id": self.namespace}]}
        resp = self.client.search(query, version=self.version, filters=filters)
        out: List[Dict[str, Any]] = []
        items = []

        if isinstance(resp, list):
            items = resp
        elif isinstance(resp, dict):
            for key in ("results", "items", "memories"):
                if key in resp and isinstance(resp[key], list):
                    items = resp[key]
                    break

        for h in items[:k]:
            out.append({
                "id": h.get("id") or h.get("memory_id") or h.get("uuid") or "",
                "text": h.get("text") or h.get("content") or "",
                "score": h.get("score") or h.get("similarity") or 0.0,
            })
        return out

    def delete(self, memory_id: str) -> bool:
        if hasattr(self.client, "delete"):
            try:
                resp = self.client.delete(memory_id, version=self.version)
                if isinstance(resp, dict):
                    return bool(resp.get("deleted") or resp.get("success"))
                return True
            except Exception:
                return False
        return False
