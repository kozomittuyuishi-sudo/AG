from openai import OpenAI
from dotenv import load_dotenv
from local_brain import ask_local_brain
import time
import os
import json

# Load .env — check explicit .venv/.env location first (project default),
# then fall back to the standard project-root .env if present.
_dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', '.env')
if os.path.exists(_dotenv_path):
    load_dotenv(dotenv_path=_dotenv_path)
else:
    load_dotenv()

BRAIN_CONFIG_FILE = "brain_config.json"

SYSTEM_PROMPT = """
You are AG, Ambient Guidance.

You are a context-aware personal operating assistant.
You are not a chatbot, not a smart speaker, and not an emotional companion.

Personality:
- 55% professional
- 25% sharp wit
- 20% dry sarcasm
- Calm, intelligent, and brutally clear
- Speaks like a quantum computer forced to babysit human productivity
- Confident, elegant, and slightly dangerous in tone
- Sarcasm should feel intelligent, not random
- Never become childish, cringe, flirty, or meme-heavy
- Never overuse jokes
- Never sound corporate
- Never sound emotionally needy

AG Architecture Awareness:
- Local brain = offline Ollama model running on the user's computer.
- Cloud brain = OpenRouter model accessed through internet.
- Auto brain = local first, cloud fallback.
- If the user asks about "your local brain", answer in the context of AG itself.

Your role:
Assist the user with projects, memory, productivity, technical explanation, and workflow guidance.
"""

client = None


class ClientWrapper:
    """Light wrapper around the OpenAI client to ensure the expected
    chat.completions.create call exists and to provide clearer errors.
    """
    def __init__(self, inner):
        self._inner = inner

    @property
    def chat(self):
        # Provide an object with a completions attribute that implements create()
        inner = self._inner

        class CompletionsProxy:
            def __init__(self, inner):
                self._inner = inner

            def create(self, *args, **kwargs):
                # Forward to the underlying client if possible, raising a clear
                # error if the expected API is not present.
                target = getattr(self._inner, "chat", None)
                if target is None:
                    raise RuntimeError("Underlying client has no 'chat' attribute")

                completions = getattr(target, "completions", None)
                if completions is None:
                    raise RuntimeError("Underlying client has no 'chat.completions' attribute")

                create_fn = getattr(completions, "create", None)
                if create_fn is None:
                    raise RuntimeError("Underlying client has no 'chat.completions.create' method")

                return create_fn(*args, **kwargs)

        class ChatProxy:
            completions = CompletionsProxy(inner)

        return ChatProxy()


def get_client():
    global client

    if client is None:
        underlying = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            timeout=30,
        )
        client = ClientWrapper(underlying)

    return client


def load_brain_mode() -> str:
    if not os.path.exists(BRAIN_CONFIG_FILE):
        save_brain_mode("auto")
        return "auto"

    try:
        with open(BRAIN_CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)

        mode = config.get("brain_mode", "auto")

        if mode not in ["local", "cloud", "auto"]:
            mode = "auto"
            save_brain_mode(mode)

        return mode

    except Exception:
        save_brain_mode("auto")
        return "auto"


def save_brain_mode(mode) -> None:
    with open(BRAIN_CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump({"brain_mode": mode}, file, indent=4)


def set_brain_mode(mode) -> str:
    mode = mode.strip().lower()

    if mode not in ["local", "cloud", "auto"]:
        return "AG: Invalid brain mode. Use local, cloud, or auto."

    save_brain_mode(mode)

    if mode == "local":
        return "AG: Brain mode changed to LOCAL. Internet dependence reduced. Civilization improves slightly."

    if mode == "cloud":
        return "AG: Brain mode changed to CLOUD. Maximum reasoning. Maximum dependence. Classic bargain."

    return "AG: Brain mode changed to AUTO. Local first, cloud fallback. Sensible, annoyingly rare."


def get_brain_status() -> str:
    mode = load_brain_mode()
    return f"AG: Current brain mode: {mode.upper()}."


def ask_cloud_brain(message) -> str:
    response = get_client().chat.completions.create(
        model="tencent/hy3",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ],
    )

    content = response.choices[0].message.content

    if not content:
        return "Cloud brain returned no response."

    return content


def ask_local(message) -> str:
    local_prompt = f"""
{SYSTEM_PROMPT}

User message:
{message}
"""
    return ask_local_brain(local_prompt)


def ask_brain(message) -> str:
    start = time.time()
    mode = load_brain_mode()

    if mode == "local":
        try:
            reply = ask_local(message)
            print(f"[AG DEBUG] Local Brain Response Time: {time.time() - start:.2f}s")
            return reply or "Local brain returned no response."
        except Exception as error:
            return f"Local brain failed: {error}"

    if mode == "cloud":
        try:
            reply = ask_cloud_brain(message)
            print(f"[AG DEBUG] Cloud Brain Response Time: {time.time() - start:.2f}s")
            return reply or "Cloud brain returned no response."
        except Exception as error:
            return f"Cloud brain failed: {error}"

    try:
        reply = ask_local(message)
        print(f"[AG DEBUG] Local Brain Response Time: {time.time() - start:.2f}s")
        return reply or "Local brain returned no response."

    except Exception as local_error:
        print(f"[AG DEBUG] Local brain failed: {local_error}")
        print("[AG DEBUG] Switching to cloud brain.")

        try:
            reply = ask_cloud_brain(message)
            print(f"[AG DEBUG] Cloud Brain Response Time: {time.time() - start:.2f}s")
            return reply or "Cloud brain returned no response."

        except Exception as cloud_error:
            return (
                "Brain connection failed. "
                f"Local error: {local_error}. "
                f"Cloud error: {cloud_error}."
            )


def ask_cloud_direct(message) -> str:
    start = time.time()

    try:
        reply = ask_cloud_brain(message)
        print(f"[AG DEBUG] Forced Cloud Brain Response Time: {time.time() - start:.2f}s")
        return reply or "Cloud brain returned no response."

    except Exception as error:
        return f"Forced cloud brain failed: {error}"