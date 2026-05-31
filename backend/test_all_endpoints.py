import urllib.request
import json

# Test public endpoints
endpoints = [
    'http://localhost:8000/',
    'http://localhost:8000/health',
    'http://localhost:8000/api/auth/me',
    'http://localhost:8000/api/settings/pageindex',
    'http://localhost:8000/api/tools',
    'http://localhost:8000/api/documents?page=1&page_size=20',
    'http://localhost:8000/api/chat/conversations',
]

for url in endpoints:
    try:
        req = urllib.request.Request(url, method='GET')
        response = urllib.request.urlopen(req)
        print(f'{url}: {response.status} OK')
    except urllib.error.HTTPError as e:
        print(f'{url}: {e.code} {e.reason}')
        if e.code >= 500:
            print(f'  Body: {e.read().decode()[:200]}')
    except Exception as e:
        print(f'{url}: ERROR - {type(e).__name__}: {e}')
