"""Local ASR, reviewable cut suggestions, and portable subtitle projects."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, json, math, os, re, shutil, subprocess, traceback, uuid


def save(path, value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def state(folder, status, message, **extra):
    old=json.loads((folder/'status.json').read_text()) if (folder/'status.json').exists() else {}
    save(folder/'status.json',{**old,'status':status,'message':message,'updated_at':datetime.now(timezone.utc).isoformat(),**extra})


def command(args, log):
    with open(log,'a') as f:
        subprocess.run(args,stdout=f,stderr=f,check=True)


def probe(path):
    r=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True)
    info=json.loads(r.stdout);v=next(s for s in info['streams'] if s['codec_type']=='video')
    if not any(s['codec_type']=='audio' for s in info['streams']):raise ValueError('视频没有音轨，无法识别逐字稿')
    a,b=map(float,v.get('avg_frame_rate','30/1').split('/'));fps=a/b if b and a else 30
    duration=float(info['format']['duration'])
    if not 0<duration<=7200:raise ValueError('当前支持 2 小时以内的视频')
    rotation=int(v.get('tags',{}).get('rotate',0))
    for x in v.get('side_data_list',[]):rotation=int(x.get('rotation',rotation))
    w,h=int(v['width']),int(v['height'])
    if abs(rotation)%180==90:w,h=h,w
    return {'source_duration':duration,'source_fps':fps,'width':w,'height':h}


def candidates(raw, silence_log, duration, fps):
    suggestions=[]
    def add(a,b,kind,reason,selected=False):
        a=max(0,round(a*fps)/fps);b=min(duration,round(b*fps)/fps)
        if b-a>=.08:suggestions.append({'id':str(uuid.uuid4()),'start':a,'end':b,'kind':kind,'reason':reason,'selected':selected})
    for match in re.finditer(r'silence_end: ([\d.]+) \| silence_duration: ([\d.]+)',silence_log):
        end,d=map(float,match.groups());start=end-d
        if d>.85:
            add(start+.25,end-.25,'停顿缩短',f'检测到 {d:.2f} 秒低音量区间，保留约 0.5 秒；请试听',True)
    words=[w for s in raw.get('segments',[]) for w in s.get('words',[])]
    for i,w in enumerate(words):
        text=re.sub(r'[\s，。！？、,.!?]','',w['word'])
        if text in {'嗯','呃','额','啊'}:add(w['start'],w['end'],'疑似语气词',text+'：需要确认是否表达语气')
        if i and len(text)>=2:
            prev=words[i-1];previous=re.sub(r'[\s，。！？、,.!?]','',prev['word'])
            if previous==text and w['start']-prev['end']<.4:
                add(prev['start'],prev['end'],'疑似重复',f'相邻两次“{text}”，建议保留后一次；需人工确认')
    return sorted(suggestions,key=lambda c:(c['start'],c['end']))


def analyze(folder):
    meta=json.loads((folder/'input.json').read_text());opts=meta.get('options',{})
    state(folder,'analyzing','检查视频并提取音频…')
    info=probe(folder/'upload.bin')
    # Normalize rotation/container once; the draft's original.mp4 is this full-length source.
    command(['ffmpeg','-nostdin','-y','-i',str(folder/'upload.bin'),'-map','0:v:0','-map','0:a:0','-vf','scale=ceil(iw/2)*2:ceil(ih/2)*2','-r',str(info['source_fps']),'-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac','-b:a','192k','-movflags','+faststart',str(folder/'original.mp4')],folder/'processing.log')
    info=probe(folder/'original.mp4');save(folder/'media.json',info)
    command(['ffmpeg','-nostdin','-y','-i',str(folder/'original.mp4'),'-vn','-ac','1','-ar','16000',str(folder/'audio.wav')],folder/'processing.log')
    state(folder,'analyzing','本机 Whisper 正在识别；首次运行会下载模型，请耐心等待…')
    import mlx_whisper
    model=os.environ.get('JSW_WHISPER_MODEL','mlx-community/whisper-large-v3-turbo')
    raw=mlx_whisper.transcribe(str(folder/'audio.wav'),path_or_hf_repo=model,language='zh',word_timestamps=True,condition_on_previous_text=False,verbose=False,initial_prompt=opts.get('prompt','中文口播视频，保留重复、语气词和原声表达。'))
    save(folder/'asr.json',raw)
    state(folder,'analyzing','检测长停顿和可疑重复…')
    command(['ffmpeg','-nostdin','-i',str(folder/'original.mp4'),'-af','silencedetect=noise=-35dB:d=0.8','-f','null','-'],folder/'silence.log')
    plan=candidates(raw,(folder/'silence.log').read_text(),info['source_duration'],info['source_fps'])
    save(folder/'suggestions.json',plan)
    (folder/'逐字稿_识别原文.txt').write_text(raw.get('text',''),encoding='utf-8')
    state(folder,'review','识别完成，请试听并勾选要删除的区间。语气词和重复默认保留，避免误删。')


def cut_map(duration,cuts):
    merged=[]
    for c in sorted(cuts,key=lambda c:c['start']):
        if not math.isfinite(c['start']) or not math.isfinite(c['end']) or not 0<=c['start']<c['end']<=duration:raise ValueError('剪切区间无效')
        if merged and c['start']<=merged[-1]['end']:
            merged[-1]['end']=max(merged[-1]['end'],c['end'])
            merged[-1]['reason']+='；'+c['reason']
        else:merged.append(dict(c))
    kept=[];source=0;output=0
    for c in merged+[{'start':duration,'end':duration}]:
        if c['start']>source:
            end=output+c['start']-source
            kept.append({'source_start':source,'source_end':c['start'],'output_start':output,'output_end':end});output=end
        source=max(source,c['end'])
    if output<.5:raise ValueError('保留内容过短，请减少删减')
    return merged,kept,output


def u16(s):return len(s.encode('utf-16-le'))//2


def build_project(raw,info,cuts,meta):
    cuts,kept,duration=cut_map(info['source_duration'],cuts)
    def mapped(t):
        for k in kept:
            if k['source_start']<=t<=k['source_end']:return k['output_start']+t-k['source_start']
        return sum(max(0,min(t,k['source_end'])-k['source_start']) for k in kept)
    events=[];punctuation='，。！？；、,.!?;\n'
    for seg in raw.get('segments',[]):
        words=seg.get('words') or [{'word':seg['text'],'start':seg['start'],'end':seg['end']}]
        for word in words:
            a,b=float(word['start']),float(word['end']);text=word['word']
            if any(c['start']<= (a+b)/2<c['end'] for c in cuts):continue
            for j,ch in enumerate(text):
                if ch in punctuation:
                    if events:events[-1]['boundary']=True
                    continue
                if ch.isspace() and (not events or events[-1]['ch'].isspace()):continue
                start=mapped(a+(b-a)*j/max(1,len(text)));end=mapped(a+(b-a)*(j+1)/max(1,len(text)))
                if end>start:events.append({'ch':ch,'start':start,'end':end,'boundary':False})
        if events:events[-1]['boundary']=True
    while events and events[-1]['ch'].isspace():events.pop()
    if not events:raise ValueError('没有识别到有效语音，请检查音轨或换一个视频')
    # Whisper timestamps may overlap. Build ordered starts and leave a small positive interval.
    n=len(events);epsilon=min(.001,duration/(2*n))
    for i,e in enumerate(events):e['start']=min(duration-(n-i)*epsilon,max(events[i-1]['start']+epsilon if i else 0,e['start']))
    for i,e in enumerate(events):e['end']=max(e['start']+epsilon,min(events[i+1]['start'] if i+1<n else duration,e['end']))
    maxchars=max(10,min(40,int(meta.get('options',{}).get('max_chars',22))))
    groups=[];buf=[]
    for i,e in enumerate(events):
        if buf and e['start']-buf[-1]['end']>.65:groups.append(buf);buf=[]
        buf.append(e)
        # Avoid splitting ASCII words; a very long ASCII word can exceed the target length.
        nextch=events[i+1]['ch'] if i+1<n else ''
        ascii_word=e['ch'].isascii() and e['ch'].isalnum() and nextch.isascii() and nextch.isalnum()
        if (e['boundary'] or len(buf)>=maxchars) and not ascii_word:groups.append(buf);buf=[]
    if buf:groups.append(buf)
    styles={'focus':{'name':'重点 · 黄色加粗','color':'#ffd65a','bold':True,'scale':1.0},'term':{'name':'关键词 · 浅蓝','color':'#8dd6ff','bold':True,'scale':1.0},'number':{'name':'数字 · 橙色','color':'#ffc28a','bold':True,'scale':1.06}}
    keywords=[s.strip() for s in re.split(r'[,，\n]',meta.get('options',{}).get('keywords','')) if s.strip()]
    captions=[]
    for group in groups:
        while group and group[0]['ch'].isspace():group=group[1:]
        while group and group[-1]['ch'].isspace():group=group[:-1]
        if not group:continue
        text=''.join(e['ch'] for e in group);emphasis=[]
        matches=[(m.start(),m.end(),'number') for m in re.finditer(r'\d+(?:\.\d+)?(?:%|％|万|亿|千|元|条|个|倍|秒|分钟)?',text)]
        for word in keywords:
            matches.extend((m.start(),m.end(),'term') for m in re.finditer(re.escape(word),text))
        for signal in ['最重要','关键','核心','必须','注意']:
            at=text.find(signal)
            if at>=0:matches.append((at,min(len(text),at+10),'focus'))
        for a,b,style in sorted(matches,key=lambda x:({'term':0,'number':1,'focus':2}[x[2]],x[0],-(x[1]-x[0]))):
            a,b=u16(text[:a]),u16(text[:b])
            if not any(a<e['end'] and b>e['start'] for e in emphasis):emphasis.append({'start':a,'end':b,'style':style})
        emphasis.sort(key=lambda e:e['start'])
        times=[]
        for e in group:
            for j in range(u16(e['ch'])):times.append({'start':e['start']+(e['end']-e['start'])*j/u16(e['ch']),'end':e['start']+(e['end']-e['start'])*(j+1)/u16(e['ch'])})
        captions.append({'id':str(uuid.uuid4()),'text':text,'start':group[0]['start'],'end':group[-1]['end'],'char_times':times,'emphasis':emphasis})
    return {'schema_version':1,'id':meta['id'],'title':meta['filename'],'source_filename':meta['filename'],**info,'duration':duration,'subtitle_size':max(24,round(info['width']*.023)),'styles':styles,'cuts':cuts,'kept':kept,'captions':captions,'review_notes':['语音识别可能存在错字，请试听核对。','断句由标点、停顿和字数规则生成；重点由关键词、数字和提示词规则生成，不代表语义模型判断。','复杂改口、纠正和口误需要人工核对，本工具不会自动改写原声。','剪映导出针对 Mac 11.6.0；已验证原型可打开和显示重点，未完成所有编辑与保存重开测试。'],'status':'awaiting_user_review','jianying_draft_generated':False}


def finalize(folder):
    state(folder,'rendering','生成预剪视频和可编辑字幕…')
    meta=json.loads((folder/'input.json').read_text());info=json.loads((folder/'media.json').read_text());raw=json.loads((folder/'asr.json').read_text());cuts=json.loads((folder/'selected_cuts.json').read_text())
    project=build_project(raw,info,cuts,meta);save(folder/'字幕项目_已修改.json',project)
    if cuts:
        ranges=project['kept'];n=len(ranges)
        vf='+'.join(f'between(t,{k["source_start"]:.9f},{k["source_end"]-1e-9:.9f})' for k in ranges)
        # Frame-aligned ranges keep A/V durations consistent; output is a review preview.
        audio='[0:a]asplit='+str(n)+''.join(f'[a{i}]' for i in range(n))+';'
        for i,k in enumerate(ranges):
            length=k['source_end']-k['source_start']
            audio+=f"[a{i}]atrim=start={k['source_start']:.9f}:end={k['source_end']:.9f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.003,afade=t=out:st={max(0,length-.003):.9f}:d=0.003[b{i}];"
        audio+=''.join(f'[b{i}]' for i in range(n))+f'concat=n={n}:v=0:a=1[a]'
        filt=f"[0:v]select='{vf}',setpts=N/({info['source_fps']}*TB)[v];"+audio
        (folder/'preview_filter.txt').write_text(filt)
        command(['ffmpeg','-nostdin','-y','-i',str(folder/'original.mp4'),'-filter_complex_script',str(folder/'preview_filter.txt'),'-map','[v]','-map','[a]','-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-movflags','+faststart',str(folder/'cleaned.mp4')],folder/'processing.log')
    else:shutil.copy2(folder/'original.mp4',folder/'cleaned.mp4')
    command(['ffmpeg','-nostdin','-y','-i',str(folder/'original.mp4'),'-frames:v','1','-update','1',str(folder/'frame.jpg')],folder/'processing.log')
    state(folder,'ready','已生成，进入字幕工作台调整断句和重点。')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['analyze','finalize']);ap.add_argument('folder');args=ap.parse_args();folder=Path(args.folder).resolve()
    try:globals()[args.action](folder)
    except Exception as exc:
        with (folder/'processing.log').open('a') as f:traceback.print_exc(file=f)
        state(folder,'error',str(exc));raise
