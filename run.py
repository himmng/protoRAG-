"""Single-command local dev launcher: `python run.py`.

Default: single-port mode — starts the backend with SERVE_FRONTEND=true so
it serves both the API and the UI on --backend-port (matching Docker's
all-in-one setup), and opens the browser there. No separate frontend
process, no extra origin to add to Google Cloud Console's Authorized
JavaScript origins beyond the one you already use for the backend.

Pass --split for the old two-port behavior (backend on --backend-port,
frontend static server on --frontend-port, auto-wired) — useful if you want
the frontend served with no build step from a different port/host, but it
requires adding that origin to Google Cloud Console separately if you use
Google sign-in.
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser


def _reexec_into_venv_if_needed():
    # Whatever interpreter was used to invoke `run.py` (a shell alias for
    # `python3`, a stale PATH entry, etc.) may not be the one with this
    # project's dependencies installed. If a `.venv` sits next to this file
    # and we're not already running from it, swap ourselves for it before
    # doing anything else — the backend/frontend subprocesses inherit
    # `sys.executable`, so getting this right here fixes them too.
    #
    # `.venv/bin/python` is typically a *symlink* venv (`python -m venv`
    # without `--copies`), so its realpath is identical to the base
    # interpreter it points at — realpath-comparing sys.executable against
    # it would always say "already in the venv" and skip re-exec. What
    # actually activates a venv's isolated site-packages is invoking
    # through that symlink path so CPython's site-init finds the adjacent
    # `pyvenv.cfg`; comparing `sys.prefix` (set by that site-init) is the
    # correct way to tell whether we're really running from it.
    repo_root = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(repo_root, ".venv")
    venv_python = os.path.join(
        venv_dir, "Scripts" if os.name == "nt" else "bin",
        "python.exe" if os.name == "nt" else "python",
    )
    if not os.path.exists(venv_python):
        return
    if os.path.abspath(sys.prefix) == os.path.abspath(venv_dir):
        return
    os.execv(venv_python, [venv_python, *sys.argv])


def wait_for_health(url, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return False


def main():
    _reexec_into_venv_if_needed()

    parser = argparse.ArgumentParser(description="Run protoRAG+ backend (+ optionally a separate frontend).")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=4444)
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser.")
    parser.add_argument(
        "--split", action="store_true",
        help="Two-port mode: backend (API only) + separate frontend static server, auto-wired. "
             "Default is single-port mode (backend serves the UI too, via SERVE_FRONTEND=true).",
    )
    args = parser.parse_args()

    backend_url = f"http://localhost:{args.backend_port}"
    frontend_url = f"http://localhost:{args.frontend_port}" if args.split else backend_url

    print(f"[run] starting backend on {backend_url} ...")
    backend_env = dict(os.environ)
    if not args.split:
        backend_env["SERVE_FRONTEND"] = "true"
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend:app", "--host", "0.0.0.0", "--port", str(args.backend_port)],
        env=backend_env,
    )

    frontend = None
    try:
        if not wait_for_health(f"{backend_url}/api/health", timeout=30):
            print("[run] backend did not become healthy within 30s — check its logs above.", file=sys.stderr)
            return 1

        if args.split:
            print(f"[run] backend healthy. starting frontend on {frontend_url} ...")
            frontend = subprocess.Popen(
                [
                    sys.executable, "-m", "frontend",
                    "--port", str(args.frontend_port),
                    "--backend", backend_url,
                ]
            )
        else:
            print(f"[run] backend healthy, serving UI + API together on {backend_url}")

        if not args.no_browser:
            time.sleep(1)
            webbrowser.open(frontend_url)

        # Exit if either process dies; otherwise wait for Ctrl+C.
        while True:
            if backend.poll() is not None:
                print(f"[run] backend exited (code {backend.returncode}), shutting down.")
                break
            if frontend is not None and frontend.poll() is not None:
                print(f"[run] frontend exited (code {frontend.returncode}), shutting down.")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[run] shutting down ...")
    finally:
        for proc in (frontend, backend):
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in (frontend, backend):
            if proc:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())
