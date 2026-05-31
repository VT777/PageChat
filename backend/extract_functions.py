import marshal
import dis
import types

with open(r'D:\projects\page_chat\backend\pageindex\__pycache__\utils.cpython-314.pyc', 'rb') as f:
    f.read(16)  # Skip header
    code = marshal.load(f)

# Extract all code objects (functions)
functions = {}
for const in code.co_consts:
    if isinstance(const, types.CodeType):
        func_name = const.co_name
        if not func_name.startswith('<'):
            functions[func_name] = const

# Print detailed info for key functions
key_functions = ['ChatGPT_API', 'ChatGPT_API_async', 'count_tokens', 'get_llm_config', 
                 'extract_text_from_pdf', 'get_pdf_title', 'get_text_of_pages',
                 'structure_to_list', 'get_nodes', 'get_leaf_nodes']

for func_name in key_functions:
    if func_name in functions:
        func_code = functions[func_name]
        print(f"\n=== {func_name} ===")
        print(f"  Arguments: {func_code.co_varnames[:func_code.co_argcount]}")
        print(f"  Local variables: {func_code.co_varnames}")
        print(f"  Constants: {[c for c in func_code.co_consts if not isinstance(c, types.CodeType)][:10]}")
        print(f"  Source file: {func_code.co_filename}")
        print(f"  First line: {func_code.co_firstlineno}")
