# adapters/letta_adapter.py
from __future__ import annotations

import os
import datetime as dt
from typing import List, Dict, Any, Optional

from .base import MemoryAdapter, Op

# --- Letta SDK ---
# 建议：pip install letta-client
try:
    from letta_client import Letta  # 同步客户端
except Exception:
    Letta = None


class LettaAdapter(MemoryAdapter):
    """
    Letta 归档记忆（Archival Memory / Passages）适配器

    主要功能：
      - write(facts): 结构化事实 -> 文本 passage -> 写入 Letta (agents.passages.create)
      - search(query): 通过 Letta 的分页接口做游标推进，返回指定页的前 k 条
      - delete(memory_id): 删除 passage（用于清理）
      - update(patch): （可选）REST 兜底 PATCH 文本；或采用上层 delete+create

    必需环境变量（若未手动传入 sdk_client/agent_id）：
      - LETTA_PROJECT : Letta Project 名称或 ID
      - LETTA_TOKEN   : Letta 访问 Token
      - LETTA_AGENT_ID: 目标 Agent ID

    可选（仅当你需要在 update() 中修改 passage 文本时才需配置）：
      - LETTA_API_BASE: 形如 https://api.letta.com 或你的自托管地址（不带末尾斜杠）
      - LETTA_API_KEY : 与 LETTA_TOKEN 一致也可
    """

    def __init__(
        self,
        sdk_client: Optional[object] = None,
        *,
        agent_id: Optional[str] = None,
        timeout: int = 30,
        use_rest_fallback_for_update: bool = False,  # 基础评测不需要修改，可关闭
    ):
        self.timeout = timeout
        self.agent_id = agent_id or os.getenv("LETTA_AGENT_ID")

        # 1) 构造/注入 SDK 客户端
        if sdk_client is not None:
            self.client = sdk_client
        else:
            if Letta is None:
                raise RuntimeError(
                    "未找到 letta_client.Letta。请 `pip install letta-client` 或在构造函数传入 sdk_client。"
                )
            project = os.getenv("LETTA_PROJECT")
            token = os.getenv("LETTA_TOKEN") or os.getenv("LETTA_API_KEY")
            if not project or not token:
                raise RuntimeError("缺少 LETTA_PROJECT / LETTA_TOKEN 环境变量（或在构造函数传入 sdk_client）。")
            self.client = Letta(project=project, token=token)

        if not self.agent_id:
            raise RuntimeError("必须提供 LETTA_AGENT_ID（或在构造函数传入 agent_id）。")

        # 2) 可选：REST 兜底（仅用于 update 文本）
        self._rest_enabled = False
        if use_rest_fallback_for_update:
            base = os.getenv("LETTA_API_BASE", "").rstrip("/")
            api_key = os.getenv("LETTA_API_KEY") or os.getenv("LETTA_TOKEN")
            if base and api_key:
                import requests

                self._rest_enabled = True
                self._rest_base = base
                self._rest = requests.Session()
                self._rest.headers.update(
                    {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }
                )

    # ---------------- 写入（Create Passage） ----------------
    def write(self, facts: List[Dict[str, Any]], *, scope: str = "long_term") -> None:
        """
        将结构化事实写入 Letta 归档记忆（passages）。
        """
        if scope != "long_term" or not facts:
            return

        def _to_text(f: Dict[str, Any]) -> str:
            s = f.get("subject", "")
            p = f.get("predicate", "")
            o = f.get("object", "")
            ts = f.get("ts", "")
            src = f.get("source", "")
            return f"{s} {p} {o} | ts={ts} | src={src}"

        for f in facts:
            text = _to_text(f)
            tags = f.get("tags")
            created_at: Optional[dt.datetime] = None
            if f.get("ts"):
                try:
                    created_at = dt.datetime.fromisoformat(f["ts"])
                except Exception:
                    created_at = None

            # Letta SDK: agents.passages.create(...)
            self.client.agents.passages.create(
                agent_id=self.agent_id,
                text=text,
                tags=tags if tags else None,
                created_at=created_at if created_at else None,
            )

    # ---------------- 搜索/分页（List Passages with search） ----------------
    def search(self, query: str, *, k: int = 10, page: int = 1, page_size: int = 50) -> List[Dict[str, Any]]:
        """
        通过多次 list(... after=...) 推进游标，抵达目标页，再返回该页前 k 条。
        ascending=True 表示旧->新；若需“最新优先”可改为 False。
        """
        after: Optional[str] = None
        current = 1
        last_page_items = []

        while current <= page:
            items = self.client.agents.passages.list(
                agent_id=self.agent_id,
                search=query if query else None,
                limit=page_size,
                after=after,
                ascending=True,
            )
            last_page_items = items
            after = items[-1].id if items else None
            if not items or after is None:
                break
            current += 1

        # 统一转成可 JSON 序列化的 dict（datetime -> ISO 字符串）
        results: List[Dict[str, Any]] = []
        for p in last_page_items[:k]:
            created_at = getattr(p, "created_at", None)
            updated_at = getattr(p, "updated_at", None)
            if hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            if hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()

            results.append(
                {
                    "id": getattr(p, "id", None),
                    "text": getattr(p, "text", None),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return results

    # ---------------- 修改/删除（评测非必需） ----------------
    def update(self, patch: Dict[str, Any]) -> None:
        """
        修改 passage 文本（需要 memory_id 与新 text）。
        - Letta SDK 的 modify() 当前无 text 参数；基础评测一般不需要修改行为。
        - 如确需修改：可开启 REST 兜底，或在上层采用“delete+create”的替代策略。
        """
        memory_id = patch.get("id") or patch.get("memory_id")
        new_text = patch.get("text")
        if not memory_id or not new_text:
            return

        if not self._rest_enabled:
            raise NotImplementedError(
                "当前 Letta SDK 的 modify() 无 text 参数；请设置 LETTA_API_BASE/LETTA_API_KEY 以启用 REST 兜底，或在上层用 delete+create。"
            )

        url = f"{self._rest_base}/v1/agents/{self.agent_id}/archival-memory/{memory_id}"
        r = self._rest.patch(url, json={"text": new_text}, timeout=self.timeout)
        if r.status_code >= 300:
            raise RuntimeError(f"Letta update failed: {r.status_code} {r.text}")

    def delete(self, memory_id: str) -> None:
        """删除 passage：用于清理（可选）。"""
        try:
            self.client.agents.passages.delete(agent_id=self.agent_id, memory_id=memory_id)
        except Exception as e:
            raise RuntimeError(f"Letta delete failed: {e}")

    # ---------------- 辅助 ----------------
    def summarize(self, items: List[Dict[str, Any]]) -> str:
        lines = []
        for it in items[:10]:
            text = it.get("text") or ""
            lines.append(f"- {text}")
        return "\n".join(lines)

    def decide_ops(self, candidate: Dict[str, Any], near: List[Dict[str, Any]]) -> Op:
        # 在 Letta 中通常由 Agent/LLM 判定；评测里用固定策略避免随机性
        return "ADD"
