import os
import json
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from adapters.letta_adapter import LettaAdapter
from letta_client import Letta

# 可选：自动加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def main():
    agent_id = os.getenv("LETTA_AGENT_ID")
    assert agent_id, "请设置 LETTA_AGENT_ID"

    sdk_client = Letta(
        token=os.getenv("LETTA_TOKEN"),
        project=os.getenv("LETTA_PROJECT"),
    )
    adapter = LettaAdapter(sdk_client=sdk_client, agent_id=os.getenv("LETTA_AGENT_ID"))

    # 1) create
    fact = {"subject": "Project Orion", "predicate": "was released in", "object": "2024", "ts": "2024-06-01T00:00:00", "tags": ["orion","release"], "source":"demo"}
    adapter.write([fact], scope="long_term")
    print("Created one passage.")

    # 2) search
    hits = adapter.search("Project Orion", k=3, page=1, page_size=10)
    print("Search hits:", json.dumps(hits, ensure_ascii=False, indent=2, default=str))

    # 3) 可选：delete（清理）
    if hits:
        adapter.delete(hits[0]["id"])
        print("Deleted passage:", hits[0]["id"])

if __name__ == "__main__":
    main()
