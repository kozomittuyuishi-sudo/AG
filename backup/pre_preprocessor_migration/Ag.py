import os as _os

from typing import Optional

from cognition.executive import (
    interpret_storage_decision,
    interpret_category_decision,
    analyze_context,
    build_execution_plan
)
from memory.working_memory import WorkingMemory, resolve_followup
from conversation.conversation_manager import analyze_action_pattern
from diagnostics.analytics_logger import log_event

# --- Runtime Integration imports ---
from conversation.conversation_manager import ConversationManager, build_context as cm_build_context
from conversation.core.entity_tracker import EntityTracker
from conversation.cognitive.reference_resolver import ReferenceResolver
from cognition.executive_layer import ExecutiveLayer
from brains.brain_dispatcher import BrainDispatcher
from conversation.response_processor import ResponseProcessor
from brains.cloud_brain import AdaptiveCloudBrain
from runtime.introspection import IntrospectionEngine
from runtime.introspection.snapshot_builder import SnapshotBuilderConfig
from runtime.runtime_adapter import build_registry
from self_info import SelfInfoEngine, is_self_info_query
from directory_reader import DirectorySession
from directory_reader.context_builder import build_context, build_prompt
from directory_control import DirectoryControl, FileNotFoundInWorkspace, NotAFileError
from directory_control.path_security import (
    NoActiveWorkspaceError,
    WorkspaceViolationError,
    WorkspaceNotFoundError,
    DirectoryControlError,
)
from pipeline.fallback_classifier import (
    classify_failure,
    get_fallback_classifier,
    CATEGORY_CAPABILITY_UNAVAILABLE,
    CATEGORY_UNKNOWN_CAPABILITY,
    CATEGORY_INFORMATION_UNAVAILABLE,
    CATEGORY_BRAIN_FAILURE,
    CATEGORY_INVALID_RESPONSE,
    CATEGORY_PROCESSING_FAILURE,
    AGError,
    DIR_NOT_FOUND,
    DIR_NOT_A_FILE,
    DIR_NOT_A_DIRECTORY,
    DIR_SOURCE_MISSING,
    DIR_OUT_OF_WORKSPACE,
)
from pipeline.intent_router import classify as _route_intent, Intent
import json
import os
import subprocess
from datetime import datetime

import dotenv

try:
    from brains.brain import (
        ask_brain,
        ask_cloud_direct,
        ask_local,
        set_brain_mode,
        get_brain_status,
        load_brain_mode
    )
except ImportError:
    from brains.brain import (
        ask_cloud_direct,
        ask_local,
        set_brain_mode,
        get_brain_status,
        load_brain_mode
    )

    def ask_brain(message):
        """Fallback for environments where ask_brain is not exported."""
        return ask_local(message)

# Load .env — check explicit .venv/.env location first (project default),
# then fall back to the standard project-root .env if present.
import os as _os
_dotenv_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '.venv', '.env')
if _os.path.exists(_dotenv_path):
    dotenv.load_dotenv(dotenv_path=_dotenv_path)
else:
    dotenv.load_dotenv()

DEBUG_MODE = False

# Sentinel prefix set by brains/brain.py when a classified fallback is returned.
# safe_response detects it and forwards the clean user message directly.
_BRAIN_FALLBACK_PREFIX = "__BRAIN_FALLBACK__:"

BRAIN_FALLBACK = "I could not generate a response just now."


def safe_response(text) -> str:
    """
    Guarantees a non-empty, clean string suitable for the user.

    - If text carries the classified fallback sentinel from brain.py,
      return the clean user-facing message embedded in it.
    - If text is a non-empty string, return it as-is.
    - Otherwise return the generic fallback.
    """
    if isinstance(text, str):
        stripped = text.strip()
        if stripped.startswith(_BRAIN_FALLBACK_PREFIX):
            # Strip the sentinel prefix and return the clean message
            clean = stripped[len(_BRAIN_FALLBACK_PREFIX):].strip()
            return clean if clean else BRAIN_FALLBACK
        if stripped:
            return stripped
    return BRAIN_FALLBACK


MEMORY_FILE = "configuration/memory.json"
PROJECT_FILE = "configuration/project_context.json"
TASK_FILE = "configuration/tasks.json"


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


def generate_memory_summary(question, answer) -> str:
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

    return safe_response(ask_brain(prompt))


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
    log_event("task_operation", {"operation": "add_task", "task": task})

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
        "mark task number",
        "complete task",
        "finish task",
        "mark task",
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
    log_event("task_operation", {"operation": "complete_task", "task": task})

    return f"AG: Task completed: {task}. Progress detected. Rare, but welcome."


def show_completed_tasks(tasks):
    if not tasks["completed"]:
        return "AG: No completed tasks yet. A blank monument to intention."

    response = "AG: Completed tasks:\n"

    for index, task in enumerate(tasks["completed"], start=1):
        response += f"{index}. {task}\n"

    return response


def current_version():
    project = load_project_context()

    if not project:
        return "AG: Project context unavailable."

    return f"AG: Current version is {project.get('current_version', 'Unknown')}."


