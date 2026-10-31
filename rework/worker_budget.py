"""Shared UTF-8 wire-message accounting; not a model tokenizer estimate."""
import json
def message_bytes(messages):
    return len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
def evidence_limit(messages,limit,evidence):
    size=message_bytes(messages)
    if size<=limit:return None
    ids=[item['id'] for item in evidence]
    # Full authoritative receipts remain in the task; no source was discarded to
    # manufacture a fit, and this path never invokes the worker or a fallback.
    return ('Evidence was collected, but its complete messages exceed the selected 9B worker budget. No worker request was sent and no evidence was truncated. Full receipts remain attached to this task. Narrow the question or select fewer sources.',
      {'status':'worker_context_limit','claim_verification':'not_synthesized','worker_executed':False,'serialized_utf8_bytes':size,'limit_utf8_bytes':limit,'evidence_ids':ids,'receipt_storage':'durable task tool_receipts','automatic_fallback':False,'truncated':False})
