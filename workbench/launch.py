"""Reuse an existing instance instead of launching duplicate servers."""
import json, os, subprocess, sys, urllib.request, webbrowser
from pathlib import Path

def main():
    config=Path(__file__).parent.parent/'.local-config.json'
    if config.exists():
        for key,value in json.loads(config.read_text()).items():
            if key in {'JSW_PORT','JSW_DATA_DIR','JSW_WHISPER_MODEL','JSW_DRAFT_ROOT'}:os.environ.setdefault(key,str(value))
    port=int(os.environ.get('JSW_PORT','8766'));url=f'http://127.0.0.1:{port}'
    try:
        with urllib.request.urlopen(url+'/health',timeout=2) as r:health=json.load(r)
        if health.get('app')!='jianying-subtitle-workbench':raise SystemExit(f'端口 {port} 已被其他应用占用，可设置 JSW_PORT')
        webbrowser.open(url)
    except (OSError,ValueError):
        subprocess.run([sys.executable,'-m','workbench.server','--port',str(port)],check=True)

if __name__=='__main__':main()
