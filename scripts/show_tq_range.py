lines = open('preprocessor_brain.py', 'rb').read().split(b'\n')
for i in range(238, 283):
    if i < len(lines):
        l = lines[i]
        has_tq = (b'"""' in l or b"'''" in l)
        marker = 'TQ' if has_tq else '  '
        print(f'{marker} {i+1:4}: {repr(l[:100])}')
