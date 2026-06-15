import subprocess
from brain import ask_brain
from dotenv import load_dotenv
import os

load_dotenv()

import json
import os

MEMORY_FILE = "memory.json"


def load_memory():
    """Load long-term memory from memory.json and ensure category structure exists."""
    default_memory = {
        "general": {},
        "projects": {},
        "vehicles": {},
        "characters": {},
        "notes": {},
        "tasks": {}
    }

    if not os.path.exists(MEMORY_FILE):
        save_memory(default_memory)
        return default_memory

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            memory = json.load(file)

        # If old flat memory exists, move it into general
        if not any(category in memory for category in default_memory):
            old_memory = memory
            memory = default_memory
            memory["general"] = old_memory
            save_memory(memory)
            return memory

        # Ensure all categories exist
        for category in default_memory:
            if category not in memory:
                memory[category] = {}

        save_memory(memory)
        return memory

    except json.JSONDecodeError:
        print("AG: Memory file is damaged or empty. Starting with structured blank memory.")
        save_memory(default_memory)
        return default_memory
    
def save_memory(memory):
    """Save long-term memory to memory.json."""
    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=4)


def startup():
    print("AG: Good evening.")
    print("AG: Systems operational.")
    print("AG: Memory loaded.")
    print("AG: Ready.")


def remember_fact(user_input, memory):
    """
    Handles commands like:
    remember parker is the agros sports sedan
    remember i am building AG
    Stores default facts in general memory.
    """

    fact = user_input.replace("remember ", "", 1).strip().lower()

    if " is " in fact:
        key, value = fact.split(" is ", 1)
    elif " am " in fact:
        key, value = fact.split(" am ", 1)
    else:
        return "AG: Memory format unclear. Use: remember X is Y or remember I am Y"

    key = key.strip()
    value = value.strip()

    if key in ["i", "i am", "me"]:
        key = "me"

    if not key or not value:
        return "AG: Memory format incomplete. A heroic failure of sentence structure."

    memory["general"][key] = value
    save_memory(memory)

    if key == "me":
        return f"AG: Memory stored in general. You are {value}."

    return f"AG: Memory stored in general. {key.capitalize()} is {value}."
  

def recall_fact(user_input, memory):
    """
    Handles questions like:
    what is parker
    who is parker
    what am i
    who am i
    Searches all memory categories.
    """

    cleaned_input = user_input.strip().lower().replace("?", "")

    if cleaned_input in ["what am i", "who am i", "what is me", "who is me"]:
        key = "me"
    elif cleaned_input.startswith("what is "):
        key = cleaned_input.replace("what is ", "", 1).strip()
    elif cleaned_input.startswith("who is "):
        key = cleaned_input.replace("who is ", "", 1).strip()
    else:
        return "AG: Recall format unclear. Even my patience has architecture."

    for category, contents in memory.items():
        if isinstance(contents, dict) and key in contents:
            if key == "me":
                return f"AG: You are {contents[key]}. Stored in {category}."

            return f"AG: {key.capitalize()} is {contents[key]}. Stored in {category}."

    return f"AG: I do not have memory of '{key}'. Yet."
def show_memory(memory):
    """Display all stored memory categories and contents."""

    response = "AG: Current stored memory:\n"

    for category, contents in memory.items():
        response += f"\n[{category.upper()}]\n"

        if not contents:
            response += "  Empty. A tragic absence of civilization.\n"
        else:
            for key, value in contents.items():
                response += f"  {key}: {value}\n"

    return response


def open_memory_file():
    """Open File Explorer and select memory.json."""

    if os.path.exists(MEMORY_FILE):
        file_path = os.path.abspath(MEMORY_FILE)
        subprocess.run(["explorer", "/select,", file_path])
        return "AG: Opening File Explorer and selecting memory.json."

    return "AG: Memory file not found. Concerning, considering memory was the assignment."
def detect_intent(user_input):
    text = user_input.strip().lower().replace("?", "")

    if text in ["exit", "quit", "shutdown", "bye"]:
        return "shutdown"

    if text.startswith("remember "):
        return "remember"

    if (
        text.startswith("what is ")
        or text.startswith("who is ")
        or text in ["what am i", "who am i"]
    ):
        return "recall"

    if text in ["hello", "hi", "hey"]:
        return "greeting"
    if text in ["show memory", "list memory", "list memories"]:
        return "show_memory"

    if text in ["open memory file", "open memory", "show memory file"]:
        return "open_memory_file"

    return "unknown"


def process_input(user_input, memory):
    intent = detect_intent(user_input)

    if intent == "shutdown":
        return "shutdown"

    if intent == "remember":
        return remember_fact(user_input, memory)

    if intent == "recall":
        return recall_fact(user_input, memory)

    if intent == "greeting":
        return "AG: Hello. Systems remain functional, despite the evidence."
    if intent == "show_memory":
        return show_memory(memory)

    if intent == "open_memory_file":
        return open_memory_file()

    # Fallback to brain for unknown intents
    return "AG: " + ask_brain(user_input)

def main():
    memory = load_memory()
    startup()

    while True:
        user_input = input("You: ")

        response = process_input(user_input, memory)

        if response == "shutdown":
            print("AG: Shutting down.")
            print("AG: Memory preserved.")
            break

        print(response)


if __name__ == "__main__":
    main()