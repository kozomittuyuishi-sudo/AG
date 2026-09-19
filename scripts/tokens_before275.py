"""Show tokens from lines 260-275 to find unclosed string."""
import tokenize, io

src = open('preprocessor_brain.py', 'rb').read()
try:
    for tok in tokenize.tokenize(io.BytesIO(src).readline):
        if 260 <= tok.start[0] <= 276:
            print(f'  line {tok.start[0]:3} col {tok.start[1]:3} type={tok.type:2} ({tokenize.tok_name[tok.type]:8}) string={repr(tok.string[:80])}')
    print('No error in range')
except tokenize.TokenError as e:
    msg, (line, col) = e.args
    print(f'TokenError: {msg} at line {line}, col {col}')
