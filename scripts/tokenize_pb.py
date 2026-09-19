"""Tokenize preprocessor_brain.py up to the error."""
import tokenize, io

src = open('preprocessor_brain.py', 'rb').read()
try:
    tokens = []
    for tok in tokenize.tokenize(io.BytesIO(src).readline):
        tokens.append(tok)
    print(f'Total tokens: {len(tokens)}')
except tokenize.TokenError as e:
    msg, (line, col) = e.args
    print(f'TokenError: {msg} at line {line}, col {col}')
    # Show the last 20 tokens before the error
    print('\nLast tokens before error:')
    for tok in tokens[-20:]:
        print(f'  {tok}')
    
    # Show file content around the error
    lines = src.decode('utf-8', errors='replace').split('\n')
    print(f'\nFile content around line {line}:')
    for i in range(max(0, line-6), min(len(lines), line+3)):
        marker = '>>>' if i+1 == line else '   '
        print(f'{marker} {i+1:4}: {repr(lines[i][:120])}')
