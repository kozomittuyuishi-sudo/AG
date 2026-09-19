"""Show tokens from lines 265-280."""
import tokenize, io

src = open('preprocessor_brain.py', 'rb').read()
try:
    tokens = []
    for tok in tokenize.tokenize(io.BytesIO(src).readline):
        if 265 <= tok.start[0] <= 280:
            tokens.append(tok)
    print(f'Tokens in lines 265-280:')
    for tok in tokens:
        print(f'  line {tok.start[0]:3} col {tok.start[1]:3} type={tok.type:2} ({tokenize.tok_name[tok.type]:8}) string={repr(tok.string[:60])}')
except tokenize.TokenError as e:
    msg, (line, col) = e.args
    print(f'TokenError: {msg} at line {line}, col {col}')
    # Show what we got up to the error
    print(f'\nTokens collected before error ({len(tokens)}):')
    for tok in tokens:
        print(f'  line {tok.start[0]:3} col {tok.start[1]:3} type={tok.type:2} ({tokenize.tok_name[tok.type]:8}) string={repr(tok.string[:60])}')
