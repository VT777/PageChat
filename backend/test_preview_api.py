import urllib.request
import json

# Login first
login_url = 'http://localhost:8000/api/auth/login'
login_data = json.dumps({
    'email': '2991920802@qq.com',
    'password': 'Admin123!'
}).encode('utf-8')

req = urllib.request.Request(login_url, data=login_data, headers={
    'Content-Type': 'application/json'
}, method='POST')

try:
    response = urllib.request.urlopen(req)
    result = json.loads(response.read().decode())
    token = result.get('token')
    print(f'Login success: {result.get("success")}')
    print(f'Response: {result}')
    
    if token:
        # Test preview API with a PDF
        url = 'http://localhost:8000/api/documents/fea96c94/preview'
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {token}'
        })
        try:
            response = urllib.request.urlopen(req)
            data = json.loads(response.read().decode())
            print(f'Preview API: OK')
            print(f'Keys: {list(data.keys())}')
            print(f'TOC nodes: {len(data.get("toc", []))}')
            print(f'Stats: {data.get("stats")}')
            if data.get("toc"):
                print(f'First TOC: {data["toc"][0]["title"]}')
        except urllib.error.HTTPError as e:
            print(f'Preview API Error: {e.code}')
            print(f'Body: {e.read().decode()[:500]}')
except Exception as e:
    print(f'Error: {e}')
