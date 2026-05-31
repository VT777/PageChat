import urllib.request
import urllib.error
import json

# Test with a real user
url = 'http://localhost:8000/api/auth/login'
data = json.dumps({
    'email': 'admin@example.com',
    'password': 'Admin123!'
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
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}')

# Also test health
print("\n--- Health Check ---")
try:
    response = urllib.request.urlopen('http://localhost:8000/health')
    print('Health:', response.status, response.read().decode())
except Exception as e:
    print(f'Health Error: {type(e).__name__}: {e}')
