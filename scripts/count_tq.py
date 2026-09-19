"""Count triple-quotes in preprocessor_brain.py to find unmatched ones."""
lines = open('preprocessor_brain.py', 'rb').read().split(b'\n')
in_triple = False
triple_char = None
open_line = None

print("Triple-quote events:")
for i, line in enumerate(lines):
    text = line.decode('utf-8', errors='replace')
    j = 0
    while j < len(text):
        if not in_triple:
            if text[j:j+3] in ('"""', "'''"):
                tc = text[j:j+3]
                in_triple = True
                triple_char = tc
                open_line = i + 1
                # Don't print all of them, just problematic ones
                j += 3
            else:
                # Also check for starting a single/double-quoted string with \
                j += 1
        else:
            if text[j:j+3] == triple_char:
                in_triple = False
                triple_char = None
                if i + 1 >= 270 and i + 1 <= 285:
                    print(f"  CLOSED at line {i+1} (opened at {open_line})")
                open_line = None
                j += 3
            else:
                j += 1

    if i + 1 == 281 and in_triple:
        print(f"  STILL OPEN at line 281: opened at {open_line}, triple_char={triple_char!r}")
        break

print(f"\nFinal state: in_triple={in_triple}, open_at={open_line}")
