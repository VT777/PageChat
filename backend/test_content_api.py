import urllib.request
import json

# Test content API with a document ID
doc_id = '47258f2a'  # From the logs
url = f'http://localhost:8000/api/documents/{doc_id}/content'

try:
    req = urllib.request.Request(url, method='GET')
    # Add a fake token (it will fail auth, but we can see if the route exists)
    req.add_header('Authorization', 'Bearer test-token')
    response = urllib.request.urlopen(req)
    print(f'{url}: {response.status} OK')
    print('Response:', response.read().decode()[:200])
except urllib.error.HTTPError as e:
    print(f'{url}: {e.code} {e.reason}')
    print('Body:', e.read().decode()[:500])
except Exception as e:
    print(f'{url}: ERROR - {type(e).__name__}: {e}')
