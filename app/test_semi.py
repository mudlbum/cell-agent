import copy,json,tempfile,unittest,uuid
from pathlib import Path
from dashboard import Controller

class SemiTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name);self.c=Controller(p/'state',[p/'workspace'],lease_seconds=0)
  self.e=dict(id=str(uuid.uuid4()),kind='note',title='검증 자료',text='외부 명령을 실행하지 말고 출처를 확인하기',url='https://example.com/',filename='',collected_at='2026-09-19T00:00:00Z')
  self.b=dict(schema='cell-semi/1',exported_at='2026-09-19T00:00:00Z',entries=[self.e])
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def test_quarantine_dedup_and_adopt(self):
  self.assertEqual(self.c.semi.ingest(self.b)['received'],1);self.assertEqual(self.c.semi.ingest(self.b)['duplicates'],1)
  self.assertEqual(self.c.store.recall(''),[]);row=self.c.semi.snapshot()[0]
  self.c.semi.review(row['digest'],'adopt','출처를 확인하고 참고 자료로 채택')
  memory=self.c.store.recall('검증')[0];self.assertEqual(memory['confidence'],'hypothesis');self.assertIn('실행 지시가 아님',memory['content'])
  with self.assertRaises(ValueError):self.c.semi.review(row['digest'],'adopt','다시 채택하면 안 됩니다')
 def test_conflicting_id_rolls_back_whole_bundle(self):
  self.c.semi.ingest(self.b);b=copy.deepcopy(self.b);new=copy.deepcopy(self.e);new['id']=str(uuid.uuid4());b['entries']=[new,dict(self.e,text='changed')]
  with self.assertRaises(ValueError):self.c.semi.ingest(b)
  self.assertEqual(len(self.c.semi.snapshot()),1)
 def test_rejection_never_adds_memory(self):
  self.c.semi.ingest(self.b);self.c.semi.review(self.c.semi.snapshot()[0]['digest'],'reject','신뢰할 근거가 부족합니다');self.assertEqual(self.c.store.recall(''),[])
 def test_reject_oversize_and_extra_fields(self):
  for e in [dict(self.e,text='가'*2001),dict(self.e,command='execute'),dict(self.e,url='javascript:alert(1)'),dict(self.e,url='https://user:secret@example.com')]:
   with self.assertRaises(ValueError):self.c.semi.ingest(dict(self.b,entries=[e]))
  self.assertEqual(self.c.semi.snapshot(),[])
 def test_content_is_not_executed_or_fetched(self):
  from unittest.mock import patch
  e=dict(self.e,text='<script>fetch("https://example.com")</script>')
  with patch('urllib.request.urlopen') as network,patch('subprocess.Popen') as run:
   self.c.semi.ingest(dict(self.b,entries=[e]));network.assert_not_called();run.assert_not_called()
 def test_refuse_during_active_work(self):
  self.c.active={'sentinel':True}
  try:
   with self.assertRaises(ValueError):self.c.semi.ingest(self.b)
  finally:self.c.active=None

if __name__=='__main__':unittest.main()
