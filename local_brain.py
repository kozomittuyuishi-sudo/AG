import ollama

def ask_local_brain(message):
    response = ollama.chat(
        model="qwen2.5:3b",
        messages=[
            {
                "role": "user",
                "content": message
            }
        ]
    )

    return response["message"]["content"]