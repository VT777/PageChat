import urllib.request
import json

# Test login API
url = 'http://localhost:8000/api/auth/login'
data = json.dumps({
    'email': 'test@example.com',
    'password': 'test123456'
}).encode('utf-8')

try:
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': 'application/json'
    }, method='POST')
    response = urllib.request.urlopen(req)
    print('Login:', response.status, response.read().decode()[:200])
except urllib.error.HTTPError as e:
    print(f'Login Error: {e.code} {e.reason}')
    print('Body:', e.read().decode()[:500])
except Exception as e:
    print(f'Login Error: {type(e).__name__}: {e}')
