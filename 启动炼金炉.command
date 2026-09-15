#!/bin/zsh
set -u

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -x /opt/homebrew/bin/python3 ]]; then
  PYTHON_BIN="/opt/homebrew/bin/python3"
elif [[ -x /usr/local/bin/python3 ]]; then
  PYTHON_BIN="/usr/local/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "未找到 Python 3，请先安装 Python 3 后再启动炼金炉。"
  exit 1
fi

cd "$APP_DIR" || exit 1
exec "$PYTHON_BIN" "$APP_DIR/app.py"
