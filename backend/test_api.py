import urllib.request
import json

# Test documents API
try:
    response = urllib.request.urlopen('http://localhost:8000/api/documents?page=1&page_size=20')
    data = json.loads(response.read().decode())
    print('Documents API:', response.status, '-', len(data.get('items', [])), 'items')
except Exception as e:
    print('Documents API Error:', e)

# Test conversations API  
try:
    response = urllib.request.urlopen('http://localhost:8000/api/chat/conversations')
    data = json.loads(response.read().decode())
    print('Conversations API:', response.status, '-', len(data), 'conversations')
except Exception as e:
    print('Conversations API Error:', e)

# Test auth API
try:
    response = urllib.request.urlopen('http://localhost:8000/api/auth/me')
    print('Auth API:', response.status)
except Exception as e:
    print('Auth API Error:', e)

# Test folders API
try:
    response = urllib.request.urlopen('http://localhost:8000/api/folders')
    data = json.loads(response.read().decode())
    print('Folders API:', response.status, '-', data.get('total', 0), 'folders')
except Exception as e:
    print('Folders API Error:', e)
