import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

from dashboard import Controller
from mesh import canonical, digest, validate_url
from share_server import make_feed
from test_control import until


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.c=Controller(self.root/'state', [self.root/'workspace'],lease_seconds=0)
    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()
    def test_chat_demo_finishes_and_persists(self):
        cid=self.c.conversations.create()['chat']
        r=self.c.conversations.send(dict(chat=cid,message='Show a demo',mode='demo',shell='deny'))
        until(lambda:not self.c.active,15)
        data=self.c.conversations.snapshot(cid)
        self.assertEqual(len(data['messages']),2)
        self.assertIn('오프라인',data['messages'][1]['content'])
        self.assertEqual(data['messages'][1]['status'],'report_ready')
        with patch.object(self.c,'start',return_value={'run':'mock'}) as start:
            self.c.conversations.send(dict(chat=cid,message='Continue',mode='demo'))
            history=start.call_args.kwargs['context']
            self.assertEqual(history[0]['content'],'Show a demo')
            self.assertEqual(len(history),2)
    def test_chat_isolation_and_failed_start(self):
        one=self.c.conversations.create()['chat'];two=self.c.conversations.create()['chat']
        self.c.kill()
        with self.assertRaises(ValueError): self.c.conversations.send(dict(chat=one,message='hello',mode='demo'))
        self.assertEqual(self.c.conversations.snapshot(one)['messages'],[])
        self.c.reset('RESUME')
        with patch.object(self.c,'start',return_value={'run':'mock'}) as start:
            self.c.conversations.send(dict(chat=one,message='private one',mode='demo'))
            self.c.conversations.send(dict(chat=two,message='private two',mode='demo'))
            self.assertEqual(start.call_args.kwargs['context'],[])
    def test_attachment_boundaries(self):
        r=self.c.conversations.attach({'name':'test.txt','text':'hello'})
        self.assertEqual(Path(r['path']).read_text(),'hello')
        for name in ('../outside.txt','file.exe','a:b.txt','x/y.txt'):
            with self.assertRaises(ValueError):self.c.conversations.attach(dict(name=name,text='x'))
        with self.assertRaises(ValueError):self.c.conversations.attach(dict(name='a.txt',text='x'*40001))
    def test_key_not_in_state_snapshot(self):
        self.c.api_key='sentinel-secret-do-not-store'
        self.assertNotIn(self.c.api_key,json.dumps(self.c.snapshot()))
        self.assertNotIn(self.c.api_key,'\n'.join(self.c.store.db.iterdump()))


class MeshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.a=Controller(self.root/'a',[self.root/'aw'],lease_seconds=0)
        self.b=Controller(self.root/'b',[self.root/'bw'],lease_seconds=0)
        r=self.a.growth.propose('source','problem','official source','search method','verify result','fallback query',[])
        self.a.growth.review(r['name'],r['digest'],'pass','Tested with independent references')
        self.h=self.a.mesh.publish(r['name'],r['digest'])['hash']
        self.server=make_feed(self.root/'a')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_address[1])
        self.pid=self.b.mesh.pair(self.url,self.a.mesh.public)['peer']
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.a.close();self.b.close();self.tmp.cleanup()
    def test_signed_transfer_quarantine_and_repair(self):
        self.assertEqual(self.b.mesh.sync(self.pid)['received'],1)
        self.assertEqual(self.b.mesh.snapshot()['packages'][0]['status'],'quarantine')
        self.assertEqual(self.b.growth.find(),[])
        self.b.mesh.adopt(self.h)
        self.assertEqual(self.b.growth.find()[0]['status'],'candidate')
        path=self.b.mesh.objects/(self.h+'.json');path.write_text('tampered')
        with self.assertRaises(ValueError):self.b.mesh.read_package(self.h)
        self.assertEqual(self.b.mesh.sync(self.pid)['repaired'],1)
        self.assertEqual(self.b.mesh.read_package(self.h)['name'],'source')
    def test_signature_and_author_rejected(self):
        raw=(self.a.mesh.objects/(self.h+'.json')).read_bytes()
        with self.assertRaises(Exception):self.b.mesh.verify(raw,self.b.mesh.public,'route')
        obj=json.loads(raw);obj['payload']['document']['strategy']='malicious altered text'
        with self.assertRaises(Exception):self.b.mesh.verify(canonical(obj),self.a.mesh.public,'route')
    def test_manifest_rollback_and_conflict(self):
        old=(self.a.mesh.directory/'manifest.json').read_bytes()
        self.a.mesh.write_manifest();self.b.mesh.sync(self.pid)
        (self.a.mesh.directory/'manifest.json').write_bytes(old)
        with self.assertRaises(ValueError):self.b.mesh.sync(self.pid)
        m=json.loads(old)['payload'];m['sequence']=2;m['packages']=[]
        (self.a.mesh.directory/'manifest.json').write_bytes(self.a.mesh.sign(m))
        with self.assertRaises(ValueError):self.b.mesh.sync(self.pid)
    def test_feed_excludes_private_and_unpublished(self):
        for path in ('/identity.key','/../identity.key','/packages/'+'a'*64):
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(self.url+path)
    def test_disabled_peer_and_url_policy(self):
        self.b.mesh.action('disable',{'peer':self.pid})
        with self.assertRaises(ValueError):self.b.mesh.sync(self.pid)
        for url in ('http://example.org','file:///x','https://user:pass@example.org','https://example.org/#x'):
            with self.assertRaises(ValueError):validate_url(url)
    def test_unreviewed_route_cannot_publish(self):
        r=self.a.growth.propose('candidate','p','l','s','v','f',[])
        with self.assertRaises(ValueError):self.a.mesh.publish(r['name'],r['digest'])


if __name__=='__main__':unittest.main()
