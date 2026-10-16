import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from workbench import semantic
from workbench.pipeline import build_project
from workbench import draft
from test_pipeline import RAW, INFO, META

class SemanticTests(unittest.TestCase):
    def test_grounded_plan_and_caption_coverage(self):
        items=semantic.words(RAW)
        value={'captions':['大家好','核心指标20%'],'highlights':[{'quote':'核心指标','before':'大家好','after':'20%','style':'term','reason':'关键词'}],'cuts':[],'corrections':[]}
        p,rejected=semantic.ground_plan(value,items);self.assertEqual(rejected,[])
        project=build_project(RAW,INFO,[],META,p);draft.validate_project(project)
        self.assertEqual(''.join(c['text'] for c in project['captions']),'大家好核心指标20%')
        self.assertTrue(project['captions'][-1]['emphasis'])
        bad={**value,'captions':['大家好','核心指数20%']}
        with self.assertRaises(ValueError):semantic.ground_plan(bad,items)

    def test_ambiguous_quotes_and_wrong_filler_are_rejected(self):
        raw={'segments':[{'text':'民生民生','start':0,'end':4,'words':[{'word':'民','start':0,'end':1},{'word':'生','start':1,'end':2},{'word':'民','start':2,'end':3},{'word':'生','start':3,'end':4}]}]}
        value={'captions':['民生民生'],'highlights':[{'quote':'民生','style':'term'}],'cuts':[{'quote':'生','before':'民','after':'民生','kind':'语气词'}],'corrections':[]}
        plan,rejected=semantic.ground_plan(value,semantic.words(raw));self.assertEqual(plan['cuts'],[]);self.assertEqual(plan['highlights'],[]);self.assertEqual(len(rejected),2)

    def test_subword_quote_does_not_expand_deletion(self):
        raw={'segments':[{'text':'想需要想要','start':0,'end':2,'words':[{'word':'想需要想要','start':0,'end':2}]}]}
        items=semantic.words(raw)
        plan,_=semantic.ground_plan({'captions':['想需要想要'],'cuts':[{'quote':'想需要','after':'想要','kind':'改口'}]},items)
        cut=plan['cuts'][0]
        self.assertEqual(''.join(w['word'] for w in items[cut['a']:cut['b']+1]),'想需要')

    def test_credentials_private_and_no_key_in_status(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'JSW_SETTINGS_DIR':tmp},clear=False):
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':''},clear=False):
                semantic.save_key('sk-test-only-not-a-real-credential')
                self.assertTrue(semantic.configured());self.assertEqual((Path(tmp)/'deepseek.json').stat().st_mode&0o777,0o600)
                self.assertEqual(Path(tmp).stat().st_mode&0o777,0o700)

    def test_ranges_and_usage_price(self):
        items=semantic.words(RAW)
        with self.assertRaises(ValueError):semantic.validate_plan({'break_after':[999],'cuts':[]},items)
        cost=semantic.cost_range({'prompt_tokens':10000,'completion_tokens':3000,'prompt_cache_hit_tokens':0})
        self.assertEqual(cost['off_peak'],.022);self.assertEqual(cost['peak'],.044)

if __name__=='__main__':unittest.main()
