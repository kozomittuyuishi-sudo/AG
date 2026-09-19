import re
import subprocess

# Compiled ANSI escape sequence pattern.
# Matches ESC[ followed by optional parameters and a final command letter.
_ANSI_ESCAPE = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI cursor-control and color escape sequences from text."""
    return _ANSI_ESCAPE.sub("", text)


def ask_local_brain(message) -> str:
    result = subprocess.run(
        ["ollama", "run", "qwen2.5:3b", message],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    reply = _strip_ansi(result.stdout).strip()

    if not reply:
        raise RuntimeError("Local brain returned an empty response.")

    return reply