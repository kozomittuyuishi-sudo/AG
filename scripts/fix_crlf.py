"""Convert CRLF to LF in preprocessor_brain.py and re-verify."""
import tokenize, io, ast

# Read as binary, replace CRLF with LF
data = open('preprocessor_brain.py', 'rb').read()
print('Original size:', len(data))
print('CRLF count:', data.count(b'\r\n'))
print('Lone CR count:', data.count(b'\r') - data.count(b'\r\n'))

data_lf = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
print('LF-only size:', len(data_lf))

# Try tokenizing LF version
try:
    list(tokenize.tokenize(io.BytesIO(data_lf).readline))
    print('tokenize LF: OK')
except tokenize.TokenError as e:
    print(f'tokenize LF error: {e}')

# Try parsing LF version
try:
    ast.parse(data_lf.decode('utf-8'))
    print('ast.parse LF: OK')
except SyntaxError as e:
    print(f'SyntaxError LF: line={e.lineno} msg={e.msg}')
    lines = data_lf.decode('utf-8').split('\n')
    for i in range(max(0, e.lineno-4), min(len(lines), e.lineno+2)):
        print(f'  {i+1}: {repr(lines[i][:120])}')

# Write the fixed version
open('preprocessor_brain.py', 'wb').write(data_lf)
print('Written LF version to preprocessor_brain.py')
