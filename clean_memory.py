"""
clean_memory.py
===============
One-time utility to strip ANSI escape sequences from all string values
stored in memory.json.

Run once:
    .venv\\Scripts\\python.exe clean_memory.py

What it does:
    - Reads memory.json
    - Walks every category and every value
    - Strips ANSI escape sequences from string values only
    - Leaves keys, structure, categories, and non-string values untouched
    - Writes the cleaned data back to memory.json
    - Prints a summary of every entry that was changed

What it does NOT do:
    - Does not delete any keys or categories
    - Does not alter semantic content
    - Does not regenerate or rewrite memory from scratch
    - Does not touch tasks.json or any other file
"""

import json
import os
import re

MEMORY_FILE = "memory.json"

_ANSI_ESCAPE = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


def clean_memory():
    if not os.path.exists(MEMORY_FILE):
        print(f"ERROR: {MEMORY_FILE} not found. Nothing to clean.")
        return

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        memory = json.load(f)

    changes = 0

    for category, contents in memory.items():
        if not isinstance(contents, dict):
            continue
        for key, value in contents.items():
            if isinstance(value, str):
                cleaned = _strip_ansi(value)
                if cleaned != value:
                    print(f"  CLEANED  [{category}] {key!r}")
                    print(f"    before: {value!r}")
                    print(f"    after:  {cleaned!r}")
                    contents[key] = cleaned
                    changes += 1

    if changes == 0:
        print("memory.json is already clean. No changes needed.")
        return

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=4)

    print(f"\nDone. {changes} entr{'y' if changes == 1 else 'ies'} cleaned in {MEMORY_FILE}.")


if __name__ == "__main__":
    clean_memory()