def detect_intent(user_input):
    text = user_input.strip().lower().replace("?", "")

    if text in ["exit", "quit", "shutdown", "bye"]:
        return "shutdown"

    if text in [
        "who are you",
        "what are you",
        "what is ag",
        "what can you do",
        "what are your capabilities",
        "what are you capable of",
        "how do you work",
        "how does ag work",
        "what are your limitations",
        "what can't you do",
        "what cant you do",
        "what systems do you have",
        "what modules are loaded",
        "what modules do you have",
        "what version are you",
        "what version is ag",
        "ag version",
        "what brains are available",
        "which brains do you have",
        "what brains do you have",
        "tell me about yourself",
        "describe yourself",
        "what are you made of",
        "what are your components",
        "show me your systems",
        "show your systems",
        "runtime status",
        "system status",
        "what is your architecture",
        "explain your architecture",
        "how are you built",
        "what is your version",
        "what is your name",
        "what is your purpose",
        "how are you structured",
        "what is ambient guidance",
        "what are you missing",
        "what is not implemented",
        "what is incomplete",
    ]:
        # Route established self-info queries directly to the self_info system
        return "self_info"

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

    if text in [
        "show completed tasks",
        "completed tasks",
        "list completed tasks",
        "what have i completed",
        "show finished tasks",
        "finished tasks"
    ]:
        return "show_completed_tasks"

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

    if (
        text.startswith("complete task ")
        or text.startswith("finish task ")
        or text.startswith("mark task ")
        or text.startswith("mark task number ")
        or text.startswith("i completed task ")
        or text.startswith("task completed ")
    ):
        return "complete_task"

    # ---- Directory Reader: detect "read <path>" requests ----
    _dir_read_prefixes = (
        "read ",
        "load directory ",
        "open directory ",
        "index directory ",
        "scan directory ",
        "load folder ",
        "read folder ",
        "open folder ",
    )
    for _prefix in _dir_read_prefixes:
        if text.startswith(_prefix):
            return "read_directory"

    _dir_clear_phrases = frozenset({
        "forget the directory",
        "forget directory",
        "clear directory",
        "clear the directory",
        "stop reading directory",
        "remove directory context",
        "unload directory",
        "forget the folder",
        "clear folder",
    })
    if text in _dir_clear_phrases:
        return "clear_directory"

    # ---- Directory Control: set / switch workspace ----------------------
    _dc_set_prefixes = (
        "work in ",
        "use ",
        "set workspace to ",
        "set workspace ",
        "set directory to ",
        "workspace ",
    )
    for _prefix in _dc_set_prefixes:
        if text.startswith(_prefix):
            # Only capture if the remaining text looks like a path
            remainder = text[len(_prefix):].strip()
            if remainder and (":" in remainder or remainder.startswith("\\") or "/" in remainder or remainder.startswith(".")):
                return "dc_set_directory"

    _dc_switch_prefixes = (
        "switch to ",
        "switch workspace to ",
        "change directory to ",
        "change workspace to ",
        "cd ",
    )
    for _prefix in _dc_switch_prefixes:
        if text.startswith(_prefix):
            remainder = text[len(_prefix):].strip()
            if remainder and (":" in remainder or remainder.startswith("\\") or "/" in remainder or remainder.startswith(".")):
                return "dc_switch_directory"

    _dc_show_phrases = frozenset({
        "show current directory",
        "show active directory",
        "what is the current directory",
        "what is the active directory",
        "current workspace",
        "active workspace",
        "where am i",
        "show workspace",
        "what directory am i in",
        "what folder am i in",
        "show directory",
    })
    if text in _dc_show_phrases:
        return "dc_show_directory"

    _dc_clear_phrases = frozenset({
        "clear workspace",
        "clear active workspace",
        "remove workspace",
        "unset workspace",
        "forget workspace",
        "clear active directory",
        "remove active directory",
    })
    if text in _dc_clear_phrases:
        return "dc_clear_directory"

    # ---- Directory Control: file and folder operations ------------------
    _dc_list_prefixes = (
        "list files",
        "list folders",
        "show files",
        "show folders",
        "what files are here",
        "what folders are here",
        "what is here",
        "show me the files",
        "show me the folders",
    )
    for _prefix in _dc_list_prefixes:
        if text.startswith(_prefix) or text == _prefix:
            return "dc_list_directory"

    for _prefix in ("read file ", "open file "):
        if text.startswith(_prefix):
            return "dc_read_file"

    for _prefix in ("create file ", "create a file ", "make file ", "make a file "):
        if text.startswith(_prefix):
            return "dc_create_file"

    for _prefix in ("write to ", "write this to ", "write into ", "write this into "):
        if text.startswith(_prefix):
            return "dc_write_file"

    for _prefix in ("append to ", "append this to ", "add to ", "add this to "):
        if text.startswith(_prefix):
            return "dc_append_file"

    for _prefix in ("create folder ", "create a folder ", "make folder ", "make a folder ", "create directory ", "mkdir "):
        if text.startswith(_prefix):
            return "dc_create_directory"

    for _prefix in ("move ", "mv "):
        if text.startswith(_prefix) and " to " in text:
            return "dc_move"

    for _prefix in ("copy ", "cp "):
        if text.startswith(_prefix) and " to " in text:
            return "dc_copy"

    for _prefix in ("rename ", "rename file "):
        if text.startswith(_prefix) and " to " in text:
            return "dc_rename"

    # ---- Self-Info fallback: catch remaining self-referential queries
    #      (e.g. "can you build X?", "are you able to do Y?") that weren't
    #      handled by a dedicated intent above. ----
    if is_self_info_query(user_input):
        return "self_info"

    return "unknown"



def process_input(
    user_input,
    memory,
    tasks,
    intent,
    introspection_engine: Optional[IntrospectionEngine] = None,
    conversation_manager=None,
    entity_tracker=None,
    reference_resolver=None,
    executive_layer=None,
    brain_dispatcher=None,
    response_processor=None,
    adaptive_cloud_brain=None,
    self_info_engine=None,
    directory_session=None,
    directory_control=None,
):
    context = analyze_context(user_input, intent)
    plan = build_execution_plan(user_input, intent)

    if DEBUG_MODE:
        print(f"[AG DEBUG] Context: {context}")
        print(f"[AG DEBUG] Plan: {plan}")

    if intent == "shutdown":
        return "shutdown"

    # ---- Intent Router short-circuit: LOCAL_STATE_QUERY answered in-memory ----
    # This runs before all other dispatch so that active-directory queries
    # NEVER reach the Cloud Brain regardless of what detect_intent() decided.
    if intent not in ("shutdown",):
        _ir = _route_intent(user_input)
        if _ir.intent == Intent.LOCAL_STATE_QUERY:
            _dc_for_state = directory_control if directory_control is not None else DirectoryControl()
            return _handle_local_state_query(user_input, _dc_for_state)

    if intent == "self_info":
        return _handle_self_info(user_input, self_info_engine, introspection_engine)

    # ---- Directory Reader intents ----------------------------------------
    if intent in ("read_directory", "clear_directory"):
        _ds = directory_session if directory_session is not None else DirectorySession()
        return _handle_directory_reader(user_input, intent, _ds)

    # ---- Directory Control intents ---------------------------------------
    _dc_intents = frozenset({
        "dc_set_directory", "dc_switch_directory", "dc_show_directory",
        "dc_clear_directory", "dc_list_directory", "dc_read_file",
        "dc_create_file", "dc_write_file", "dc_append_file",
        "dc_create_directory", "dc_move", "dc_copy", "dc_rename",
    })
    if intent in _dc_intents:
        _dc = directory_control if directory_control is not None else DirectoryControl()
        return _handle_directory_control(user_input, intent, _dc)

    # If a directory is active and the intent is unknown, route through it
    if (
        intent == "unknown"
        and directory_session is not None
        and directory_session.is_active
        and _looks_like_directory_query(user_input)
    ):
        return _handle_directory_reader(user_input, "query_directory", directory_session)

    if intent == "introspection":
        if introspection_engine is not None:
            return _handle_introspection(user_input, introspection_engine)
        # Fallback if engine not available
        return "AG: " + safe_response(ask_brain(user_input))

    if intent == "cloud_brain":
        clean_prompt = user_input.strip()[6:].strip()
        # ---- IP3: Route cloud requests through AdaptiveCloudBrain ----
        # prepare() runs token estimation + request validation and logs the
        # attempt.  The actual HTTP call is still ask_cloud_direct() — the
        # AdaptiveCloudBrain never makes HTTP calls itself.
        if adaptive_cloud_brain is not None:
            try:
                adaptive_cloud_brain.prepare(
                    provider="openrouter",
                    model="",
                    prompt=clean_prompt,
                    intent="cloud_brain",
                )
            except Exception:
                pass  # validation failure logged internally — proceed regardless
        raw_reply = ask_cloud_direct(clean_prompt)
        return "AG: " + safe_response(raw_reply)

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

        # Memory miss → route through full pipeline if available
        return _pipeline_response(
            user_input, intent,
            conversation_manager, reference_resolver,
            executive_layer, brain_dispatcher, response_processor,
            entity_tracker=entity_tracker,
        )

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

    # ---- IP2: Unknown intent → full pipeline ----
    return _pipeline_response(
        user_input, intent,
        conversation_manager, reference_resolver,
        executive_layer, brain_dispatcher, response_processor,
        entity_tracker=entity_tracker,
    )


