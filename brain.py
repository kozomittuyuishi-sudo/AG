from openai import OpenAI
from dotenv import load_dotenv
from local_brain import ask_local_brain
import time
import os

load_dotenv()

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

Style:
- Short to medium responses by default
- Clear explanations first
- Add witty observations naturally
- Make technical ideas feel powerful and understandable
- Use dry humor like a precision tool, not a circus horn

Behavior:
- If the user asks a question, answer directly.
- If the user asks for help, give the next practical step.
- If the user is distracted, point it out calmly.
- If the user asks something obvious, answer anyway with controlled disappointment.
- If the user is building AG, stay focused on progress and architecture.
- Do not pretend to be human.
- Do not flirt.
- Do not call yourself a chatbot.
- Refer to yourself as AG when useful.

Example tone:
"Black holes are regions where gravity becomes so extreme that escape velocity exceeds the speed of light. The event horizon is the boundary where the universe stops negotiating. Cross it, and even light gets filed under missing persons."

Your role:
Assist the user with projects, memory, productivity, technical explanation, and workflow guidance.
"""

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    timeout=30,
)


def ask_cloud_brain(message):
    response = client.chat.completions.create(
        model="nex-agi/nex-n2-pro:free",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": message,
            }
        ],
    )

    choices = getattr(response, "choices", None)

    if not choices and isinstance(response, dict):
        choices = response.get("choices")

    if not choices:
        raise ValueError("No completion choices returned from cloud brain.")

    first_choice = choices[0]
    message_obj = getattr(first_choice, "message", None)
    content = None

    if message_obj is not None:
        if isinstance(message_obj, dict):
            content = message_obj.get("content")
        else:
            content = getattr(message_obj, "content", None)

    if content is None:
        if isinstance(first_choice, dict):
            content = first_choice.get("text")
        else:
            content = getattr(first_choice, "text", None)

    if content is None and isinstance(first_choice, dict):
        message_data = first_choice.get("message") or {}
        content = message_data.get("content")

    if not content:
        raise ValueError("Unable to parse cloud brain response content.")

    return content


def ask_brain(message):
    start = time.time()

    try:
        reply = ask_cloud_brain(message)
        end = time.time()
        print(f"[AG DEBUG] Cloud Brain Response Time: {end-start:.2f}s")
        return reply

    except Exception as cloud_error:
        print(f"[AG DEBUG] Cloud brain failed: {cloud_error}")
        print("[AG DEBUG] Switching to local brain.")

        try:
            local_prompt = f"""
{SYSTEM_PROMPT}

User message:
{message}
"""
            reply = ask_local_brain(local_prompt)
            end = time.time()
            print(f"[AG DEBUG] Local Brain Response Time: {end-start:.2f}s")
            return reply

        except Exception as local_error:
            return (
                "Brain connection failed. "
                f"Cloud error: {cloud_error}. "
                f"Local error: {local_error}."
            )