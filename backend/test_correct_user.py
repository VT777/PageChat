import urllib.request
import json

# Login with the correct user
login_url = 'http://localhost:8000/api/auth/login'
login_data = json.dumps({
    'email': '2991920802@qq.com',
    'password': 'Admin123!'
}).encode('utf-8')

try:
    req = urllib.request.Request(login_url, data=login_data, headers={
        'Content-Type': 'application/json'
    }, method='POST')
    response = urllib.request.urlopen(req)
    result = json.loads(response.read().decode())
    print('Login success:', result.get('success'))
    if result.get('token'):
        token = result['token']
        
        # Test documents API
        url = 'http://localhost:8000/api/documents?page=1&page_size=20&include_subfolders=true'
        req = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + token
        })
        response = urllib.request.urlopen(req)
        data = json.loads(response.read().decode())
        print('Documents count:', len(data.get('items', [])))
        print('Total:', data.get('total', 0))
except Exception as e:
    print('Error:', e)
