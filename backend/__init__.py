"""protoRAG+ backend package.

Re-exports the FastAPI app so `uvicorn backend:app` keeps working after the
single-file → package refactor.
"""

import os
import sys


def _reexec_into_venv_if_launched_directly():
    # `python -m backend` imports this __init__ before backend/__main__.py's
    # own code ever runs, so if we're the wrong interpreter (missing deps),
    # the crash happens right here — there's no later point to intercept it.
    #
    # By the time __init__.py runs, `sys.argv` has already been rewritten by
    # runpy down to just `['-m']` (the module name isn't in it at all at
    # this phase) — useless for telling "direct `-m backend` launch" apart
    # from "`backend` imported as a dependency" (`uvicorn backend:app`, a
    # test suite, ...), where blindly rewriting the caller's real argv could
    # drop flags (`--reload`) or misfire. `sys.orig_argv` (3.10+) preserves
    # the actual original command line, so use that instead.
    orig = getattr(sys, "orig_argv", None)
    if not orig or "-m" not in orig:
        return
    m_index = orig.index("-m")
    if m_index + 1 >= len(orig) or orig[m_index + 1] != "backend":
        return
    extra_args = orig[m_index + 2:]

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_dir = os.path.join(repo_root, ".venv")
    venv_python = os.path.join(
        venv_dir, "Scripts" if os.name == "nt" else "bin",
        "python.exe" if os.name == "nt" else "python",
    )
    if not os.path.exists(venv_python):
        return
    # `.venv/bin/python` is typically a *symlink* venv, so its realpath is
    # identical to the interpreter it points at — comparing `sys.prefix`
    # (set correctly by CPython's site-init only when launched through that
    # symlink, where `pyvenv.cfg` lives) is what actually tells them apart.
    if os.path.abspath(sys.prefix) == os.path.abspath(venv_dir):
        return
    os.execv(venv_python, [venv_python, "-m", "backend", *extra_args])


_reexec_into_venv_if_launched_directly()

# Load .env BEFORE importing app — submodules (auth/deps.py, etc.) read env
# vars at import time, so populating os.environ must happen first. Real env
# vars set by the host (Render, systemd, etc.) win over .env values.
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    # python-dotenv not installed → just rely on real env vars.
    pass

from .app import app

__all__ = ["app"]
