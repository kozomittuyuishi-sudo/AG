"""
cognitive/
==========
AG Phase 2 — Cognitive pipeline modules.

Contains the reasoning stages that sit between raw user input and the Brain.
No module in this package answers questions or generates responses.
Each module transforms or annotates a Thought object.

Modules
-------
evaluator           CognitiveEvaluator  — intent, missing info, context flags.
context_resolver    ContextResolver     — rewrites incomplete prompts.
confidence_engine   ConfidenceEngine    — scores resolution confidence.
response_verifier   ResponseVerifier    — validates responses before delivery.
"""
