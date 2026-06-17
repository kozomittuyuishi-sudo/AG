from openai import OpenAI
from dotenv import load_dotenv
from local_brain import ask_local_brain
import time
import os
import json

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

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    timeout=30,
)


def load_brain_mode():
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


def save_brain_mode(mode):
    with open(BRAIN_CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump({"brain_mode": mode}, file, indent=4)


def set_brain_mode(mode):
    if mode not in ["local", "cloud", "auto"]:
        return "AG: Invalid brain mode. Use local, cloud, or auto."

    save_brain_mode(mode)

    if mode == "local":
        return "AG: Brain mode changed to LOCAL. Internet dependence reduced. Civilization improves slightly."

    if mode == "cloud":
        return "AG: Brain mode changed to CLOUD. Maximum reasoning. Maximum dependence. Classic bargain."

    return "AG: Brain mode changed to AUTO. Local first, cloud fallback. Sensible, annoyingly rare."


def get_brain_status():
    mode = load_brain_mode()
    return f"AG: Current brain mode: {mode.upper()}."


def ask_cloud_brain(message):
    response = client.chat.completions.create(
        model="nex-agi/nex-n2-pro:free",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ],
    )

    return response.choices[0].message.content


def ask_local(message):
    local_prompt = f"""
{SYSTEM_PROMPT}

User message:
{message}
"""
    return ask_local_brain(local_prompt)


def ask_brain(message):
    start = time.time()
    mode = load_brain_mode()

    if mode == "local":
        try:
            reply = ask_local(message)
            print(f"[AG DEBUG] Local Brain Response Time: {time.time()-start:.2f}s")
            return reply
        except Exception as error:
            return f"Local brain failed: {error}"

    if mode == "cloud":
        try:
            reply = ask_cloud_brain(message)
            print(f"[AG DEBUG] Cloud Brain Response Time: {time.time()-start:.2f}s")
            return reply
        except Exception as error:
            return f"Cloud brain failed: {error}"

    # AUTO MODE: local first, cloud fallback
    try:
        reply = ask_local(message)
        print(f"[AG DEBUG] Local Brain Response Time: {time.time()-start:.2f}s")
        return reply

    except Exception as local_error:
        print(f"[AG DEBUG] Local brain failed: {local_error}")
        print("[AG DEBUG] Switching to cloud brain.")

        try:
            reply = ask_cloud_brain(message)
            print(f"[AG DEBUG] Cloud Brain Response Time: {time.time()-start:.2f}s")
            return reply

        except Exception as cloud_error:
            return (
                "Brain connection failed. "
                f"Local error: {local_error}. "
                f"Cloud error: {cloud_error}."
            )


def ask_cloud_direct(message):
    start = time.time()

    try:
        reply = ask_cloud_brain(message)
        print(f"[AG DEBUG] Forced Cloud Brain Response Time: {time.time()-start:.2f}s")
        return reply

    except Exception as error:
        return f"Forced cloud brain failed: {error}"