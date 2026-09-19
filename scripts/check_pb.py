"""Check preprocessor_brain.py for syntax issues."""
import py_compile
import ast
import sys

path = "preprocessor_brain.py"

# Check raw bytes around the problem
lines = open(path, 'rb').readlines()
print(f"Total lines: {len(lines)}")
print(f"Line 1: {repr(lines[0])}")
print(f"Line 2: {repr(lines[1])}")

# Count triple-quote opens vs closes in the file header
triple_count = 0
for i, raw in enumerate(lines[:80]):
    count = raw.count(b'"""')
    if count:
        triple_count += count
        print(f"L{i+1} ({count} triple-quotes, running total {triple_count}): {repr(raw[:100])}")

# Try py_compile and capture full error
try:
    py_compile.compile(path, doraise=True)
    print("\npy_compile: OK")
except py_compile.PyCompileError as e:
    print(f"\npy_compile error: {e}")

# Try ast.parse
try:
    src = open(path, encoding='utf-8').read()
    ast.parse(src)
    print("ast.parse: OK")
except SyntaxError as e:
    print(f"ast.parse SyntaxError: line {e.lineno}: {e.msg}")
    print(f"  Text: {repr(e.text)}")
