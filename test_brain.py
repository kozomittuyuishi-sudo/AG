from brain import (
    ask_brain,
    get_brain_status,
    load_brain_mode
)

print("=" * 50)
print("AG Brain Test")
print("=" * 50)

print(f"Current Mode : {load_brain_mode()}")
print(get_brain_status())
print()

try:
    reply = ask_brain("Say hello in one sentence.")
    print("Brain Response:")
    print(reply)
except Exception as e:
    print("Brain Test Failed!")
    print(e)

print("=" * 50)