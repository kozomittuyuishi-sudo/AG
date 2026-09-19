src = open('preprocessor_brain.py', 'rb').read()
text = src.decode('utf-8')
lines = text.split('\n')
print('Total lines:', len(lines))
print('Line 61:', repr(lines[60][:120]))
print('Line 62:', repr(lines[61][:120]))
print('Line 63:', repr(lines[62][:120]))

# Check if there's a BOM or unusual bytes
print('First 10 bytes:', repr(src[:10]))

# Try to compile with more detail
try:
    compile(text, 'preprocessor_brain.py', 'exec')
    print('compile OK')
except SyntaxError as e:
    print(f'SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}')
    if e.lineno:
        for i in range(max(0, e.lineno-4), min(len(lines), e.lineno+3)):
            mark = '>>>' if i+1 == e.lineno else '   '
            print(f'{mark} {i+1:4}: {repr(lines[i][:120])}')
except Exception as e:
    print(f'Other error: {type(e).__name__}: {e}')
