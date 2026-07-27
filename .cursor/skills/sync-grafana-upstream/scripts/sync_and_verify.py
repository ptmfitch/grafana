#!/usr/bin/env python3

import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM_URL = "https://github.com/grafana/grafana.git"
HEALTH_URL = "http://127.0.0.1:3000/api/health"
LOGIN_URL = "http://127.0.0.1:3000/login"


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print(f"+ {shlex.join(command)}", flush=True)
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def git_output(*args: str) -> str:
    return run(["git", *args], capture=True).stdout.strip()


def require_safe_checkout() -> None:
    if git_output("rev-parse", "--show-toplevel") != str(Path.cwd().resolve()):
        raise RuntimeError("Run this workflow from the repository root.")
    if git_output("branch", "--show-current") != "main":
        raise RuntimeError("Checkout main before syncing upstream.")
    if git_output("status", "--porcelain"):
        raise RuntimeError("The worktree is not clean. Commit or stash changes before syncing.")


def configure_upstream() -> None:
    remotes = git_output("remote").splitlines()
    if "upstream" not in remotes:
        run(["git", "remote", "add", "upstream", UPSTREAM_URL])
        return

    remote_url = git_output("remote", "get-url", "upstream").removesuffix(".git")
    accepted_urls = {
        "https://github.com/grafana/grafana",
        "git@github.com:grafana/grafana",
        "ssh://git@github.com/grafana/grafana",
    }
    if remote_url not in accepted_urls:
        raise RuntimeError(f"The upstream remote points to an unexpected repository: {remote_url}")


def sync_and_build() -> None:
    run(["git", "fetch", "upstream", "main"])
    run(["git", "merge", "--no-edit", "upstream/main"])
    run(["yarn", "install", "--immutable"])
    run(["make", "build-backend"])
    run(["yarn", "build"])


def require_free_port(port: int) -> None:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(
                f"Port {port} is already in use. Stop the existing service before verification."
            )


def start_server(command: list[str], log_path: Path) -> tuple[subprocess.Popen[bytes], object]:
    log_file = log_path.open("wb")
    print(f"+ {shlex.join(command)} > {log_path}", flush=True)
    try:
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except BaseException:
        log_file.close()
        raise
    return process, log_file


def health_is_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
            health = json.load(response)
        with urllib.request.urlopen(LOGIN_URL, timeout=5) as response:
            login_ok = response.status == 200
        return health.get("database") == "ok" and login_ok
    except (OSError, ValueError, urllib.error.URLError):
        return False


def wait_until_ready(processes: list[subprocess.Popen[bytes]], timeout: int = 600) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process in processes:
            return_code = process.poll()
            if return_code is not None:
                raise RuntimeError(f"A development server exited early with status {return_code}.")
        if health_is_ready():
            print(f"Verified {HEALTH_URL} and {LOGIN_URL}", flush=True)
            return
        time.sleep(2)
    raise RuntimeError(f"Development servers were not healthy within {timeout} seconds.")


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=10)


def print_log_tail(path: Path, lines: int = 80) -> None:
    print(f"\nLast {lines} lines of {path}:", flush=True)
    content = path.read_text(errors="replace").splitlines()
    print("\n".join(content[-lines:]), flush=True)


def verify_servers() -> None:
    require_free_port(3000)
    log_dir = Path(tempfile.mkdtemp(prefix="grafana-upstream-verify-"))
    processes: list[subprocess.Popen[bytes]] = []
    log_files: list[object] = []
    log_paths = [log_dir / "backend.log", log_dir / "frontend.log"]
    failure: BaseException | None = None

    try:
        backend, backend_log = start_server(["make", "run"], log_paths[0])
        processes.append(backend)
        log_files.append(backend_log)
        frontend, frontend_log = start_server(["yarn", "start"], log_paths[1])
        processes.append(frontend)
        log_files.append(frontend_log)
        wait_until_ready(processes)
    except BaseException as error:
        failure = error
    finally:
        for process in reversed(processes):
            stop_server(process)
        for log_file in log_files:
            log_file.close()
        print("Stopped backend and frontend development servers.", flush=True)

    if failure is not None:
        for path in log_paths:
            if path.exists():
                print_log_tail(path)
        print(f"\nFull server logs: {log_dir}", flush=True)
        raise failure

    shutil.rmtree(log_dir)


def main() -> None:
    require_safe_checkout()
    configure_upstream()
    sync_and_build()
    verify_servers()
    print("Grafana is synced with upstream/main, built, and verified locally.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Interrupted; development servers were stopped.")
    except (RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"ERROR: {error}")
