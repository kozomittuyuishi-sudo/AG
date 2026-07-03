from typing import Dict, Tuple, Optional, Any
from brain import ask_brain


class ExecutiveState:
    def __init__(self):
        self.goal = None
        self.plan = None
        self.confidence = 1.0
        self.requires_clarification = False
        self.use_cloud = False
        self.use_memory = False
        self.update_project = False


def clean_category_name(name: str) -> str:
    name = name.strip().lower()
    name = name.replace(" ", "_")
    name = "".join(char for char in name if char.isalnum() or char == "_")
    return name


def interpret_storage_decision(user_input: str) -> str:
    text = user_input.strip().lower()

    quick_store = ["yes", "y", "yeah", "yep", "sure", "store", "save", "save it", "store it", "go ahead", "do it"]
    quick_skip = ["no", "n", "nah", "nope", "skip", "not now", "dont", "don't", "leave it", "ignore it"]

    if text in quick_store:
        return "STORE"

    if text in quick_skip:
        return "SKIP"

    prompt = f"""
You are AG's Executive Layer.

AG asked:
"Should I store this for future access?"

User replied:
{text}

Classify the user's intention.

Return ONLY one word:
STORE
SKIP
CLARIFY
"""

    decision = ask_brain(prompt).strip().upper()

    if "STORE" in decision:
        return "STORE"

    if "SKIP" in decision:
        return "SKIP"

    return "CLARIFY"


def interpret_category_decision(user_input: str, memory: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    text = user_input.strip().lower()

    # Numbers are assigned in the same order Ag.py prints the menu,
    # so they always line up with what the user was shown.
    numbered_categories = {
        str(index): category
        for index, category in enumerate(memory.keys(), start=1)
    }

    if text in numbered_categories:
        return ("EXISTING", numbered_categories[text])

    for category in memory:
        if text == category:
            return ("EXISTING", category)

    existing_categories = ", ".join(memory.keys())

    prompt = f"""
You are AG's Executive Layer.

AG is asking the user where to store a memory entry.

Existing memory divisions:
{existing_categories}

User replied:
{text}

Decide whether the user wants to use an existing memory division,
create a new memory division, or if the answer is unclear.

Return ONLY one of these formats:

USE:<existing_category>
CREATE:<new_category>
UNKNOWN

Strict rules:
- Use USE only if the user explicitly mentions an existing category.
- Never guess based on meaning.
- Never substitute a related category.
- If the user mentions a category that does not exist, return CREATE:<that_category>.
- If the user says "robotics", do NOT choose "vehicles" unless "vehicles" was explicitly mentioned.
- If the user invents a category name that is not in the existing list, never map it to an existing category. Always CREATE it.
- Category names must be lowercase with underscores.
- Do not explain.

Examples:

User: put it in projects
Response: USE:projects

User: put it in robotics
Response: CREATE:robotics

User: create one with name as misc
Response: CREATE:misc

User: store it in misc
Response: CREATE:misc if misc does not exist, otherwise USE:misc
"""

    decision = ask_brain(prompt).strip()

    if decision.startswith("USE:"):
        category = clean_category_name(decision.replace("USE:", "", 1))

        if category in memory:
            return ("EXISTING", category)

        return ("UNKNOWN", None)

    if decision.startswith("CREATE:"):
        category = clean_category_name(decision.replace("CREATE:", "", 1))

        if category:
            return ("NEW", category)

    return ("UNKNOWN", None)
def create_execution_plan(user_input: str, intent: str) -> Dict[str, Any]:
    plan: Dict[str, Any] = {
        "goal": None,
        "intent": intent,
        "needs_brain": False,
        "needs_memory": False,
        "needs_project_context": False,
        "needs_clarification": False,
        "store_after": False,
        "action": "respond"
    }

    if intent in ["show_memory", "recall", "remember"]:
        plan["needs_memory"] = True
        plan["action"] = "memory_operation"

    elif intent in ["project_status", "project_name", "next_step", "completed_milestones"]:
        plan["needs_project_context"] = True
        plan["action"] = "project_operation"

    elif intent in ["add_task", "show_tasks", "complete_task", "show_completed_tasks"]:
        plan["action"] = "task_operation"

    elif intent in ["unknown", "cloud_brain"]:
        plan["needs_brain"] = True
        plan["store_after"] = True
        plan["action"] = "brain_response"

    return plan