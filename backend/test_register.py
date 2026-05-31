import urllib.request
import urllib.error
import json

# Test register API
url = 'http://localhost:8000/api/auth/register'
data = json.dumps({
    'username': 'testuser123',
    'email': 'testuser123@example.com',
    'password': 'Test123!@#'
}).encode('utf-8')

req = urllib.request.Request(url, data=data, headers={
    'Content-Type': 'application/json'
}, method='POST')

try:
    response = urllib.request.urlopen(req)
    print('Register Success:', response.status)
    print('Response:', response.read().decode())
except urllib.error.HTTPError as e:
    print(f'HTTP Error: {e.code} {e.reason}')
    body = e.read().decode()
    print(f'Body: {body}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}')
