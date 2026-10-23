"""Model transport and parser regression tests; no database or GPU required."""
import json
import unittest
from unittest.mock import patch

import conversation_understanding as extraction


class ModelResponseTests(unittest.TestCase):
    def test_plain_and_complete_fenced_json(self):
        for text in ('{"items":[]}', '```json\n{"items":[]}\n```', '```\r\n{"items":[]}\r\n```'):
            with self.subTest(text=text):
                self.assertEqual(extraction.parse_response(text), {'items': []})

    def test_partial_or_ambiguous_answers_are_rejected(self):
        for text in (None, '', '[]', '{}', '{"items":{}}', '{"items":[',
                     '```json\n{"items":[]}', '{"items":[]} trailing text',
                     'Explanation {"items":[]}', '```python\n{"items":[]}\n```'):
            with self.subTest(text=text):
                with self.assertRaises(extraction.ModelResponseInvalid):
                    extraction.parse_response(text)

    def invoke(self, payload):
        with patch.object(extraction.urllib.request, 'urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = payload
            return extraction.local_model([{'role': 'user', 'content': 'Synthetic input'}])

    def test_answer_is_separate_from_reasoning(self):
        payload = {'choices': [{'finish_reason': 'stop', 'message': {
            'content': '{"items":[]}', 'reasoning_content': 'Not a source fact'}}]}
        self.assertEqual(self.invoke(json.dumps(payload).encode()), '{"items":[]}')

    def test_truncation_is_explicit_even_if_json_looks_valid(self):
        payload = {'choices': [{'finish_reason': 'length', 'message': {'content': '{"items":[]}'}}]}
        with self.assertRaises(extraction.ModelOutputTruncated):
            self.invoke(json.dumps(payload).encode())

    def test_bad_envelopes_and_empty_answers(self):
        for value in ({}, {'choices': []}, {'choices': [None]}, {'choices': [{}]},
                      {'choices': [{'finish_reason': 'stop', 'message': {'content': None}}]},
                      {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': '{}'}}]}):
            with self.subTest(value=value):
                with self.assertRaises(extraction.ModelResponseInvalid):
                    self.invoke(json.dumps(value).encode())
        for payload in (b'not JSON', b'x' * 256001):
            with self.assertRaises(extraction.ModelResponseInvalid):
                self.invoke(payload)

    def test_unavailable_model_is_not_a_successful_empty_extraction(self):
        with patch.object(extraction.urllib.request, 'urlopen', side_effect=ConnectionRefusedError):
            with self.assertRaises(ConnectionRefusedError):
                extraction.local_model([])

    def test_invalid_sources_never_become_memories(self):
        source = {'role': 'user', 'source_id': 'synthetic', 'content': 'I prefer detailed answers.'}
        items = [
            {'kind': 'preferences', 'title': 'Detailed answers', 'source_id': 'synthetic', 'quote': source['content']},
            {'kind': 'preferences', 'title': 'Invented', 'source_id': 'synthetic', 'quote': 'I prefer invented facts.'},
            {'kind': 'preferences', 'title': 'Other project', 'source_id': 'outside', 'quote': source['content']},
        ]
        result = extraction.suggest([source], lambda _: json.dumps({'items': items}))
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['status'], 'draft')


if __name__ == '__main__':
    unittest.main()
