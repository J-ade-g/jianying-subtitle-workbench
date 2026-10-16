"""Loopback-only, single-user local workbench. No cloud upload or paid API."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, quote
import argparse, concurrent.futures, json, os, re, shutil, subprocess, sys, threading, uuid, webbrowser
from . import draft
from .pipeline import save, state

WEB=Path(__file__).parent/'web'
DATA=Path(os.environ.get('JSW_DATA_DIR',str(Path.home()/'Library/Application Support/JianyingSubtitleWorkbench'))).expanduser().resolve()
JOBS=concurrent.futures.ThreadPoolExecutor(max_workers=1)
EXPORT_LOCK=threading.Lock()
PORT=8766
MAX_UPLOAD=10*1024**3


def folder_for(pid):
    if not re.fullmatch(r'[a-f0-9]{32}',pid):raise ValueError('无效项目 ID')
    folder=DATA/pid
    if not (folder/'input.json').is_file():raise ValueError('项目不存在')
    return folder


def worker(action,folder):
    try:
        state(folder,'queued','等待本地处理…')
        subprocess.run([sys.executable,'-m','workbench.pipeline',action,str(folder)],check=True)
    except Exception as exc:
        try:
            current=json.loads((folder/'status.json').read_text())
            if current['status']!='error':state(folder,'error',str(exc))
        except Exception:pass


class Handler(SimpleHTTPRequestHandler):
    def log_message(self,fmt,*args):
        # Avoid query strings and original filenames in routine terminal logs.
        print(f'{self.command} {urlparse(self.path).path}: {args[1] if len(args)>1 else ""}',flush=True)

    def json(self,value,status=200):
        content=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(content)

    def body(self):
        n=int(self.headers.get('Content-Length',0))
        if not 0<n<=3_000_000:raise ValueError('请求大小无效')
        return json.loads(self.rfile.read(n))

    def allowed(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{PORT}',f'localhost:{PORT}'}:return False
        origin=self.headers.get('Origin')
        return not origin or origin in {f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}

    def do_GET(self):
        if not self.allowed():self.send_error(403);return
        path=unquote(urlparse(self.path).path)
        try:
            if path=='/health':return self.json({'app':'jianying-subtitle-workbench','version':'0.1.0'})
            if path=='/api/projects':
                items=[]
                for f in DATA.glob('*/input.json'):
                    meta=json.loads(f.read_text());status=json.loads((f.parent/'status.json').read_text());items.append({**meta,**status})
                return self.json(sorted(items,key=lambda p:p.get('updated_at',''),reverse=True))
            if path=='/api/environment':return self.json({'ffmpeg':bool(shutil.which('ffmpeg')),'ffprobe':bool(shutil.which('ffprobe')),'data_dir':str(DATA),'model':os.environ.get('JSW_WHISPER_MODEL','mlx-community/whisper-large-v3-turbo')})
            m=re.fullmatch(r'/api/projects/([a-f0-9]{32})(?:/(suggestions|transcript))?',path)
            if m:
                folder=folder_for(m[1]);what=m[2] or 'status'
                if what=='transcript':return self.json({'text':(folder/'逐字稿_识别原文.txt').read_text()})
                return self.json(json.loads((folder/(what+'.json')).read_text()))
            if path in ['/','/home.js','/style.css']:
                return self.file(WEB/('home.html' if path=='/' else path[1:]))
            m=re.fullmatch(r'/p/([a-f0-9]{32})/(.+)',path)
            if not m:self.send_error(404);return
            folder=folder_for(m[1]);relative=m[2]
            if relative=='字幕审阅.html':
                p=json.loads((folder/'字幕项目_已修改.json').read_text());embedded=json.dumps(p,ensure_ascii=False).replace('</','<\\/')
                html=(WEB/'editor.html').read_text().replace('__PROJECT_JSON__',embedded).replace('__EDITOR_JS__',(WEB/'editor.js').read_text())
                return self.bytes(html.encode(),'text/html; charset=utf-8')
            target=(folder/relative).resolve()
            if not target.is_relative_to(folder.resolve()):self.send_error(403);return
            if target.suffix not in {'.mp4','.md','.json','.srt','.ass','.jpg'}:self.send_error(403);return
            return self.file(target)
        except (ValueError,FileNotFoundError) as exc:self.json({'error':str(exc)},404)
        except Exception as exc:self.json({'error':str(exc)},400)

    def do_POST(self):
        if not self.allowed():self.send_error(403);return
        path=unquote(urlparse(self.path).path)
        try:
            if path=='/api/projects':
                body=self.body();filename=Path(body.get('filename','video.mp4')).name
                if Path(filename).suffix.lower() not in {'.mp4','.mov','.mkv','.webm','.m4v'}:raise ValueError('请选择 MP4、MOV、MKV 或 WebM 视频')
                opts=body.get('options',{});opts={'max_chars':max(10,min(40,int(opts.get('max_chars',22)))),'keywords':str(opts.get('keywords',''))[:2000],'prompt':str(opts.get('prompt',''))[:1500]}
                pid=uuid.uuid4().hex;folder=DATA/pid;folder.mkdir();save(folder/'input.json',{'id':pid,'filename':filename,'options':opts});state(folder,'created','等待导入视频')
                return self.json({'id':pid},201)
            m=re.fullmatch(r'/api/projects/([a-f0-9]{32})/(video|finalize)',path)
            if m:
                folder=folder_for(m[1]);status=json.loads((folder/'status.json').read_text())['status']
                if m[2]=='video':
                    if status!='created':raise ValueError('项目已经接收视频，请新建项目')
                    n=int(self.headers.get('Content-Length',0))
                    if not 0<n<=MAX_UPLOAD:raise ValueError('视频为空或超过 10GB 限制')
                    state(folder,'uploading','正在接收本机视频…')
                    with (folder/'upload.bin').open('xb') as f:
                        left=n
                        while left:
                            block=self.rfile.read(min(left,1024*1024))
                            if not block:raise ValueError('导入中断，请重新创建项目')
                            f.write(block);left-=len(block)
                    JOBS.submit(worker,'analyze',folder);return self.json({'queued':True})
                if status!='review':raise ValueError('请等待识别完成；每次确认只生成一次预剪版本')
                ids=set(self.body().get('selected',[]));suggestions=json.loads((folder/'suggestions.json').read_text())
                if ids-{c['id'] for c in suggestions}:raise ValueError('未知删除区间')
                save(folder/'selected_cuts.json',[c for c in suggestions if c['id'] in ids]);state(folder,'queued','等待生成预剪视频…');JOBS.submit(worker,'finalize',folder);return self.json({'queued':True})
            m=re.fullmatch(r'/p/([a-f0-9]{32})/export/(project|srt|ass|jianying)',path)
            if not m:self.send_error(404);return
            folder=folder_for(m[1]);kind=m[2];content=self.body()['content']
            if not isinstance(content,str):raise ValueError('内容无效')
            if kind in {'project','jianying'}:
                project=json.loads(content)
                if project.get('id')!=m[1]:raise ValueError('项目不匹配')
                draft.validate_project(project)
            if kind=='jianying':
                if draft.jianying_running():return self.json({'needs_exit':True,'message':'请先保存并退出剪映，再点击导出。导出完成后重开剪映首页。'},409)
                if not EXPORT_LOCK.acquire(False):raise ValueError('另一个草稿正在导出，请稍候')
                try:
                    draft.OUTPUT=folder
                    result=draft.install(draft.generate(project));save(folder/'字幕项目_已修改.json',project)
                    result['instructions_url']='/p/'+m[1]+'/剪映草稿/'+quote(result['name'])+'/使用说明.md'
                    return self.json(result)
                finally:EXPORT_LOCK.release()
            filename={'project':'字幕项目_已修改.json','srt':'字幕_已修改.srt','ass':'重点字幕_已修改.ass'}[kind]
            temp=folder/(filename+'.tmp');temp.write_text(content,encoding='utf-8');temp.replace(folder/filename);return self.json({'filename':filename})
        except Exception as exc:self.json({'error':str(exc)},400)

    def bytes(self,data,content_type):
        self.send_response(200);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-cache');self.end_headers();self.wfile.write(data)

    def file(self,path):
        size=path.stat().st_size;start=0;end=size-1;r=self.headers.get('Range');partial=False
        if r:
            m=re.fullmatch(r'bytes=(\d+)-(\d*)',r)
            if not m:self.send_error(416);return
            start=int(m[1]);end=min(end,int(m[2]) if m[2] else end);partial=True
            if start>end:self.send_error(416);return
        self.send_response(206 if partial else 200);self.send_header('Content-Type',self.guess_type(str(path))+'; charset=utf-8' if path.suffix in {'.html','.js','.css','.md'} else self.guess_type(str(path)));self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-cache')
        if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as f:
                f.seek(start);left=end-start+1
                while left:
                    b=f.read(min(left,256*1024));self.wfile.write(b);left-=len(b)
        except (BrokenPipeError,ConnectionResetError):pass


def main():
    global PORT
    ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=8766);ap.add_argument('--no-open',action='store_true');args=ap.parse_args();PORT=args.port;DATA.mkdir(parents=True,exist_ok=True)
    # Interrupted workers do not silently stay in a permanent running state.
    for path in DATA.glob('*/status.json'):
        old=json.loads(path.read_text())
        if old['status'] in {'uploading','queued','analyzing','rendering'}:state(path.parent,'error','上次处理被中断。原文件已保留，请重新导入创建项目。')
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler);print(f'字幕工作台：http://127.0.0.1:{PORT}\n项目目录：{DATA}',flush=True)
    if not args.no_open:webbrowser.open(f'http://127.0.0.1:{PORT}')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();JOBS.shutdown(wait=False)


if __name__=='__main__':main()
