import urllib.request
import urllib.error
import json
import traceback

# Test login API with detailed error capture
url = 'http://localhost:8000/api/auth/login'
data = json.dumps({
    'email': 'testuser123@example.com',
    'password': 'Test123!@#'
}).encode('utf-8')

req = urllib.request.Request(url, data=data, headers={
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}, method='POST')

try:
    response = urllib.request.urlopen(req)
    print('Login Success:', response.status)
    print('Response:', response.read().decode())
except urllib.error.HTTPError as e:
    print(f'HTTP Error: {e.code} {e.reason}')
    print(f'Headers: {dict(e.headers)}')
    body = e.read().decode()
    print(f'Body: {body}')
    print(f'Body length: {len(body)}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}')
    traceback.print_exc()

# Also test register to see if it still works
print("\n--- Register Test ---")
url2 = 'http://localhost:8000/api/auth/register'
data2 = json.dumps({
    'username': 'testuser456',
    'email': 'testuser456@example.com',
    'password': 'Test123!@#'
}).encode('utf-8')

req2 = urllib.request.Request(url2, data=data2, headers={
    'Content-Type': 'application/json'
}, method='POST')

try:
    response = urllib.request.urlopen(req2)
    print('Register Success:', response.status)
    print('Response:', response.read().decode()[:200])
except urllib.error.HTTPError as e:
    print(f'Register Error: {e.code} {e.reason}')
    print('Body:', e.read().decode()[:200])
except Exception as e:
    print(f'Register Error: {type(e).__name__}: {e}')
