import importlib.util
import types
import inspect

# Load the .pyc file
spec = importlib.util.spec_from_file_location("utils", r'D:\projects\page_chat\backend\pageindex\__pycache__\utils.cpython-314.pyc')
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)

# Print all functions and their signatures
print("Functions in utils module:")
for name in dir(utils):
    obj = getattr(utils, name)
    if callable(obj) and not name.startswith('_'):
        try:
            sig = inspect.signature(obj)
            print(f"  def {name}{sig}:")
        except (ValueError, TypeError):
            print(f"  {name} = {type(obj).__name__}")

# Print key constants
print("\nKey attributes:")
for name in ['CHATGPT_API_KEY', 'CHATGPT_BASE_URL', 'count_tokens', 'get_llm_config', 'ChatGPT_API', 'ChatGPT_API_async']:
    if hasattr(utils, name):
        obj = getattr(utils, name)
        if callable(obj):
            try:
                sig = inspect.signature(obj)
                print(f"  {name}{sig}")
            except:
                print(f"  {name}: callable")
        else:
            print(f"  {name} = {repr(obj)[:100]}")
