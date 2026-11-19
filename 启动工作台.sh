#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
if [ -x .venv/bin/python ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "未找到 Python。请安装 Python 3.11 或更高版本，并将其加入 PATH。"
  exit 2
fi
"$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || {
  echo "Formatly 需要 Python 3.11 或更高版本。请检查当前 Python 或项目 .venv 环境。"
  exit 2
}
exec "$PY" "$PWD/app.py" "$@"
