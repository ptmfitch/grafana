#!/usr/bin/env python3
"""Start, stop, restart, reload frontend, or report status of local Grafana development servers."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HEALTH_URL = "http://127.0.0.1:3000/api/health"
LOGIN_URL = "http://127.0.0.1:3000/login"
BACKEND_PORT = 3000
STATE_DIR_NAME = ".grafana-dev"
BACKEND_LOG = "backend.log"
FRONTEND_LOG = "frontend.log"
BACKEND_PID = "backend.pid"
FRONTEND_PID = "frontend.pid"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def state_dir() -> Path:
    path = repo_root() / STATE_DIR_NAME
    path.mkdir(exist_ok=True)
    return path


def yarn_command(*args: str) -> list[str]:
    yarn = shutil.which("yarn")
    if yarn is not None:
        return [yarn, *args]

    corepack = shutil.which("corepack")
    if corepack is not None:
        return [corepack, "yarn", *args]

    raise RuntimeError("Yarn or Corepack must be installed.")


def configure_node_toolchain() -> None:
    root = repo_root()
    expected_version = (root / ".nvmrc").read_text().strip()
    major_version = expected_version.removeprefix("v").split(".", 1)[0]
    candidates = [
        Path.home() / ".nvm" / "versions" / "node" / expected_version / "bin",
        Path("/opt/homebrew/opt") / f"node@{major_version}" / "bin",
        Path("/usr/local/opt") / f"node@{major_version}" / "bin",
    ]

    for bin_dir in candidates:
        if (bin_dir / "node").exists() and (
            (bin_dir / "yarn").exists() or (bin_dir / "corepack").exists()
        ):
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
            break

    node = shutil.which("node")
    if node is None:
        raise RuntimeError(f"Node {expected_version} must be installed.")

    actual_version = subprocess.run(
        [node, "--version"], check=True, text=True, capture_output=True
    ).stdout.strip()
    actual_major = actual_version.removeprefix("v").split(".", 1)[0]
    if actual_major != major_version:
        raise RuntimeError(f"Expected Node {major_version}.x, but found {actual_version}.")


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def pids_listening_on(port: int) -> set[int]:
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return set()
    return {int(line) for line in result.stdout.splitlines() if line.strip().isdigit()}


def process_command_line(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid_file(name: str) -> int | None:
    path = state_dir() / name
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
    except ValueError:
        return None
    if not is_alive(pid):
        path.unlink(missing_ok=True)
        return None
    return pid


def write_pid_file(name: str, pid: int) -> None:
    (state_dir() / name).write_text(f"{pid}\n")


def clear_pid_file(name: str) -> None:
    (state_dir() / name).unlink(missing_ok=True)


def pgrep_patterns(patterns: list[str]) -> set[int]:
    pids: set[int] = set()
    root = str(repo_root())
    for pattern in patterns:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                check=False,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError:
            return set()
        for line in result.stdout.splitlines():
            if not line.strip().isdigit():
                continue
            pid = int(line)
            command = process_command_line(pid)
            if root in command or "grafana" in command.lower():
                pids.add(pid)
    return pids


def find_backend_pids() -> set[int]:
    pids = set(pids_listening_on(BACKEND_PORT))
    tracked = read_pid_file(BACKEND_PID)
    if tracked is not None:
        pids.add(tracked)
    pids |= pgrep_patterns(
        [
            r"bin/grafana-air",
            r"air -c \.air\.toml",
            r"make run",
        ]
    )
    return {pid for pid in pids if is_alive(pid)}


def find_frontend_pids() -> set[int]:
    pids: set[int] = set()
    tracked = read_pid_file(FRONTEND_PID)
    if tracked is not None:
        pids.add(tracked)
    pids |= pgrep_patterns(
        [
            r"webpack\.dev\.ts",
            r"yarn start",
            r"nx exec -- webpack",
        ]
    )
    # Keep only watch/dev processes, not one-off builds.
    filtered: set[int] = set()
    for pid in pids:
        command = process_command_line(pid)
        if "webpack.prod" in command or "webpack.stats" in command:
            continue
        if any(token in command for token in ("webpack.dev.ts", "yarn start", "nx exec -- webpack")):
            filtered.add(pid)
    return {pid for pid in filtered if is_alive(pid)}


def kill_pid_tree(pid: int) -> None:
    if not is_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return
        time.sleep(0.25)

    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def stop_frontend() -> None:
    frontend = find_frontend_pids()
    for pid in sorted(frontend, reverse=True):
        print(f"Stopping frontend pid {pid}", flush=True)
        kill_pid_tree(pid)
    clear_pid_file(FRONTEND_PID)
    if frontend:
        print("Frontend development server stopped.", flush=True)
    else:
        print("No frontend development server was running.", flush=True)


def stop_servers() -> None:
    backend = find_backend_pids()
    # Kill frontends first so webpack does not race a dying backend.
    stop_frontend()
    for pid in sorted(backend, reverse=True):
        print(f"Stopping backend pid {pid}", flush=True)
        kill_pid_tree(pid)

    clear_pid_file(BACKEND_PID)

    # Wait for the HTTP port to release.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and port_open(BACKEND_PORT):
        for pid in pids_listening_on(BACKEND_PORT):
            kill_pid_tree(pid)
        time.sleep(0.5)

    if port_open(BACKEND_PORT):
        raise RuntimeError(f"Port {BACKEND_PORT} is still in use after stop.")

    print("Grafana development servers stopped.", flush=True)


def wait_until_frontend_ready(timeout: int = 300) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not find_frontend_pids():
            raise RuntimeError("Frontend process exited before becoming ready.")
        if not find_backend_pids() and not port_open(BACKEND_PORT):
            raise RuntimeError("Backend is not running; start Grafana before reloading the frontend.")
        if health_is_ready():
            print(f"Verified {HEALTH_URL} and {LOGIN_URL}", flush=True)
            return
        time.sleep(2)
    raise RuntimeError(f"Frontend was not ready within {timeout} seconds.")


def reload_frontend() -> None:
    """Restart only the webpack frontend; leave the backend running."""
    configure_node_toolchain()
    os.chdir(repo_root())

    if not find_backend_pids() and not port_open(BACKEND_PORT):
        raise RuntimeError("Backend is not running. Use `start` instead of `reload-frontend`.")

    stop_frontend()

    logs = state_dir()
    frontend_pid = start_detached(yarn_command("start"), logs / FRONTEND_LOG)
    write_pid_file(FRONTEND_PID, frontend_pid)

    print(f"Frontend pid {frontend_pid}", flush=True)
    print(f"Logs: {logs / FRONTEND_LOG}", flush=True)
    wait_until_frontend_ready()
    print_status()


def start_detached(command: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("ab")
    print(f"+ {shlex.join(command)} >> {log_path}", flush=True)
    try:
        process = subprocess.Popen(
            command,
            cwd=repo_root(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_file.close()
    return process.pid


def health_is_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
            health = json.load(response)
        with urllib.request.urlopen(LOGIN_URL, timeout=5) as response:
            login_ok = response.status == 200
        return health.get("database") == "ok" and login_ok
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return False


def wait_until_ready(timeout: int = 600) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        backend = find_backend_pids()
        frontend = find_frontend_pids()
        if not backend:
            raise RuntimeError("Backend process exited before becoming healthy.")
        if not frontend:
            raise RuntimeError("Frontend process exited before becoming healthy.")
        if health_is_ready():
            print(f"Verified {HEALTH_URL} and {LOGIN_URL}", flush=True)
            return
        time.sleep(2)
    raise RuntimeError(f"Servers were not healthy within {timeout} seconds.")


def start_servers(*, force_restart: bool = False) -> None:
    configure_node_toolchain()
    os.chdir(repo_root())

    backend_running = bool(find_backend_pids()) or port_open(BACKEND_PORT)
    frontend_running = bool(find_frontend_pids())
    if backend_running or frontend_running or force_restart:
        if backend_running or frontend_running:
            print("Existing Grafana servers detected; restarting.", flush=True)
        stop_servers()

    logs = state_dir()
    backend_pid = start_detached(["make", "run"], logs / BACKEND_LOG)
    write_pid_file(BACKEND_PID, backend_pid)
    frontend_pid = start_detached(yarn_command("start"), logs / FRONTEND_LOG)
    write_pid_file(FRONTEND_PID, frontend_pid)

    print(f"Backend pid {backend_pid}, frontend pid {frontend_pid}", flush=True)
    print(f"Logs: {logs / BACKEND_LOG}, {logs / FRONTEND_LOG}", flush=True)
    wait_until_ready()
    print_status()


def print_status() -> None:
    backend = sorted(find_backend_pids())
    frontend = sorted(find_frontend_pids())
    healthy = health_is_ready()
    print(f"backend:  {'running' if backend else 'stopped'} {backend}", flush=True)
    print(f"frontend: {'running' if frontend else 'stopped'} {frontend}", flush=True)
    print(f"port {BACKEND_PORT}: {'open' if port_open(BACKEND_PORT) else 'closed'}", flush=True)
    print(f"health:   {'ok' if healthy else 'not ready'} ({HEALTH_URL})", flush=True)
    if backend or frontend:
        print(f"logs:     {state_dir() / BACKEND_LOG}, {state_dir() / FRONTEND_LOG}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "reload-frontend", "status"],
        help=(
            "start = restart if running else start; restart = always bounce; "
            "reload-frontend = restart webpack only"
        ),
    )
    args = parser.parse_args()

    if Path.cwd().resolve() != repo_root():
        os.chdir(repo_root())

    if args.command == "status":
        print_status()
    elif args.command == "stop":
        stop_servers()
    elif args.command == "restart":
        start_servers(force_restart=True)
    elif args.command == "reload-frontend":
        reload_frontend()
    elif args.command == "start":
        start_servers(force_restart=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Interrupted.")
    except (RuntimeError, subprocess.CalledProcessError, FileNotFoundError) as error:
        raise SystemExit(f"ERROR: {error}")