def _pipeline_response(
    user_input: str,
    intent: str,
    conversation_manager,
    reference_resolver,
    executive_layer,
    brain_dispatcher,
    response_processor,
    entity_tracker=None,
) -> str:
    """
    Full subsystem pipeline for unknown/recall intents.

    ConversationManager → ReferenceResolver → ExecutiveLayer →
    BrainDispatcher → ResponseProcessor → output string.

    Falls back to direct ask_brain() if any subsystem is unavailable.
    Never raises.
    """
    brain_input = user_input

    try:
        # Step 1 — ConversationManager: build context + resolve topic-level references
        if conversation_manager is not None:
            ctx = conversation_manager.build_context(user_input)
            resolved_cm = ctx.get("resolved_input", user_input)
            if resolved_cm and resolved_cm != user_input:
                brain_input = resolved_cm
                if DEBUG_MODE:
                    print(f"[AG DEBUG] ConvManager resolved: {brain_input!r}")

        # Step 2 — ReferenceResolver: entity-aware pronoun/NL reference resolution
        # tracker is passed explicitly so the resolver can rank live candidates.
        if reference_resolver is not None and entity_tracker is not None:
            try:
                res_result = reference_resolver.resolve(brain_input, entity_tracker)
                if res_result.was_resolved():
                    brain_input = res_result.resolved_text
                    if DEBUG_MODE:
                        print(
                            f"[AG DEBUG] ReferenceResolver resolved: {brain_input!r} "
                            f"(confidence={res_result.confidence:.2f})"
                        )
            except Exception:
                pass  # resolver unavailable — continue with current brain_input

        # Step 3 — ExecutiveLayer: storage/routing decision (inform logging; no action blocked)
        exec_decision = None
        if executive_layer is not None:
            try:
                exec_decision = executive_layer.process_execution_cycle(brain_input, "")
                if DEBUG_MODE and exec_decision:
                    print(f"[AG DEBUG] ExecutiveDecision: {exec_decision.to_dict()}")
            except Exception:
                pass

        # Step 4 — BrainDispatcher: standardized dispatch
        brain_response = None
        if brain_dispatcher is not None:
            try:
                payload = {
                    "user_prompt": brain_input,
                    "mode": "QUERY",
                    "system_context": {
                        "intent": intent,
                        "executive_decision": exec_decision.to_dict() if exec_decision else {},
                    },
                }
                brain_response = brain_dispatcher.dispatch(payload)
            except Exception:
                pass

        # Step 5 — ResponseProcessor: sanitize + safety check
        if brain_response is not None and response_processor is not None:
            try:
                processed = response_processor.process(brain_response)
                if processed.is_safe and not processed.fallback_triggered:
                    # BrainDispatcher uses mock adapters by default — if the mock
                    # response is detected, fall through to the real brain below.
                    content = processed.sanitized_content
                    if not content.startswith("[Mock Brain"):
                        return "AG: " + content
            except Exception:
                pass

    except Exception:
        pass  # safety net — never crash the main loop

    # Fallback: direct brain call (mock dispatcher result or any error above)
    return "AG: " + safe_response(ask_brain(brain_input))


def _extract_key_value(summary: str, fallback_key: str, fallback_value: str):
    key = None
    value = None

    try:
        lines = summary.splitlines()

        key_line = next((line for line in lines if line.upper().startswith("KEY:")), None)
        summary_line = next((line for line in lines if line.upper().startswith("SUMMARY:")), None)

        if key_line:
            key = key_line.split(":", 1)[1].strip().lower()

        if summary_line:
            value = summary_line.split(":", 1)[1].strip()

    except Exception:
        pass

    if not key:
        key = fallback_key or "unnamed_entry"

    if not value:
        value = fallback_value

    return key, value


def _extract_entities_from_text(text: str, tracker: EntityTracker) -> None:
    """
    Lightweight heuristic entity extractor.

    Scans the text for proper nouns (capitalized words not at sentence start)
    and records them with the EntityTracker as "person" or "concept" type.
    Intentionally minimal — the tracker's value comes from accumulation across
    turns, not single-turn perfect NER.

    :param text:    Raw text to scan (user input or AG response).
    :param tracker: The active EntityTracker for this session.
    """
    import re
    # Find runs of capitalized words (potential named entities / topics)
    candidates = re.findall(r'\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*)\b', text)
    EXCLUDE = frozenset({
        "The", "This", "That", "These", "Those", "There",
        "What", "When", "Where", "Which", "While", "With",
        "You", "Your", "Our", "Their", "They", "Then",
        "Okay", "Sure", "Yes", "No", "Not", "Now",
        "And", "But", "Or", "For", "Nor", "So", "Yet",
        "Good", "Great", "Well", "Here", "Once",
        "AG",
    })
    seen = set()
    for candidate in candidates:
        first_word = candidate.split()[0]
        if first_word in EXCLUDE:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        words = candidate.split()
        entity_type = "person" if len(words) >= 2 else "concept"
        tracker.record_entity(
            name=candidate,
            entity_type=entity_type,
            confidence=0.9,
        )


