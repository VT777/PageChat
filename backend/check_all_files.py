import os

def check_files(root_dir, extensions):
    corrupted = []
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                path = os.path.join(root, file)
                try:
                    with open(path, 'rb') as f:
                        content = f.read(1024)  # Check first 1KB
                        null_count = content.count(b'\x00')
                        if null_count > 100:  # More than 100 null bytes in first 1KB means corrupted
                            corrupted.append((path, null_count))
                except Exception as e:
                    print(f"Error reading {path}: {e}")
    return corrupted

# Check frontend source files
frontend_src = r'D:\projects\page_chat\frontend\src'
corrupted_vue = check_files(frontend_src, ['.vue', '.ts', '.js'])

print("Corrupted frontend files:")
for path, nulls in corrupted_vue:
    print(f"  {path}: {nulls} null bytes")

# Check backend source files
backend_src = r'D:\projects\page_chat\backend\app'
corrupted_py = check_files(backend_src, ['.py'])

print("\nCorrupted backend files:")
for path, nulls in corrupted_py:
    print(f"  {path}: {nulls} null bytes")

if not corrupted_vue and not corrupted_py:
    print("No corrupted files found!")
