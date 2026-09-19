lines = open('preprocessor_brain.py', 'rb').read().split(b'\n')
for i in range(260, 295):
    if i < len(lines):
        l = lines[i]
        has_tq = b'"""' in l or b"'''" in l
        print(f"{'TQ ' if has_tq else '   '}{i+1:4}: {repr(l[:100])}")
