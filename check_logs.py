import sqlite3, json, glob, os

doc_dir = "D:/projects/page_chat/backend/data/documents"
log_dir = "D:/projects/page_chat/backend/logs"

doc_ids = {
    "AI_Agent_2026": "9cf5b5be",
    "第五范式_2025": "90e75e6f",
    "AI眼镜_2025": "d9b2b5ea",
    "技术应用洞察_2025": "097e50d9",
}

print("Processing Log Analysis")
print("=" * 80)

for name, doc_id in doc_ids.items():
    # Find log files
    log_pattern = f"{log_dir}/{doc_id}_*.json"
    log_files = glob.glob(log_pattern)
    
    if not log_files:
        print(f"\n{name}: No log files found")
        continue
    
    # Get the most recent log
    log_file = sorted(log_files)[-1]
    
    with open(log_file, "r", encoding="utf-8") as f:
        log_data = json.load(f)
    
    print(f"\n{name}:")
    print(f"  Log file: {os.path.basename(log_file)}")
    print(f"  Data type: {type(log_data)}")
    
    # Extract key events
    if isinstance(log_data, list):
        events = log_data
    elif isinstance(log_data, dict):
        events = log_data.get("events", [])
    else:
        print(f"  Unknown data format")
        continue
    
    for event in events[:30]:
        if isinstance(event, dict):
            msg = event.get("message", "")
            if any(k in msg for k in ["Route", "Fast failed", "escalating", "FAST_TOC", "Phase 1", "execution_mode", "trying fast"]):
                print(f"  {msg}")
        elif isinstance(event, str):
            if any(k in event for k in ["Route", "Fast failed", "escalating", "FAST_TOC", "Phase 1", "execution_mode", "trying fast"]):
                print(f"  {event}")
