#!/bin/zsh
# 同步仓库最新代码/前端到调试包（不覆盖调试包的 data/）
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Applications/炼金炉"
rsync -a --delete \
  --exclude='__pycache__' --exclude='dist' --exclude='.workbuddy' --exclude='*.app' \
  --exclude='PROJECT_STATE.md' --exclude='RELEASE_NOTES*' --exclude='照片素材' \
  --exclude='packaging' --exclude='tools' --exclude='.DS_Store' --exclude='data' \
  --exclude='.venv' --exclude='.chromeprofile' \
  "$SRC/" "$DEST/"
mkdir -p "$DEST/data"
echo "已同步代码到 $DEST（data/ 保留调试包现状）"
