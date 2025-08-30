# runners/smoke_mem0_sdk.py
import os
import json
from mem0 import MemoryClient

# 可选：自动加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def main():
    api_key = os.getenv("MEM0_API_KEY")
    assert api_key, "请先设置 MEM0_API_KEY"
    namespace = os.getenv("MEM0_NAMESPACE", "default")
    version = "v2"

    client = MemoryClient(api_key=api_key)

    # 1) 写入一条事实（作为一轮 user 消息）
    text = "Project Orion was released in 2024. (source:demo, tags:orion,release, ts:2024-06-01T00:00:00)"
    resp_add = client.add(
        messages=[{"role": "user", "content": text}],
        user_id=namespace,
        version=version,
    )
    print("ADD resp:", json.dumps(resp_add, ensure_ascii=False, indent=2))

    # 从返回中尽量解析一个 memory_id（兼容不同字段名）
    memory_id = None
    if isinstance(resp_add, dict):
        if "memories" in resp_add and isinstance(resp_add["memories"], list) and resp_add["memories"]:
            memory_id = resp_add["memories"][0].get("id") or resp_add["memories"][0].get("memory_id")
        else:
            memory_id = resp_add.get("id") or resp_add.get("memory_id") or resp_add.get("uuid")

    # 2) 搜索（限定 user_id=namespace）
    query = "Orion released"
    filters = {"AND": [{"user_id": namespace}]}
    resp_search = client.search(query, version=version, filters=filters)

    # 规整输出
    items = []
    if isinstance(resp_search, list):
        items = resp_search
    elif isinstance(resp_search, dict):
        for key in ("results", "items", "memories"):
            if key in resp_search and isinstance(resp_search[key], list):
                items = resp_search[key]
                break

    print("SEARCH hits:", json.dumps(items[:5], ensure_ascii=False, indent=2))

    # 3) （可选）删除刚才写入的那条
    if memory_id and hasattr(client, "delete"):
        try:
            resp_del = client.delete(memory_id, version=version)
            print("DELETE resp:", json.dumps(resp_del, ensure_ascii=False, indent=2))
        except Exception as e:
            print("DELETE failed (可能此 SDK 版本未提供 delete):", e)
    else:
        print("跳过 DELETE：未解析到 memory_id 或 SDK 无 delete 方法。")


if __name__ == "__main__":
    main()
