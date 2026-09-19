"""Diagnostic script: run all required self-info regression queries."""
import sys
sys.path.insert(0, 'D:/AG')

from preprocessor_brain import Domain, Intent, PreprocessorBrain

pb = PreprocessorBrain()

queries = [
    ("What can you do?",                         "GET_CAPABILITIES",  "SELF_INFO"),
    ("What are your capabilities?",              "GET_CAPABILITIES",  "SELF_INFO"),
    ("Tell me your capabilities.",               "GET_CAPABILITIES",  "SELF_INFO"),
    ("List your capabilities.",                  "GET_CAPABILITIES",  "SELF_INFO"),
    ("State your capabilities.",                 "GET_CAPABILITIES",  "SELF_INFO"),
    ("What can you currently do?",               "GET_CAPABILITIES",  "SELF_INFO"),
    ("What are you capable of?",                 "GET_CAPABILITIES",  "SELF_INFO"),
    ("What functionality do you have?",          "GET_CAPABILITIES",  "SELF_INFO"),
    ("What can you help me with?",               "GET_CAPABILITIES",  "SELF_INFO"),
    ("What functions do you support?",           "GET_CAPABILITIES",  "SELF_INFO"),
    ("What systems do you have?",                "GET_ARCHITECTURE",  "SELF_INFO"),
    ("What brains do you have?",                 "GET_BRAIN_INFO",    "SELF_INFO"),
    ("How many brains do you have?",             "GET_BRAIN_INFO",    "SELF_INFO"),
    ("Which brains are available?",              "GET_BRAIN_INFO",    "SELF_INFO"),
    ("How do you process requests?",             "GET_ARCHITECTURE",  "SELF_INFO"),
    ("How do you work internally?",              "GET_ARCHITECTURE",  "SELF_INFO"),
    ("What can't you do?",                       "GET_LIMITATIONS",   "SELF_INFO"),
    ("What are your limitations?",               "GET_LIMITATIONS",   "SELF_INFO"),
    ("What operations do you support?",          "GET_CAPABILITIES",  "SELF_INFO"),
    ("What operations don't you support?",       "GET_LIMITATIONS",   "SELF_INFO"),
    ("So what can you do?",                      "GET_CAPABILITIES",  "SELF_INFO"),
    ("And what are you capable of?",             "GET_CAPABILITIES",  "SELF_INFO"),
    ("Tell me about yourself.",                  "GET_IDENTITY",      "SELF_INFO"),
    ("What do you know about yourself?",         "GET_IDENTITY",      "SELF_INFO"),
    ("What do you know about your capabilities?","GET_CAPABILITIES",  "SELF_INFO"),
]

print(f"{'Query':<50} {'Exp.Intent':<22} {'Got.Intent':<22} {'LLM?':<6} {'PASS?'}")
print("-" * 110)

passes = 0
fails = 0
failures = []

for query, expected_intent, expected_domain in queries:
    r = pb.process(query)
    llm = r.requires_llm
    got_domain = r.domain
    got_intent = r.intent
    ok_domain = (got_domain == expected_domain)
    ok_intent = (got_intent == expected_intent)
    ok_no_llm = not llm
    ok_result = bool(r.result)
    passed = ok_domain and ok_intent and ok_no_llm and ok_result and r.success
    status = "PASS" if passed else "FAIL"
    if passed:
        passes += 1
    else:
        fails += 1
        failures.append((query, expected_domain, got_domain, expected_intent, got_intent, llm))
    print(f"{query:<50} {expected_intent:<22} {got_intent:<22} {str(llm):<6} {status}")

print()
print(f"Results: {passes} passed, {fails} failed")
if failures:
    print("\nFailed queries detail:")
    for q, ed, gd, ei, gi, llm in failures:
        print(f"  Query: {q!r}")
        print(f"    Expected domain={ed}, intent={ei}")
        print(f"    Got     domain={gd}, intent={gi}, requires_llm={llm}")
