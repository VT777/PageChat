import marshal
import dis
import types

with open(r'D:\projects\page_chat\backend\pageindex\__pycache__\utils.cpython-314.pyc', 'rb') as f:
    f.read(16)  # Skip header
    code = marshal.load(f)

# List all functions and classes
print("Functions and classes in utils.py:")
for name in code.co_names:
    print(f"  {name}")

print(f"\nConstants: {code.co_consts[:20]}")
print(f"\nLocal variables: {code.co_varnames[:20]}")
