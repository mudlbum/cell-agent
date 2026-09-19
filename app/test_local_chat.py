import json
import unittest
from unittest.mock import patch, MagicMock
from local_chat import chat,ENDPOINT


class LocalChatTests(unittest.TestCase):
    def test_local_request_with_history_and_no_tools_or_keys(self):
        opened=MagicMock()
        opened.open.return_value.__enter__.return_value.read.return_value=json.dumps({"choices":[{"message":{"content":"안녕하세요"},"finish_reason":"stop"}]}).encode()
        with patch('local_chat.urllib.request.build_opener',return_value=opened):
            self.assertEqual(chat('질문',[{'role':'user','content':'앞선 질문'}]),'안녕하세요')
        request=opened.open.call_args.args[0]
        self.assertEqual(request.full_url,ENDPOINT)
        self.assertFalse(request.has_header('Authorization'))
        payload=json.loads(request.data)
        self.assertEqual(payload['messages'][-2]['content'],'앞선 질문')
        self.assertNotIn('tools',payload)
    def test_empty_response_rejected(self):
        opened=MagicMock();opened.open.return_value.__enter__.return_value.read.return_value=b'{"choices":[{"message":{"content":""}}]}'
        with patch('local_chat.urllib.request.build_opener',return_value=opened):
            with self.assertRaises(ValueError):chat('x')

    def test_oversized_input_fails_before_network(self):
        with patch('local_chat.urllib.request.build_opener') as opener:
            with self.assertRaises(ValueError): chat('x'*1801)
            opener.assert_not_called()

    def test_paid_provider_blocked_before_network(self):
        from cell_agent import OpenAIProvider
        with patch('urllib.request.urlopen') as request:
            with self.assertRaises(RuntimeError):
                OpenAIProvider('unused').response('',[],None,[])
            request.assert_not_called()


if __name__=='__main__':unittest.main()
