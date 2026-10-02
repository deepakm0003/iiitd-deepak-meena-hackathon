# ADR 0002: Lite mode is the default run path

**Status:** accepted (2026-10-02)

**Context.** The top evaluation criterion is "runs end-to-end from README instructions without errors". Docker, API keys and GPUs are common failure points on a reviewer's machine.

**Decision.** `pip install -r requirements.txt` followed by one `python -m tripwire ...` command must work offline with no keys: SQLite, in-memory queue and replay data. Heavy offline jobs (model training, bulk scoring) may use a GPU, but their outputs are saved as small files in the repository so the default path never needs one. CI runs the exact README commands on Ubuntu and Windows on every push.

**Consequences.** Live collectors and full mode are optional extras. Anything the demo shows must be reproducible from committed, replayable data.
