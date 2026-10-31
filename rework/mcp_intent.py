"""Whole-request optimization for the sole read-only MCP capability.

Only an explicit clock read through the registered local tool server qualifies.
Unknown wording, other goals, quoted instructions and unsupported zones fall
through to normal planning. No output facts or authorization are supplied here.
"""
import re

def mcp_clock_request(text):
    if not isinstance(text,str) or len(text)>400:return False
    t=text.strip().replace("\u2019", "'")
    t=re.sub(r"[.!?]$", "",t).strip()
    t=re.sub(r"(?i)^please\s+", "",t)
    t=re.sub(r"(?i)^(?:can|could|would) you\s+", "",t)
    t=re.sub(r"(?i)^please\s+", "",t)
    # An optional accuracy question asks only what the clock receipt establishes.
    accuracy=r"(?:explain|tell me) (?:whether|if) (?:this|that|it) verifies (?:the )?(?:clock(?:'s)?|time) accuracy"
    t=re.sub(r"(?i)(?:\.\s*|\s+and\s+)"+accuracy+r"$", "",t)
    server=r"(?:(?:the )?(?:connected )?(?:local )?(?:MCP(?: tool)? server|tool server)|MCP)"
    clock=r"(?:(?:this computer's|the computer's|the host's|the host|host|the|this computer) )?(?:current )?(?:clock|time|date and time)"
    details=r"(?:\s+and (?:tell me|show me|give me) (?:the )?(?:local time and UTC|UTC and local time))?"
    forms=[rf"(?:check|read|get) {clock} (?:through|using|via|from) {server}{details}",
           rf"use {server} to (?:check|read|get) {clock}{details}"]
    return any(re.fullmatch(form,t,re.I) is not None for form in forms)