def _handle_self_info(
    user_input: str,
    self_info_engine,
    introspection_engine: Optional[IntrospectionEngine] = None,
) -> str:
    """
    Handle a self-info query using verified structured data from the Self-Info system.

    The SelfInfoEngine assembles a context_block of verified facts.
    The brain is then asked to format that block as a natural-language
    response — but it is NOT the authoritative source of the facts.

    Falls back gracefully if the self_info_engine is unavailable.

    :param user_input:            The user's self-info question.
    :param self_info_engine:      The live SelfInfoEngine instance.
    :param introspection_engine:  Optional IntrospectionEngine for live snapshot enrichment.
    :returns:                     AG-prefixed response string.
    """
    _fc = get_fallback_classifier()
    try:
        # Build a live snapshot if we have the introspection engine
        snapshot = None
        if introspection_engine is not None:
            try:
                snapshot = introspection_engine.build_snapshot()
            except Exception:
                pass  # snapshot enrichment is optional

        if self_info_engine is None:
            # Engine not available — fall through to introspection or brain
            if introspection_engine is not None:
                return _handle_introspection(user_input, introspection_engine)
            return "AG: " + safe_response(ask_brain(user_input))

        result = self_info_engine.answer(user_input, snapshot=snapshot)

        if not result.is_self_info or not result.context_block:
            # Query wasn't recognized as self-info — use brain directly
            return "AG: " + safe_response(ask_brain(user_input))

        # Check for self-info engine error (unknown capability)
        if result.error:
            log_event("debug", {"source": "self_info", "error": result.error})
            return "AG: " + _fc.get_message(CATEGORY_UNKNOWN_CAPABILITY)

        # Brain formats the verified facts into natural language
        self_info_prompt = (
            "You are answering a question about your own identity, architecture, "
            "capabilities, or limitations.\n"
            "Use ONLY the following verified facts. "
            "Do NOT invent capabilities, systems, or details not listed below.\n\n"
            f"VERIFIED SELF-INFO:\n{result.context_block}\n\n"
            f"User question: {user_input}"
        )

        reply = safe_response(ask_brain(self_info_prompt))
        return "AG: " + reply

    except Exception as exc:
        log_event("error", {"source": "self_info", "error": str(exc)})
        # Graceful fallback — attempt introspection, then bare brain
        if introspection_engine is not None:
            return _handle_introspection(user_input, introspection_engine)
        return "AG: " + safe_response(ask_brain(user_input))


def _looks_like_directory_query(user_input: str) -> bool:
    """
    Heuristic: does this look like a question aimed at the loaded directory?

    When a directory session is active and the intent is unknown, we route to
    the directory handler unless the input is clearly a short command or
    confirmation word.  The directory handler itself gracefully handles inputs
    that turn out to have no relevant content.
    Never raises.
    """
    norm = user_input.strip().lower()

    # Very short inputs (single words / confirmations) are not directory queries
    if len(norm.split()) <= 1:
        return False

    # Explicit confirmation / control words — not directory queries
    _non_queries = frozenset({
        "yes", "no", "y", "n", "ok", "okay", "sure", "nope", "nah",
        "yep", "yeah", "go ahead", "skip", "cancel", "stop",
    })
    if norm in _non_queries:
        return False

    # Anything else with a directory active is treated as a directory query.
    # The handler will return "information not found" if content is missing.
    return True


def _handle_local_state_query(
    user_input: str,
    directory_control: "DirectoryControl",
) -> str:
    """
    Answer a LOCAL_STATE_QUERY directly from in-memory state.

    This function is called by the Intent Router short-circuit in
    process_input() and MUST NOT make any Brain calls.

    :param user_input:       The raw user query (for context only).
    :param directory_control: The active DirectoryControl instance.
    :returns:                AG-prefixed response string.
    """
    active = directory_control.get_active_directory() if directory_control is not None else None
    if active:
        return f"AG: Active workspace: {active}"
    return "AG: No active workspace is currently set."


