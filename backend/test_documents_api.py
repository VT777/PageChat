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
print('Login Success')

# Test documents API with different parameters
endpoints = [
    'http://localhost:8000/api/documents?page=1&page_size=20',
    'http://localhost:8000/api/documents?page=1&page_size=20&include_subfolders=true',
    'http://localhost:8000/api/documents?page=1&page_size=20&include_subfolders=false',
]

for url in endpoints:
    try:
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {token}'
        })
        response = urllib.request.urlopen(req)
        data = json.loads(response.read().decode())
        print(f'{url.split("?")[1]}: {len(data.get("items", []))} items, total={data.get("total", 0)}')
    except Exception as e:
        print(f'{url.split("?")[1]}: ERROR - {e}')
