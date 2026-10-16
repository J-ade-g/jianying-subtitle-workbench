#!/bin/zsh
set -e
cd -- "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "当前版本仅支持 Apple Silicon Mac。"; read -k 1; exit 1
fi
if ! command -v ffmpeg >/dev/null; then
  echo "请先安装 FFmpeg：brew install ffmpeg"; read -k 1; exit 1
fi
if [[ -z "$JSW_PYTHON" ]]; then
  for candidate in python3.12 python3.11 /opt/homebrew/opt/python@3.12/bin/python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      JSW_PYTHON="$candidate"; break
    fi
  done
fi
"$JSW_PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "需要 Python 3.11 或更新版本；可先运行 brew install python@3.12，并设置 JSW_PYTHON"'
"$JSW_PYTHON" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
echo "安装完成。双击 启动工作台.command 开始使用。"
read -k 1