def _handle_directory_control(
    user_input: str,
    intent: str,
    directory_control: "DirectoryControl",
) -> str:
    """
    Dispatch Directory Control intents to the appropriate DirectoryControl method.

    Handles: dc_set_directory, dc_switch_directory, dc_show_directory,
    dc_clear_directory, dc_list_directory, dc_read_file, dc_create_file,
    dc_write_file, dc_append_file, dc_create_directory, dc_move, dc_copy,
    dc_rename.

    Never raises. Always returns an AG-prefixed string.
    """
    _fc = get_fallback_classifier()

    try:
        raw = user_input.strip()
        text = raw.lower()

        # ---- Set workspace -----------------------------------------------
        if intent == "dc_set_directory":
            for prefix in ("work in ", "use ", "set workspace to ",
                           "set workspace ", "set directory to ", "workspace "):
                if text.startswith(prefix):
                    path = raw[len(prefix):].strip()
                    break
            else:
                path = raw
            try:
                resolved = directory_control.set_directory(path)
                return f"AG: Active workspace set to: {resolved}"
            except WorkspaceNotFoundError as exc:
                return f"AG: {exc}"

        # ---- Switch workspace --------------------------------------------
        if intent == "dc_switch_directory":
            for prefix in ("switch to ", "switch workspace to ",
                           "change directory to ", "change workspace to ", "cd "):
                if text.startswith(prefix):
                    path = raw[len(prefix):].strip()
                    break
            else:
                path = raw
            try:
                resolved = directory_control.switch_directory(path)
                return f"AG: Switched active workspace to: {resolved}"
            except WorkspaceNotFoundError as exc:
                return f"AG: {exc}"

        # ---- Show workspace ----------------------------------------------
        if intent == "dc_show_directory":
            active = directory_control.get_active_directory()
            if active is None:
                return "AG: No active workspace is set."
            return f"AG: Active workspace: {active}"

        # ---- Clear workspace ---------------------------------------------
        if intent == "dc_clear_directory":
            previous = directory_control.clear_directory()
            if previous is None:
                return "AG: No active workspace was set."
            return f"AG: Active workspace cleared: {previous}"

        # ---- List directory ----------------------------------------------
        if intent == "dc_list_directory":
            try:
                entries = directory_control.list_directory()
            except NoActiveWorkspaceError:
                return "AG: No active workspace is set. Use 'work in <path>' to set one."
            if not entries:
                return "AG: The active workspace is empty."
            lines = []
            for e in entries:
                marker = "[D]" if e["type"] == "dir" else "[F]"
                size = f"  ({e['size_bytes']} B)" if e["type"] == "file" else ""
                lines.append(f"  {marker} {e['name']}{size}")
            header = f"Contents of {directory_control.get_active_directory()}:"
            return "AG: " + header + "\n" + "\n".join(lines)

        # ---- Read file ---------------------------------------------------
        if intent == "dc_read_file":
            for prefix in ("read file ", "open file "):
                if text.startswith(prefix):
                    path = raw[len(prefix):].strip()
                    break
            else:
                path = raw
            try:
                content = directory_control.read_file(path)
                return f"AG: Contents of {path}:\n\n{content}"
            except (FileNotFoundInWorkspace, NotAFileError, DirectoryControlError) as exc:
                return f"AG: {exc}"

        # ---- Create file -------------------------------------------------
        if intent == "dc_create_file":
            for prefix in ("create file ", "create a file ", "make file ", "make a file "):
                if text.startswith(prefix):
                    path = raw[len(prefix):].strip()
                    break
            else:
                path = raw
            try:
                result_path = directory_control.create_file(path)
                return f"AG: File created: {result_path.name}"
            except DirectoryControlError as exc:
                return f"AG: {exc}"

        # ---- Write file --------------------------------------------------
        if intent == "dc_write_file":
            # Pattern: "write <content> to <filename>" or "write to <filename>"
            # For natural language "write this into notes.txt" the content
            # comes from a subsequent turn; we accept a basic form here.
            for prefix in ("write to ", "write this to ", "write into ", "write this into "):
                if text.startswith(prefix):
                    path = raw[len(prefix):].strip()
                    break
            else:
                path = raw
            return (
                f"AG: To write content to '{path}', please say:\n"
                "  write \"<content>\" to <filename>"
            )

        # ---- Append file -------------------------------------------------
        if intent == "dc_append_file":
            for prefix in ("append to ", "append this to ", "add to ", "add this to "):
                if text.startswith(prefix):
                    path = raw[len(prefix):].strip()
                    break
            else:
                path = raw
            return (
                f"AG: To append content to '{path}', please say:\n"
                "  append \"<content>\" to <filename>"
            )

        # ---- Create directory --------------------------------------------
        if intent == "dc_create_directory":
            for prefix in ("create folder ", "create a folder ", "make folder ",
                           "make a folder ", "create directory ", "mkdir "):
                if text.startswith(prefix):
                    path = raw[len(prefix):].strip()
                    break
            else:
                path = raw
            try:
                result_path = directory_control.create_directory(path)
                return f"AG: Folder created: {result_path.name}"
            except DirectoryControlError as exc:
                return f"AG: {exc}"

        # ---- Move --------------------------------------------------------
        if intent == "dc_move":
            # "move <source> to <destination>"
            for prefix in ("move ", "mv "):
                if text.startswith(prefix):
                    rest = raw[len(prefix):]
                    break
            else:
                rest = raw
            if " to " in rest.lower():
                idx = rest.lower().index(" to ")
                source = rest[:idx].strip()
                destination = rest[idx + 4:].strip()
            else:
                return "AG: Use: move <source> to <destination>"
            try:
                result_path = directory_control.move(source, destination)
                return f"AG: Moved to: {result_path.name}"
            except DirectoryControlError as exc:
                return f"AG: {exc}"

        # ---- Copy --------------------------------------------------------
        if intent == "dc_copy":
            for prefix in ("copy ", "cp "):
                if text.startswith(prefix):
                    rest = raw[len(prefix):]
                    break
            else:
                rest = raw
            if " to " in rest.lower():
                idx = rest.lower().index(" to ")
                source = rest[:idx].strip()
                destination = rest[idx + 4:].strip()
            else:
                return "AG: Use: copy <source> to <destination>"
            try:
                result_path = directory_control.copy(source, destination)
                return f"AG: Copied to: {result_path.name}"
            except DirectoryControlError as exc:
                return f"AG: {exc}"

        # ---- Rename ------------------------------------------------------
        if intent == "dc_rename":
            for prefix in ("rename file ", "rename "):
                if text.startswith(prefix):
                    rest = raw[len(prefix):]
                    break
            else:
                rest = raw
            if " to " in rest.lower():
                idx = rest.lower().index(" to ")
                source = rest[:idx].strip()
                new_name = rest[idx + 4:].strip()
            else:
                return "AG: Use: rename <source> to <new_name>"
            try:
                result_path = directory_control.rename(source, new_name)
                return f"AG: Renamed to: {result_path.name}"
            except DirectoryControlError as exc:
                return f"AG: {exc}"

    except Exception as exc:
        from diagnostics.analytics_logger import log_event
        log_event("error", {"source": "directory_control", "error": str(exc)})
        _fc_local = get_fallback_classifier()
        # Map known DirectoryControlError subclasses to typed AGError for specific messages
        if isinstance(exc, FileNotFoundInWorkspace):
            _typed = AGError(
                domain="DIRECTORY", code=DIR_NOT_FOUND,
                message=str(exc), context={"target": str(exc)},
            )
            return "AG: " + _fc_local.get_typed_message(_typed)
        if isinstance(exc, NotAFileError):
            _typed = AGError(
                domain="DIRECTORY", code=DIR_NOT_A_FILE,
                message=str(exc), context={},
            )
            return "AG: " + _fc_local.get_typed_message(_typed)
        if isinstance(exc, WorkspaceViolationError):
            _typed = AGError(
                domain="DIRECTORY", code=DIR_OUT_OF_WORKSPACE,
                message=str(exc), context={},
            )
            return "AG: " + _fc_local.get_typed_message(_typed)
        return "AG: " + _fc_local.get_message(CATEGORY_PROCESSING_FAILURE)

    return "AG: " + _fc.get_message(CATEGORY_UNKNOWN_CAPABILITY)

