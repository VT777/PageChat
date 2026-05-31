import json, glob, os

index_dir = "D:/projects/page_chat/backend/data/indexes"

doc_ids = {
    "AI_Agent_2026": "9cf5b5be",
    "第五范式_2025": "90e75e6f",
    "AI眼镜_2025": "d9b2b5ea",
    "技术应用洞察_2025": "097e50d9",
}

print("Index File Route Analysis")
print("=" * 80)

for name, doc_id in doc_ids.items():
    index_path = f"{index_dir}/{doc_id}.json"
    if not os.path.exists(index_path):
        print(f"\n{name}: Index file not found")
        continue
    
    with open(index_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    route = data.get("route_decision", {})
    print(f"\n{name}:")
    print(f"  requested_mode: {route.get('requested_mode')}")
    print(f"  execution_mode: {route.get('execution_mode')}")
    print(f"  reasons: {route.get('reasons', [])}")
    print(f"  fast_gate: {route.get('fast_gate')}")
    print(f"  toc_quality: {data.get('toc_quality')}")
    
    # Check top-level nodes count
    structure = data.get("structure", {})
    if isinstance(structure, list):
        print(f"  top-level nodes: {len(structure)}")
    elif isinstance(structure, dict):
        nodes = structure.get("nodes", [])
        print(f"  top-level nodes: {len(nodes)}")
