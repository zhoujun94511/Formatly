"""Python HTTP API and delivery adapter for the separately built Vue frontend."""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import secrets
import signal
import socket
import sys
import sqlite3
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore, Event, Thread, current_thread, main_thread
from time import monotonic
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import ProxyHandler, build_opener

from .. import __version__
from ..application.service import AuditService
from ..files import MAX_FILE_BYTES, safe_child
from ..persistence.schools import MAX_TEXT, SchoolVersionConflict
from ..persistence.reviews import ReviewVersionConflict
from .assets import frontend_directory
from .network import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    host_authorities,
    normalize_bind_host,
    service_urls,
)

STATIC = frontend_directory()
MAX_REQUEST = MAX_FILE_BYTES * 2 + 2 * 1024 * 1024


def listen_reuses_address(platform: str = sys.platform) -> bool:
    """Reuse a Linux port left in TIME_WAIT. macOS SO_REUSEADDR allows a second listener."""
    return platform.startswith("linux")


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows uses an exclusive address below. macOS must not set SO_REUSEADDR.
    allow_reuse_address = listen_reuses_address()
    allowed_hosts: frozenset[str] = frozenset()
    allow_interface_hosts = False
    request_timeout: float = 30
    max_connections = 32
    max_uploads = 4

    def __init__(self, *args, **kwargs):
        self._connections = BoundedSemaphore(self.max_connections)
        self.upload_slots = BoundedSemaphore(self.max_uploads)
        super().__init__(*args, **kwargs)

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        request, address = super().get_request()
        # This runs before BaseHTTPRequestHandler reads the request line.
        request.settimeout(self.request_timeout)
        return request, address

    def try_acquire_connection(self) -> bool:
        return self._connections.acquire(blocking=False)

    def release_connection(self) -> None:
        self._connections.release()

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        if not self.try_acquire_connection():
            self._reject_connection(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.release_connection()
            raise

    def _reject_connection(self, request: socket.socket) -> None:
        """Deliver an overload response before a bounded graceful socket close."""
        try:
            deadline = monotonic() + .1
            request.settimeout(.1)
            request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\nRetry-After: 2\r\n\r\n')
            request.shutdown(socket.SHUT_WR)
            # Closing with unread request bytes can reset TCP and erase the
            # response on Windows. Half-close output, then consume pending
            # input until the peer closes, with strict time and byte limits.
            remaining = 64 * 1024
            while remaining:
                timeout = deadline - monotonic()
                if timeout <= 0:
                    break
                request.settimeout(timeout)
                data = request.recv(min(8192, remaining))
                if not data:
                    break
                remaining -= len(data)
        except OSError:
            pass
        finally:
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.release_connection()

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_app(service: AuditService) -> type[BaseHTTPRequestHandler]:
    """Return a request handler bound to an application service, without global state."""
    class Handler(BaseHTTPRequestHandler):
        server: LocalHTTPServer
        server_version = "Formatly/" + __version__

        def log_message(self, _format: str, *args) -> None:
            # No uploaded names, query strings or document contents in access logs.
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8", filename=None) -> None:
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                from urllib.parse import quote
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
            self.end_headers()
            self.wfile.write(body)

        def check_origin(self):
            host = self.headers.get("Host", "")
            allowed_hosts = getattr(self.server, "allowed_hosts", frozenset())
            if getattr(self.server, "allow_interface_hosts", False):
                # A wildcard-bound socket knows the exact local interface that
                # accepted this connection, even when hostname lookup missed it.
                address, port = self.connection.getsockname()[:2]
                allowed_hosts = allowed_hosts | {f"{address}:{port}"}
                if port == 80:
                    allowed_hosts = allowed_hosts | {address}
            if host not in allowed_hosts:
                raise PermissionError("请求地址不属于当前 Formatly 服务")
            origin = self.headers.get("Origin")
            expected_origins = {"http://" + host}
            if self.server.server_address[1] == 80 and host.endswith(":80"):
                expected_origins.add("http://" + host[:-3])
            if origin and origin not in expected_origins:
                raise PermissionError("不接受其他站点发起的请求")
            if self.command != "GET" and self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise PermissionError("不接受跨站写入请求")

        def body(self, maximum=MAX_REQUEST):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("不支持分块请求，请提供Content-Length")
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > min(maximum, MAX_REQUEST):
                self.close_connection = True
                raise ValueError("请求为空或超过该接口大小限制")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("请求未完整上传")
            return raw

        def json_body(self, maximum=2 * 1024 * 1024):
            if self.headers.get_content_type() != "application/json":
                raise ValueError("请使用application/json")
            raw = self.body(maximum)
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as exc:
                raise ValueError("JSON请求格式无效或嵌套过深") from exc
            if not isinstance(value, dict):
                raise ValueError("JSON请求须为对象")
            return value

        def multipart(self, file_fields, text_fields, text_limit=1024):
            content_type = self.headers.get("Content-Type", "")
            if self.headers.get_content_type() != "multipart/form-data" or "boundary=" not in content_type:
                raise ValueError("请选择文档后提交multipart/form-data")
            message = BytesParser(policy=policy.default).parsebytes(
                b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode("ascii") + b"\r\n\r\n" + self.body())
            if not isinstance(message, EmailMessage) or not message.is_multipart():
                raise ValueError("上传格式不完整")
            fields, files = {}, {}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if name not in file_fields | text_fields:
                    raise ValueError("不支持的上传字段")
                if name in fields or name in files:
                    raise ValueError("上传字段不能重复")
                data = part.get_payload(decode=True)
                if data is None:
                    data = b""
                if not isinstance(data, bytes):
                    raise ValueError("上传字段必须为文件字节或 UTF-8 文本")
                if part.get_filename() is not None:
                    if name not in file_fields or len(data) > MAX_FILE_BYTES:
                        raise ValueError("不支持的文件字段或文件超过40MB")
                    files[name] = (part.get_filename(), data)
                else:
                    if name not in text_fields or len(data) > text_limit:
                        raise ValueError("上传字段格式错误")
                    try:
                        fields[name] = data.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise ValueError("文本字段必须使用UTF-8") from exc
            return fields, files

        def upload(self):
            from ..application.document_scopes import MAX_BINDING_BYTES
            fields, files = self.multipart({"document", "pdf"}, {"profile_id", "kind", "render_word", "collection_id", "revision_of_job_id", "preview_id", "scope_bindings"}, MAX_BINDING_BYTES)
            if "document" not in files and not fields.get("preview_id"):
                raise ValueError("缺少待检文档")
            render = fields.get("render_word", "false")
            if render not in {"true", "false"}:
                raise ValueError("render_word仅支持true或false")
            document = files.get("document", ("preview.docx", b""))
            return service.create(document[1], document[0],
                                  fields.get("profile_id", "generic"), fields.get("kind", "thesis"),
                                  files["pdf"][1] if "pdf" in files else None, render == "true",
                                  collection_id=fields.get("collection_id") or None,
                                  revision_of_job_id=fields.get('revision_of_job_id') or None,
                                  preview_id=fields.get("preview_id") or None,
                                  scope_bindings=self.scope_bindings(fields))

        @staticmethod
        def scope_bindings(fields):
            if "scope_bindings" not in fields:
                return None
            try:
                value = json.loads(fields["scope_bindings"])
            except (json.JSONDecodeError, RecursionError) as exc:
                raise ValueError("原稿范围确认 JSON 格式无效") from exc
            if value is None:
                raise ValueError("原稿范围确认不能为 null")
            return value

        def upload_document_preview(self):
            fields, files = self.multipart({"document"}, {"profile_id", "kind"})
            if "document" not in files:
                raise ValueError("缺少待检文档")
            filename, document = files["document"]
            return service.document_preview(document, filename, fields.get("profile_id", "generic"), fields.get("kind", "thesis"))

        def upload_batch(self):
            from ..application.document_scopes import MAX_BINDING_BYTES
            fields, files = self.multipart({f'document{index}' for index in range(20)},
                {'profile_id', 'kind', 'collection_id', 'batch_key', 'scope_bindings'}, MAX_BINDING_BYTES)
            documents = [files[key] for key in sorted(files, key=lambda value: int(value[8:]))]
            return service.create_batch(documents, profile_id=fields.get('profile_id', 'generic'),
                kind=fields.get('kind', 'thesis'), collection_id=fields.get('collection_id') or None,
                batch_key=fields.get('batch_key'), scope_bindings=self.scope_bindings(fields))

        def upload_school_source(self, school_id):
            fields, files = self.multipart({"source"}, {"kind", "role", "transcription"}, MAX_TEXT)
            if "source" not in files:
                raise ValueError("缺少学校依据文件")
            return service.schools.add_source(school_id, files["source"][0], files["source"][1],
                fields.get("kind", "thesis"), fields.get("role", "template"), fields.get("transcription", ""))

        def dispatch(self) -> None:
            self.check_origin()
            path = unquote(urlparse(self.path).path)
            if self.command == "GET":
                if path == "/api/health":
                    return self.send(200, {"status": "ok", "version": __version__})
                if path == "/api/capabilities":
                    return self.send(200, service.capabilities())
                if path == '/api/profile-fields':
                    from ..application.profile_capabilities import profile_fields
                    return self.send(200, profile_fields())
                if path == '/api/schemas':
                    from ..application.contracts import catalog
                    return self.send(200, catalog())
                match = re.fullmatch(r'/api/schemas/([a-z-]+)\.json', path)
                if match:
                    from ..application.contracts import schema
                    return self.send(200, schema(match[1]))
                match = re.fullmatch(r'/api/document-previews/([a-f0-9]{32})/(styles|sections)', path)
                if match:
                    query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                    options = {"offset": int(query.get("offset", ["0"])[0]), "limit": int(query.get("limit", ["10"])[0])}
                    result = (service.document_preview_styles(match[1], query.get("q", [""])[0], **options)
                              if match[2] == "styles" else service.document_preview_sections(match[1], **options))
                    return self.send(200, result)
                if path == "/api/profiles":
                    return self.send(200, {"items": service.profiles.list(), "warnings": service.profiles.list_errors()})
                match = re.fullmatch(r"/api/profiles/([a-z][a-z0-9-]{0,63})/preflight", path)
                if match:
                    params = parse_qs(urlparse(self.path).query)
                    kind = params.get("kind", ["thesis"])[0]
                    return self.send(200, service.profile_preflight(match[1], kind, params.get("format", ["docx"])[0]))
                if path.startswith("/api/profiles/"):
                    return self.send(200, service.profiles.get(path.removeprefix("/api/profiles/")))
                if path == "/api/schools":
                    return self.send(200, service.schools.list_with_warnings())
                match = re.fullmatch(r"/api/schools/([a-z0-9-]{1,64})/sources/([a-z0-9-]{1,64})/(styles|context)", path)
                if match:
                    school_id, source_id, action = match.groups()
                    query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                    if action == "styles":
                        return self.send(200, service.schools.source_styles(school_id, source_id,
                            query.get("q", [""])[0], int(query.get("offset", ["0"])[0]), int(query.get("limit", ["20"])[0])))
                    return self.send(200, service.schools.source_context(school_id, source_id,
                        query.get("locator", [""])[0], query.get("excerpt", [""])[0]))
                match = re.fullmatch(r'/api/schools/([a-z0-9-]{1,64})/draft', path)
                if match:
                    return self.send(200, service.schools.get_draft(match[1]))
                match = re.fullmatch(r"/api/schools/([a-z0-9-]{1,64})(?:/sources/([a-z0-9-]{1,64}))?", path)
                if match:
                    school_id, source_id = match.groups()
                    if source_id:
                        source = service.schools.source(school_id, source_id)
                        return self.send(200, source.read_bytes(), mimetypes.guess_type(source.name)[0] or "application/octet-stream", source.name)
                    return self.send(200, service.schools.get(school_id))
                if path == "/api/collections":
                    return self.send(200, service.collections.list_with_warnings())
                match = re.fullmatch(r"/api/collections/([a-z0-9-]{1,64})", path)
                if match:
                    return self.send(200, service.collection(match[1]))
                if path == "/api/plugins":
                    return self.send(200, {"items": service.registry.list()})
                if path == "/api/doctor":
                    return self.send(200, service.doctor())
                if path == "/api/jobs":
                    params = parse_qs(urlparse(self.path).query)
                    return self.send(200, service.page(int(params.get("limit", ["100"])[0]),
                        int(params.get("offset", ["0"])[0]), params.get("q", [""])[0], params.get("status", [""])[0]))
                match = re.fullmatch(r'/api/batches/([a-f0-9]{32})', path)
                if match:
                    return self.send(200, service.batch(match[1]))
                match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(evidence|ocr-evidence|comparison|reviews)', path)
                if match:
                    job_id, action = match.groups()
                    if action == 'ocr-evidence':
                        location = parse_qs(urlparse(self.path).query).get('location', [''])[0]
                        return self.send(200, service.ocr_evidence(job_id, location))
                    if action == 'evidence':
                        index = int(parse_qs(urlparse(self.path).query).get('issue', ['-1'])[0])
                        return self.send(200, service.issue_evidence(job_id, index))
                    if action == 'comparison':
                        return self.send(200, service.comparison(job_id))
                    return self.send(200, service.job_reviews(job_id))
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/repairs", path)
                if match:
                    return self.send(200, service.repair_plan(match[1]))
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})(?:/(artifacts)(?:/(.+))?)?", path)
                if match:
                    job_id, artifacts, relative = match.groups()
                    if relative:
                        file, data = service.artifact_bytes(job_id, relative)
                        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                        # HTML reports contain their own offline Vue runtime. Download
                        # them without weakening the workbench's script policy.
                        download = None if file.suffix.lower() in {".png", ".jpg", ".pdf"} else file.name
                        return self.send(200, data, content_type, download)
                    return self.send(200, {"items": service.artifacts(job_id)} if artifacts else service.get(job_id))
                if path.startswith("/api/"):
                    return self.send(404, {"error": "接口不存在"})
                file = safe_child(STATIC, "index.html" if path == "/" else path.lstrip("/"))
                if not file.is_file():
                    return self.send(404, {"error": "页面不存在"})
                content_type = "text/javascript" if file.suffix == ".js" else mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                return self.send(200, file.read_bytes(), content_type + ("; charset=utf-8" if file.suffix in {".html", ".css", ".js"} else ""))
            if self.command == "POST":
                if path == "/api/document-previews":
                    return self.send(201, self.upload_document_preview())
                match = re.fullmatch(r'/api/document-previews/([a-f0-9]{32})/discard', path)
                if match:
                    if self.json_body():
                        raise ValueError("关闭预览不接受额外字段")
                    return self.send(200, service.discard_document_preview(match[1]))
                match = re.fullmatch(r'/api/profiles/([a-z][a-z0-9-]{0,63})/trial', path)
                if match:
                    from ..application.samples import sample_docx
                    body = self.json_body()
                    if set(body) - {'kind'}:
                        raise ValueError('试跑仅接受材料类型 kind')
                    job = service.create(sample_docx(), 'Formatly匿名样例.docx', profile_id=match[1], kind=body.get('kind', 'thesis'))
                    service.schedule(job['id'])
                    return self.send(202, job)
                if path == '/api/batches':
                    return self.send(202, self.upload_batch())
                match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(cancel|reviews)', path)
                if match:
                    job_id, action = match.groups()
                    if action == 'cancel':
                        self.json_body()
                        return self.send(200, service.cancel(job_id))
                    return self.send(200, service.job_reviews(job_id, self.json_body()))
                match = re.fullmatch(r'/api/schools/([a-z0-9-]{1,64})/draft(?:/(discard))?', path)
                if match:
                    value = self.json_body(4 * 1024 * 1024)
                    result = service.schools.discard_draft(match[1], value.get('expected_draft_version')) if match[2] else service.schools.save_draft(match[1], value)
                    return self.send(200, result)
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/repairs", path)
                if match:
                    body = self.json_body()
                    if set(body) != {"plan_id", "selected_ids"}:
                        raise ValueError("修复请求仅接受 plan_id 和 selected_ids")
                    job = service.repair(match[1], body["plan_id"], body["selected_ids"])
                    service.schedule(job["id"])
                    return self.send(202, job)
                if path == "/api/jobs":
                    job = self.upload()
                    service.schedule(job["id"])
                    return self.send(202, job)
                if path == "/api/profiles":
                    return self.send(201, service.save_profile(self.json_body()))
                if path == "/api/schools":
                    return self.send(201, service.schools.create(self.json_body().get("name", "")))
                match = re.fullmatch(r"/api/schools/([a-z0-9-]{1,64})/(sources|confirm)", path)
                if match:
                    school_id, action = match.groups()
                    if action == "sources":
                        return self.send(201, self.upload_school_source(school_id))
                    value = self.json_body()
                    version = value.get("expected_version")
                    if type(version) is not int or version < 1:
                        raise ValueError("确认要求须提交学校依据包的正整数 expected_version")
                    return self.send(200, service.confirm_school(school_id, value.get("requirements"), expected_version=version))
                if path == "/api/collections":
                    value = self.json_body()
                    return self.send(201, service.collections.create(value.get("name", ""), value.get("required_kinds")))
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/retry", path)
                if match:
                    job = service.retry(match.group(1))
                    service.schedule(job["id"])
                    return self.send(202, job)
            return self.send(404, {"error": "接口不存在"})

        def handle_request(self) -> None:
            upload_slot = self.headers.get_content_type() == 'multipart/form-data'
            if upload_slot and not self.server.upload_slots.acquire(blocking=False):
                self.close_connection = True
                return self.send(503, {'error': '当前上传较多，请稍后重试'})
            try:
                self.dispatch()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except TimeoutError:
                self.close_connection = True
                self.send(408, {'error': '上传超时，请重新提交'})
            except PermissionError as exc:
                from ..privacy import redact_local_paths
                self.send(403, {"error": redact_local_paths(str(exc))})
            except KeyError as exc:
                self.send(404, {"error": str(exc).strip("'")})
            except (SchoolVersionConflict, ReviewVersionConflict) as exc:
                self.send(409, {"error": str(exc)})
            except ValueError as exc:
                self.send(400, {"error": str(exc)})
            except (OSError, RuntimeError, TypeError, AttributeError, LookupError, sqlite3.Error):
                incident = secrets.token_hex(6)
                import traceback
                from ..privacy import redact_local_paths
                logging.error("HTTP incident %s: %s", incident, redact_local_paths(traceback.format_exc()))
                self.send(500, {"error": f"服务处理失败，请查看终端日志，编号{incident}"})
            finally:
                if upload_slot:
                    self.server.upload_slots.release()

        do_GET = handle_request
        do_POST = handle_request

    return Handler