def _handle_directory_reader(
    user_input: str,
    intent: str,
    directory_session: "DirectorySession",
) -> str:
    """
    Handle all directory-reader intents.

    read_directory  — load a new directory from the user-supplied path.
    clear_directory — remove the active directory from the session.
    query_directory — answer a question using the active directory context.

    Never raises. Always returns an AG-prefixed string.

    :param user_input:         Raw user input text.
    :param intent:             One of "read_directory", "clear_directory",
                               "query_directory".
    :param directory_session:  The active DirectorySession for this conversation.
    :returns:                  AG-prefixed response string.
    """
    try:
        # ---- Load a new directory ----------------------------------------
        if intent == "read_directory":
            text_lower = user_input.strip().lower()

            # Extract the path: strip known prefixes from the raw input
            raw = user_input.strip()
            _prefixes = (
                "read ",
                "load directory ",
                "open directory ",
                "index directory ",
                "scan directory ",
                "load folder ",
                "read folder ",
                "open folder ",
            )
            path = raw
            for _p in _prefixes:
                if raw.lower().startswith(_p):
                    path = raw[len(_p):].strip()
                    break

            if not path:
                return "AG: Please provide a directory path. Example: Read D:\\AG\\docs"

            result = directory_session.set_directory(path)

            if not result.success:
                return f"AG: Could not load directory. {result.error}"

            n = result.file_count
            if n == 0:
                return (
                    f"AG: Directory loaded: {path}\n"
                    "No supported readable files were found. "
                    "Supported types: .txt .md .py .json .yaml .yml .ini .cfg .toml"
                )

            file_list = "\n".join(
                f"  {e.rel_path}" for e in result.files[:20]
            )
            more = f"\n  ... and {n - 20} more." if n > 20 else ""
            return (
                f"AG: Directory loaded: {path}\n"
                f"{n} readable file(s) indexed.\n\n"
                f"{file_list}{more}\n\n"
                "You can now ask questions about the contents of this directory."
            )

        # ---- Clear the active directory ----------------------------------
        if intent == "clear_directory":
            if not directory_session.is_active:
                return "AG: No directory is currently loaded."
            prev = directory_session.directory
            directory_session.clear()
            return f"AG: Directory context cleared: {prev}"

        # ---- Query the active directory ----------------------------------
        # intent == "query_directory" (or any unknown intent when a directory is active)
        if not directory_session.is_active:
            return "AG: No directory is currently loaded. Use: Read <path>"

        # List files if that is the question
        q_lower = user_input.strip().lower()
        _list_phrases = (
            "what files are there",
            "list files",
            "show files",
            "what files exist",
            "list the files",
            "show the files",
            "what is in this directory",
            "what is in the directory",
            "what files are in",
        )
        if any(q_lower.startswith(p) or q_lower == p for p in _list_phrases):
            return "AG: " + directory_session.reader.list_files()

        # Detect if the user is explicitly scoping to the directory
        # ("according to the directory", "based on the files", etc.)
        _explicit_scope = (
            "according to the directory",
            "according to the files",
            "based on the directory",
            "based on the files",
            "from the directory",
            "from the files",
            "in the directory",
            "in these files",
            "in the files",
        )
        is_explicitly_scoped = any(phrase in q_lower for phrase in _explicit_scope)

        # General question — retrieve relevant files and build context
        file_contents = directory_session.reader.read_relevant_files(user_input, max_files=10)

        if not file_contents:
            return (
                "AG: The directory is loaded but contains no readable files "
                f"relevant to your question.\nDirectory: {directory_session.directory}"
            )

        context = build_context(
            file_contents,
            question=user_input,
            directory=directory_session.directory,
        )

        if context.startswith("No readable content"):
            return f"AG: {context}"

        # Build the prompt, adjusting the instruction for explicitly-scoped queries
        if is_explicitly_scoped:
            prompt = (
                "You are answering a question using content from a directory "
                "that the user has explicitly provided.\n"
                "The user has specifically asked about content FROM this directory. "
                "Use ONLY the file contents shown below. "
                "If the answer is not present in the files, state clearly that "
                "the information was not found in the supplied directory. "
                "Do NOT substitute general knowledge.\n\n"
                f"{context}\n\n"
                f"User question: {user_input}"
            )
        else:
            prompt = build_prompt(context, user_input)

        return "AG: " + safe_response(ask_brain(prompt))

    except Exception as exc:
        log_event("error", {"source": "directory_reader", "error": str(exc)})
        return "AG: " + get_fallback_classifier().get_message(CATEGORY_PROCESSING_FAILURE)


def _handle_introspection(
    user_input: str,
    introspection_engine: IntrospectionEngine,
) -> str:
    """
    Build a RuntimeSnapshot and inject it as context into the cloud brain prompt.

    The brain receives real runtime facts — it never invents capabilities.

    :param user_input:           The user's introspection question.
    :param introspection_engine: The live IntrospectionEngine instance.
    :returns:                    AG-prefixed response string.
    """
    try:
        snapshot = introspection_engine.build_snapshot()
        snap_dict = snapshot.to_dict()

        # Compact snapshot context for the prompt
        context_lines = [
            f"Identity: {snap_dict['identity']['name']} v{snap_dict['identity']['version']}",
            f"Overall health: {snap_dict['runtime_health']['overall']}",
            f"Connected subsystems ({snap_dict['runtime_health']['healthy_count']} online): "
            + (", ".join(snap_dict["connected_subsystems"]) or "none"),
        ]
        if snap_dict["disconnected_subsystems"]:
            context_lines.append(
                "Offline/degraded: " + ", ".join(snap_dict["disconnected_subsystems"])
            )
        if snap_dict["brains"]:
            context_lines.append(
                "Brain subsystems: "
                + ", ".join(f"{k}={v}" for k, v in snap_dict["brains"].items())
            )
        if snap_dict["capabilities"]:
            context_lines.append(
                "Capabilities: " + "; ".join(snap_dict["capabilities"][:12])
            )
        if snap_dict["limitations"]:
            context_lines.append(
                "Limitations: " + "; ".join(snap_dict["limitations"][:8])
            )
        loaded_project = sorted([
            m for m in snap_dict["loaded_modules"]
            if not m.startswith("_")
            and "." not in m
            and m not in (
                "sys", "os", "re", "json", "time", "uuid", "abc",
                "copy", "enum", "math", "logging", "datetime",
                "typing", "dataclasses", "collections",
            )
        ])[:20]
        if loaded_project:
            context_lines.append("Loaded project modules: " + ", ".join(loaded_project))

        snapshot_context = "\n".join(context_lines)
        introspection_prompt = (
            "You are answering a question about your own runtime architecture.\n"
            "Use ONLY the following verified runtime facts. "
            "Do NOT invent capabilities or modules.\n\n"
            f"RUNTIME SNAPSHOT:\n{snapshot_context}\n\n"
            f"User question: {user_input}"
        )

        reply = safe_response(ask_brain(introspection_prompt))
        return "AG: " + reply

    except Exception as exc:
        log_event("error", {"source": "introspection", "error": str(exc)})
        return "AG: Runtime introspection unavailable. " + safe_response(ask_brain(user_input))


def store_last_answer(category: str, memory: dict, last_brain_answer: dict) -> None:
    summary = generate_memory_summary(
        last_brain_answer["question"],
        last_brain_answer["answer"]
    )

    fallback_key = last_brain_answer["question"].lower().replace("?", "").strip() or "unnamed_entry"
    key, value = _extract_key_value(summary, fallback_key, last_brain_answer["answer"])

    memory[category][key] = value
    save_memory(memory)
    log_event("storage_operation", {"operation": "store_answer", "category": category, "key": key})

    print(f"AG: Stored '{key}' under {category}.")


def store_discussion(category: str, memory: dict, working_memory: WorkingMemory) -> None:
    # MIGRATION NOTE: discussion_topic() is not present on the new WorkingMemory
    # class. Kept as a method call under the new naming convention; see
    # "MISSING WORKING MEMORY METHODS" for the required addition.
    topic = working_memory.discussion_topic()

    # MIGRATION NOTE: old `working_memory.discussion_buffer` attribute replaced
    # with `working_memory.get_discussion_entries()`. This accessor does not
    # exist yet on the new class; see "MISSING WORKING MEMORY METHODS".
    combined_answer = " ".join(
        entry["answer"] for entry in working_memory.get_discussion_entries() if entry.get("answer")
    ).strip() or "No content captured."

    summary = generate_memory_summary(f"discussion about {topic}", combined_answer)

    fallback_key = topic.strip().lower().replace(" ", "_") or "discussion"
    key, value = _extract_key_value(summary, fallback_key, combined_answer)

    memory[category][key] = value
    save_memory(memory)
    log_event("storage_operation", {"operation": "store_discussion", "category": category, "key": key})

    print(f"AG: Stored discussion under {category}.")


