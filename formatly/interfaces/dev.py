"""Manage Formatly's Python server and Vite development processes."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Lock, Thread
from types import FrameType
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from ..files import write_json
from ..persistence.locks import write_lock
from .network import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    normalize_bind_host,
    parse_port,
    service_urls,
)

# ``dev.py`` lives two package levels below the project root.  Resolve the
# workspace root explicitly so the launcher can find frontend/ when invoked
# from an IDE with a virtual-environment interpreter.
ROOT = Path(__file__).resolve().parents[2]
STATE_DIRECTORY = ROOT / ".formatly" / "dev"
STATE_FILE = STATE_DIRECTORY / "instance.json"
_PRINT_LOCK = Lock()
SignalHandler = Callable[[int, FrameType | None], object] | int | None


def _print(message: str) -> None:
    with _PRINT_LOCK:
        print("[formatly-dev] " + message, flush=True)


@dataclass
class _Child:
    name: str
    process: subprocess.Popen[str]
    output: deque[str]
    reader: Thread

    def check(self) -> None:
        code = self.process.poll()
        if code is not None:
            with _PRINT_LOCK:
                for line in tuple(self.output):
                    print(f"[{self.name}] {line}", flush=True)
            raise RuntimeError(f"{self.name} 意外退出（退出码 {code}），请查看上方日志")


def _stop_windows_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    completed = subprocess.run(
        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True, timeout=6, check=False,
    )
    if completed.returncode and process.poll() is None:
        raise OSError(f"无法回收已启动的进程树（PID {process.pid}）")


class _Processes:
    def __init__(self, verbose: bool) -> None:
        self.children: list[_Child] = []
        self.verbose = verbose

    def start(self, name: str, command: list[str], directory: Path, environment: dict[str, str]) -> None:
        _print("正在启动 " + name)
        output: deque[str] = deque(maxlen=60)

        def relay() -> None:
            stream = process.stdout
            if stream is None:
                return
            try:
                for raw in stream:
                    line = raw.rstrip("\r\n")
                    with _PRINT_LOCK:
                        output.append(line)
                        if self.verbose or any(word in line.lower() for word in ("error", "warn", "traceback", "失败")):
                            print(f"[{name}] {line}", flush=True)
            finally:
                stream.close()

        reader = Thread(target=relay, name=f"formatly-{name}-log", daemon=True)
        # Allocate the reader before creating an OS process. If its start
        # fails, the registered child still belongs to close().
        process = subprocess.Popen(
            command, cwd=directory, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        self.children.append(_Child(name, process, output, reader))
        reader.start()

    def check(self) -> None:
        for child in self.children:
            child.check()

    def close(self) -> None:
        failures: list[str] = []
        for child in reversed(self.children):
            process = child.process
            try:
                if process.poll() is None:
                    try:
                        if os.name == "nt":
                            process.send_signal(signal.CTRL_BREAK_EVENT)
                        else:
                            os.killpg(process.pid, signal.SIGTERM)
                    except OSError:
                        if os.name == "nt":
                            _stop_windows_tree(process)
                        else:
                            os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        # Only process handles/groups created above may be stopped.
                        if os.name == "nt":
                            _stop_windows_tree(process)
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError) as exc:
                failures.append(child.name + "：" + str(exc))
                if process.poll() is None:
                    try:
                        if os.name == "nt":
                            _stop_windows_tree(process)
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                    except (OSError, subprocess.SubprocessError) as final_error:
                        failures.append(str(final_error))
            finally:
                if child.reader.ident is not None:
                    child.reader.join(timeout=2)
                elif process.stdout is not None:
                    # No relay ran to close this pipe after start() failed.
                    try:
                        process.stdout.close()
                    except OSError as exc:
                        failures.append(child.name + "：" + str(exc))
        if failures:
            raise RuntimeError("进程回收异常：" + "; ".join(failures))


def _wait_for_http(url: str, processes: _Processes, stopped: Event) -> bool:
    deadline = time.monotonic() + 30
    opener = build_opener(ProxyHandler({}))
    last_error = "尚无响应"
    while time.monotonic() < deadline:
        if stopped.is_set():
            return False
        processes.check()
        try:
            with opener.open(Request(url), timeout=1) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError) as exc:
            last_error = str(exc)
        stopped.wait(.1)
    raise RuntimeError(f"服务未在 30 秒内就绪：{url}（{last_error}）")


def _check_port(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise ValueError(f"无法使用 {host}:{port}，请关闭占用程序或更换端口；不会结束其他进程") from exc


def _restore_signal_handlers(handlers: dict[int, SignalHandler]) -> None:
    for signum, previous in handlers.items():
        signal.signal(signum, previous)


def _control_server(stopped: Event, token: str, instance: str) -> HTTPServer:
    class ControlServer(HTTPServer):
        def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            pass

        def _do_post(self) -> None:
            self.connection.settimeout(2)
            authenticated = secrets.compare_digest(self.headers.get("X-Formatly-Dev-Token", "").encode("utf-8"), token.encode("ascii"))
            accepted = self.path == "/stop" and authenticated and not self.headers.get("Origin")
            payload = json.dumps({"instance": instance} if accepted else {"error": "请求无效"}).encode("utf-8")
            self.send_response(202 if accepted else 403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            if accepted:
                stopped.set()

        # BaseHTTPRequestHandler dispatches by this exact protocol method name.
        # Keep the implementation PEP 8 compliant while preserving that API.
        do_POST = _do_post

    def handler_factory(
        request: socket.socket,
        client_address: tuple[str, int],
        server: ControlServer,
    ) -> BaseHTTPRequestHandler:
        return Handler(request, client_address, server)

    return ControlServer(("127.0.0.1", 0), handler_factory)


def _stop() -> int:
    if not STATE_FILE.is_file():
        _print("当前项目没有由 start_dev.py 管理的开发服务")
        return 0
    if STATE_FILE.stat().st_size > 8192:
        raise ValueError("开发实例状态异常；未停止任何进程")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("root") != str(ROOT):
        raise ValueError("开发实例不属于当前项目；未停止任何进程")
    token, instance = state.get("token"), state.get("instance")
    port = state.get("control_port")
    if not isinstance(token, str) or not isinstance(instance, str) or not isinstance(port, int):
        raise ValueError("开发实例状态不完整；未停止任何进程")
    connection = http.client.HTTPConnection("127.0.0.1", parse_port(port), timeout=3)
    try:
        connection.request("POST", "/stop", headers={"X-Formatly-Dev-Token": token, "Content-Length": "0"})
        response = connection.getresponse()
        payload = json.loads(response.read(8192))
        if response.status != 202 or not isinstance(payload, dict) or payload.get("instance") != instance:
            raise ValueError("开发实例身份核验失败；未停止任何进程")
    except OSError as exc:
        raise ValueError("开发启动器已退出或状态过期；未按端口或 PID 强制结束任何进程") from exc
    finally:
        connection.close()
    deadline = time.monotonic() + 30
    while STATE_FILE.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    if STATE_FILE.exists():
        raise RuntimeError("停止请求已送达，服务仍在退出；请检查原启动终端日志")
    _print("开发服务已停止")
    return 0


def _start(args: argparse.Namespace) -> int:
    frontend = ROOT / "frontend"
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = python if python.is_file() else Path(sys.executable)
    version = subprocess.run(
        [str(python), "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"],
        capture_output=True, timeout=5, check=False,
    )
    if version.returncode:
        raise ValueError("Formatly 需要 Python 3.11 或更高版本")
    node = shutil.which("node")
    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    if not node:
        raise ValueError("未找到 Node.js；请将 Node.js 22+ 加入 PyCharm 终端的 PATH")
    if not vite.is_file():
        raise ValueError(f"未找到本地 Vite：{vite}；请在项目 frontend 目录执行 npm install")
    node_version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5, check=False)
    if node_version.returncode or int(node_version.stdout.strip().removeprefix("v").split(".")[0]) < 22:
        raise ValueError("开发模式需要 Node.js 22 或更高版本")
    if not all((frontend / "dist" / name).is_file() for name in ("index.html", "report-template.html")):
        raise ValueError("缺少报告构建资源，请先在 frontend 中执行 npm run build")
    backend_port = parse_port(args.backend_port)
    frontend_port = parse_port(args.frontend_port)
    if backend_port == frontend_port:
        raise ValueError("后端与前端端口不能相同")
    host = normalize_bind_host(args.host)
    # Both services use IPv4; Node may otherwise resolve localhost to ::1.
    if host == "localhost":
        host = "127.0.0.1"
    _check_port(host, backend_port)
    _check_port(host, frontend_port)
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "localhost"} else host
    backend_url = f"http://{connect_host}:{backend_port}"
    frontend_url = f"http://{connect_host}:{frontend_port}"
    stopped = Event()
    processes = _Processes(args.verbose_logs)
    token, instance = secrets.token_hex(32), secrets.token_hex(16)
    control = _control_server(stopped, token, instance)
    previous_handlers: dict[int, SignalHandler] = {}
    try:
        with control:
            control_thread = Thread(target=control.serve_forever, name="formatly-dev-control", daemon=True)
            for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
                signum = getattr(signal, name, None)
                if isinstance(signum, int):
                    previous_handlers[signum] = signal.signal(signum, lambda _number, _frame: stopped.set())
            control_thread.start()
            try:
                write_json(STATE_FILE, {"root": str(ROOT), "instance": instance, "token": token, "control_port": control.server_port})
                environment = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "FORMATLY_OPEN_BROWSER": "0"}
                backend_command = [str(python), "-B", str(ROOT / "app.py"), "--host", host, "--port", str(backend_port), "--no-browser"]
                if args.data_dir:
                    backend_command.extend(["--data-dir", str(Path(args.data_dir).resolve())])
                processes.start("backend", backend_command, ROOT, environment)
                if _wait_for_http(backend_url + "/api/health", processes, stopped):
                    environment = {**environment, "FORMATLY_DEV_HOST": host, "FORMATLY_DEV_PORT": str(frontend_port), "FORMATLY_API_TARGET": backend_url}
                    processes.start("frontend", [node, str(vite), "--host", host, "--port", str(frontend_port), "--strictPort"], frontend, environment)
                    if (_wait_for_http(frontend_url, processes, stopped)
                            and _wait_for_http(frontend_url + "/api/health", processes, stopped)):
                        for url in service_urls(host, frontend_port):
                            _print("前端：" + url)
                        for url in service_urls(host, backend_port):
                            _print("后端：" + url)
                        _print("服务已就绪，按 Ctrl+C 或运行 python start_dev.py stop 退出")
                        if args.open_browser:
                            try:
                                webbrowser.open_new_tab(service_urls(host, frontend_port)[0])
                            except (OSError, webbrowser.Error) as exc:
                                _print("无法自动打开浏览器：" + str(exc))
                        while not stopped.wait(.25):
                            processes.check()
            finally:
                try:
                    processes.close()
                finally:
                    try:
                        control.shutdown()
                    finally:
                        control_thread.join(timeout=3)
    finally:
        try:
            STATE_FILE.unlink(missing_ok=True)
        finally:
            _restore_signal_handlers(previous_handlers)
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="一键启动或停止 Formatly Python + Vue/Vite 开发环境")
    parser.add_argument("command", choices=("start", "stop"), nargs="?", default="start")
    hosts = parser.add_mutually_exclusive_group()
    hosts.add_argument("--host", type=normalize_bind_host, default=os.environ.get("FORMATLY_HOST", DEFAULT_HOST))
    hosts.add_argument("--local-only", dest="host", action="store_const", const="127.0.0.1", help="仅允许本机访问")
    parser.add_argument("--backend-port", type=parse_port, default=os.environ.get("FORMATLY_PORT", str(DEFAULT_PORT)))
    parser.add_argument("--frontend-port", type=parse_port, default=os.environ.get("FORMATLY_DEV_PORT", "5173"))
    parser.add_argument("--data-dir", help="传给现有 Python 服务的数据目录")
    parser.add_argument("--no-browser", dest="open_browser", action="store_false", help="就绪后不自动打开浏览器")
    parser.set_defaults(open_browser=os.environ.get("FORMATLY_OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no", "off"})
    parser.add_argument("--verbose-logs", action="store_true", help="转发完整子进程日志")
    args = parser.parse_args(argv)
    try:
        if args.command == "stop":
            return _stop()
        STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        with write_lock(STATE_DIRECTORY, Lock()):
            return _start(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, http.client.HTTPException) as exc:
        _print("操作失败：" + str(exc))
        return 2
