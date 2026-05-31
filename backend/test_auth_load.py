import sys
sys.path.insert(0, r'D:\projects\page_chat\backend')

# Test if auth module loads correctly
from app.api.auth import check_login_attempts
print("Auth module loaded successfully")

# Test datetime parsing
from datetime import datetime

test_times = [
    '2026-04-28 08:23:39',
    '2026-04-28T08:23:39',
    '2026-04-28T08:23:39Z',
    '2026-04-28T08:23:39+00:00',
]

for t in test_times:
    try:
        dt = datetime.fromisoformat(t.replace('Z', '+00:00').replace('+00:00', ''))
        print(f"OK: '{t}' -> {dt}")
    except Exception as e:
        print(f"FAIL: '{t}' -> {e}")

# Test with strptime
try:
    dt = datetime.strptime('2026-04-28 08:23:39', '%Y-%m-%d %H:%M:%S')
    print(f"OK strptime: {dt}")
except Exception as e:
    print(f"FAIL strptime: {e}")
