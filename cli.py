"""CalcMCP process manager CLI.

Usage:
    calcmcp start [--transport sse|streamable-http|stdio] [--port N] [--host H] [--headless]
    calcmcp stop
    calcmcp restart [same flags as start]
    calcmcp status
    calcmcp logs [-f] [-n N] [--clear]
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Runtime paths
# ---------------------------------------------------------------------------

RUNTIME_DIR = Path.home() / ".local" / "share" / "calcmcp"
PID_FILE = RUNTIME_DIR / "server.pid"
META_FILE = RUNTIME_DIR / "server.json"   # transport / host / port
LOG_FILE = RUNTIME_DIR / "server.log"
SERVER_SCRIPT = Path(__file__).parent / "server.py"


def _ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------

def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def _is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # process exists but owned by another user


def _lo_pids() -> list[int]:
    """Return PIDs of any running soffice.bin processes."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "soffice.bin"], text=True
        )
        return [int(p) for p in out.split()]
    except subprocess.CalledProcessError:
        return []


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> None:
    pid = _read_pid()
    if _is_running(pid):
        print(f"Server already running (PID {pid})")
        return

    _ensure_runtime_dir()

    env = os.environ.copy()
    env["CALCMCP_HOST"] = args.host
    env["CALCMCP_PORT"] = str(args.port)
    if args.headless:
        env["CALCMCP_HEADLESS"] = "1"
    else:
        env.pop("CALCMCP_HEADLESS", None)

    with LOG_FILE.open("a") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), "--transport", args.transport],
            stdout=log_fh,
            stderr=log_fh,
            env=env,
            start_new_session=True,   # detach from terminal
        )

    PID_FILE.write_text(str(proc.pid))
    META_FILE.write_text(json.dumps({
        "transport": args.transport,
        "host": args.host,
        "port": args.port,
        "headless": args.headless,
        "pid": proc.pid,
    }))

    print(f"Server started (PID {proc.pid})")
    if args.transport in ("sse", "streamable-http"):
        path = "/sse" if args.transport == "sse" else "/mcp"
        print(f"Endpoint: http://{args.host}:{args.port}{path}")
    print(f"Logs:     {LOG_FILE}")


def cmd_stop(args: argparse.Namespace) -> None:
    pid = _read_pid()
    meta: dict = {}
    try:
        meta = json.loads(META_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    port = meta.get("port", None)

    if not _is_running(pid):
        print("Server is not running")
        PID_FILE.unlink(missing_ok=True)
        META_FILE.unlink(missing_ok=True)
        if port:
            _kill_by_port(port, verbose=True)
        _kill_lo(verbose=True)
        return

    print(f"Stopping server (PID {pid}) …", end="", flush=True)
    # Kill the whole process group so uvicorn worker children are also stopped.
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for _ in range(20):          # wait up to 10 s
        time.sleep(0.5)
        if not _is_running(pid):
            break
    else:
        print(" timed out, sending SIGKILL")
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    print(" done")
    PID_FILE.unlink(missing_ok=True)
    META_FILE.unlink(missing_ok=True)

    # Kill anything still holding the port (e.g. orphaned uvicorn workers).
    if port:
        _kill_by_port(port, verbose=True)

    # The server's atexit handler shuts down LO; give it a moment then clean up
    time.sleep(1)
    _kill_lo(verbose=True)


def _kill_lo(verbose: bool = False) -> None:
    pids = _lo_pids()
    if not pids:
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if verbose:
        print(f"Stopped LibreOffice (PID{'s' if len(pids) > 1 else ''}: {', '.join(map(str, pids))})")


def _kill_by_port(port: int, verbose: bool = False) -> None:
    """Kill any process holding the given TCP port (using fuser)."""
    try:
        out = subprocess.check_output(
            ["fuser", f"{port}/tcp"], text=True, stderr=subprocess.DEVNULL
        )
        pids = [int(p) for p in out.split()]
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if verbose and pids:
        print(f"Freed port {port} (PID{'s' if len(pids) > 1 else ''}: {', '.join(map(str, pids))})")


def cmd_restart(args: argparse.Namespace) -> None:
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_status(args: argparse.Namespace) -> None:
    pid = _read_pid()
    running = _is_running(pid)

    # Stale PID file cleanup
    if pid and not running:
        PID_FILE.unlink(missing_ok=True)
        META_FILE.unlink(missing_ok=True)

    # Server
    if running:
        meta: dict = {}
        try:
            meta = json.loads(META_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        print(f"Server:      running  (PID {pid})")
        if meta.get("transport") in ("sse", "streamable-http"):
            path = "/sse" if meta["transport"] == "sse" else "/mcp"
            print(f"Transport:   {meta.get('transport', '?')}")
            print(f"Endpoint:    http://{meta.get('host', '?')}:{meta.get('port', '?')}{path}")
        elif meta.get("transport"):
            print(f"Transport:   {meta['transport']}")
        print(f"Headless:    {meta.get('headless', '?')}")
    else:
        print("Server:      stopped")

    # LibreOffice
    lo = _lo_pids()
    if lo:
        print(f"LibreOffice: running  (PID{'s' if len(lo) > 1 else ''}: {', '.join(map(str, lo))})")
    else:
        print("LibreOffice: stopped")

    # Log file
    if LOG_FILE.exists():
        size = LOG_FILE.stat().st_size
        size_str = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
        print(f"Log file:    {LOG_FILE}  ({size_str})")
    else:
        print(f"Log file:    {LOG_FILE}  (not yet created)")


def cmd_logs(args: argparse.Namespace) -> None:
    if args.clear:
        if LOG_FILE.exists():
            LOG_FILE.write_text("")
            print("Log cleared.")
        else:
            print("No log file to clear.")
        return

    if not LOG_FILE.exists():
        print("No log file found — has the server been started?")
        return

    if args.follow:
        # Replace process with `tail -f` so Ctrl-C works naturally
        os.execvp("tail", ["tail", "-f", "-n", str(args.lines), str(LOG_FILE)])
    else:
        lines = LOG_FILE.read_text().splitlines()
        print("\n".join(lines[-args.lines:]))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _add_start_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--transport",
        default="sse",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport protocol (default: sse)",
    )
    p.add_argument("--port", type=int, default=8000, help="Port for SSE/HTTP transport (default: 8000)")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run LibreOffice without a visible window",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="calcmcp",
        description="Manage the CalcMCP server and LibreOffice instance",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Start the MCP server in the background")
    _add_start_args(p_start)

    sub.add_parser("stop", help="Stop the MCP server and LibreOffice")

    p_restart = sub.add_parser("restart", help="Restart the MCP server")
    _add_start_args(p_restart)

    sub.add_parser("status", help="Show status of the server and LibreOffice")

    p_logs = sub.add_parser("logs", help="View server logs")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output (like tail -f)")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="Number of lines to show (default: 50)")
    p_logs.add_argument("--clear", action="store_true", help="Clear the log file")

    args = parser.parse_args()

    {
        "start":   cmd_start,
        "stop":    cmd_stop,
        "restart": cmd_restart,
        "status":  cmd_status,
        "logs":    cmd_logs,
    }[args.command](args)


if __name__ == "__main__":
    main()
