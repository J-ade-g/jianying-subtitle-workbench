import json, tempfile, unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from workbench.pipeline import build_project, cut_map, candidates
from workbench import draft

RAW={'segments':[{'text':'大家好，核心指标20%。','start':.2,'end':3.5,'words':[{'word':'大家好，','start':.2,'end':1.},{'word':'核心指标','start':1.2,'end':2.4},{'word':'20%。','start':2.5,'end':3.5}]}]}
INFO={'source_duration':6.,'source_fps':30.,'width':1080,'height':1920}
META={'id':'a'*32,'filename':'demo.mp4','options':{'max_chars':12,'keywords':'核心指标'}}

class PipelineTests(unittest.TestCase):
    def test_cut_mapping_overlap(self):
        cuts,kept,duration=cut_map(6,[{'start':1,'end':2,'reason':'one'},{'start':1.5,'end':3,'reason':'two'}])
        self.assertEqual(len(cuts),1);self.assertEqual(duration,4)
        self.assertEqual(kept[-1],{'source_start':3,'source_end':6,'output_start':1,'output_end':4})
        with self.assertRaises(ValueError):cut_map(6,[{'start':0,'end':7,'reason':'invalid'}])

    def test_caption_time_and_highlights(self):
        p=build_project(RAW,INFO,[],META);draft.validate_project(p)
        self.assertEqual(''.join(c['text'] for c in p['captions']),'大家好核心指标20%')
        self.assertTrue(any(e['style']=='term' for c in p['captions'] for e in c['emphasis']))
        self.assertTrue(any(e['style']=='number' for c in p['captions'] for e in c['emphasis']))
        for c in p['captions']:self.assertEqual(len(c['char_times']),len(c['text'].encode('utf-16-le'))//2)

    def test_unicode_and_cut_caption_shift(self):
        raw={'segments':[{'text':'你好😀世界','start':1,'end':4,'words':[{'word':'你好😀世界','start':1,'end':4}]}]}
        p=build_project(raw,INFO,[{'start':0,'end':.5,'reason':'intro'}],META);draft.validate_project(p)
        self.assertEqual(p['captions'][0]['start'],.5)
        self.assertEqual(len(p['captions'][0]['char_times']),6)

    def test_fillers_not_removed_without_review(self):
        raw={'segments':[{'words':[{'word':'嗯','start':.1,'end':.3},{'word':'可以','start':.5,'end':.8},{'word':'可以','start':.9,'end':1.2}]}]}
        plan=candidates(raw,'silence_end: 4.0 | silence_duration: 2.0',6,30)
        self.assertTrue(any(c['selected'] for c in plan if c['kind']=='停顿缩短'))
        self.assertTrue(all(not c['selected'] for c in plan if c['kind']!='停顿缩短'))

    def test_native_export_portable_and_no_overwrite(self):
        p=build_project(RAW,INFO,[],META)
        p['captions'][-1]['emphasis'][0]['overrides']={'color':'#12ab34','bold':False,'scale':1.4}
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'data';out.mkdir();(out/'original.mp4').write_bytes(b'test-media-placeholder')
            native=Path(tmp)/'native';native.mkdir();draft.write_json(native/'root_meta_info.json',{'all_draft_store':[{'draft_id':'existing'}],'draft_ids':1})
            template=json.loads(draft.TEMPLATE.read_text());font=Path(tmp)/'font.ttf';font.touch();template['text_material']['font_path']=str(font);template_path=Path(tmp)/'schema.json';draft.write_json(template_path,template)
            with patch.object(draft,'TEMPLATE',template_path),patch.object(draft,'OUTPUT',out),patch.object(draft,'DRAFT_ROOT',native),patch.object(draft,'jianying_running',return_value=False):
                result=draft.install(draft.generate(p));folder=Path(result['installed_path']);draft.validate_draft(folder,p)
                doc=json.loads((folder/'draft_info.json').read_text());self.assertEqual(doc['canvas_config']['height'],1920)
                self.assertEqual(doc['materials']['videos'][0]['width'],1080)
                registry=json.loads((native/'root_meta_info.json').read_text());self.assertEqual(registry['draft_ids'],2)
                with self.assertRaises(ValueError):draft.install(result)
                registry['all_draft_store'][0]['draft_id']='app-reindexed';draft.write_json(native/'root_meta_info.json',registry);draft.register_existing(result)
                self.assertEqual(json.loads((native/'root_meta_info.json').read_text())['draft_ids'],2)
            with patch.object(draft,'jianying_running',return_value=True):
                with self.assertRaises(ValueError):draft.require_jianying_closed()

if __name__=='__main__':unittest.main()
