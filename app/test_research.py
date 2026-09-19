import json,unittest
from unittest.mock import MagicMock,patch
from research import lookup,answer
import test_autonomy

class ResearchTests(unittest.TestCase):
 def test_only_fixed_provider_plain_snippets_and_source(self):
  o=MagicMock();o.open.return_value.__enter__.return_value.read.return_value=json.dumps({'query':{'search':[{'title':'Example','snippet':'<b>자료</b> &amp; 근거','pageid':12}]}}).encode()
  with patch('research.urllib.request.build_opener',return_value=o):r=lookup('검색')
  self.assertEqual(r['results'][0]['snippet'],'자료 & 근거');self.assertEqual(r['results'][0]['url'],'https://ko.wikipedia.org/?curid=12')
  self.assertTrue(o.open.call_args.args[0].full_url.startswith('https://ko.wikipedia.org/w/api.php?'))
 def test_invalid_query_no_network(self):
  with patch('research.urllib.request.build_opener') as p:
   for q in ('','x'*121,None):
    with self.assertRaises(ValueError):lookup(q)
   p.assert_not_called()
 def test_empty_results_no_invented_answer(self):
  with patch('research.lookup',return_value={'results':[]}),patch('local_chat.chat') as m:
   self.assertIn('찾지 못했습니다',answer('없는 말'));m.assert_not_called()
 def test_sources_appended_independently_of_model(self):
  with patch('research.lookup',return_value={'results':[{'title':'T','snippet':'data','url':'https://ko.wikipedia.org/?curid=2'}]}),patch('local_chat.chat',return_value='요약'):
   self.assertIn('https://ko.wikipedia.org/?curid=2',answer('질문'))

class ResearchSchedulingTests(unittest.TestCase):
 setUp=test_autonomy.AutonomyTests.setUp
 tearDown=test_autonomy.AutonomyTests.tearDown
 def test_topic_disabled_and_kill_respected(self):
  self.c.autonomy.configure(True);self.c.autonomy.topic('공개 주제',False)
  with patch.object(self.c,'start',return_value={'run':'r'}) as start:
   self.c.autonomy.tick();start.assert_not_called();self.c.autonomy.topic('공개 주제',True);self.c.autonomy.tick();self.assertEqual(start.call_args.args[0]['mode'],'research')
 def test_topic_limits(self):
  with self.assertRaises(ValueError):self.c.autonomy.topic('x'*121)

if __name__=='__main__':unittest.main()
