import urllib.request
import urllib.error
import json

# Test login API with detailed error capture
url = 'http://localhost:8000/api/auth/login'
data = json.dumps({
    'email': 'test@example.com',
    'password': 'test123456'
}).encode('utf-8')

req = urllib.request.Request(url, data=data, headers={
    'Content-Type': 'application/json'
}, method='POST')

try:
    response = urllib.request.urlopen(req)
    print('Login Success:', response.status)
    print('Response:', response.read().decode())
except urllib.error.HTTPError as e:
    print(f'HTTP Error: {e.code} {e.reason}')
    body = e.read().decode()
    print(f'Body: {body}')
    
    # Try to get more details
    print(f'\nHeaders: {dict(e.headers)}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}')
