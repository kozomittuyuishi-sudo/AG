"""Strip the plain-text file header from preprocessor_brain.py and leave only the Python module."""
import shutil
from pathlib import Path

src = Path('preprocessor_brain.py')
data = src.read_bytes()
text = data.decode('utf-8', errors='replace')
lines = text.split('\n')

print(f"Total lines: {len(lines)}")

# Find the line where the Python triple-quoted module docstring starts
start_line = None
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == '"""':
        start_line = i
        print(f"Module docstring starts at line {i+1}")
        print(f"Context: lines {i}: {repr(lines[i])}, {i+1}: {repr(lines[i+1][:80])}, {i+2}: {repr(lines[i+2][:80])}")
        break

if start_line is None:
    print("ERROR: Could not find Python module start")
    exit(1)

# Show what's just before the start line
print(f"\nLines just before start ({start_line-2} to {start_line}):")
for j in range(max(0, start_line-3), start_line+3):
    print(f"  {j+1}: {repr(lines[j][:100])}")

# Write the fixed file
python_content = '\n'.join(lines[start_line:])
backup_path = Path('preprocessor_brain.py.header_backup')
if not backup_path.exists():
    backup_path.write_bytes(data)
    print(f"\nBacked up original to {backup_path}")

src.write_text(python_content, encoding='utf-8')
print(f"Fixed: removed {start_line} lines of plain-text header")
print(f"New file: {src.stat().st_size} bytes")

# Verify it parses
import ast
try:
    ast.parse(python_content)
    print("preprocessor_brain.py: syntax OK after fix")
except SyntaxError as e:
    print(f"SYNTAX ERROR after fix: {e}")
