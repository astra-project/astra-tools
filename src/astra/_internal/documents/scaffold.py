"""The empty spec scaffold: an ``astra.yaml`` with nothing declared yet.

``astra init`` and ``astra.api.init_analysis`` both scaffold through :func:`init_analysis`, so
this is the one definition of what a fresh ASTRA analysis contains.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

SPEC_VERSION = "0.1.0"
"""The `spec_version` a new analysis is written at."""


def init_analysis(directory: Path) -> None:
    """Converge ``directory`` into an analysis: write the empty spec scaffold where the folder
    has no ``astra.yaml``, making the folder if need be.

    Idempotent: an ``astra.yaml`` already there is left exactly as it is, so a second call
    changes nothing and a folder that holds an analysis is safe to pass. It touches nothing
    else (no ``.gitignore``, no git init), so downstream tools can scaffold into existing
    directories under their own conventions. Universes are written in ``astra.yaml`` since
    ASTRA 0.1, so there is no ``universes/`` folder.
    """
    file = directory / "astra.yaml"
    if file.exists() or file.is_symlink():  # a link that leads nowhere is the user's too
        return
    directory.mkdir(parents=True, exist_ok=True)
    name = directory.resolve().name or "My Analysis"
    write_text(
        file,
        "# ASTRA Analysis Specification\n\n"
        f'spec_version: "{SPEC_VERSION}"\n'
        f"label: {json.dumps(name, ensure_ascii=False)}\n",
    )


def write_text(file: Path, text: str) -> None:
    """Write ``text`` to ``file`` atomically; its folder is made if need be."""
    file.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{file.name}.", dir=file.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, file)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
