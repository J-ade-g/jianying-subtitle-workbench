# -*- coding: utf-8 -*-
"""Build independent, editable Mac Jianying 11.6 drafts from the review project."""
from copy import deepcopy
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse,json,math,shutil,time,uuid,os,subprocess

WORK=Path(__file__).resolve().parent
OUTPUT=Path(os.environ.get('JSW_PROJECT_DIR','.')).resolve()
DRAFT_ROOT=Path(os.environ.get('JSW_DRAFT_ROOT',str(Path.home()/'Movies/JianyingPro/User Data/Projects/com.lveditor.draft'))).expanduser()
TEMPLATE=WORK/'templates/mac_11_6.json'
def ident():return str(uuid.uuid4()).upper()
def us(value):return round(value*1_000_000)
def utf16len(s):return len(s.encode('utf-16-le'))//2
def write_json(p,data):p.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
def atomic_json(p,data):
    tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    try:write_json(tmp,data);os.replace(tmp,p)
    finally:
        if tmp.exists():tmp.unlink()
def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def jianying_running():
    result=subprocess.run(['/usr/bin/pgrep','-f','/Applications/VideoFusion-macOS.app/Contents/MacOS/VideoFusion-macOS'],capture_output=True)
    if result.returncode not in [0,1]:raise RuntimeError('无法检查剪映运行状态，请确认本机进程访问权限')
    return result.returncode==0
def require_jianying_closed():
    if jianying_running():raise ValueError('请先保存当前剪映项目并退出剪映，再点击“导出到剪映”。导出后重新打开剪映首页。')
def valid_style(s):
    c=s.get('color','')
    try:ok=isinstance(c,str) and len(c)==7 and c[0]=='#' and 0<=int(c[1:],16)<=0xffffff
    except ValueError:ok=False
    return ok and isinstance(s.get('bold'),bool) and finite(s.get('scale')) and .8<=s['scale']<=1.8
def validate_project(p):
    if not isinstance(p.get('id'),str) or not p['id']:raise ValueError('项目 ID 无效')
    if not finite(p.get('duration')) or not 0<p['duration']<=7200:raise ValueError('项目时长无效')
    styles=p.get('styles',{})
    if not styles or not all(valid_style(s) for s in styles.values()):raise ValueError('样式无效')
    kept=p.get('kept',[])
    if not kept:raise ValueError('缺少原片剪切映射')
    end=0;source_end=0
    for k in kept:
        if not all(finite(k.get(n)) for n in ['source_start','source_end','output_start','output_end']):raise ValueError('剪切时间无效')
        if k['source_start']<source_end-1e-5 or k['source_end']<=k['source_start'] or k['source_end']>p['source_duration']+.001:raise ValueError('原片区间无效')
        if abs(k['output_start']-end)>.0001 or abs(k['output_end']-k['output_start']-k['source_end']+k['source_start'])>.0001:raise ValueError('清理后时间轴不连续')
        source_end=k['source_end'];end=k['output_end']
    if abs(end-p['duration'])>.0001:raise ValueError('项目时长与剪切映射不一致')
    end=0
    if not p.get('captions'):raise ValueError('没有字幕')
    for c in p['captions']:
        if not isinstance(c.get('text'),str) or not c['text'] or not finite(c.get('start')) or not finite(c.get('end')):raise ValueError('字幕内容无效')
        if c['start']<end-.0001 or c['end']<=c['start'] or c['end']>p['duration']+.001:raise ValueError('字幕时间无效')
        end=c['end'];n=utf16len(c['text']);last=0
        for e in sorted(c.get('emphasis',[]),key=lambda e:e['start']):
            if e.get('style') not in styles or not isinstance(e.get('start'),int) or not isinstance(e.get('end'),int) or not last<=e['start']<e['end']<=n:raise ValueError('重点区间无效')
            if not valid_style({**styles[e['style']],**e.get('overrides',{})}):raise ValueError('单处重点样式无效')
            last=e['end']

