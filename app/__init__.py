"""Powerlifting training-log agent.

Three layers, deliberately separated:

    app.agent      Layer 1 — Gemini turns messy English into structured arguments.
    app.storage    Layer 2 — SQLite; one file, one table.
    app.decision   Layer 3 — plain Python; decides progressing / stalled / deload.

The model never decides anything an athlete acts on.
"""

__version__ = "0.1.0"
