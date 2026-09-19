"""Diagnose syntax error in preprocessor_brain.py"""
import ast

src = open('preprocessor_brain.py', encoding='utf-8').read()
lines = src.split('\n')
print(f"Total lines: {len(lines)}")
print(f"Line 1: {repr(lines[0])}")
print(f"Line 2: {repr(lines[1])}")
print(f"Line 3: {repr(lines[2])}")

# Show around the error (line 62)
print(f"\nLines around 62:")
for i in range(58, 68):
    if i < len(lines):
        print(f"  {i+1}: {repr(lines[i][:100])}")

try:
    ast.parse(src)
    print("Syntax OK")
except SyntaxError as e:
    print(f"SyntaxError at line {e.lineno}: {e.msg}")
    print(f"Text: {repr(e.text)}")
    
    # Show more context around the error
    if e.lineno:
        start = max(0, e.lineno - 5)
        end = min(len(lines), e.lineno + 5)
        print(f"\nContext (lines {start+1}-{end}):")
        for i in range(start, end):
            marker = ">>>" if i+1 == e.lineno else "   "
            print(f"  {marker} {i+1}: {repr(lines[i][:100])}")
