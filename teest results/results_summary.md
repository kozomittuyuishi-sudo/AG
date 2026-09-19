# AG self-info and compound-request runtime results

Environment: `D:\AG\.venv\Scripts\python.exe` (Python 3.14.6)

## Single self-info requests

All tested single requests returned a deterministic local response and emitted no
`[BRAIN_DIAG]` line. This includes capabilities, identity, brains, architecture,
and limitations queries, plus natural variations such as current capabilities,
functionality, help, supported functions, supported operations, and self-knowledge.

## Compound requests

| Input | Result |
| --- | --- |
| `What can you do and what can't you do?` | Both capability and limitation responses were returned; no cloud diagnostic. |
| `Tell me about yourself, what can you do, and how do you work internally.` | Identity, capability, and architecture responses were returned; no cloud diagnostic. |
| `Tell me who you are, what you're capable of, and how you work internally.` | Identity and capability responses were deterministic. The architecture wording `how you work internally` fell through to a cloud request, which failed because credentials were absent. |

## Evidence files

- `ag_self_info_and_compound_run.txt` — raw output from the first run.
- `ag_extended_self_info_and_compound_run.txt` — raw output from the extended run.

No AG source files were changed during this runtime test.
