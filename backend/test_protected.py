import urllib.request
import json

# Login first
login_url = 'http://localhost:8000/api/auth/login'
login_data = json.dumps({
    'email': 'testuser123@example.com',
    'password': 'Test123!@#'
}).encode('utf-8')

req = urllib.request.Request(login_url, data=login_data, headers={
    'Content-Type': 'application/json'
}, method='POST')

response = urllib.request.urlopen(req)
result = json.loads(response.read().decode())
token = result['token']
print('Login Success, token:', token[:50] + '...')

# Test protected endpoints
endpoints = [
    'http://localhost:8000/api/documents?page=1&page_size=20',
    'http://localhost:8000/api/folders',
    'http://localhost:8000/api/chat/conversations',
    'http://localhost:8000/api/auth/me',
]

for url in endpoints:
    try:
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {token}'
        })
        response = urllib.request.urlopen(req)
        print(f'GET {url}: {response.status} OK')
    except urllib.error.HTTPError as e:
        print(f'GET {url}: {e.code} {e.reason}')
    except Exception as e:
        print(f'GET {url}: ERROR - {type(e).__name__}')
