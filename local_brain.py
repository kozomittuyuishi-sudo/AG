import subprocess


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

    reply = result.stdout.strip()

    if not reply:
        raise RuntimeError("Local brain returned an empty response.")

    return reply