def make_server(service: AuditService, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> LocalHTTPServer:
    host = normalize_bind_host(host)
    handler_type = create_app(service)

    def handle_connection(request, client_address, current_server: LocalHTTPServer) -> BaseHTTPRequestHandler:
        return handler_type(request, client_address, current_server)

    server = LocalHTTPServer((host, port), handle_connection)
    server.allowed_hosts = host_authorities(host, server.server_address[1])
    server.allow_interface_hosts = host == DEFAULT_HOST
    server.daemon_threads = True
    return server


def _serve_requests(server: LocalHTTPServer, stopped: Event) -> None:
    """Process requests until shutdown, keeping the stop event observable."""
    server.timeout = .25
    while not stopped.is_set():
        server.handle_request()


def _close_server(
    service: AuditService,
    server: LocalHTTPServer,
    stopped: Event,
    browser_thread: Thread | None,
    previous_signals: dict,
) -> None:
    """Release all resources after the request loop exits."""
    stopped.set()

    def restore_signals() -> None:
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)

    try:
        if browser_thread is not None and browser_thread.ident is not None:
            browser_thread.join(timeout=3)
    finally:
        try:
            server.server_close()
        finally:
            try:
                service.close()
            finally:
                restore_signals()


def serve(service: AuditService, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    if not all((STATIC / name).is_file() for name in ("index.html", "report-template.html")):
        raise ValueError("缺少前端构建资源，请在 frontend 运行 npm run build 或安装完整的 Formatly 发布包")
    server = make_server(service, host, port)
    stopped = Event()
    browser_thread: Thread | None = None
    previous_signals = {}

    def stop_service(_signum, _frame) -> None:
        raise KeyboardInterrupt

    try:
        if current_thread() is main_thread():
            for signum in (signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
                if signum is not None:
                    previous_signals[signum] = signal.signal(signum, stop_service)
        service.start_worker()
        urls = service_urls(host, server.server_address[1])
        print("Formatly · Academic formatting, checked.", flush=True)
        print(f"监听地址：{host}:{server.server_address[1]}", flush=True)
        for url in urls:
            print("Formatly 工作台：" + url, flush=True)
        print("按 Ctrl+C 停止服务。", flush=True)
        if open_browser:
            browser_thread = Thread(target=_open_when_ready, args=(urls[0], stopped), daemon=True, name="formatly-browser")
            browser_thread.start()
        _serve_requests(server, stopped)
    except KeyboardInterrupt:
        pass
    except BaseException:
        _close_server(service, server, stopped, browser_thread, previous_signals)
        raise
    _close_server(service, server, stopped, browser_thread, previous_signals)


def _open_when_ready(url: str, stopped: Event) -> None:
    """Open exactly once, only after this server answers a real health request."""
    import webbrowser

    opener = build_opener(ProxyHandler({}))
    for _ in range(40):
        if stopped.is_set():
            return
        ready = False
        try:
            with opener.open(url + "/api/health", timeout=1) as response:
                payload = json.load(response)
                ready = response.status == 200 and isinstance(payload, dict) and payload.get("status") == "ok"
        except (OSError, TypeError, ValueError):
            pass
        if ready:
            if not stopped.is_set():
                try:
                    webbrowser.open_new_tab(url)
                except (OSError, webbrowser.Error):
                    logging.warning("无法自动打开浏览器，请访问 %s", url)
            return
        if stopped.wait(.25):
            return
    logging.warning("浏览器自动打开前的就绪检查超时，请检查启动日志。")


