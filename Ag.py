from executive import interpret_storage_decision, interpret_category_decision
import json
import os
import subprocess
from datetime import datetime

import dotenv

from brain import (
    ask_brain,
    ask_cloud_direct,
    set_brain_mode,
    get_brain_status
)

dotenv.load_dotenv()

MEMORY_FILE = "memory.json"
PROJECT_FILE = "project_context.json"
TASK_FILE = "tasks.json"


def load_memory():
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

        if not any(category in memory for category in default_memory):
            old_memory = memory
            memory = default_memory
            memory["general"] = old_memory
            save_memory(memory)
            return memory

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
    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=4)


def load_project_context():
    if not os.path.exists(PROJECT_FILE):
        return None

    try:
        with open(PROJECT_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return None


def load_tasks():
    default_tasks = {
        "active": [],
        "completed": []
    }

    if not os.path.exists(TASK_FILE):
        save_tasks(default_tasks)
        return default_tasks

    try:
        with open(TASK_FILE, "r", encoding="utf-8") as file:
            tasks = json.load(file)

        if "active" not in tasks:
            tasks["active"] = []

        if "completed" not in tasks:
            tasks["completed"] = []

        save_tasks(tasks)
        return tasks

    except json.JSONDecodeError:
        save_tasks(default_tasks)
        return default_tasks


def save_tasks(tasks):
    with open(TASK_FILE, "w", encoding="utf-8") as file:
        json.dump(tasks, file, indent=4)


def startup():
    current_hour = datetime.now().hour

    if 5 <= current_hour < 12:
        greeting = "Good morning."
    elif 12 <= current_hour < 17:
        greeting = "Good afternoon."
    elif 17 <= current_hour < 22:
        greeting = "Good evening."
    else:
        greeting = "You're awake at an unreasonable hour."

    print(f"AG: {greeting}")
    print("AG: Systems operational.")
    print("AG: Memory loaded.")
    print("AG: Project context available.")
    print("AG: Tasks loaded.")
    print("AG: Ready.")


def remember_fact(user_input, memory):
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
    cleaned_input = user_input.strip().lower().replace("?", "")

    phrase_starters = [
        "what is ",
        "who is ",
        "do you know about ",
        "have i told you about ",
        "what do you remember about ",
        "search memory for ",
        "find memory for ",
        "find in memory ",
        "search and find memory for ",
        "search and find ",
        "find memory about ",
        "search for ",
        "find "
    ]

    if cleaned_input in ["what am i", "who am i", "what is me", "who is me"]:
        key = "me"
    else:
        key = None

        for starter in phrase_starters:
            if cleaned_input.startswith(starter):
                key = cleaned_input.replace(starter, "", 1).strip()
                break

        if not key:
            return "AG: Recall format unclear. Even my patience has architecture."

    for category, contents in memory.items():
        if isinstance(contents, dict) and key in contents:
            if key == "me":
                return f"AG: You are {contents[key]}. Stored in {category}."

            return f"AG: {key.capitalize()} is {contents[key]}. Stored in {category}."

    return f"AG: I do not have memory of '{key}'. Yet."


def show_memory(memory):
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
    if os.path.exists(MEMORY_FILE):
        file_path = os.path.abspath(MEMORY_FILE)
        subprocess.run(["explorer", "/select,", file_path])
        return "AG: Opening File Explorer and selecting memory.json."

    return "AG: Memory file not found. Concerning, considering memory was the assignment."


def generate_memory_summary(question, answer):
    prompt = f"""
Create a memory entry from this information.

Question:
{question}

Answer:
{answer}

Rules:
- Return ONLY this format:

KEY: <short key>

SUMMARY: <short summary>

Example:

KEY: gravity

SUMMARY: Force that attracts masses toward each other.
"""

    return ask_brain(prompt)


def project_status():
    project = load_project_context()

    if not project:
        return "AG: Project context unavailable."

    completed = project.get("completed_milestones", [])

    return (
        f"AG Project Status\n\n"
        f"Project: {project.get('full_name', 'Unknown')}\n"
        f"Short Name: {project.get('project_name', 'Unknown')}\n"
        f"Version: {project.get('current_version', 'Unknown')}\n"
        f"Phase: {project.get('current_phase', 'Unknown')}\n"
        f"Objective: {project.get('current_objective', 'Unknown')}\n\n"
        f"Completed Milestones: {len(completed)}\n"
        f"Next Milestone: {project.get('next_milestone', 'Unknown')}\n\n"
        f"Rule: {project.get('development_rule', 'No rule set. Dangerous. Very human.')}"
    )


def project_name():
    project = load_project_context()

    if not project:
        return "AG: Project context unavailable."

    return (
        f"AG: You are building "
        f"{project.get('full_name', 'Unknown')} "
        f"({project.get('project_name', 'Unknown')})."
    )


def next_step():
    project = load_project_context()

    if not project:
        return "AG: Project context unavailable."

    return f"AG: Next milestone: {project.get('next_milestone', 'Unknown')}."


def show_completed_milestones():
    project = load_project_context()

    if not project:
        return "AG: Project context unavailable."

    milestones = project.get("completed_milestones", [])

    if not milestones:
        return "AG: No completed milestones recorded. A bold and empty legacy."

    response = "AG: Completed milestones:\n"

    for index, milestone in enumerate(milestones, start=1):
        response += f"{index}. {milestone}\n"

    return response


def add_task(user_input, tasks):
    task = user_input.strip()

    prefixes = [
        "add task",
        "add this to my tasks",
        "add this task",
        "create task",
        "create a task",
        "i need to do",
        "i have to do",
        "i should do",
        "remind me to"
    ]

    for prefix in prefixes:
        if task.lower().startswith(prefix):
            task = task[len(prefix):].strip()
            break

    if not task:
        return "AG: Task cannot be empty. Even chaos needs content."

    tasks["active"].append(task)
    save_tasks(tasks)

    return f"AG: Task added. Active tasks: {len(tasks['active'])}."


def show_tasks(tasks):
    if not tasks["active"]:
        return "AG: No active tasks. Suspiciously peaceful."

    response = "AG: Active tasks:\n"

    for index, task in enumerate(tasks["active"], start=1):
        response += f"{index}. {task}\n"

    return response


def complete_task(user_input, tasks):
    text = user_input.strip().lower()

    prefixes = [
        "complete task",
        "finish task",
        "mark task",
        "mark task number",
        "i completed task",
        "task completed"
    ]

    number_text = text

    for prefix in prefixes:
        if text.startswith(prefix):
            number_text = text.replace(prefix, "", 1).strip()
            break

    number_text = number_text.replace("done", "").strip()

    if not number_text.isdigit():
        return "AG: Specify the task number. Numbers remain useful, despite humanity."

    task_index = int(number_text) - 1

    if task_index < 0 or task_index >= len(tasks["active"]):
        return "AG: Task number invalid. Reality refuses the request."

    task = tasks["active"].pop(task_index)
    tasks["completed"].append(task)
    save_tasks(tasks)

    return f"AG: Task completed: {task}. Progress detected. Rare, but welcome."


def show_completed_tasks(tasks):
    if not tasks["completed"]:
        return "AG: No completed tasks yet. A blank monument to intention."

    response = "AG: Completed tasks:\n"

    for index, task in enumerate(tasks["completed"], start=1):
        response += f"{index}. {task}\n"

    return response

def detect_intent(user_input):
    text = user_input.strip().lower().replace("?", "")

    if text in ["exit", "quit", "shutdown", "bye"]:
        return "shutdown"

    if text.startswith("cloud "):
        return "cloud_brain"

    if text in [
        "switch to local brain",
        "use local brain",
        "local brain",
        "go offline",
        "offline mode",
        "use offline mode",
        "use local ai",
        "work offline",
        "enable local brain"
    ]:
        return "set_brain_local"

    if text in [
        "switch to cloud brain",
        "use cloud brain",
        "cloud brain",
        "go online",
        "online mode",
        "use cloud ai",
        "enable cloud brain",
        "work online"
    ]:
        return "set_brain_cloud"

    if text in [
        "switch to auto brain",
        "use auto brain",
        "auto brain",
        "automatic mode",
        "smart mode",
        "brain auto mode"
    ]:
        return "set_brain_auto"

    if text in [
        "brain status",
        "current brain",
        "what brain are you using",
        "which brain are you using",
        "which brain is active",
        "who is answering",
        "who is responding",
        "what mode are you in",
        "current mode"
    ]:
        return "brain_status"

    if text.startswith("remember "):
        return "remember"

    if any(
        text.startswith(prefix)
        for prefix in [
            "what is ",
            "who is ",
            "do you know about ",
            "have i told you about ",
            "what do you remember about ",
            "search memory for ",
            "find memory for ",
            "find in memory ",
            "search and find memory for ",
            "search and find ",
            "find memory about ",
            "search for ",
            "find "
        ]
    ) or text in ["what am i", "who am i"]:
        return "recall"

    if text in ["hello", "hi", "hey"]:
        return "greeting"

    if text in ["show memory", "list memory", "list memories"]:
        return "show_memory"

    if text in ["open memory file", "open memory", "show memory file"]:
        return "open_memory_file"

    if text in [
        "project status",
        "status",
        "ag status",
        "how is ag doing",
        "where are we",
        "where are we at",
        "show progress",
        "how far have we come",
        "project progress"
    ]:
        return "project_status"

    if text in [
        "what am i building",
        "what project am i building",
        "what are we building",
        "what is ag",
        "what project is this"
    ]:
        return "project_name"

    if text in [
        "current version",
        "what version are we on",
        "version",
        "ag version"
    ]:
        return "current_version"

    if text in [
        "what is next",
        "next milestone",
        "next objective",
        "what should we build next",
        "what's next",
        "our next step",
        "what should we do next",
        "where do we go from here"
    ]:
        return "next_step"

    if text in [
        "completed milestones",
        "show milestones",
        "what is completed",
        "what have we completed",
        "what have we finished",
        "show completed work",
        "show achievements",
        "what progress have we made"
    ]:
        return "completed_milestones"

    if (
        text.startswith("add task ")
        or text.startswith("add this to my tasks ")
        or text.startswith("add this task ")
        or text.startswith("create task ")
        or text.startswith("create a task ")
        or text.startswith("i need to do ")
        or text.startswith("i have to do ")
        or text.startswith("i should do ")
        or text.startswith("remind me to ")
    ):
        return "add_task"

    if text in [
        "show tasks",
        "list tasks",
        "active tasks",
        "what are my tasks",
        "what tasks are pending",
        "what's pending",
        "what is pending",
        "what work is left",
        "what do i need to do today",
        "what should i do today",
        "show my work"
    ]:
        return "show_tasks"

    if (
        text.startswith("complete task ")
        or text.startswith("finish task ")
        or text.startswith("mark task ")
        or text.startswith("mark task number ")
        or text.startswith("i completed task ")
        or text.startswith("task completed ")
    ):
        return "complete_task"

    if text in [
        "show completed tasks",
        "completed tasks",
        "list completed tasks",
        "what have i completed",
        "show finished tasks",
        "finished tasks"
    ]:
        return "show_completed_tasks"

    return "unknown"

def process_input(user_input, memory, tasks, intent):
    if intent == "shutdown":
        return "shutdown"

    if intent == "cloud_brain":
        clean_prompt = user_input.strip()[6:].strip()
        return "AG: " + ask_cloud_direct(clean_prompt)

    if intent == "set_brain_local":
        return set_brain_mode("local")

    if intent == "set_brain_cloud":
        return set_brain_mode("cloud")

    if intent == "set_brain_auto":
        return set_brain_mode("auto")

    if intent == "brain_status":
        return get_brain_status()

    if intent == "remember":
        return remember_fact(user_input, memory)

    if intent == "recall":
        result = recall_fact(user_input, memory)

        if "I do not have memory of" not in result:
            return result

        return "AG: " + ask_brain(user_input)

    if intent == "greeting":
        return "AG: Hello. Systems remain functional, despite the evidence."

    if intent == "show_memory":
        return show_memory(memory)

    if intent == "open_memory_file":
        return open_memory_file()

    if intent == "project_status":
        return project_status()

    if intent == "project_name":
        return project_name()

    if intent == "next_step":
        return next_step()

    if intent == "completed_milestones":
        return show_completed_milestones()

    if intent == "add_task":
        return add_task(user_input, tasks)

    if intent == "show_tasks":
        return show_tasks(tasks)

    if intent == "complete_task":
        return complete_task(user_input, tasks)

    if intent == "show_completed_tasks":
        return show_completed_tasks(tasks)

    if intent == "current_version":
        return current_version()

    return "AG: " + ask_brain(user_input)

def current_version():
    project = load_project_context()

    if not project:
        return "AG: Project context unavailable."

    return f"AG: Current version is {project.get('current_version', 'Unknown')}."

def main():
    memory = load_memory()
    tasks = load_tasks()
    startup()

    last_brain_answer = None
    pending_store = False
    pending_category = False

    while True:
        user_input = input("You: ")
        cleaned_input = user_input.strip().lower()
        if pending_store:
            decision = interpret_storage_decision(user_input, ask_brain)

            if decision == "STORE":
                pending_store = False
                pending_category = True

                print("AG: Where should I store it?")

                for index, category in enumerate(memory.keys(), start=1):
                    print(f"AG: {index}. {category.capitalize()}")

                print("AG: Or name a new division to create one.")
                continue

            if decision == "SKIP":
                pending_store = False
                last_brain_answer = None
                print("AG: Not stored. The cloud shall be bothered again later, apparently.")
                continue

            print("AG: I could not tell whether you wanted that stored. Answer clearly, humanity permitting.")
            continue
        if pending_category:
            category_type, category = interpret_category_decision(user_input, memory, ask_brain)

            if category_type == "NEW":
                memory[category] = {}
                save_memory(memory)
                print(f"AG: Created new memory division '{category}'.")

            elif category_type != "EXISTING":
                print("AG: I could not identify that memory division. Use a number, category name, or ask me to create one.")
                continue

            summary = generate_memory_summary(
                last_brain_answer["question"],
                last_brain_answer["answer"]
            )

            try:
                lines = summary.splitlines()

                key_line = next(
                    line for line in lines
                    if line.upper().startswith("KEY:")
                )

                summary_line = next(
                    line for line in lines
                    if line.upper().startswith("SUMMARY:")
                )

                key = key_line.split(":", 1)[1].strip().lower()
                value = summary_line.split(":", 1)[1].strip()

            except Exception:
                key = last_brain_answer["question"].lower().replace("?", "").strip()
                value = last_brain_answer["answer"]

            memory[category][key] = value
            save_memory(memory)

            print(f"AG: Stored '{key}' under {category}.")

            pending_category = False
            last_brain_answer = None
            continue

        intent = detect_intent(user_input)
        response = process_input(user_input, memory, tasks, intent)

        if response == "shutdown":
            print("AG: Shutting down.")
            print("AG: Memory preserved.")
            break

        print(response)

        if response.startswith("AG: ") and intent in ["unknown", "cloud_brain"]:
            last_brain_answer = {
                "question": user_input,
                "answer": response.replace("AG: ", "", 1)
            }

            pending_store = True
            print("AG: Should I store this for future access?")


if __name__ == "__main__":
    main()