with open(r'D:\projects\page_chat\backend\pageindex\page_index.py', 'rb') as f:
    content = f.read()
    null_count = content.count(b'\x00')
    print(f'Null bytes: {null_count}')
    if null_count > 0:
        first_null = content.find(b'\x00')
        print(f'First null at position: {first_null}')
        print(f'Context around first null: {content[max(0,first_null-20):first_null+20]}')
