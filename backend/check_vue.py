import os

# Check TableViewer.vue
with open(r'D:\projects\page_chat\frontend\src\components\preview\TableViewer.vue', 'rb') as f:
    content = f.read()
    null_count = content.count(b'\x00')
    print(f'TableViewer.vue: {len(content)} bytes, null bytes: {null_count}')
    if null_count > 0:
        print(f'  First null at: {content.find(b"\x00")}')

# Check for other potentially corrupted .vue files
corrupted = []
for root, dirs, files in os.walk(r'D:\projects\page_chat\frontend\src'):
    for file in files:
        if file.endswith('.vue'):
            path = os.path.join(root, file)
            with open(path, 'rb') as f:
                content = f.read()
                null_count = content.count(b'\x00')
                if null_count > 0:
                    corrupted.append((path, len(content), null_count))

print(f'\nCorrupted .vue files: {len(corrupted)}')
for path, size, nulls in corrupted:
    print(f'  {path}: {size} bytes, {nulls} nulls')
