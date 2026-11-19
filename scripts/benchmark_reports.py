"""Serve anonymous reports with passive, local browser measurements."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formatly.application.reports import REPORT_TEMPLATE, render_reports  # noqa: E402
from formatly.files import write_json  # noqa: E402


MEASUREMENT_SCRIPT = r"""<script>
(() => {
  const tasks = [];
  try { new PerformanceObserver(list => tasks.push(...list.getEntries().map(e => ({ start: e.startTime, duration: e.duration })))).observe({ type: 'longtask', buffered: true }); } catch {}
  let interaction = 0, printStarted = 0;
  function sample(event, started = 0) {
    const now = performance.now();
    const memory = performance.memory;
    const value = {
      report: location.pathname, event, elapsed_ms: started ? now - started : now,
      template_sha256: '__TEMPLATE_SHA256__', browser: navigator.userAgent.match(/Chrome\/[^ ]+/)?.[0] || '其他浏览器',
      screen_issues: document.querySelectorAll('.report-screen-copy .issue-card').length,
      print_issues: document.querySelectorAll('.report-print-copy .issue-card').length,
      dom_elements: document.querySelectorAll('*').length,
      long_tasks: tasks.filter(e => e.start >= started).map(e => Math.round(e.duration * 100) / 100),
      js_heap_bytes: memory ? memory.usedJSHeapSize : null,
    };
    navigator.sendBeacon('/__measurements', new Blob([JSON.stringify(value)], { type: 'application/json' }));
  }
  const painted = callback => requestAnimationFrame(() => requestAnimationFrame(callback));
  window.addEventListener('load', () => {
    sample('load');
    // Register after Vue has mounted so its synchronous beforeprint handler
    // has prepared the complete copy before these counters are collected.
    window.addEventListener('beforeprint', () => sample('beforeprint', printStarted));
  });
  document.addEventListener('input', event => {
    if (event.target instanceof HTMLInputElement && event.target.type === 'search') {
      const started = performance.now(), version = ++interaction;
      painted(() => { if (version === interaction) sample('search', started); });
    }
  }, true);
  document.addEventListener('click', event => {
    if (event.target instanceof Element && event.target.closest('button')?.textContent === '打印完整报告') printStarted = performance.now();
    if (event.target instanceof Element && event.target.closest('.issue-pagination button')) {
      const started = performance.now(); painted(() => sample('pagination', started));
    }
  }, true);
  window.addEventListener('afterprint', () => setTimeout(() => sample('afterprint'), 0));
})();
</script>"""


class BenchmarkServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_reports(output: Path, counts: list[int]) -> None:
    for count in counts:
        target = output / str(count)
        target.mkdir(parents=True, exist_ok=True)
        result = {
            'status': 'needs_changes', 'kind': 'thesis', 'input_format': 'docx',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'profile_id': 'anonymous-report-benchmark', 'input_sha256': '0' * 64,
            'profile_snapshot': {'id': 'anonymous-report-benchmark', 'name': '匿名验证方案'},
            'input_unchanged': True, 'counts': {'error': count, 'warning': 0, 'manual': 0},
            'engines': [], 'issues': [
                {'rule_id': 'body-font-size', 'level': 'error',
                 'message': f'第 {index} 处字号偏差', 'location': f'段落 {index}',
                 'expected': '12 磅', 'actual': '11 磅', 'source': '匿名验证方案'}
                for index in range(1, count + 1)
            ],
            'coverage': {'complete': True, 'format_checks': count,
                         'summary': {'failed': count}, 'checks': [
                             {'rule_id': 'body-font-size', 'status': 'failed',
                              'label': '正文字号', 'expected': '12 磅', 'actual': '11 磅'}]},
        }
        render_reports(result, target, f'匿名报告-{count}项')
        report = target / 'report.html'
        page = report.read_text(encoding='utf-8')
        measurement_script = MEASUREMENT_SCRIPT.replace('__TEMPLATE_SHA256__', hashlib.sha256(REPORT_TEMPLATE.read_bytes()).hexdigest())
        script_body = measurement_script.removeprefix('<script>').removesuffix('</script>')
        script_hash = base64.b64encode(hashlib.sha256(script_body.encode('utf-8')).digest()).decode('ascii')
        # The generated report forbids networking. Only the disposable benchmark
        # copy permits its own script and local measurement endpoint.
        page = page.replace("script-src ", f"connect-src 'self'; script-src 'sha256-{script_hash}' ", 1)
        page = page.replace('<title>', measurement_script + '<title>', 1)
        report.write_text(page, encoding='utf-8')


def serve(output: Path, port: int) -> None:
    evidence_path = output / 'browser-measurements.json'
    measurements: list[dict] = json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.is_file() else []

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(output), **kwargs)

        def log_message(self, _format, *args):
            pass

        def handle_post(self):
            if urlsplit(self.path).path != '/__measurements':
                self.send_error(404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 32768:
                    raise ValueError('Invalid measurement size')
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict) or value.get('event') not in {
                    'load', 'search', 'pagination', 'beforeprint', 'afterprint'
                }:
                    raise ValueError('Invalid measurement')
                # Only anonymous counters are retained; request headers and
                # search strings are never written into the evidence file.
                allowed = {'report', 'event', 'elapsed_ms', 'template_sha256', 'browser', 'screen_issues', 'print_issues',
                           'dom_elements', 'long_tasks', 'js_heap_bytes'}
                measurements.append({key: value[key] for key in allowed if key in value})
                write_json(output / 'browser-measurements.json', measurements)
            except (ValueError, TypeError, OSError):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()

        do_POST = handle_post

    server = BenchmarkServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    print(f'Anonymous reports: http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--counts', type=int, nargs='+', default=[125, 10000])
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--generate-only', action='store_true')
    args = parser.parse_args()
    if any(count < 1 or count > 20000 for count in args.counts):
        parser.error('counts must be between 1 and 20000')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    create_reports(output, args.counts)
    if not args.generate_only:
        serve(output, args.port)


if __name__ == '__main__':
    main()
