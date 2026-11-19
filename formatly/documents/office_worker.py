"""Export one trusted, local snapshot in a newly owned Word/WPS instance."""
from __future__ import annotations

import importlib
from pathlib import Path
import sys

from ..files import write_json
from .office import PROGIDS, validate_office_input
from .processes import managed_windows_process


class OfficeExportError(ValueError):
    def __init__(self, message: str, stage: str, native_type: str, code: object):
        super().__init__(message)
        self.office_stage = stage
        self.native_type = native_type
        self.hresult = code if type(code) is int else None


def export(source: Path, target: Path, progid: str) -> dict:
    if sys.platform != "win32" or progid not in PROGIDS:
        raise ValueError("本机不支持所选 Word/WPS 导出接口")
    validate_office_input(source)
    pythoncom = importlib.import_module("pythoncom")
    client = importlib.import_module("win32com.client")
    win32process = importlib.import_module("win32process")
    win32api = importlib.import_module("win32api")
    pythoncom.CoInitialize()
    application = None
    owned = False
    blank = None
    previous_security = None
    stage = "launch"
    completed: dict | None = None
    try:
        existing = set(win32process.EnumProcesses())
        application = client.DispatchEx(progid)
        stage = "ownership"
        if int(application.Documents.Count) != 0:
            raise ValueError("本地应用复用了已有进程；已停止导出，请自行提供配对 PDF")
        previous_security = application.AutomationSecurity
        application.AutomationSecurity = 3
        # Word exposes HWND on a Window, rather than Application. An empty
        # disposable document establishes process ownership before any input
        # is opened; an existing process is never terminated or closed.
        blank = application.Documents.Add()
        _, pid = win32process.GetWindowThreadProcessId(int(application.ActiveWindow.Hwnd))
        if pid in existing:
            raise ValueError("本地应用复用了已有进程；已停止导出，请自行提供配对 PDF")
        owned = True
        with managed_windows_process(pid):
            document = None
            try:
                stage = "settings"
                application.Visible = False
                application.DisplayAlerts = 0
                application.AutomationSecurity = 3
                handle = win32api.OpenProcess(0x0410, False, pid)
                try:
                    executable = Path(win32process.GetModuleFileNameEx(handle, 0)).name
                finally:
                    handle.Close()
                stage = "open"
                document = application.Documents.Open(str(source.resolve()), ReadOnly=True, AddToRecentFiles=False,
                                                      ConfirmConversions=False)
                document.Repaginate()
                stage = "export"
                document.ExportAsFixedFormat(str(target.resolve()), 17)
                completed = {"status": "completed", "renderer": str(application.Name), "version": str(application.Version),
                             "executable": executable}
            finally:
                try:
                    if document is not None:
                        document.Close(0)
                finally:
                    pending = blank
                    blank = None
                    try:
                        if pending is not None:
                            pending.Close(0)
                    finally:
                        try:
                            application.Quit(0)
                        finally:
                            owned = False
                            application = None
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "本地 Word/WPS 导出失败，请自行提供配对 PDF"
        raise OfficeExportError(message, stage, type(error).__name__, getattr(error, "hresult", None)) from error
    finally:
        try:
            if blank is not None:
                blank.Close(0)
            if application is not None:
                if owned:
                    application.Quit(0)
                elif previous_security is not None:
                    application.AutomationSecurity = previous_security
        finally:
            pythoncom.CoUninitialize()
    if completed is None:
        raise OfficeExportError("本地 Word/WPS 导出失败，请自行提供配对 PDF", stage, "RuntimeError", None)
    return completed


def main() -> int:
    source, target, status = (Path(value) for value in sys.argv[1:4])
    try:
        result = export(source, target, sys.argv[4])
    except Exception as error:
        # Native errors may include local paths or document text. Keep those
        # inside the worker; expose only the actionable, controlled reason.
        message = str(error) if isinstance(error, ValueError) else "本地 Word/WPS 导出失败，请自行提供配对 PDF"
        write_json(status, {"status": "failed", "message": message, "error_type": getattr(error, "native_type", type(error).__name__),
                            "error_code": getattr(error, "hresult", None), "stage": getattr(error, "office_stage", "cleanup")})
        return 1
    write_json(status, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
