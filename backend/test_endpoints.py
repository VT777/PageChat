import urllib.request
import urllib.error
import json

# Test with different endpoints
endpoints = [
    ('GET', 'http://localhost:8000/api/documents?page=1&page_size=20', None),
    ('GET', 'http://localhost:8000/api/folders', None),
    ('GET', 'http://localhost:8000/api/chat/conversations', None),
]

for method, url, data in endpoints:
    try:
        req = urllib.request.Request(url, method=method)
        if data:
            req.data = json.dumps(data).encode('utf-8')
            req.add_header('Content-Type', 'application/json')
        response = urllib.request.urlopen(req)
        print(f'{method} {url}: {response.status} OK')
    except urllib.error.HTTPError as e:
        print(f'{method} {url}: {e.code} {e.reason}')
    except Exception as e:
        print(f'{method} {url}: ERROR - {type(e).__name__}')
