#!/bin/zsh
set -e
cd -- "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "请先双击 安装依赖.command；也可按 README 在终端安装。"; read -k 1; exit 1
fi
exec .venv/bin/python -m workbench.launch