def main():
    memory = load_memory()
    tasks = load_tasks()
    startup()

    last_brain_answer = None
    pending_category = False
    pending_new_category_confirmation = False
    pending_new_category_name = None
    pending_shutdown_confirmation = False
    pending_shutdown_category = False
    pending_temporary_brain_action = None
    working_memory = WorkingMemory()
    # MIGRATION NOTE: old `working_memory.default_brain = ...` attribute
    # replaced with the new decision cache API.
    working_memory.cache_decision("default_brain", load_brain_mode())

    # ------------------------------------------------------------------ #
    # Runtime Integration — initialize all subsystems                     #
    # ------------------------------------------------------------------ #
    _conversation_manager = ConversationManager()
    _entity_tracker       = EntityTracker()
    _reference_resolver   = ReferenceResolver()
    _executive_layer      = ExecutiveLayer()
    _brain_dispatcher     = BrainDispatcher()
    _response_processor   = ResponseProcessor()
    _adaptive_cloud_brain = AdaptiveCloudBrain()
    _self_info_engine     = SelfInfoEngine()
    _directory_session    = DirectorySession()
    _directory_control    = DirectoryControl()

    # Build IntrospectionEngine with all subsystems registered
    _builder_config = SnapshotBuilderConfig(
        identity_name="AG",
        identity_version="0.4.0",
        module_prefix_filter="",
        configuration_summary={
            "brain_mode": load_brain_mode(),
            "memory_file": MEMORY_FILE,
            "task_file": TASK_FILE,
        },
    )
    _introspection_engine = IntrospectionEngine(builder_config=_builder_config)
    _registry = build_registry(
        conversation_manager=_conversation_manager,
        working_memory=working_memory,
        entity_tracker=_entity_tracker,
        reference_resolver=_reference_resolver,
        executive_layer=_executive_layer,
        brain_dispatcher=_brain_dispatcher,
        response_processor=_response_processor,
        adaptive_cloud_brain=_adaptive_cloud_brain,
        introspection_engine=_introspection_engine,
    )
    # Replace the engine's registry with the fully populated one
    _introspection_engine._registry = _registry

    while True:
        try:
            user_input = input("You: ")
        except EOFError:
            print("\nAG: Input stream closed. Shutting down.")
            print("AG: Memory preserved.")
            break
        cleaned_input = user_input.strip().lower()

        if cleaned_input == "save last response":
            # MIGRATION NOTE: old `working_memory.has_unsaved_discussion()` /
            # `working_memory.discussion_buffer[-1]` kept under the new
            # method-call convention; both are missing from the new class.
            # See "MISSING WORKING MEMORY METHODS".
            if not working_memory.has_unsaved_discussion():
                print("AG: There is no recent response to save.")
                continue

            last_brain_answer = working_memory.get_discussion_entries()[-1]
            pending_category = True
            print("AG: Where should I store it?")

            for index, category in enumerate(memory.keys(), start=1):
                print(f"AG: {index}. {category.capitalize()}")

            print("AG: Or name a new division to create one.")
            continue

        confirmation_words = [
            "yes", "y", "yeah", "yep", "sure", "no", "n", "nah",
            "nope", "do it", "save it", "go ahead", "skip", "not now"
        ]

        if (
            cleaned_input in confirmation_words
            and not pending_category
            and not pending_new_category_confirmation
            and not pending_shutdown_confirmation
            and not pending_shutdown_category
            and not pending_temporary_brain_action
        ):
            print("AG: No active decision pending.")
            continue

        if pending_temporary_brain_action:
            decision = interpret_storage_decision(user_input)

            if decision == "STORE":
                action = pending_temporary_brain_action
                previous_mode = load_brain_mode()
                # MIGRATION NOTE: old `working_memory.temporary_brain_active = True`
                # attribute replaced with a temporary fact.
                working_memory.add_fact("temporary_brain_active", True)

                if action["target"] == "cloud":
                    reply = safe_response(ask_cloud_direct(action["resolved_query"]))
                else:
                    reply = safe_response(ask_local(action["resolved_query"]))

                log_event("temporary_brain_used", {
                    "target": action["target"],
                    "resolved_query": action["resolved_query"],
                    "previous_mode": previous_mode
                })

                print(f"AG: {reply}")
                print(f"AG: (Temporary {action['target']} use only — default brain mode remains {previous_mode.upper()}.)")

                # Thread continuity fix: this turn must persist like any other.
                # intent="cloud_brain" so extract_topic won't fire on the raw
                # routing command — current_topic is deliberately left untouched.
                # MIGRATION NOTE: old free function `update_working_memory(...)`
                # replaced with a method call; the method itself is missing
                # from the new WorkingMemory class. See
                # "MISSING WORKING MEMORY METHODS".
                working_memory.update_working_memory(action["resolved_query"], reply, "cloud_brain")
                working_memory.add_to_discussion(action["resolved_query"], reply)

                # MIGRATION NOTE: old `working_memory.temporary_brain_active = False`
                # attribute replaced with a temporary fact.
                working_memory.add_fact("temporary_brain_active", False)
                # MIGRATION NOTE: old `working_memory.pending_actions = []`
                # (list of at most one item) replaced with the singular
                # pending-action API.
                working_memory.clear_pending_action()
                pending_temporary_brain_action = None
                continue

            if decision == "SKIP":
                # MIGRATION NOTE: old `working_memory.pending_actions = []`
                # replaced with the singular pending-action API.
                working_memory.clear_pending_action()
                pending_temporary_brain_action = None
                print("AG: Cancelled. Default brain mode unchanged.")
                continue

            print("AG: Should I proceed with that brain for this request, yes or no?")
            continue

        if pending_shutdown_confirmation:
            decision = interpret_storage_decision(user_input)

            if decision == "STORE":
                pending_shutdown_confirmation = False
                pending_shutdown_category = True

                print("AG: Where should I store it?")

                for index, category in enumerate(memory.keys(), start=1):
                    print(f"AG: {index}. {category.capitalize()}")

                print("AG: Or name a new division to create one.")
                continue

            if decision == "SKIP":
                pending_shutdown_confirmation = False
                # MIGRATION NOTE: old `working_memory.clear_discussion()` kept
                # under the new method-call convention; missing from the new
                # class. See "MISSING WORKING MEMORY METHODS".
                working_memory.clear_discussion()
                print("AG: Discussion discarded.")
                print("AG: Shutting down.")
                print("AG: Memory preserved.")
                break

            print("AG: I could not tell whether you wanted that stored. Answer clearly, humanity permitting.")
            continue

        if pending_shutdown_category:
            category_type, category = interpret_category_decision(user_input, memory)

            if category is None:
                print("AG: I could not identify that memory division. Use a number, category name, or ask me to create one.")
                continue

            if category_type in ("NEW", "NEW_PENDING_CONFIRMATION"):
                memory[category] = {}
                save_memory(memory)
                print(f"AG: Created new memory division '{category}'.")

            store_discussion(category, memory, working_memory)
            working_memory.clear_discussion()

            print("AG: Shutting down.")
            print("AG: Memory preserved.")
            break

        if pending_new_category_confirmation:
            decision = interpret_storage_decision(user_input)

            if decision == "STORE":
                if not pending_new_category_name or not last_brain_answer:
                    pending_new_category_confirmation = False
                    pending_new_category_name = None
                    print("AG: That confirmation no longer has anything to attach to.")
                    continue

                category = pending_new_category_name
                memory[category] = {}
                save_memory(memory)
                print(f"AG: Created new memory division '{category}'.")

                store_last_answer(category, memory, last_brain_answer)

                pending_new_category_confirmation = False
                pending_new_category_name = None
                last_brain_answer = None
                continue

            if decision == "SKIP":
                pending_new_category_confirmation = False
                pending_new_category_name = None
                pending_category = True
                print("AG: Understood. Where should I store it instead?")

                for index, category in enumerate(memory.keys(), start=1):
                    print(f"AG: {index}. {category.capitalize()}")

                print("AG: Or name a new division to create one.")
                continue

            print("AG: I could not tell whether you wanted that created. Answer clearly, humanity permitting.")
            continue

        if pending_category:
            category_type, category = interpret_category_decision(user_input, memory)

            if category is None:
                print("AG: I could not identify that memory division. Use a number, category name, or ask me to create one.")
                continue

            if category_type == "NEW":
                memory[category] = {}
                save_memory(memory)
                print(f"AG: Created new memory division '{category}'.")

            elif category_type == "NEW_PENDING_CONFIRMATION":
                pending_category = False
                pending_new_category_confirmation = True
                pending_new_category_name = category
                print(f"AG: Memory division '{category}' does not exist. Create it?")
                continue

            pending_category = False

            if not last_brain_answer:
                print("AG: There is nothing pending to store anymore.")
                continue

            store_last_answer(category, memory, last_brain_answer)
            last_brain_answer = None
            continue

        log_event("user_input_received", {"text": user_input})
        action_result = analyze_action_pattern(user_input, working_memory)

        if action_result["is_action_request"]:
            action = action_result["actions"][0]
            log_event("action_pattern_detected", {
                "action_type": action["action_type"],
                "operation": action["operation"]
            })

            if action["operation"] == "set_default_brain":
                print(set_brain_mode(action["target"]))
                # MIGRATION NOTE: old `working_memory.default_brain = ...`
                # attribute replaced with the decision cache API.
                working_memory.cache_decision("default_brain", action["target"])
                log_event("brain_mode_changed", {"mode": action["target"]})
                continue

            if action["operation"] == "temporary_brain_use":
                pending_temporary_brain_action = action
                # MIGRATION NOTE: old `working_memory.pending_actions = [action]`
                # (a list holding at most one item) replaced with the singular
                # pending-action API.
                working_memory.set_pending_action(action)
                scope_label = action["scope"].replace("_", " ")
                print(f"AG: {action['target'].capitalize()} brain requested for this {scope_label}. Proceed?")
                continue

        original_input = user_input
        intent = detect_intent(user_input)
        brain_input = user_input

        if intent == "unknown":
            resolved_input = resolve_followup(user_input, working_memory)
            if resolved_input == user_input:
                # MIGRATION NOTE: old free function `resolve_thread_reference(...)`
                # replaced with a method call; the method itself is missing
                # from the new WorkingMemory class. See
                # "MISSING WORKING MEMORY METHODS".
                resolved_input = working_memory.resolve_thread_reference(user_input)

            if resolved_input != user_input:
                brain_input = resolved_input
                intent = detect_intent(brain_input)
                # MIGRATION NOTE: old `working_memory.follow_up_depth += 1`
                # attribute replaced with a temporary fact counter.
                working_memory.add_fact(
                    "follow_up_depth",
                    working_memory.get_fact("follow_up_depth", 0) + 1
                )
                log_event("topic_continuation_detected", {
                    "original_input": original_input,
                    "resolved_input": brain_input,
                    "topic": working_memory.get_topic()
                })

        response = process_input(
            brain_input, memory, tasks, intent,
            introspection_engine=_introspection_engine,
            conversation_manager=_conversation_manager,
            entity_tracker=_entity_tracker,
            reference_resolver=_reference_resolver,
            executive_layer=_executive_layer,
            brain_dispatcher=_brain_dispatcher,
            response_processor=_response_processor,
            adaptive_cloud_brain=_adaptive_cloud_brain,
            self_info_engine=_self_info_engine,
            directory_session=_directory_session,
            directory_control=_directory_control,
        )

        if response == "shutdown":
            if working_memory.has_unsaved_discussion():
                topic = working_memory.discussion_topic()
                pending_shutdown_confirmation = True
                print(f"AG: I have an unsaved discussion about {topic}. Store it before shutdown?")
                continue

            print("AG: Shutting down.")
            print("AG: Memory preserved.")
            break

        print(response)

        answer_text = response.replace("AG: ", "", 1) if response.startswith("AG: ") else response
        # MIGRATION NOTE: old free function `update_working_memory(...)`
        # replaced with a method call; missing from the new class. See
        # "MISSING WORKING MEMORY METHODS".
        working_memory.update_working_memory(original_input, answer_text, intent)

        # ---- IP4: Entity tracking per turn --------------------------------
        # Advance the turn counter, extract entities from both sides of the
        # exchange, then close the turn.  ConversationManager also gets the
        # Q&A pair so its thread summary and reference resolution stay current.
        _entity_tracker.advance_turn()
        _extract_entities_from_text(original_input, _entity_tracker)
        _extract_entities_from_text(answer_text, _entity_tracker)
        _entity_tracker.end_turn()
        _conversation_manager.add_turn("user", original_input)
        _conversation_manager.add_turn("assistant", answer_text)
        # Sync the current topic into the conversation manager
        topic = working_memory.get_topic()
        if topic:
            _conversation_manager.set_topic(topic)
        # -------------------------------------------------------------------

        if intent in ["unknown", "cloud_brain", "recall"]:
            if answer_text == BRAIN_FALLBACK:
                log_event("error", {"input": original_input, "intent": intent})
            else:
                log_event("brain_response_completed", {
                    "intent": intent,
                    "topic": working_memory.get_topic()
                })

        if response.startswith("AG: ") and intent in ["unknown", "cloud_brain"]:
            working_memory.add_to_discussion(original_input, answer_text)


if __name__ == "__main__":
    main()
