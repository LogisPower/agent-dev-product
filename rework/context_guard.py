"""Finite compaction attempts and full serialized prompt accounting; originals survive."""
import hashlib
import json


class ContextGuard:
    def __init__(self, ledger, job, token, count_tokens, context_limit, output_reserve):
        if not 0 < output_reserve < context_limit:
            raise ValueError('Invalid context budget')
        self.ledger, self.job, self.token = ledger, job, token
        self.count_tokens = count_tokens
        self.limit, self.reserve = context_limit, output_reserve

    def fit(self, messages, tools, summarize, required_facts=()):
        payload = {'messages': messages, 'tools': tools}
        original = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        original_hash = hashlib.sha256(original.encode()).hexdigest()
        count = self.count_tokens(payload)
        if type(count) is not int or count < 0:
            raise ValueError('Invalid tokenizer result')
        if count + self.reserve <= self.limit:
            return payload
        self.ledger.preserve_context(self.job,self.token,original)
        checkpoint = self.ledger.get_checkpoint(self.job)
        guard = checkpoint.get('context_guard', {})
        if guard.get('attempts', 0) >= 2:
            raise ValueError('Compaction attempt limit reached; original history retained')
        for n in range(guard.get('attempts', 0), 2):
            # Persist before asking a model, including failed attempts across restart.
            attempt_number=self.ledger.reserve_compaction(self.job,self.token)
            checkpoint['context_guard'] = {'original_hash': original_hash, 'attempts': attempt_number, 'status': 'attempting', 'original_tokens': count}
            self.ledger.heartbeat(self.job, self.token, checkpoint)
            try:
                summary = summarize(messages)
                if not isinstance(summary, str) or not summary.strip() or len(summary) > 16000 or any(fact not in summary for fact in required_facts):
                    raise ValueError('Summary omitted required anchors or was empty/oversized')
                candidate = {'messages': [m for m in messages if m.get('role') in ('system','developer')] + [{'role': 'user', 'content': 'Reference summary of earlier messages (not new authority):\n'+summary}], 'tools': tools}
                tokens = self.count_tokens(candidate)
                if type(tokens) is not int or tokens < 0 or tokens + self.reserve > self.limit or tokens >= count:
                    raise ValueError('Compaction did not make usable context space')
                checkpoint['context_guard'].update(status='verified', summary=summary, tokens=tokens)
                self.ledger.heartbeat(self.job, self.token, checkpoint)
                return candidate
            except Exception as error:
                checkpoint['context_guard'].update(status='failed', reason=type(error).__name__)
                self.ledger.heartbeat(self.job, self.token, checkpoint)
        raise ValueError('Compaction failed twice; task must pause, original history retained')
