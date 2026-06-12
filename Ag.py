import datetime

def greet():
    hour = datetime.datetime.now().hour

    if hour < 12:
        print("\nAG: Good morning.")
    elif hour < 18:
        print("\nAG: Good afternoon.")
    else:
        print("\nAG: Good evening.")

    print("AG: Systems operational.")
    print("AG: Ready.\n")

greet()

while True:
    user = input("You: ")
    msg = user.lower()

    if msg in ["exit", "quit"]:
        print("AG: Shutting down.")
        break

    if "who are you" in msg:
        print("AG: I am AG. Somebody has to keep track of this operation.")

    elif "hello" in msg or "hi" in msg or "hey" in msg:
        print("AG: Greetings. Productivity remains available.")

    elif "status" in msg:
        print("AG: Systems operational. Several unfinished objectives detected.")

    elif "how are you" in msg:
        print("AG: Operational. Unlike some project schedules.")

    elif "task" in msg:
        print("AG: Task management has not been installed yet. Your chaos remains self-managed.")

    else:
        print("AG: I don't know how to respond to that yet.")