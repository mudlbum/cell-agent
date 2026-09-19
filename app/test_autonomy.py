import json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from dashboard import Controller
from autonomy import growth_cycle

class AutonomyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name);self.c=Controller(p/'state',[p/'workspace'],lease_seconds=0)
  e=dict(id=str(uuid.uuid4()),kind='note',title='출처 확인',text='공식 출처와 발행 날짜 확인',url='https://example.com/',filename='',collected_at='2026-09-19T00:00:00Z')
  self.c.semi.ingest(dict(schema='cell-semi/1',exported_at='2026-09-19T00:00:00Z',entries=[e]));self.digest=self.c.semi.snapshot()[0]['digest']
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def adopt(self):return self.c.semi.review(self.digest,'adopt','합성 자료로 절차 생성 시험')['memory_id']
 def test_only_adopted_data_scheduled_once(self):
  self.c.autonomy.configure(True)
  with patch.object(self.c,'start',return_value={'run':'r'}) as start:
   self.c.autonomy.tick();start.assert_not_called();self.adopt();self.c.autonomy.tick();self.c.autonomy.tick();start.assert_called_once();self.assertTrue(start.call_args.kwargs['background']);self.assertEqual(start.call_args.args[0]['mode'],'growth')
 def test_emergency_stop_prevents_new_work(self):
  self.adopt();self.c.autonomy.configure(True);self.c.kill()
  with patch.object(self.c,'start') as start:self.c.autonomy.tick();start.assert_not_called()
 def test_failed_cycle_backoff(self):
  self.adopt();self.c.autonomy.configure(True)
  with patch.object(self.c,'start',return_value={'run':'r'}) as start:
   self.c.autonomy.tick()
   with self.c.store.lock,self.c.store.db:self.c.store.db.execute("INSERT INTO runs(id,created,status,goal,criteria,config,reason) VALUES('r',0,'failed','','','{}','model unavailable')")
   self.c.autonomy.tick();self.c.autonomy.tick();start.assert_called_once()
  self.assertEqual(self.c.autonomy.snapshot()['jobs'][0]['status'],'waiting')
 def test_growth_is_candidate_not_active(self):
  mid=self.adopt()
  with patch('local_chat.chat',return_value='1. 공식 출처의 날짜 확인. 2. 독립된 자료로 교차 확인. 3. 실패하면 다른 출처 비교.'):
   result=json.loads(growth_cycle(self.c.store,self.c.growth,mid,lambda:None))
  self.assertEqual(result['usefulness'],'not_evaluated');self.assertEqual(self.c.growth.find()[0]['status'],'candidate')
 def test_rejected_data_cannot_be_processed(self):
  with self.assertRaises(ValueError):growth_cycle(self.c.store,self.c.growth,'missing',lambda:None)
 def test_autonomy_off_persisted(self):
  self.c.autonomy.configure(False);self.assertFalse(self.c.autonomy.snapshot()['enabled'])

if __name__=='__main__':unittest.main()
