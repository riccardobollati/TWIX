"""Stage 2 — sandboxed runner for the generated extractor.

code_gen.md §7: subprocess, wall-clock timeout, no network. We enforce a
quick static check that the script does not import requests/urllib.request
and run it in a subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional


_FORBIDDEN_IMPORTS = (
    "import requests",
    "from requests",
    "urllib.request",
    "import urllib3",
    "from urllib3",
    "import httpx",
    "from httpx",
)


def static_check(extractor_code: str) -> Optional[str]:
    """Return an error string if the code uses banned imports, else None."""
    for needle in _FORBIDDEN_IMPORTS:
        if needle in extractor_code:
            return f"banned import detected: {needle!r}"
    return None


_RUN_DRIVER = textwrap.dedent(
    """\
    import importlib.util, json, sys, traceback
    spec = importlib.util.spec_from_file_location("extractor", sys.argv[1])
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.stderr.write(traceback.format_exc())
        sys.exit(2)
    if not hasattr(mod, "extract"):
        sys.stderr.write("extractor.py missing `extract(pdf_path: str) -> dict`\\n")
        sys.exit(3)
    try:
        result = mod.extract(sys.argv[2])
    except Exception:
        sys.stderr.write(traceback.format_exc())
        sys.exit(4)
    try:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=False))
    except Exception:
        sys.stderr.write(traceback.format_exc())
        sys.exit(5)
    """
)


def run_extractor(
    extractor_path: str | Path,
    pdf_path: str | Path,
    timeout_s: int = 60,
    cwd: str | Path | None = None,
) -> tuple[dict | None, str | None]:
    """Run extractor.extract(pdf_path) in a subprocess.

    Returns (output_dict, error_text). Exactly one is non-None.
    """
    extractor_path = Path(extractor_path)
    pdf_path = Path(pdf_path)
    code = extractor_path.read_text(encoding="utf-8", errors="replace")
    err = static_check(code)
    if err:
        return None, f"static check failed: {err}"

    env = os.environ.copy()
    # Block easy network access by setting empty proxies; subprocess inherits.
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RUN_DRIVER, str(extractor_path), str(pdf_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        return None, f"timeout after {timeout_s}s\nstderr (partial):\n{(e.stderr or '')[-2000:]}"
    if proc.returncode != 0:
        return None, f"exit={proc.returncode}\nstderr:\n{proc.stderr[-3000:]}\nstdout:\n{proc.stdout[-1000:]}"
    try:
        out = json.loads(proc.stdout)
    except Exception as e:
        return None, f"extractor stdout was not JSON: {e}\nstdout (head):\n{proc.stdout[:2000]}"
    return out, None