def style_runs(c,p,font):
    n=utf16len(c['text']);points={0,n}
    for e in c.get('emphasis',[]):points.update([e['start'],e['end']])
    points=sorted(points);runs=[]
    for a,b in zip(points,points[1:]):
        e=next((e for e in c.get('emphasis',[]) if e['start']<=a and e['end']>=b),None)
        st={**p['styles'][e['style']],**e.get('overrides',{})} if e else {'color':'#ffffff','bold':False,'scale':1.0}
        h=st['color'].lstrip('#');color=[int(h[i:i+2],16)/255 for i in [0,2,4]]
        runs.append({'range':[a,b],'size':p.get('subtitle_size',44)/6*st['scale'],'bold':st['bold'],'italic':False,'underline':False,'useLetterColor':True,'font':{'id':'','path':font},'fill':{'alpha':1.0,'content':{'render_type':'solid','solid':{'alpha':1.0,'color':color}}},'strokes':[{'width':.04,'mode':0,'content':{'render_type':'solid','solid':{'alpha':1.0,'color':[0,0,0]}}}]})
    return runs

def generate(p):
    validate_project(p)
    t=json.loads(TEMPLATE.read_text());now=time.time_ns()//1000
    name='口播预剪_'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:4]
    parent=(OUTPUT/'剪映草稿').resolve();parent.mkdir(exist_ok=True)
    target=parent/name;target.mkdir()
    try:
        (target/'Resources').mkdir()
        source=OUTPUT/'original.mp4'
        if not source.is_file():raise ValueError('原视频缺失，请恢复工作台 original.mp4')
        shutil.copy2(source,target/'Resources/original.mp4')
        cover=OUTPUT/'frame.jpg'
        if cover.exists():shutil.copy2(cover,target/'draft_cover.jpg')
        font=t['text_material']['font_path']
        if not Path(font).exists():raise ValueError('剪映系统字体未找到，请检查应用安装位置')
        doc=deepcopy(t['document']);doc.update(id=ident(),name=name,duration=us(p['duration']),fps=60.,create_time=now//1_000_000,update_time=now//1_000_000,path=str(target),cover='draft_cover.jpg')
        doc['canvas_config']={'width':p['width'],'height':p['height'],'ratio':'original'}
        doc['fps']=float(p.get('source_fps',30))
        doc['static_cover_image_path']='';doc['retouch_cover']=None
        doc['materials']={k:[] for k in doc['materials']}
        video_track=deepcopy(t['video_track']);video_track.update(id=ident(),name='预剪视频（原片可回调）',is_default_name=False,segments=[])
        text_track=deepcopy(t['text_track']);text_track.update(id=ident(),name='字幕与重点',is_default_name=False,segments=[])
        for k in p['kept']:
            material=deepcopy(t['video_material']);material.update(id=ident(),local_material_id=ident(),material_name='original.mp4',path=str(target/'Resources/original.mp4'),duration=us(p['source_duration']),width=p['width'],height=p['height'])
            doc['materials']['videos'].append(material)
            seg=deepcopy(t['video_segment']);seg.update(id=ident(),material_id=material['id'],source_timerange={'start':us(k['source_start']),'duration':us(k['source_end'])-us(k['source_start'])},target_timerange={'start':us(k['output_start']),'duration':us(k['output_end'])-us(k['output_start'])},extra_material_refs=[],speed=1.,volume=1.,last_nonzero_volume=1.)
            for kind,aux in t['video_aux']:
                new=deepcopy(aux);new['id']=ident();doc['materials'][kind].append(new);seg['extra_material_refs'].append(new['id'])
            fade={'id':ident(),'type':'audio_fade','fade_in_duration':3000,'fade_out_duration':3000,'fade_type':0};doc['materials']['audio_fades'].append(fade);seg['extra_material_refs'].append(fade['id'])
            video_track['segments'].append(seg)
        group='Auto_'+str(now//1000)
        for c in p['captions']:
            material=deepcopy(t['text_material']);content={'text':c['text'],'styles':style_runs(c,p,font)}
            material.update(id=ident(),content=json.dumps(content,ensure_ascii=False),base_content=json.dumps(content,ensure_ascii=False),recognize_text=c['text'],recognize_model='',recognize_task_id='',group_id=group,fonts=[],font_size=p.get('subtitle_size',44)/6,text_size=p.get('subtitle_size',44),font_id='',font_resource_id='',font_title='系统',font_name='',font_path=font,background_alpha=0.,check_flag=15,has_shadow=False,subtitle_keywords={'range':[{'location':e['start'],'length':e['end']-e['start'],'source_type':'manual'} for e in c.get('emphasis',[])]})
            material['words']={'start_time':[],'end_time':[],'text':[]};material['current_words']={'start_time':[],'end_time':[],'text':[]}
            doc['materials']['texts'].append(material)
            seg=deepcopy(t['text_segment']);seg.update(id=ident(),material_id=material['id'],extra_material_refs=[],target_timerange={'start':us(c['start']),'duration':us(c['end'])-us(c['start'])},render_index=14000,track_render_index=1)
            seg['clip']['scale']={'x':1.,'y':1.};seg['clip']['transform']={'x':0.,'y':-.76};seg['common_keyframes']=[]
            text_track['segments'].append(seg)
        doc['tracks']=[video_track,text_track]
        meta=deepcopy(t['meta']);meta.update(draft_id=doc['id'],draft_name=name,draft_fold_path=str(target),draft_root_path=str(parent),draft_cover='draft_cover.jpg',tm_draft_create=now,tm_draft_modified=now,tm_duration=doc['duration'])
        meta['draft_timeline_materials_size_']=(target/'Resources/original.mp4').stat().st_size
        write_json(target/'draft_info.json',doc);write_json(target/'draft_meta_info.json',meta)
        write_json(target/'字幕项目.json',p)
        report=validate_draft(target,p)
        write_json(target/'导出检查.json',report)
        (target/'使用说明.md').write_text(f'# {name}\n\n视频 {len(video_track["segments"])} 个片段；字幕 {len(p["captions"])} 句；时长 {p["duration"]:.3f} 秒。\n\n1. 保存当前剪映项目并退出剪映。\n2. 在工作台点击“导出到剪映”，等待成功提示。\n3. 重新打开剪映，在首页打开提示中的同名草稿。\n\n视频引用原片的保留区间；字幕和局部重点是独立文本对象，可继续编辑。无需分别导入 JSON、SRT。工作台 JSON 用于回到工作台继续修改。\n\n每次导出创建一个新工程，已有工程不会覆盖。剪映内后续修改暂不回传工作台。所有素材在 Resources 中，移动草稿后需要重新定位素材路径。\n\n此目录为导出备份，剪映使用的是本机草稿目录中的安装副本。结构检查已通过；实际打开、修改、保存重开的兼容性以本机验证为准。\n',encoding='utf-8')
        return {'name':name,'draft_id':doc['id'],'output_path':str(target),'video_segments':len(video_track['segments']),'captions':len(p['captions']),'duration':p['duration'],'checks':report}
    except Exception:
        shutil.rmtree(target);raise

def validate_draft(folder,p):
    d=json.loads((folder/'draft_info.json').read_text());materials={v['id']:v for vs in d['materials'].values() if isinstance(vs,list) for v in vs if 'id' in v}
    if len(materials)!=sum(len(vs) for vs in d['materials'].values() if isinstance(vs,list)):raise ValueError('重复素材 ID')
    for track in d['tracks']:
        end=0
        for seg in track['segments']:
            a=seg['target_timerange']['start'];b=a+seg['target_timerange']['duration']
            if a<end-2 or b<=a or b>d['duration']+2:raise ValueError('轨道片段时间错误')
            end=b
            if seg['material_id'] not in materials or any(ref not in materials for ref in seg['extra_material_refs']):raise ValueError('素材引用缺失')
    expected=p['captions'];actual=d['materials']['texts']
    if len(expected)!=len(actual):raise ValueError('字幕数量不符')
    for c,m in zip(expected,actual):
        content=json.loads(m['content']);n=utf16len(c['text'])
        if content['text']!=c['text']:raise ValueError('字幕文字不符')
        last=0
        for run in content['styles']:
            if run['range'][0]!=last:raise ValueError('文字样式区间不连续')
            last=run['range'][1]
        if last!=n:raise ValueError('文字样式未覆盖整句')
        for e in c.get('emphasis',[]):
            st={**p['styles'][e['style']],**e.get('overrides',{})}
            matching=[r for r in content['styles'] if e['start']<=r['range'][0] and r['range'][1]<=e['end']]
            if not matching or any(abs(r['size']-p.get('subtitle_size',44)/6*st['scale'])>1e-8 or r['bold']!=st['bold'] for r in matching):raise ValueError('重点样式不符')
            h=st['color'].lstrip('#');expected_color=[int(h[i:i+2],16)/255 for i in [0,2,4]]
            if any(any(abs(a-b)>1e-8 for a,b in zip(r['fill']['content']['solid']['color'],expected_color)) for r in matching):raise ValueError('重点颜色不符')
    if any(not Path(m['path']).is_file() for m in d['materials']['videos']):raise ValueError('原片路径不可用')
    return {'structural_validation':'passed','video_segments':len(d['tracks'][0]['segments']),'captions':len(actual),'rich_text_captions':sum(len(json.loads(m['content'])['styles'])>1 for m in actual),'app_open_test':'pending'}

def install(result):
    require_jianying_closed()
    source=Path(result['output_path']).resolve()
    if source.parent!= (OUTPUT/'剪映草稿').resolve():raise ValueError('无效草稿目录')
    root=DRAFT_ROOT.resolve()
    if not root.is_dir():raise ValueError('剪映草稿目录不存在')
    target=root/result['name']
    if target.exists():raise ValueError('同名草稿已存在，拒绝覆盖')
    registry=root/'root_meta_info.json'
    data=json.loads(registry.read_text())
    if not isinstance(data.get('all_draft_store'),list):raise ValueError('剪映草稿索引无效')
    (OUTPUT/'backups').mkdir(exist_ok=True)
    backup=OUTPUT/'backups'/('root_meta_'+str(time.time_ns())+'.json');shutil.copy2(registry,backup)
    staging=root/('.pending_'+uuid.uuid4().hex)
    try:
        shutil.copytree(source,staging)
        def relocate(x):
            if isinstance(x,str):return x.replace(str(source),str(target))
            if isinstance(x,list):return [relocate(v) for v in x]
            if isinstance(x,dict):return {k:relocate(v) for k,v in x.items()}
            return x
        for file in ['draft_info.json','draft_meta_info.json']:
            d=relocate(json.loads((staging/file).read_text()))
            if file=='draft_meta_info.json':d['draft_root_path']=str(root)
            write_json(staging/file,d)
        staging.rename(target)
        meta=json.loads((target/'draft_meta_info.json').read_text())
        entry=deepcopy(json.loads(TEMPLATE.read_text())['root_entry'])
        for k in list(entry):
            if k in meta:entry[k]=meta[k]
        entry.update(draft_cover=str(target/'draft_cover.jpg'),draft_json_file=str(target/'draft_info.json'),draft_root_path=str(root),draft_timeline_materials_size=(target/'Resources/original.mp4').stat().st_size)
        # Merge the latest index again rather than writing a stale copy.
        latest=json.loads(registry.read_text());latest['all_draft_store'].insert(0,entry);latest['draft_ids']=len(latest['all_draft_store']);atomic_json(registry,latest)
        result.update(installed_path=str(target),registered=True)
        write_json(source/'导出结果.json',result)
        write_json(OUTPUT/'最近剪映导出.json',result)
        return result
    except Exception:
        if staging.exists():shutil.rmtree(staging)
        # A fully written draft is left recoverable if index registration fails.
        raise

def register_existing(result):
    """Restore the index for an already-copied draft, without changing its contents."""
    require_jianying_closed()
    target=Path(result['installed_path']).resolve()
    if target.parent!=DRAFT_ROOT.resolve() or not (target/'draft_info.json').is_file():raise ValueError('草稿路径无效')
    meta=json.loads((target/'draft_meta_info.json').read_text())
    if meta['draft_id']!=result['draft_id']:raise ValueError('草稿 ID 不符')
    registry=DRAFT_ROOT/'root_meta_info.json';current=json.loads(registry.read_text())
    (OUTPUT/'backups').mkdir(exist_ok=True)
    backup=OUTPUT/'backups'/('root_meta_'+str(time.time_ns())+'.json');shutil.copy2(registry,backup)
    entry=deepcopy(json.loads(TEMPLATE.read_text())['root_entry'])
    for key in entry:
        if key in meta:entry[key]=meta[key]
    entry.update(draft_cover=str(target/'draft_cover.jpg'),draft_json_file=str(target/'draft_info.json'),draft_root_path=str(DRAFT_ROOT),draft_timeline_materials_size=(target/'Resources/original.mp4').stat().st_size)
    current['all_draft_store']=[e for e in current['all_draft_store'] if e.get('draft_id')!=result['draft_id'] and e.get('draft_fold_path')!=str(target)]
    current['all_draft_store'].insert(0,entry);current['draft_ids']=len(current['all_draft_store']);atomic_json(registry,current)
    result['registered']=True;write_json(OUTPUT/'最近剪映导出.json',result);return result
