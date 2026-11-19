"""CLI adapter; every command delegates to the same service used by HTTP."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .. import __version__
from ..application.service import AuditService, default_data_dir
from ..files import MAX_FILE_BYTES
from .network import DEFAULT_HOST, DEFAULT_PORT, normalize_bind_host, parse_port


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_json_file(value):
    path = Path(value)
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("JSON 文件不存在或超过 2MB")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("JSON 文件格式无效或嵌套过深") from exc


def result_exit(job):
    result = job.get("result")
    if job["status"] != "completed" or not result or result["status"] == "incomplete":
        return 2
    return 1 if result["counts"]["error"] else 0


def parser():
    root = argparse.ArgumentParser(prog="formatly", description="Formatly · 毕业论文与实习报告格式检测工具 · Academic formatting, checked.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--data-dir", help="任务、方案和报告的数据目录")
    sub = root.add_subparsers(dest="command", required=True)
    def command(name, description):
        item = sub.add_parser(name, help=description)
        item.add_argument("--data-dir", default=argparse.SUPPRESS)
        return item
    check = command("check", "检测一个 DOCX/PDF/TXT/MD/JSON，保存完整证据和报告")
    check.add_argument("--input", required=True)
    check.add_argument("--profile", default="generic")
    check.add_argument("--scope-bindings", help="与此原稿、方案摘要匹配的范围确认 JSON 文件")
    check.add_argument("--kind", choices=["thesis", "intern", "certificate"], default="thesis")
    check.add_argument("--collection", help="关联已有材料集合 ID")
    check.add_argument('--revision-of', help='关联原检测任务，比较修改前后的格式问题')
    check.add_argument("--pdf")
    check.add_argument("--render-word", action="store_true", help="使用已安装的 Word/WPS 只读导出 PDF（Windows 可选能力）")
    check.add_argument("--output", help="复制完整结果到新的或空的目录")
    check.add_argument("--json", action="store_true", help="标准输出为任务JSON")
    web = command("serve", "启动 Formatly Web 工作台，默认支持局域网访问")
    binding = web.add_mutually_exclusive_group()
    binding.add_argument("--host", type=normalize_bind_host, default=os.environ.get("FORMATLY_HOST", DEFAULT_HOST),
                         help="监听 IPv4 地址，默认 0.0.0.0；也可通过 FORMATLY_HOST 配置")
    binding.add_argument("--local-only", dest="host", action="store_const", const="127.0.0.1", help="仅允许本机访问")
    web.add_argument("--port", type=parse_port, default=os.environ.get("FORMATLY_PORT", str(DEFAULT_PORT)))
    browser = web.add_mutually_exclusive_group()
    browser.add_argument("--open", action="store_true", help="服务就绪后打开浏览器（默认）")
    browser.add_argument("--no-browser", dest="open", action="store_false", help="只启动服务，不打开浏览器")
    web.set_defaults(open=os.environ.get("FORMATLY_OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no", "off"})
    profiles = command("profiles", "查看或导入规则方案")
    profiles.add_argument("action", choices=["list", "show", "import", "preflight"])
    profiles.add_argument("value", nargs="?")
    profiles.add_argument("--kind", choices=["thesis", "intern", "certificate"], default="thesis")
    profiles.add_argument("--format", choices=["docx", "pdf", "txt", "md", "json"], default="docx", help="预检待检原稿格式")
    schools = command("schools", "保存学校依据、确认规则并生成方案")
    schools.add_argument("action", choices=["list", "create", "show", "add-source", "confirm"])
    schools.add_argument("id", nargs="?")
    schools.add_argument("--name")
    schools.add_argument("--source", help="学校依据 DOCX/PDF/TXT/MD/JSON 路径")
    schools.add_argument("--kind", choices=["thesis", "intern", "certificate"], default="thesis")
    schools.add_argument("--role", choices=["template", "instructions"], default="template")
    schools.add_argument("--transcription", help="PDF 依据可选的已核对 UTF-8 校正文本路径")
    schools.add_argument("--requirements", help="审核后的要求 JSON 文件路径")
    schools.add_argument("--expected-version", type=int,
                         help="确认学校要求时必须匹配的依据包版本，避免旧窗口覆盖新编辑")
    collections = command("collections", "建立和核验关联材料集合")
    collections.add_argument("action", choices=["list", "create", "show"])
    collections.add_argument("id", nargs="?")
    collections.add_argument("--name")
    collections.add_argument("--required-kind", choices=["thesis", "intern", "certificate"], action="append")
    plugins = command("plugins", "查看可用检测插件")
    plugins.add_argument("action", choices=["list"], default="list", nargs="?")
    command("doctor", "诊断核心与可选引擎状态")
    engines = command("engines", "在服务主机检查、配置或移除兼容的外部专项引擎")
    engines.description = (
        "仅支持符合专项适配契约的完整引擎包，不是通用转换工具接口。"
        "接入目录及配置说明见 docs/external-engines.md。"
        "配置需在运行 Formatly 的主机执行，使用与服务相同的数据目录。"
    )
    engines.add_argument("action", choices=["check", "configure", "clear"],
                         help="check 仅检查；configure 检查通过后保存；clear 移除本地接入配置")
    engines.add_argument("--root", help="完整兼容引擎的根目录；configure 必填")
    engines.add_argument("--python", help="外部引擎 Python 解释器；省略时按发现顺序查找")
    schemas = command('schemas', '导出公开 JSON Schema 协议')
    schemas.add_argument('name', nargs='?', choices=['profile', 'requirement', 'report', 'check', 'plugin-result', 'scope-bindings'])
    preview = command('document-preview', '预览当前 DOCX 的样式和分节，确认检测范围')
    preview.add_argument('action', choices=['create', 'styles', 'sections', 'discard'])
    preview.add_argument('--input', help='create 时的 DOCX 原稿路径')
    preview.add_argument('--profile', default='generic')
    preview.add_argument('--kind', choices=['thesis', 'intern', 'certificate'], default='thesis')
    preview.add_argument('--id', help='create 返回的临时预览 ID')
    preview.add_argument('--query', default='')
    preview.add_argument('--offset', type=int, default=0)
    preview.add_argument('--limit', type=int, default=10)
    batch = command('batch', '使用同一方案批量检测，每份原稿独立保存结果')
    batch.add_argument('--input', action='append', required=True)
    batch.add_argument('--profile', default='generic')
    batch.add_argument('--scope-bindings', help='与 --input 顺序一致、每份独立确认的 JSON 数组；未确认项为 null')
    batch.add_argument('--kind', choices=['thesis', 'intern', 'certificate'], default='thesis')
    batch.add_argument('--collection')
    batch.add_argument('--batch-key', help='重试相同提交时使用原32位批次标识')
    jobs = command("jobs", "查看历史任务，按原规则快照重试")
    jobs.add_argument("action", choices=["list", "show", "retry", "cancel"])
    jobs.add_argument("id", nargs="?")
    jobs.add_argument("--limit", type=int, default=100, help="列表每页条数（1至100）")
    jobs.add_argument("--offset", type=int, default=0, help="列表起始偏移")
    jobs.add_argument("--query", default="", help="按文档名搜索全部历史")
    jobs.add_argument("--status", default="", help="按任务状态筛选")
    repairs = command("repairs", "预览并选择性修复 DOCX 格式问题")
    repairs.add_argument("action", choices=["preview", "apply"])
    repairs.add_argument("id", help="原检测任务 ID")
    repairs.add_argument("--plan-id", help="预览返回的计划 ID，apply 必填")
    repairs.add_argument("--select", action="append", help="要修复的选项 ID，可重复使用此参数")
    repairs.add_argument("--output", help="导出修复副本及复检报告到新的或空的目录")
    return root


def engine_command(args: argparse.Namespace) -> int:
    """Configure trusted local executables without creating task storage."""
    from ..adapters.engine_config import clear_engine_config, save_engine_config
    from ..adapters.legacy import probe_legacy, public_engine_info

    data_dir = Path(args.data_dir or default_data_dir()).expanduser().resolve()
    environment_overrides = [name for name in ("FORMATLY_LEGACY_ROOT", "FORMATLY_LEGACY_PYTHON")
                             if os.environ.get(name)]
    warnings = (["当前进程中的 " + "、".join(environment_overrides)
                 + " 优先于本地配置；请同步调整服务启动环境，再重启服务。"]
                if environment_overrides else [])
    if args.action == "clear":
        if args.root or args.python:
            raise ValueError("engines clear 不接受 --root 或 --python")
        removed = clear_engine_config(data_dir)
        print_json({"cleared": removed, "restart_required": removed,
                    "message": ("本地外部引擎配置已移除；重启服务后按环境变量或默认目录发现。" if removed
                                else "尚未保存本地外部引擎配置；仍按环境变量或默认目录发现。"),
                    "warnings": warnings})
        return 0
    if args.action == "configure" and not args.root:
        raise ValueError("engines configure 需使用 --root 指定完整兼容引擎的根目录")
    result = probe_legacy(data_dir=data_dir, root=args.root, python=args.python)
    public = public_engine_info(result)
    if args.action == "check":
        print_json(public)
        return 0 if result["available"] else 2
    if not result["available"]:
        print_json({"saved": False, "message": "引擎检查未通过，原接入配置未修改。",
                    "verification": public, "warnings": warnings})
        return 2
    save_engine_config(data_dir, result["root"], result["python"])
    print_json({"saved": True, "restart_required": True,
                "message": "接入配置已保存；请重启使用同一数据目录的服务后重新检查。",
                "verification": public, "warnings": warnings})
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    service = None
    try:
        if args.command == 'schemas':
            from ..application.contracts import catalog, schema
            print_json(schema(args.name) if args.name else catalog())
            return 0
        if args.command == 'engines':
            return engine_command(args)
        service = AuditService(args.data_dir)
        if args.command == 'document-preview':
            if args.action == 'create':
                if not args.input or args.id:
                    raise ValueError('create 须提供 --input，不能提供 --id')
                path = Path(args.input)
                if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
                    raise ValueError('原稿不存在、为空或超过40MiB')
                print_json(service.document_preview(path.read_bytes(), path.name, args.profile, args.kind))
            else:
                if not args.id or args.input:
                    raise ValueError('styles/sections/discard 须提供 --id，不能提供 --input')
                if args.action == 'discard':
                    print_json(service.discard_document_preview(args.id))
                elif args.action == 'styles':
                    print_json(service.document_preview_styles(args.id, args.query, args.offset, args.limit))
                else:
                    print_json(service.document_preview_sections(args.id, args.offset, args.limit))
            return 0
        if args.command == "check":
            if args.output:
                output = Path(args.output).resolve()
                if output.is_relative_to(service.jobs_dir.resolve()):
                    raise ValueError("导出目录不能位于任务存储目录内")
                if output.exists() and (not output.is_dir() or any(output.iterdir())):
                    raise ValueError("导出目录须为新目录或空目录")
            job = service.create_from_path(args.input, profile_id=args.profile, kind=args.kind,
                                           pdf_path=args.pdf, render_word=args.render_word, collection_id=args.collection,
                                           revision_of_job_id=args.revision_of,
                                           scope_bindings=read_json_file(args.scope_bindings) if args.scope_bindings else None)
            job = service.run(job["id"])
            report_dir = service.export(job["id"], args.output) if args.output else service.jobs_dir / job["id"]
            if args.json:
                print_json({**job, "report_dir": str(report_dir)})
            else:
                result = job.get("result") or {}
                print(f"Formatly · 任务 {job['id']}：{job['status']} / {result.get('status', job.get('error'))}")
                print("问题数量：" + str(result.get("counts", {})))
                print("报告目录：" + str(report_dir))
                print("人工复核和未完成项不计为通过。")
            return result_exit(job)
        if args.command == 'batch':
            import uuid
            documents = []
            for value in args.input:
                path = Path(value)
                if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError('批量原稿不存在或超过40MiB：' + path.name)
                documents.append((path.name, path.read_bytes()))
            result = service.create_batch(documents, profile_id=args.profile, kind=args.kind,
                                         collection_id=args.collection, batch_key=args.batch_key or uuid.uuid4().hex,
                                         scope_bindings=read_json_file(args.scope_bindings) if args.scope_bindings else None)
            service.close()
            result = service.batch(result['batch_id'])
            print_json(result)
            exits = [result_exit(item['job']) if 'job' in item else 2 for item in result['items']]
            return max(exits, default=2)
        if args.command == "serve":
            from .http import serve
            serve(service, args.host, args.port, args.open)
            return 0
        if args.command == "profiles":
            if args.action == "list":
                print_json({"items": service.profiles.list()})
            elif args.action == "show" and args.value:
                print_json(service.profiles.get(args.value))
            elif args.action == "import" and args.value:
                print_json(service.save_profile(read_json_file(args.value)))
            elif args.action == "preflight" and args.value:
                print_json(service.profile_preflight(args.value, args.kind, args.format))
            else:
                raise ValueError("show/preflight 需提供方案 ID；import 需提供 JSON 路径")
        elif args.command == "schools":
            if args.action == "list":
                print_json(service.schools.list_with_warnings())
            elif args.action == "create":
                print_json(service.schools.create(args.name or ""))
            elif not args.id:
                raise ValueError("请提供学校依据包 ID")
            elif args.action == "show":
                print_json(service.schools.get(args.id))
            elif args.action == "add-source":
                if not args.source:
                    raise ValueError("请使用 --source 提供学校依据文件")
                path = Path(args.source)
                if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
                    raise ValueError("学校依据文件不存在、为空或超过 40MB")
                transcription = ""
                if args.transcription:
                    text = Path(args.transcription)
                    from ..persistence.schools import MAX_TEXT
                    # UTF-8 BOM is removed by the decoder before the shared
                    # domain validation applies its 1MiB text-byte budget.
                    if not text.is_file() or text.stat().st_size > MAX_TEXT + 3:
                        raise ValueError("转录文本不存在或超过 1MiB")
                    transcription = text.read_text(encoding="utf-8-sig")
                print_json(service.schools.add_source(args.id, path.name, path.read_bytes(), args.kind, args.role, transcription))
            else:
                if not args.requirements:
                    raise ValueError("请使用 --requirements 提供审核后的要求 JSON")
                value = read_json_file(args.requirements)
                requirements = value.get("requirements") if isinstance(value, dict) else value
                print_json(service.confirm_school(args.id, requirements, expected_version=args.expected_version))
        elif args.command == "collections":
            if args.action == "list":
                print_json(service.collections.list_with_warnings())
            elif args.action == "create":
                print_json(service.collections.create(args.name or "", args.required_kind))
            elif args.id:
                print_json(service.collection(args.id))
            else:
                raise ValueError("请提供材料集合 ID")
        elif args.command == "plugins":
            print_json({"items": service.registry.list()})
        elif args.command == "doctor":
            print_json(service.doctor())
        elif args.command == "repairs":
            if args.action == "preview":
                if args.plan_id or args.select or args.output:
                    raise ValueError("preview 仅需提供任务 ID")
                print_json(service.repair_plan(args.id))
            else:
                if args.output:
                    output = Path(args.output).resolve()
                    if output.is_relative_to(service.jobs_dir.resolve()):
                        raise ValueError("导出目录不能位于任务存储目录内")
                    if output.exists() and (not output.is_dir() or any(output.iterdir())):
                        raise ValueError("导出目录须为新目录或空目录")
                job = service.repair(args.id, args.plan_id, args.select)
                job = service.run(job["id"])
                report_dir = service.export(job["id"], args.output) if args.output else service.jobs_dir / job["id"]
                print_json({**job, "report_dir": str(report_dir)})
                return result_exit(job)
        elif args.command == "jobs":
            if args.action == "list":
                print_json(service.page(args.limit, args.offset, args.query, args.status))
            elif not args.id:
                raise ValueError("请提供任务ID")
            elif args.action == "show":
                print_json(service.get(args.id))
            elif args.action == 'cancel':
                print_json(service.cancel(args.id))
            else:
                job = service.retry(args.id)
                job = service.run(job["id"])
                print_json(job)
                return result_exit(job)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        message = ("无法读取或写入本机接入配置，请检查数据目录权限"
                   if args.command == "engines" and isinstance(exc, OSError) else str(exc))
        print(f"操作失败：{message}", file=sys.stderr)
        return 2
    finally:
        if service:
            service.close()

