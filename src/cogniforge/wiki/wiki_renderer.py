"""WikiRenderer — converts Agent-format JSON into user-facing HTML."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def _esc(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    return (
        text.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def _repair_json_text(text: str) -> str:
    """Repair unescaped ASCII double quotes inside JSON string values.

    Uses a state machine to detect when a ``"`` inside a string value is
    not the actual closing delimiter (the next non-whitespace char is not
    one of ``,`` ``}`` ``]`` ``:``) and escapes it.
    """
    IN_NORMAL, IN_STRING = 0, 1
    state = IN_NORMAL
    result = []
    i = 0

    while i < len(text):
        c = text[i]

        if state == IN_NORMAL:
            result.append(c)
            if c == '"':
                state = IN_STRING
        else:  # IN_STRING
            if c == '\\':
                result.append(c)
                if i + 1 < len(text):
                    result.append(text[i + 1])
                    i += 1
            elif c == '"':
                # Peek past whitespace to decide: real delimiter or stray quote?
                j = i + 1
                while j < len(text) and text[j] in ' \t\n\r':
                    j += 1
                if j < len(text) and text[j] not in ',}]:':
                    # Stray quote inside a string value — escape it
                    result.append('\\"')
                else:
                    # Real closing delimiter
                    result.append(c)
                    state = IN_NORMAL
            else:
                result.append(c)

        i += 1

    return ''.join(result)


def load_json_with_repair(file_path: Path) -> dict:
    """Read a JSON file, attempting repair if the initial parse fails."""
    raw = file_path.read_text(encoding="utf-8")
    data, _ = repair_truncated_json(raw)
    return data


def repair_truncated_json(text: str) -> tuple[dict, bool]:
    """Attempt to repair truncated LLM-generated JSON by closing missing brackets.

    Returns (data, incomplete): parsed dict and whether truncation was repaired.
    Raises ValueError when repair fails completely.
    """
    # 1. Try direct parse first
    try:
        return json.loads(text), False
    except json.JSONDecodeError:
        pass

    # 2. Repair unescaped quotes in string values
    repaired = _repair_json_text(text)

    # 3. Close missing brackets — common in LLM token-limit truncation
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")
    if open_braces > 0 or open_brackets > 0:
        suffix = "\n" + "]" * open_brackets + "}" * open_braces
        repaired += suffix

    try:
        data = json.loads(repaired)
        data.setdefault("meta", {})["incomplete"] = True
        return data, True
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 自修复失败: {e}") from e


# ---------------------------------------------------------------------------
# Shared CSS (dark theme, self-contained)
# ---------------------------------------------------------------------------

_SHARED_CSS = """
  :root {
    --c-bg: #0b0f19; --c-surface: #131926; --c-card: #191e2e;
    --c-border: #252b3d; --c-text: #c8d2e0; --c-heading: #e2e8f4;
    --c-muted: #6b7394; --c-accent: #5b8def; --c-accent2: #7c6ff7;
    --c-green: #34d399; --c-amber: #fbbf24; --c-red: #f87171;
    --c-cyan: #22d3ee; --radius: 10px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
    background: var(--c-bg); color: var(--c-text);
    line-height: 1.75; font-size: 15px;
    max-width: 860px; margin: 0 auto; padding: 48px 40px 80px;
  }
  body:has(.page-layout) { max-width: none; margin: 0; padding: 0; }
  .top-bar {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 40px; padding-bottom: 24px;
    border-bottom: 1px solid var(--c-border);
  }
  .doc-id { font-size: 0.8em; color: var(--c-muted); font-family: monospace; }
  .badge {
    display: inline-flex; padding: 5px 14px; border-radius: 20px;
    font-size: 0.78em; font-weight: 500;
    background: rgba(255,255,255,0.04); border: 1px solid var(--c-border);
    color: var(--c-muted);
  }
  .badge.accent { border-color: rgba(91,141,239,0.3); color: var(--c-accent); }
  .badge.green  { border-color: rgba(52,211,153,0.3); color: var(--c-green); }
  h1 {
    font-size: 2.4em; font-weight: 800; color: #fff;
    letter-spacing: -1px; line-height: 1.2; margin-bottom: 6px;
  }
  h1 span {
    background: linear-gradient(135deg, var(--c-accent), var(--c-cyan));
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .meta { font-size: 0.85em; color: var(--c-muted); margin-bottom: 4px; }
  .section { margin-bottom: 36px; }
  .section-header {
    display: flex; align-items: center; gap: 12px; margin-bottom: 18px;
  }
  .section-header .icon {
    width: 40px; height: 40px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.2em; flex-shrink: 0;
  }
  .section-header h2 {
    font-size: 1.25em; font-weight: 700; color: var(--c-heading);
  }
  .section-body {
    background: var(--c-card); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 28px 32px;
  }
  .section-body p { margin-bottom: 12px; }
  .section-body p:last-child { margin-bottom: 0; }
  .req-item {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 18px 22px; margin-bottom: 10px;
  }
  .req-item:last-child { margin-bottom: 0; }
  .req-item h3 { font-size: 1em; font-weight: 600; color: var(--c-heading); margin-bottom: 6px; }
  .req-desc { font-size: 0.9em; color: var(--c-muted); margin-bottom: 10px; }
  .ac-list { list-style: none; padding: 0; margin: 0; }
  .ac-list li {
    padding: 4px 0 4px 18px; position: relative;
    font-size: 0.88em; color: var(--c-text);
  }
  .ac-list li::before {
    content: ""; position: absolute; left: 0; top: 12px;
    width: 6px; height: 6px; border-radius: 50%; background: var(--c-green);
  }
  .ac-label {
    font-size: 0.75em; font-weight: 600; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;
  }
  .story-item {
    display: flex; align-items: flex-start; gap: 12px;
    padding: 14px 18px; border-radius: 8px;
    background: var(--c-surface); border: 1px solid var(--c-border);
    margin-bottom: 8px;
  }
  .story-item:last-child { margin-bottom: 0; }
  .story-role {
    font-size: 0.8em; font-weight: 600; color: var(--c-accent);
    background: rgba(91,141,239,0.1); padding: 2px 10px;
    border-radius: 12px; white-space: nowrap; flex-shrink: 0;
  }
  .story-text { font-size: 0.92em; }
  .story-text .goal { color: var(--c-muted); font-size: 0.88em; }
  .priority-grid { display: flex; flex-wrap: wrap; gap: 8px; }
  .priority-tag {
    display: inline-flex; padding: 6px 14px; border-radius: 6px;
    font-size: 0.85em; font-weight: 500;
  }
  .priority-tag.high   { background: rgba(248,113,113,0.1);  color: #fca5a5; }
  .priority-tag.medium { background: rgba(251,191,36,0.1);  color: #fcd34d; }
  .priority-tag.low    { background: rgba(107,115,148,0.15); color: #9ca3af; }
  .comp-item {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 18px 22px; margin-bottom: 10px;
  }
  .comp-item h3 { font-size: 1em; font-weight: 600; color: var(--c-heading); }
  .comp-type {
    font-size: 0.78em; color: var(--c-accent); margin-bottom: 8px;
  }
  .comp-resp { margin-top: 8px; font-size: 0.88em; }
  .comp-resp li { margin: 2px 0; }

  /* ── Contract Groups ── */
  .contract-group {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); margin-bottom: 12px; overflow: hidden;
  }
  .contract-group[open] { border-color: rgba(91,141,239,0.25); }
  .contract-group summary {
    display: flex; align-items: center; gap: 10px;
    padding: 14px 20px; cursor: pointer; user-select: none;
    font-weight: 600; font-size: 0.95em; color: var(--c-heading);
    background: rgba(255,255,255,0.015);
  }
  .contract-group summary:hover { background: rgba(255,255,255,0.03); }
  .contract-group summary::-webkit-details-marker { display: none; }
  .contract-group summary::before {
    content: "›"; display: inline-block; font-size: 1.3em; font-weight: 400;
    width: 16px; color: var(--c-muted); transition: transform 0.2s;
  }
  .contract-group[open] summary::before { transform: rotate(90deg); }
  .cg-count {
    font-size: 0.78em; font-weight: 500; color: var(--c-muted);
    background: rgba(255,255,255,0.04); padding: 2px 10px; border-radius: 10px;
  }
  .contract-card {
    padding: 16px 20px; border-top: 1px solid var(--c-border);
  }
  .contract-card:first-of-type { border-top: 1px solid var(--c-border); }
  .cc-head {
    display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
    flex-wrap: wrap;
  }
  .cc-head .cc-name { font-weight: 600; font-size: 0.93em; color: var(--c-heading); }
  .method-badge {
    font-family: monospace; font-size: 0.75em; font-weight: 700;
    padding: 3px 8px; border-radius: 5px; white-space: nowrap;
  }
  .method-badge.get      { background: rgba(52,211,153,0.15);  color: var(--c-green); }
  .method-badge.post     { background: rgba(91,141,239,0.15);  color: var(--c-accent); }
  .method-badge.put      { background: rgba(251,191,36,0.12);  color: var(--c-amber); }
  .method-badge.delete   { background: rgba(248,113,113,0.12); color: var(--c-red); }
  .method-badge.patch    { background: rgba(34,211,238,0.12);  color: var(--c-cyan); }
  .method-badge.mq       { background: rgba(124,111,247,0.13); color: var(--c-accent2); }
  .method-badge.ws       { background: rgba(124,111,247,0.13); color: var(--c-accent2); }
  .method-badge.frontend { background: rgba(34,211,238,0.12);  color: var(--c-cyan); }
  .method-badge.internal { background: rgba(107,115,148,0.15); color: var(--c-muted); }
  .cc-endpoint {
    font-family: monospace; font-size: 0.82em; color: var(--c-text);
    background: rgba(255,255,255,0.03); padding: 2px 8px; border-radius: 4px;
  }
  .cc-type-tag {
    font-size: 0.72em; font-weight: 600; padding: 3px 8px; border-radius: 4px;
    text-transform: uppercase; letter-spacing: 0.4px;
    background: rgba(91,141,239,0.1); color: var(--c-accent);
  }
  .cc-meta {
    font-size: 0.82em; color: var(--c-muted); margin-bottom: 6px;
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  }
  .cc-meta .cc-consumer {
    font-size: 0.85em; color: var(--c-accent2);
    background: rgba(124,111,247,0.08); padding: 1px 8px; border-radius: 4px;
  }
  .cc-desc { font-size: 0.85em; color: var(--c-muted); margin-bottom: 10px; }
  .body-table {
    width: 100%; border-collapse: collapse; font-size: 0.8em; margin: 6px 0 4px;
  }
  .body-table th {
    text-align: left; padding: 5px 10px; font-weight: 600;
    color: var(--c-muted); font-size: 0.85em; text-transform: uppercase;
    letter-spacing: 0.4px; border-bottom: 2px solid var(--c-border);
    background: rgba(255,255,255,0.015);
  }
  .body-table td {
    padding: 4px 10px; border-bottom: 1px solid rgba(255,255,255,0.04);
    color: var(--c-text);
  }
  .body-table .field-type { color: var(--c-accent); font-family: monospace; font-size: 0.9em; }
  .body-label {
    font-size: 0.72em; font-weight: 700; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px; margin: 8px 0 2px;
  }
  .model-item {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 18px 22px; margin-bottom: 10px;
  }
  .model-item h3 { font-size: 1em; font-weight: 600; color: var(--c-heading); }
  table {
    width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.9em;
  }
  th {
    text-align: left; padding: 10px 14px; font-weight: 600;
    color: var(--c-muted); font-size: 0.8em; text-transform: uppercase;
    letter-spacing: 0.5px; border-bottom: 2px solid var(--c-border);
  }
  td { padding: 10px 14px; border-bottom: 1px solid var(--c-border); }
  tr:hover td { background: rgba(255,255,255,0.015); }
  .footer {
    margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--c-border);
    text-align: center; color: var(--c-muted); font-size: 0.8em;
  }
  /* ── System Overview ── */
  .overview-hero {
    background: linear-gradient(135deg, rgba(124,111,247,0.08), rgba(91,141,239,0.05));
    border: 1px solid rgba(124,111,247,0.18); border-radius: var(--radius);
    padding: 24px 28px; margin-bottom: 24px;
  }
  .overview-hero .hero-label {
    font-size: 0.72em; font-weight: 700; color: var(--c-accent2);
    text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 10px;
  }
  .overview-hero p { font-size: 1.02em; line-height: 1.85; color: var(--c-text); }
  .role-cards {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
  }
  .role-card {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 22px 20px; text-align: center;
  }
  .role-card .role-icon {
    width: 48px; height: 48px; border-radius: 50%; margin: 0 auto 12px;
    display: flex; align-items: center; justify-content: center; font-size: 1.3em;
  }
  .role-card .role-name {
    font-size: 1em; font-weight: 700; color: var(--c-heading); margin-bottom: 10px;
  }
  .role-card .role-perms {
    font-size: 0.84em; color: var(--c-muted); line-height: 1.7;
    list-style: none; padding: 0;
  }
  .role-card .role-perms li { padding: 1px 0; }

  /* ── Architecture Diagram ── */
  .arch-diagram {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 24px 20px 20px; margin-bottom: 22px;
  }
  .arch-tier {
    display: flex; align-items: center; margin-bottom: 4px;
  }
  .arch-tier-label {
    font-size: 0.68em; font-weight: 700; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px; flex-shrink: 0;
    width: 52px; text-align: right; padding-right: 16px;
  }
  .arch-tier-boxes { display: flex; gap: 8px; flex: 1; flex-wrap: wrap; }
  .arch-box {
    border-radius: 8px; padding: 12px 16px; text-align: center;
    font-weight: 600; font-size: 0.85em; flex: 1; min-width: 80px;
  }
  .arch-box.frontend {
    background: rgba(34,211,238,0.12); border: 1px solid rgba(34,211,238,0.28);
    color: var(--c-cyan);
  }
  .arch-box.gateway {
    background: rgba(124,111,247,0.13); border: 1px solid rgba(124,111,247,0.3);
    color: var(--c-accent2);
  }
  .arch-box.service {
    background: rgba(91,141,239,0.1); border: 1px solid rgba(91,141,239,0.22);
    color: var(--c-accent);
  }
  .arch-box.db {
    background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.22);
    color: var(--c-green);
  }
  .arch-box.cache {
    background: rgba(251,191,36,0.09); border: 1px solid rgba(251,191,36,0.22);
    color: var(--c-amber);
  }
  .arch-box.mq {
    background: rgba(248,113,113,0.07); border: 1px solid rgba(248,113,113,0.18);
    color: var(--c-red);
  }
  .arch-overview {
    display: flex; align-items: center; gap: 0; margin-bottom: 20px;
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 8px; overflow: hidden;
  }
  .arch-ov-item {
    flex: 1; text-align: center; padding: 16px 12px; position: relative;
  }
  .arch-ov-item .ov-count {
    font-size: 1.8em; font-weight: 800; line-height: 1.1;
  }
  .arch-ov-item .ov-label {
    font-size: 0.75em; color: var(--c-muted); margin-top: 4px;
  }
  .arch-ov-arrow {
    font-size: 1.1em; color: var(--c-muted); flex-shrink: 0;
    padding: 0 2px;
  }
  .arch-style-badge {
    display: inline-flex; padding: 6px 16px; border-radius: 20px;
    font-size: 0.85em; font-weight: 700; margin-bottom: 16px;
    background: linear-gradient(135deg, rgba(124,111,247,0.15), rgba(91,141,239,0.1));
    border: 1px solid rgba(124,111,247,0.25); color: var(--c-accent2);
  }
  .arch-features {
    display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px;
    padding-top: 16px; border-top: 1px solid var(--c-border);
  }
  .arch-feature-tag {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 14px; border-radius: 18px; font-size: 0.82em; font-weight: 500;
    background: rgba(255,255,255,0.03); border: 1px solid var(--c-border);
    color: var(--c-text);
  }
  .arch-feature-tag .dot {
    width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
  }
  .arch-desc { margin-bottom: 18px; color: var(--c-text); line-height: 1.8; }

  /* ── Topology ── */
  .topo-diagram {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 24px 20px 20px; margin-bottom: 22px;
  }
  .topo-tier {
    display: flex; align-items: stretch; margin-bottom: 2px;
  }
  .topo-tier-label {
    font-size: 0.68em; font-weight: 700; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px; flex-shrink: 0;
    width: 52px; text-align: right; padding-right: 16px; padding-top: 12px;
  }
  .topo-tier-content { flex: 1; display: flex; flex-wrap: wrap; gap: 8px; }
  .topo-node {
    border-radius: 8px; padding: 10px 15px; text-align: center;
    font-weight: 600; font-size: 0.83em; flex: 1; min-width: 80px;
  }
  .topo-node.frontend {
    background: rgba(34,211,238,0.12); border: 1px solid rgba(34,211,238,0.28);
    color: var(--c-cyan);
  }
  .topo-node.gateway {
    background: rgba(124,111,247,0.13); border: 1px solid rgba(124,111,247,0.3);
    color: var(--c-accent2);
  }
  .topo-node.service {
    background: rgba(91,141,239,0.1); border: 1px solid rgba(91,141,239,0.22);
    color: var(--c-accent);
  }
  .topo-node.db {
    background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.22);
    color: var(--c-green);
  }
  .topo-node.cache {
    background: rgba(251,191,36,0.09); border: 1px solid rgba(251,191,36,0.22);
    color: var(--c-amber);
  }
  .topo-node.mq {
    background: rgba(248,113,113,0.07); border: 1px solid rgba(248,113,113,0.18);
    color: var(--c-red);
  }
  .topo-connector {
    display: flex; align-items: center; padding: 2px 0 2px 52px;
    gap: 10px; flex-wrap: wrap;
  }
  .topo-connector-line {
    flex: 1; min-width: 60px; display: flex; align-items: center; gap: 6px;
    color: var(--c-muted); font-size: 0.75em; font-weight: 500;
  }
  .topo-connector-line::before {
    content: ""; display: inline-block; width: 12px; height: 1px;
    background: var(--c-border); flex-shrink: 0;
  }
  .topo-connector-line .proto {
    color: var(--c-accent2); font-family: monospace; font-size: 0.9em;
    background: rgba(124,111,247,0.08); padding: 1px 6px; border-radius: 4px;
  }

  /* ── Data Flow ── */
  .flow-cards { display: flex; flex-direction: column; gap: 16px; }
  .flow-card {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 20px 22px;
  }
  .flow-card-header {
    display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
  }
  .flow-card-header .flow-num {
    width: 28px; height: 28px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.8em; font-weight: 700; flex-shrink: 0;
  }
  .flow-card-header .flow-name {
    font-weight: 700; font-size: 0.95em; color: var(--c-heading);
  }
  .flow-steps {
    display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
  }
  .flow-step {
    font-size: 0.82em; padding: 5px 10px; border-radius: 6px;
    background: rgba(255,255,255,0.03); border: 1px solid var(--c-border);
    color: var(--c-text); white-space: nowrap;
  }
  .flow-step.start  { border-color: rgba(52,211,153,0.3);  color: var(--c-green); }
  .flow-step.mid    { border-color: rgba(91,141,239,0.25);  color: var(--c-accent); }
  .flow-step.end    { border-color: rgba(124,111,247,0.3);  color: var(--c-accent2); }
  .flow-arrow { color: var(--c-muted); font-size: 0.85em; flex-shrink: 0; }

  /* ── Error Handling ── */
  .err-strategy {
    background: linear-gradient(135deg, rgba(251,191,36,0.06), rgba(248,113,113,0.04));
    border: 1px solid rgba(251,191,36,0.2);
    border-radius: var(--radius); padding: 20px 24px; margin-bottom: 20px;
  }
  .err-strategy .err-label {
    font-size: 0.72em; font-weight: 700; color: var(--c-amber);
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;
  }
  .err-strategy p { font-size: 0.92em; line-height: 1.8; color: var(--c-text); }

  .err-format-box {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 18px 22px; margin-bottom: 20px;
  }
  .err-format-box .err-label {
    font-size: 0.72em; font-weight: 700; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px;
  }
  .err-format-box pre {
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 0.84em; color: var(--c-text);
    background: rgba(0,0,0,0.2); padding: 14px 18px; border-radius: 6px;
    overflow-x: auto; line-height: 1.7;
  }

  .err-categories { display: flex; flex-direction: column; gap: 10px; }
  .err-category {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 18px 22px;
    display: flex; gap: 16px; align-items: flex-start;
  }
  .err-category:hover { border-color: rgba(255,255,255,0.1); }
  .err-code-badge {
    font-family: monospace; font-size: 0.85em; font-weight: 700;
    padding: 6px 12px; border-radius: 6px; white-space: nowrap;
    flex-shrink: 0; min-width: 48px; text-align: center;
  }
  .err-code-badge._4xx { background: rgba(251,191,36,0.12); color: var(--c-amber); }
  .err-code-badge._5xx { background: rgba(248,113,113,0.12); color: var(--c-red); }
  .err-code-badge._other { background: rgba(124,111,247,0.1); color: var(--c-accent2); }
  .err-category-body { flex: 1; min-width: 0; }
  .err-category-body .err-cat-name {
    font-weight: 600; font-size: 0.93em; color: var(--c-heading); margin-bottom: 6px;
  }
  .err-category-body .err-cat-desc {
    font-size: 0.85em; color: var(--c-muted); line-height: 1.7;
  }

  /* ── Domain Objects ── */
  .domain-obj {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 18px 22px; margin-bottom: 10px;
  }
  .domain-obj h3 { font-size: 1em; font-weight: 600; color: var(--c-heading); margin-bottom: 6px; }
  .obj-tag {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.72em; font-weight: 600; margin-left: 6px;
  }
  .obj-tag.entity   { background: rgba(91,141,239,0.12);  color: var(--c-accent); }
  .obj-tag.dto      { background: rgba(52,211,153,0.12);  color: var(--c-green); }
  .obj-tag.value_object { background: rgba(124,111,247,0.1); color: var(--c-accent2); }
  .obj-tag.enum     { background: rgba(251,191,36,0.1);   color: var(--c-amber); }
  .attr-source-tag {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 0.7em; font-weight: 600; font-family: monospace;
    color: var(--c-muted); background: rgba(107,115,148,0.1);
  }

  /* ── Service Contracts ── */
  .svc-contract {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); margin-bottom: 12px; overflow: hidden;
  }
  .svc-contract summary {
    display: flex; align-items: center; gap: 10px;
    padding: 14px 20px; cursor: pointer; user-select: none;
    font-weight: 600; font-size: 0.95em; color: var(--c-heading);
    background: rgba(255,255,255,0.015);
  }
  .svc-contract summary:hover { background: rgba(255,255,255,0.03); }
  .svc-contract summary::-webkit-details-marker { display: none; }
  .svc-contract summary::before {
    content: "›"; display: inline-block; font-size: 1.3em; font-weight: 400;
    width: 16px; color: var(--c-muted); transition: transform 0.2s;
  }
  .svc-contract[open] summary::before { transform: rotate(90deg); }
  .svc-method {
    padding: 16px 20px; border-top: 1px solid var(--c-border);
  }
  .svc-method-header {
    display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
    flex-wrap: wrap;
  }
  .svc-method-header .method-name {
    font-weight: 600; font-size: 0.93em; color: var(--c-heading);
    font-family: "JetBrains Mono", "Fira Code", monospace;
  }
  .svc-method-header .return-type {
    font-size: 0.82em; color: var(--c-accent); font-family: monospace;
    background: rgba(91,141,239,0.08); padding: 2px 8px; border-radius: 4px;
  }
  .sig-block {
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 0.84em; color: var(--c-text);
    background: rgba(255,255,255,0.02); padding: 10px 14px;
    border-radius: 6px; margin: 8px 0; overflow-x: auto;
    border: 1px solid var(--c-border);
  }
  .pre-post {
    display: flex; gap: 12px; margin: 8px 0; flex-wrap: wrap;
  }
  .pre-post-item {
    flex: 1; min-width: 180px;
    background: rgba(255,255,255,0.015); border: 1px solid var(--c-border);
    border-radius: 6px; padding: 10px 14px;
  }
  .pre-post-item .pp-label {
    font-size: 0.68em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 4px;
  }
  .pre-post-item.pre .pp-label { color: var(--c-green); }
  .pre-post-item.post .pp-label { color: var(--c-accent); }
  .pre-post-item .pp-text { font-size: 0.84em; color: var(--c-text); }
  .exc-item {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 14px; margin: 2px 4px 2px 0;
    font-size: 0.8em; background: rgba(248,113,113,0.06);
    border: 1px solid rgba(248,113,113,0.15);
  }
  .exc-item .exc-name { font-weight: 600; color: var(--c-red); font-family: monospace; font-size: 0.85em; }
  .exc-item .exc-http { font-size: 0.82em; color: var(--c-muted); }
  .repo-dep {
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 0.82em; color: var(--c-muted);
    padding: 2px 0 2px 12px; border-left: 2px solid var(--c-border);
    margin: 2px 0 2px 8px;
  }

  /* ── Business Rules ── */
  .invariant-list {
    list-style: none; padding: 0; margin: 0;
  }
  .invariant-list li {
    padding: 8px 14px; margin-bottom: 6px;
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 6px; font-size: 0.9em;
    display: flex; align-items: flex-start; gap: 10px;
  }
  .invariant-list li .inv-icon {
    color: var(--c-amber); font-weight: 700; flex-shrink: 0;
  }
  .state-diagram {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 20px; margin-bottom: 12px;
  }
  .state-diagram .sd-title {
    font-weight: 600; font-size: 0.93em; color: var(--c-heading); margin-bottom: 12px;
  }
  .state-row {
    display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px;
  }
  .state-node {
    display: inline-flex; align-items: center; justify-content: center;
    padding: 8px 18px; border-radius: 20px; font-size: 0.85em; font-weight: 600;
    border: 1px solid var(--c-border); background: var(--c-card);
    color: var(--c-text);
  }
  .state-node.active { border-color: rgba(91,141,239,0.4); color: var(--c-accent); background: rgba(91,141,239,0.06); }
  .state-node.terminal { border-color: rgba(52,211,153,0.3); color: var(--c-green); background: rgba(52,211,153,0.06); }
  .state-node.error   { border-color: rgba(248,113,113,0.3); color: var(--c-red); background: rgba(248,113,113,0.06); }
  .state-arrow {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 0.78em; color: var(--c-muted); padding: 0 4px;
  }
  .state-arrow .trigger-text {
    font-size: 0.85em; background: rgba(107,115,148,0.1);
    padding: 2px 8px; border-radius: 4px;
  }
  .irrev-rule {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 12px; border-radius: 14px; margin: 4px;
    font-size: 0.8em; background: rgba(248,113,113,0.06);
    border: 1px solid rgba(248,113,113,0.15); color: var(--c-red);
  }
  .cross-svc-rule {
    padding: 6px 12px; margin: 4px 0;
    font-size: 0.85em; color: var(--c-accent2);
    background: rgba(124,111,247,0.05); border-left: 3px solid rgba(124,111,247,0.3);
    border-radius: 4px;
  }

  /* ── Component Tree ── */
  .comp-node {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 16px 20px; margin-bottom: 8px;
    margin-left: 0;
  }
  .comp-node.child { margin-left: 20px; border-left: 2px solid rgba(91,141,239,0.2); }
  .comp-node .cn-header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap;
  }
  .comp-node .cn-name { font-weight: 600; font-size: 0.95em; color: var(--c-heading); }
  .comp-node .cn-path {
    font-family: monospace; font-size: 0.78em; color: var(--c-accent);
    background: rgba(91,141,239,0.08); padding: 2px 8px; border-radius: 4px;
  }
  .cn-section { margin: 8px 0; }
  .cn-section .cn-label {
    font-size: 0.68em; font-weight: 700; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;
  }
  .cn-tag {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 8px; border-radius: 4px; margin: 2px;
    font-size: 0.78em; background: rgba(255,255,255,0.03);
    border: 1px solid var(--c-border); color: var(--c-text);
  }
  .cn-tag.prop { border-color: rgba(91,141,239,0.2); color: var(--c-accent); }
  .cn-tag.event { border-color: rgba(52,211,153,0.2); color: var(--c-green); }
  .cn-tag.state { border-color: rgba(251,191,36,0.2); color: var(--c-amber); }
  .cn-behavior { font-size: 0.84em; color: var(--c-text); }
  .cn-edge { font-size: 0.82em; color: var(--c-muted); }
  .cn-edge .edge-icon { color: var(--c-amber); }

  /* ── State Design ── */
  .state-global-item {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 10px 14px; margin-bottom: 6px;
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 6px;
  }
  .state-global-item .sg-name {
    font-weight: 600; font-size: 0.9em; color: var(--c-heading); font-family: monospace;
  }
  .state-global-item .sg-type {
    font-size: 0.82em; color: var(--c-accent); font-family: monospace;
    background: rgba(91,141,239,0.06); padding: 1px 6px; border-radius: 3px;
  }

  /* ── Route Design ── */
  .route-row {
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    padding: 10px 14px; border-bottom: 1px solid var(--c-border);
  }
  .route-row:last-child { border-bottom: none; }

  /* ── Interaction Flows ── */
  .flow-timeline {
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 16px 20px; margin-bottom: 12px;
  }
  .flow-timeline .ft-title {
    font-weight: 600; font-size: 0.93em; color: var(--c-heading); margin-bottom: 10px;
  }
  .ft-step {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 6px 0; font-size: 0.86em;
  }
  .ft-step .ft-num {
    width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
    background: rgba(91,141,239,0.1); color: var(--c-accent);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.8em;
  }
  .ft-step .ft-text { color: var(--c-text); padding-top: 2px; }

  /* ── Gateway ── */
  .mw-flow {
    display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
    padding: 14px 18px;
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; margin-bottom: 12px;
  }
  .mw-node {
    padding: 6px 14px; border-radius: 6px; font-size: 0.84em; font-weight: 500;
    background: var(--c-card); border: 1px solid var(--c-border);
    color: var(--c-text); white-space: nowrap;
  }
  .mw-node.special {
    border-color: rgba(91,141,239,0.25); color: var(--c-accent);
    background: rgba(91,141,239,0.06);
  }
  .mw-arrow { color: var(--c-muted); font-size: 0.85em; }

  .auth-matrix {
    width: 100%; border-collapse: collapse; font-size: 0.85em;
  }
  .auth-matrix th {
    text-align: left; padding: 8px 12px; font-weight: 600;
    color: var(--c-muted); border-bottom: 2px solid var(--c-border);
  }
  .auth-matrix td { padding: 8px 12px; border-bottom: 1px solid var(--c-border); }
  .role-tag {
    display: inline-block; padding: 2px 8px; border-radius: 4px; margin: 1px 3px 1px 0;
    font-size: 0.82em; background: rgba(91,141,239,0.08); color: var(--c-accent);
  }

  @media (max-width: 700px) {
    body { padding: 24px 16px 48px; }
    h1 { font-size: 1.6em; }
    .section-body { padding: 20px 16px; }
    .role-cards { grid-template-columns: 1fr; }
    .arch-overview { flex-wrap: wrap; }
    .arch-ov-arrow { display: none; }
    .arch-tier { flex-direction: column; align-items: flex-start; gap: 4px; }
    .arch-tier-label { width: auto; text-align: left; padding-right: 0; }
    .arch-arrows { padding-left: 0; justify-content: flex-start; }
    .arch-tier-boxes { width: 100%; }
    .topo-tier { flex-direction: column; align-items: flex-start; gap: 4px; }
    .topo-tier-label { width: auto; text-align: left; padding-right: 0; padding-top: 0; }
    .topo-connector { padding-left: 0; }
    .flow-steps { flex-direction: column; align-items: flex-start; }
    .flow-arrow { display: none; }
    .cc-head { flex-direction: column; align-items: flex-start; gap: 6px; }
    .cc-meta { flex-direction: column; align-items: flex-start; }
    .page-layout { flex-direction: column; }
    .sidebar { display: none; }
    .sidebar.mobile-open { display: flex; }
    .sidebar-toggle { display: flex; }
  }

  /* ── Sidebar Layout ── */
  .page-layout {
    display: flex; min-height: 100vh;
  }
  .sidebar {
    position: fixed; top: 0; left: 0; bottom: 0;
    width: 230px; overflow-y: auto;
    background: var(--c-surface); border-right: 1px solid var(--c-border);
    display: flex; flex-direction: column; padding: 24px 0;
    z-index: 100;
  }
  .sidebar-header {
    padding: 0 20px 20px; border-bottom: 1px solid var(--c-border); margin-bottom: 12px;
  }
  .sidebar-header .sid {
    font-size: 0.72em; font-weight: 600; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  .sidebar-header .stitle {
    font-size: 0.95em; font-weight: 700; color: var(--c-heading);
    margin-top: 4px; line-height: 1.3;
  }
  .sidebar-nav { flex: 1; padding: 0 12px; }
  .sidebar-link {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px; border-radius: 7px;
    font-size: 0.86em; color: var(--c-muted); text-decoration: none;
    margin-bottom: 2px; transition: all 0.15s;
  }
  .sidebar-link:hover { color: var(--c-text); background: rgba(255,255,255,0.03); }
  .sidebar-link.active {
    color: var(--c-accent); background: rgba(91,141,239,0.1);
    font-weight: 600;
  }
  .sidebar-link .sl-icon { font-size: 1.05em; width: 20px; text-align: center; flex-shrink: 0; }
  .sidebar-toggle {
    display: none; position: fixed; top: 12px; left: 12px; z-index: 200;
    width: 36px; height: 36px; border-radius: 8px; border: 1px solid var(--c-border);
    background: var(--c-surface); color: var(--c-text); font-size: 1.2em;
    cursor: pointer; align-items: center; justify-content: center;
  }
  .main-content {
    margin-left: 230px; flex: 1; min-width: 0;
    max-width: 860px; padding: 48px 40px 80px;
  }
  html { scroll-behavior: smooth; }
  /* ── WBS / Task new fields ── */
  .layer-badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.8em; font-weight: 600; margin-right: 8px;
  }
  .layer-0 { background: rgba(124,111,247,0.15); color: var(--c-accent2); }
  .layer-1 { background: rgba(91,141,239,0.15); color: var(--c-accent); }
  .layer-2 { background: rgba(52,211,153,0.15); color: var(--c-green); }
  .layer-3 { background: rgba(251,191,36,0.12); color: var(--c-amber); }
  .layer-other { background: rgba(107,115,148,0.12); color: var(--c-muted); }
  .file-list { list-style: none; padding: 0; margin: 0; }
  .file-list li {
    font-family: "JetBrains Mono", "Cascadia Code", monospace;
    font-size: 0.88em; color: var(--c-accent);
    padding: 3px 0; border-bottom: 1px solid var(--c-border);
  }
  .file-list li:last-child { border-bottom: none; }
  .ref-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  .ref-table th, .ref-table td {
    text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--c-border);
  }
  .ref-table th { color: var(--c-muted); font-weight: 500; font-size: 0.85em; }
  .ac-item {
    padding: 6px 10px; border-radius: 6px; margin-bottom: 4px;
    border: 1px solid var(--c-border); font-size: 0.92em;
  }
  .ac-item .ac-vtype {
    display: inline-block; padding: 1px 8px; border-radius: 4px;
    font-size: 0.78em; font-weight: 600; margin-right: 6px;
  }
  .ac-vtype-precondition  { background: rgba(251,191,36,0.12); color: var(--c-amber); }
  .ac-vtype-postcondition { background: rgba(52,211,153,0.15); color: var(--c-green); }
  .ac-vtype-http_status   { background: rgba(91,141,239,0.15); color: var(--c-accent); }
  .ac-vtype-invariant     { background: rgba(239,68,68,0.12); color: var(--c-red); }
  .ac-vtype-state_transition { background: rgba(124,111,247,0.13); color: var(--c-accent2); }
  .ac-vtype-field_definition { background: rgba(34,211,238,0.12); color: var(--c-cyan); }
  .upstream-item {
    padding: 8px 12px; border-radius: 6px; margin-bottom: 6px;
    background: rgba(52,211,153,0.06); border: 1px solid rgba(52,211,153,0.15);
  }
  .upstream-item .up-name { font-weight: 600; color: var(--c-heading); }
  .scope-summary { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
  .scope-card {
    padding: 8px 12px; border-radius: 6px; border: 1px solid var(--c-border);
    font-size: 0.9em;
  }
  .scope-card .sc-count { font-size: 1.4em; font-weight: 700; color: var(--c-accent); }
  .scope-card .sc-label { color: var(--c-muted); font-size: 0.82em; }
  @media print {
    body { background: #fff; color: #222; }
    .section-body, .req-item, .story-item { background: #fff; border: 1px solid #ddd; }
    h1 { color: #111; }
  }
"""


def _page_start(title: str, doc_id: str, badge_label: str, created: str, author: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)} — {_esc(doc_id)}</title>
<style>{_SHARED_CSS}</style>
</head>
<body>
<div class="top-bar">
  <div class="doc-id">{_esc(doc_id)}</div>
  <div><span class="badge accent">{_esc(badge_label)}</span></div>
</div>
<h1><span>{_esc(badge_label)}</span> {_esc(title)}</h1>
<div class="meta">{_esc(created)} &middot; 作者: {_esc(author)}</div>
"""


_PAGE_END = """
<div class="footer">CogniForge 文档驱动系统</div>
</body>
</html>"""


def _section_header(icon: str, title: str, bg_color: str, sid: str = "") -> str:
    id_attr = f' id="{sid}"' if sid else ""
    return (
        f'<div class="section"{id_attr}>\n'
        f'  <div class="section-header">\n'
        f'    <div class="icon" style="background:{bg_color}">{icon}</div>\n'
        f'    <h2>{_esc(title)}</h2>\n'
        f'  </div>\n'
        f'  <div class="section-body">\n'
    )


_SECTION_FOOT = "  </div>\n</div>\n"


def _render_requirements(reqs: list) -> str:
    if not reqs:
        return "<p>暂无需求定义</p>"
    items = []
    for i, r in enumerate(reqs, 1):
        req_id = _esc(r.get("id", f"REQ-{i:03d}"))
        name = _esc(r.get("name", f"需求 {i}"))
        desc = _esc(r.get("description", ""))
        status = r.get("status", "draft")
        priority = r.get("priority", "")
        version = r.get("version", 1)
        ac = r.get("acceptance_criteria", [])

        # Status badge
        status_colors = {
            "draft": ("rgba(107,115,148,0.15)", "#9ca3af"),
            "active": ("rgba(52,211,153,0.15)", "#6ee7b7"),
            "changed": ("rgba(251,191,36,0.12)", "#fcd34d"),
            "deprecated": ("rgba(248,113,113,0.12)", "#fca5a5"),
            "removed": ("rgba(248,113,113,0.08)", "#6b7394"),
        }
        sc, st = status_colors.get(status, status_colors["draft"])
        status_badge = (
            f'<span style="font-size:0.75em;padding:2px 10px;border-radius:10px;'
            f'background:{sc};color:{st};margin-left:8px;">{_esc(status)}</span>'
        )

        # Priority tag
        pri_html = ""
        if priority:
            css = "high" if "高" in priority else ("medium" if "中" in priority else "low")
            pri_html = (
                f'<span class="priority-tag {css}" style="margin-left:6px;font-size:0.75em;">'
                f'{_esc(priority)}</span>'
            )

        ac_html = ""
        if ac:
            ac_items = "\n".join(f"<li>{_esc(a)}</li>" for a in ac)
            ac_html = (
                '<span class="ac-label">验收条件</span>\n'
                f'<ul class="ac-list">\n{ac_items}\n</ul>'
            )

        # Change history
        ch_html = ""
        ch = r.get("change_history", [])
        if ch:
            ch_rows = []
            for h in ch[-3:]:  # Show last 3 entries
                h_ver = h.get("version", "?")
                h_type = _esc(h.get("change_type", ""))
                h_summary = _esc(h.get("summary", ""))
                ch_rows.append(
                    f'<tr>'
                    f'<td style="color:var(--c-muted);white-space:nowrap;">v{h_ver}</td>'
                    f'<td style="color:var(--c-dim);white-space:nowrap;">{h_type}</td>'
                    f'<td>{h_summary}</td>'
                    f'</tr>'
                )
            ch_html = (
                '<details style="margin-top:8px;">\n'
                '<summary style="color:var(--c-muted);cursor:pointer;font-size:0.85em;">'
                '变更历史</summary>\n'
                '<table style="width:100%;font-size:0.82em;margin-top:4px;">\n'
                + "\n".join(ch_rows) +
                '\n</table>\n</details>'
            )

        # Dependencies
        deps = r.get("depends_on", [])
        supersedes = r.get("supersedes", [])
        meta_parts = []
        if deps:
            meta_parts.append(f'依赖: {", ".join(_esc(d) for d in deps)}')
        if supersedes:
            meta_parts.append(f'替代: {", ".join(_esc(s) for s in supersedes)}')

        dep_html = ""
        if meta_parts:
            dep_html = (
                f'<div style="font-size:0.8em;color:var(--c-muted);margin-top:6px;">'
                f'{"; ".join(meta_parts)}</div>'
            )

        items.append(
            f'<div class="req-item">\n'
            f'  <h3>'
            f'    <span style="font-family:monospace;font-size:0.85em;'
            f'color:var(--c-muted);margin-right:6px;">{req_id}</span>'
            f'    {name}{status_badge}{pri_html}'
            f'    <span style="font-size:0.75em;color:var(--c-muted);float:right;">'
            f'v{version}</span>'
            f'  </h3>\n'
            f'  <div class="req-desc">{desc}</div>\n'
            f'  {dep_html}\n'
            f'  {ac_html}\n'
            f'  {ch_html}\n'
            f'</div>'
        )
    return "\n".join(items)


def _render_stories(stories: list) -> str:
    if not stories:
        return "<p>暂无用户故事</p>"
    items = []
    for s in stories:
        sid = s.get("id", "")
        role = _esc(s.get("role", "用户"))
        action = _esc(s.get("action", "做某事"))
        goal = _esc(s.get("goal", ""))
        sid_html = f'<span style="font-family:monospace;font-size:0.8em;color:var(--c-muted);margin-right:6px;">{_esc(sid)}</span>' if sid else ""
        items.append(
            f'<div class="story-item">\n'
            f'  {sid_html}'
            f'  <span class="story-role">{role}</span>\n'
            f'  <div class="story-text">\n'
            f'    作为 <strong>{role}</strong>，我想要 <strong>{action}</strong>\n'
            f'    <br><span class="goal">以便：{goal}</span>\n'
            f'  </div>\n'
            f'</div>'
        )
    return "\n".join(items)


def _render_priorities(priorities: dict, reqs: list = None) -> str:
    if not priorities:
        return "<p>暂无优先级定义</p>"
    # Build ID → name lookup from requirements
    id_to_name = {}
    if reqs:
        for r in reqs:
            rid = r.get("id", "")
            rname = r.get("name", "")
            if rid and rname:
                id_to_name[rid] = rname
    tags = []
    for key, pri in priorities.items():
        display = id_to_name.get(key, key)
        css = "high" if "高" in pri else ("medium" if "中" in pri else "low")
        tags.append(
            f'<span class="priority-tag {css}">{_esc(display)} &middot; {_esc(pri)}</span>'
        )
    return f'<div class="priority-grid">\n' + "".join(tags) + "\n</div>"


# ---------------------------------------------------------------------------
# Render dispatcher
# ---------------------------------------------------------------------------

def render_to_html(doc_type: str, data: dict) -> str:
    """Convert an Agent-format JSON dict to a self-contained HTML string."""
    if doc_type == "prd":
        return _render_prd(data)
    elif doc_type == "sad":
        return _render_sad(data)
    elif doc_type == "lld":
        return _render_lld(data)
    elif doc_type == "report":
        return _render_report(data)
    elif doc_type == "test_case":
        return _render_test_case(data)
    elif doc_type == "deploy":
        return _render_deploy(data)
    elif doc_type == "adr":
        return _render_adr(data)
    elif doc_type == "task":
        return _render_task(data)
    else:
        return _render_generic(doc_type, data)


def render_file(json_path: Path, wiki_root: Path | None = None) -> Optional[Path]:
    """Read a JSON file, render to HTML under html/ subdir.  Returns the HTML path."""
    if not json_path.exists():
        return None
    try:
        data = load_json_with_repair(json_path)
    except (json.JSONDecodeError, ValueError):
        return None

    meta = data.get("meta", {})
    doc_type = meta.get("type", "prd")

    try:
        html = render_to_html(doc_type, data)
    except Exception:
        return None

    # Map .cogniforge/wiki/{type}[/{module}]/file.json → .cogniforge/html/{type}[/{module}]/file.html
    path_str = json_path.as_posix()
    marker = ".cogniforge/wiki/"
    idx = path_str.find(marker)
    if idx != -1:
        cogniforge_root = Path(path_str[:idx + len(".cogniforge/")])
        rel = Path(path_str[idx + len(marker):])
        html_dir = cogniforge_root / "html" / rel.parent
    else:
        html_dir = json_path.parent.parent / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / (json_path.stem + ".html")
    html_path.write_text(html, encoding="utf-8")
    return html_path


# ---------------------------------------------------------------------------
# Per-type renderers
# ---------------------------------------------------------------------------

def _render_prd(d: dict) -> str:
    m = d.get("meta", {})
    version = m.get("version", 1)
    last_modified = m.get("last_modified", m.get("created", ""))
    last_author = m.get("last_author", m.get("author", "pm_agent"))
    parts = [_page_start(
        m.get("title", "PRD"), m.get("doc_id", ""), "产品需求文档",
        m.get("created", ""), m.get("author", "pm_agent"),
    )]
    # Version info
    parts.append(
        f'<div class="meta">'
        f'版本 v{version} &middot; '
        f'最后修改: {_esc(last_modified)} &middot; '
        f'修改者: {_esc(last_author)}'
        f'</div>'
    )
    # Overview
    parts.append(_section_header("📋", "概述", "rgba(124,111,247,0.12)"))
    parts.append(f"<p>{_esc(d.get('overview', ''))}</p>")
    parts.append(_SECTION_FOOT)
    # Requirements
    reqs = d.get("requirements", [])
    parts.append(_section_header("📝", f"功能需求 ({len(reqs)})", "rgba(91,141,239,0.12)"))
    parts.append(_render_requirements(reqs))
    parts.append(_SECTION_FOOT)
    # User Stories
    stories = d.get("user_stories", [])
    parts.append(_section_header("👥", f"用户故事 ({len(stories)})", "rgba(34,211,238,0.12)"))
    parts.append(_render_stories(stories))
    parts.append(_SECTION_FOOT)
    # Priorities
    parts.append(_section_header("🎯", "优先级", "rgba(251,191,36,0.12)"))
    parts.append(_render_priorities(d.get("priorities", {}), d.get("requirements", [])))
    parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
    return "\n".join(parts)


def _render_overview_section(data) -> str:
    if not isinstance(data, dict):
        return "<p>系统概述数据缺失</p>"

    desc = data.get("description", "")
    roles = data.get("roles", [])
    parts = []
    if desc:
        parts.append(
            '<div class="overview-hero">'
            '<div class="hero-label">系统定位</div>'
            f"<p>{_esc(desc)}</p>"
            "</div>"
        )
    if roles:
        role_colors = {
            "管理员": ("rgba(124,111,247,0.15)", "#c4b5fd"),
            "老师":   ("rgba(91,141,239,0.15)", "#93c5fd"),
            "学生":   ("rgba(52,211,153,0.15)", "#6ee7b7"),
        }
        role_icons = {"管理员": "👤", "老师": "👩‍🏫", "学生": "🎓"}
        cards = []
        for r in roles:
            name = r.get("name", "")
            perms_list = r.get("permissions", [])
            bg, color = role_colors.get(name, ("rgba(255,255,255,0.04)", "var(--c-muted)"))
            icon = role_icons.get(name, "👤")
            perms_html = "".join(f"<li>{_esc(p)}</li>" for p in perms_list)
            cards.append(
                '<div class="role-card">'
                f'<div class="role-icon" style="background:{bg};color:{color}">{icon}</div>'
                f'<div class="role-name">{_esc(name)}</div>'
                f'<ul class="role-perms">{perms_html}</ul>'
                "</div>"
            )
        parts.append(f'<div class="role-cards">{"".join(cards)}</div>')
    if not desc and not roles:
        parts.append("<p>暂无概述</p>")
    return "\n".join(parts)


def _render_architecture_section(data, components: list) -> str:
    if not isinstance(data, dict):
        return "<p>架构数据缺失</p>"

    desc_text = data.get("description", "")
    style = data.get("style", "")
    features = data.get("features", [])
    layers = data.get("layers", [])
    connections = data.get("connections", [])
    parts = []

    if style:
        parts.append(f'<div class="arch-style-badge">{_esc(style)}</div>')
    if desc_text:
        parts.append(f'<div class="arch-desc">{_esc(desc_text)}</div>')

    # Layered diagram
    if layers:
        diag_parts = []
        css_map = {
            "frontend": "frontend", "gateway": "gateway", "service": "service",
            "database": "db", "infrastructure": "cache",
        }
        for idx, layer in enumerate(layers):
            layer_name = layer.get("name", "")
            boxes = []
            for comp_name in layer.get("components", []):
                css_cls = "service"
                for c in components:
                    if c.get("name") == comp_name:
                        css_cls = css_map.get(c.get("type", ""), "service")
                        break
                boxes.append(f'<div class="topo-node {css_cls}">{_esc(comp_name)}</div>')
            if boxes:
                diag_parts.append(
                    '<div class="topo-tier">'
                    f'<div class="topo-tier-label">{_esc(layer_name)}</div>'
                    f'<div class="topo-tier-content">{"".join(boxes)}</div>'
                    '</div>'
                )
            if idx < len(layers) - 1 and idx < len(connections):
                proto = connections[idx].get("protocol", "")
                diag_parts.append(
                    '<div class="topo-connector">'
                    f'<div class="topo-connector-line"><span class="proto">{_esc(proto)}</span></div>'
                    '</div>'
                )
        parts.append(f'<div class="topo-diagram">{"".join(diag_parts)}</div>')

    # Feature tags
    if features:
        color_map = {
            "微服务": "var(--c-accent2)", "API Gateway": "var(--c-accent)",
            "关系型数据库": "var(--c-green)", "Redis": "var(--c-amber)",
            "消息队列": "var(--c-red)", "RESTful": "var(--c-cyan)",
            "独立部署": "var(--c-accent)",
        }
        tags = []
        for f in features:
            color = "var(--c-muted)"
            for key, c in color_map.items():
                if key in f:
                    color = c
                    break
            tags.append(
                f'<span class="arch-feature-tag">'
                f'<span class="dot" style="background:{color}"></span>{_esc(f)}'
                f'</span>'
            )
        if tags:
            parts.append(f'<div class="arch-features">{"".join(tags)}</div>')

    if not parts:
        parts.append("<p>暂无架构描述</p>")
    return "\n".join(parts)


def _render_techstack_section(data) -> str:
    """Render tech_stack as a structured table grouped by category."""
    if not isinstance(data, dict) or not data:
        return "<p>暂无技术选型</p>"

    rows = []
    for category, value in data.items():
        if isinstance(value, dict):
            tags = "".join(
                f'<span class="arch-feature-tag" style="margin:2px">'
                f'<span class="dot" style="background:var(--c-accent)"></span>'
                f'{_esc(f"{k}: {v}")}</span>'
                for k, v in value.items()
            )
        else:
            tags = (
                f'<span class="arch-feature-tag" style="margin:2px">'
                f'<span class="dot" style="background:var(--c-accent)"></span>'
                f'{_esc(str(value))}</span>'
            )
        rows.append(
            f'<tr>'
            f'<td style="font-weight:600;color:var(--c-heading);width:160px">'
            f'{_esc(category)}</td>'
            f'<td>{tags}</td>'
            f'</tr>'
        )

    return (
        '<table style="width:100%;border-collapse:collapse;margin-top:8px">'
        f'{"".join(rows)}'
        '</table>'
    )


def _render_dataflow_section(data) -> str:
    if not isinstance(data, list) or not data:
        return "<p>暂无数据流描述</p>"

    schemes = [
        ("rgba(52,211,153,0.15)", "var(--c-green)"),
        ("rgba(91,141,239,0.15)", "var(--c-accent)"),
        ("rgba(251,191,36,0.12)", "var(--c-amber)"),
        ("rgba(124,111,247,0.15)", "var(--c-accent2)"),
    ]
    cards = []
    for idx, flow in enumerate(data):
        name = flow.get("name", f"Flow {idx + 1}")
        steps = flow.get("steps", [])
        bg, color = schemes[idx % len(schemes)]
        step_htmls = []
        for si, step in enumerate(steps):
            css = "start" if si == 0 else ("end" if si == len(steps) - 1 else "mid")
            step_htmls.append(f'<span class="flow-step {css}">{_esc(step)}</span>')
            if si < len(steps) - 1:
                step_htmls.append('<span class="flow-arrow">→</span>')
        cards.append(
            '<div class="flow-card">'
            '<div class="flow-card-header">'
            f'<div class="flow-num" style="background:{bg};color:{color}">{idx + 1}</div>'
            f'<div class="flow-name">{_esc(name)}</div>'
            '</div>'
            f'<div class="flow-steps">{"".join(step_htmls)}</div>'
            '</div>'
        )
    return f'<div class="flow-cards">{"".join(cards)}</div>'


# ---------------------------------------------------------------------------
# Enhanced component card (SAD)
# ---------------------------------------------------------------------------

def _render_component_card(c: dict, type_icons: dict) -> str:
    """Render a single enhanced component card with status/version/traceability/history."""
    ctype = c.get("type", "")
    icon = type_icons.get(ctype, "📦")
    cid = _esc(c.get("id", ""))
    name = _esc(c.get("name", ""))
    desc = _esc(c.get("description", ""))
    status = c.get("status", "active")
    version = c.get("version", 1)

    # Status badge
    status_colors = {
        "draft": ("rgba(107,115,148,0.15)", "#9ca3af"),
        "active": ("rgba(52,211,153,0.15)", "#6ee7b7"),
        "changed": ("rgba(251,191,36,0.12)", "#fcd34d"),
        "deprecated": ("rgba(248,113,113,0.12)", "#fca5a5"),
        "removed": ("rgba(248,113,113,0.08)", "#6b7394"),
    }
    sc, st = status_colors.get(status, status_colors["draft"])
    status_badge = (
        f'<span style="font-size:0.72em;padding:2px 10px;border-radius:10px;'
        f'background:{sc};color:{st};margin-left:8px;">{_esc(status)}</span>'
    )

    items_html = "".join(f"<li>{_esc(r)}</li>" for r in c.get("responsibilities", []))

    # Source requirements
    src_reqs = c.get("source_requirements", [])
    src_html = ""
    if src_reqs:
        tags = " ".join(
            f'<span class="cn-tag prop">{_esc(r)}</span>' for r in src_reqs
        )
        src_html = (
            f'<div style="margin-top:6px;font-size:0.82em;color:var(--c-muted)">'
            f'关联需求: {tags}</div>'
        )

    # Depends on
    deps = c.get("depends_on_components", [])
    dep_html = ""
    if deps:
        tags = " ".join(
            f'<span class="cc-consumer">{_esc(d)}</span>' for d in deps
        )
        dep_html = (
            f'<div style="margin-top:4px;font-size:0.82em;color:var(--c-muted)">'
            f'依赖组件: {tags}</div>'
        )

    # Contracts
    comp_ctrs = c.get("contracts", [])
    ctr_html = ""
    if comp_ctrs:
        tags = " ".join(
            f'<span style="font-family:monospace;font-size:0.82em;color:var(--c-accent);'
            f'background:rgba(91,141,239,0.08);padding:1px 6px;border-radius:4px;margin:1px">'
            f'{_esc(ct)}</span>' for ct in comp_ctrs
        )
        ctr_html = (
            f'<div style="margin-top:4px;font-size:0.82em;color:var(--c-muted)">'
            f'提供契约: {tags}</div>'
        )

    # Change history
    ch_html = ""
    ch = c.get("change_history", [])
    if ch:
        ch_rows = []
        for h in ch[-3:]:
            h_ver = h.get("version", "?")
            h_type = _esc(h.get("change_type", ""))
            h_summary = _esc(h.get("summary", ""))
            ch_rows.append(
                f'<tr>'
                f'<td style="color:var(--c-muted);white-space:nowrap;">v{h_ver}</td>'
                f'<td style="color:var(--c-dim);white-space:nowrap;">{h_type}</td>'
                f'<td>{h_summary}</td>'
                f'</tr>'
            )
        ch_html = (
            '<details style="margin-top:6px;">'
            '<summary style="color:var(--c-muted);cursor:pointer;font-size:0.82em;">'
            '变更历史</summary>'
            '<table style="width:100%;font-size:0.8em;margin-top:4px;">'
            + "".join(ch_rows) +
            '</table></details>'
        )

    return (
        f'<div class="comp-item">\n'
        f'  <h3>{icon} {name}'
        f'    <span style="font-family:monospace;font-size:0.8em;'
        f'color:var(--c-muted);margin-left:6px;">{cid}</span>'
        f'    {status_badge}'
        f'    <span style="font-size:0.75em;color:var(--c-muted);float:right;">v{version}</span>'
        f'  </h3>\n'
        f'  <div class="comp-type">{_esc(ctype)}</div>\n'
        f'  <p>{desc}</p>\n'
        f'  {src_html}\n'
        f'  {dep_html}\n'
        f'  {ctr_html}\n'
        f'  <ul class="comp-resp">{items_html}</ul>\n'
        f'  {ch_html}\n'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Enhanced contracts section (SAD)
# ---------------------------------------------------------------------------

def _render_contracts_section_enhanced(contracts: list) -> str:
    """Render contracts grouped by provider with enhanced fields."""
    if not contracts:
        return ""

    from collections import OrderedDict
    groups: dict[str, list] = OrderedDict()
    for c in contracts:
        provider = c.get("provider", "Other")
        groups.setdefault(provider, []).append(c)

    parts = []
    for provider, items in groups.items():
        cards = []
        for c in items:
            ctype = c.get("type", "REST")
            endpoint = c.get("endpoint", "")
            method = ""
            ep_path = endpoint
            parts_ep = endpoint.split(" ", 1)
            if len(parts_ep) == 2 and parts_ep[0] in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                method = parts_ep[0]
                ep_path = parts_ep[1]
            elif ctype in ("MQ", "WebSocket", "SSE", "Event", "CLI", "InternalFunction"):
                method = ctype

            # Status badge
            status = c.get("status", "active")
            status_colors = {
                "draft": ("rgba(107,115,148,0.15)", "#9ca3af"),
                "active": ("rgba(52,211,153,0.15)", "#6ee7b7"),
                "changed": ("rgba(251,191,36,0.12)", "#fcd34d"),
                "deprecated": ("rgba(248,113,113,0.12)", "#fca5a5"),
                "removed": ("rgba(248,113,113,0.08)", "#6b7394"),
            }
            sc, st = status_colors.get(status, status_colors["draft"])
            status_badge = (
                f'<span style="font-size:0.72em;padding:2px 10px;border-radius:10px;'
                f'background:{sc};color:{st};margin-left:6px;">{_esc(status)}</span>'
            )

            # Provider component ID
            pid = c.get("provider_component_id", "")
            pid_html = ""
            if pid:
                pid_html = (
                    f'<span style="font-family:monospace;font-size:0.78em;color:var(--c-muted);'
                    f'margin-left:4px;">[{_esc(pid)}]</span>'
                )

            version = c.get("version", 1)
            consumers = c.get("consumers", [])
            consumers_html = " ".join(
                f'<span class="cc-consumer">{_esc(x)}</span>' for x in consumers
            )

            # Request body table
            req_body = c.get("request", {}).get("body", {})
            req_html = ""
            if isinstance(req_body, dict) and req_body:
                rows = ""
                for k, v in req_body.items():
                    rows += (
                        f'<tr><td>{_esc(k)}</td>'
                        f'<td class="field-type">{_esc(v)}</td></tr>'
                    )
                req_html = (
                    '<div class="body-label">Request</div>'
                    '<table class="body-table"><thead><tr>'
                    '<th>字段</th><th>类型</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )

            # Response body table
            resp_body = c.get("response", {}).get("body", {})
            resp_html = ""
            if isinstance(resp_body, dict) and resp_body:
                rows = ""
                for k, v in resp_body.items():
                    rows += (
                        f'<tr><td>{_esc(k)}</td>'
                        f'<td class="field-type">{_esc(v)}</td></tr>'
                    )
                resp_html = (
                    '<div class="body-label">Response</div>'
                    '<table class="body-table"><thead><tr>'
                    '<th>字段</th><th>类型</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )

            # Errors table
            errors = c.get("errors", [])
            err_html = ""
            if errors:
                err_rows = ""
                for e in errors:
                    err_rows += (
                        f'<tr><td style="font-family:monospace">{_esc(str(e.get("status","")))}</td>'
                        f'<td style="font-family:monospace;color:var(--c-red)">{_esc(e.get("code",""))}</td>'
                        f'<td style="font-size:0.85em">{_esc(e.get("message",""))}</td></tr>'
                    )
                err_html = (
                    '<div class="body-label">错误码</div>'
                    '<table class="body-table"><thead><tr><th>状态</th><th>Code</th><th>说明</th></tr></thead>'
                    f'<tbody>{err_rows}</tbody></table>'
                )

            # Source requirements
            src_reqs = c.get("source_requirements", [])
            src_html = ""
            if src_reqs:
                tags = " ".join(
                    f'<span class="cn-tag prop">{_esc(r)}</span>' for r in src_reqs
                )
                src_html = (
                    f'<div style="margin-top:4px;font-size:0.8em;color:var(--c-muted)">'
                    f'关联需求: {tags}</div>'
                )

            # Change history
            ch_html = ""
            ch = c.get("change_history", [])
            if ch:
                ch_rows = []
                for h in ch[-3:]:
                    h_ver = h.get("version", "?")
                    h_type = _esc(h.get("change_type", ""))
                    h_summary = _esc(h.get("summary", ""))
                    ch_rows.append(
                        f'<tr>'
                        f'<td style="color:var(--c-muted);white-space:nowrap;">v{h_ver}</td>'
                        f'<td style="color:var(--c-dim);white-space:nowrap;">{h_type}</td>'
                        f'<td>{h_summary}</td>'
                        f'</tr>'
                    )
                ch_html = (
                    '<details style="margin-top:6px;">'
                    '<summary style="color:var(--c-muted);cursor:pointer;font-size:0.82em;">'
                    '变更历史</summary>'
                    '<table style="width:100%;font-size:0.8em;margin-top:4px;">'
                    + "".join(ch_rows) +
                    '</table></details>'
                )

            method_cls = method.lower() if method else ""
            cards.append(
                '<div class="contract-card">'
                '<div class="cc-head">'
                + (f'<span class="method-badge {method_cls}">{_esc(method)}</span>' if method else "")
                + f'<span class="cc-endpoint">{_esc(ep_path)}</span>'
                + f'<span class="cc-type-tag">{_esc(ctype)}</span>'
                + f'<span class="cc-name">{_esc(c.get("interface", ""))}</span>'
                + f'{pid_html}{status_badge}'
                + f'<span style="font-size:0.75em;color:var(--c-muted);margin-left:auto;">v{version}</span>'
                '</div>'
                f'<div class="cc-desc">{_esc(c.get("description", ""))}</div>'
                + (f'<div class="cc-meta">→ {consumers_html}</div>' if consumers_html else "")
                + req_html + resp_html + err_html + src_html + ch_html
                + '</div>'
            )

        parts.append(
            '<details class="contract-group" open>'
            f'<summary>{_esc(provider)} <span class="cg-count">{len(items)}</span></summary>'
            f'{"".join(cards)}'
            '</details>'
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Data models section (SAD)
# ---------------------------------------------------------------------------

def _render_sad_data_models(models: list) -> str:
    """Render SAD-level data models."""
    if not models:
        return "<p>暂无数据模型</p>"
    cards = []
    for dm in models:
        rows = ""
        for f in dm.get("fields", []):
            if isinstance(f, str):
                rows += f"<tr><td>{_esc(f)}</td><td></td><td></td></tr>"
            else:
                required = f.get("required", False)
                req_mark = ' <span style="color:var(--c-red);font-size:0.75em">*</span>' if required else ""
                rows += (
                    f"<tr><td>{_esc(f.get('name',''))}{req_mark}</td>"
                    f"<td class=\"field-type\">{_esc(f.get('type',''))}</td>"
                    f"<td>{_esc(f.get('description',''))}</td></tr>"
                )
        src_reqs = dm.get("source_requirements", [])
        src_html = ""
        if src_reqs:
            tags = " ".join(
                f'<span class="cn-tag prop">{_esc(r)}</span>' for r in src_reqs
            )
            src_html = (
                f'<div style="margin-top:4px;font-size:0.8em;color:var(--c-muted)">'
                f'关联需求: {tags}</div>'
            )
        cards.append(
            f'<div class="contract-card" style="border-top:none">'
            f'<h3 style="font-size:0.95em;font-weight:600;color:var(--c-heading);margin-bottom:4px">'
            f'🗄️ {_esc(dm.get("name",""))}'
            f'<span style="font-family:monospace;font-size:0.8em;color:var(--c-muted);margin-left:6px">'
            f'{_esc(dm.get("id",""))}</span></h3>'
            f'<p style="font-size:0.85em;color:var(--c-muted);margin-bottom:8px">{_esc(dm.get("description",""))}</p>'
            f'{src_html}'
            f'<div class="body-label">字段</div>'
            f'<table class="body-table"><thead><tr><th>字段名</th><th>类型</th><th>描述</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
            f'</div>'
        )
    return "\n".join(cards)


# ---------------------------------------------------------------------------
# Requirement traceability section (SAD)
# ---------------------------------------------------------------------------

def _render_traceability_section(traces: list) -> str:
    """Render requirement traceability matrix."""
    if not traces:
        return "<p>暂无需求追溯</p>"
    coverage_colors = {
        "full": ("rgba(52,211,153,0.15)", "#6ee7b7"),
        "partial": ("rgba(251,191,36,0.12)", "#fcd34d"),
        "none": ("rgba(248,113,113,0.12)", "#fca5a5"),
        "blocked": ("rgba(107,115,148,0.15)", "#9ca3af"),
    }
    rows = []
    for t in traces:
        rid = _esc(t.get("requirement_id", ""))
        cov = t.get("coverage", "none")
        cov_bg, cov_color = coverage_colors.get(cov, coverage_colors["none"])
        cov_badge = (
            f'<span style="font-size:0.8em;padding:2px 10px;border-radius:10px;'
            f'background:{cov_bg};color:{cov_color};">{_esc(cov)}</span>'
        )
        comps = " ".join(
            f'<span class="cn-tag prop">{_esc(c)}</span>'
            for c in t.get("components", [])
        )
        ctrs = " ".join(
            f'<span style="font-family:monospace;font-size:0.8em;color:var(--c-accent)">{_esc(ct)}</span>'
            for ct in t.get("contracts", [])
        )
        dms = " ".join(
            f'<span style="font-family:monospace;font-size:0.8em;color:var(--c-accent2)">{_esc(d)}</span>'
            for d in t.get("data_models", [])
        )
        notes = _esc(t.get("notes", ""))
        rows.append(
            f'<tr>'
            f'<td style="font-family:monospace;font-weight:600">{rid}</td>'
            f'<td>{cov_badge}</td>'
            f'<td>{comps or "—"}</td>'
            f'<td>{ctrs or "—"}</td>'
            f'<td>{dms or "—"}</td>'
            f'<td style="font-size:0.85em;color:var(--c-muted)">{notes}</td>'
            f'</tr>'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:0.88em">'
        '<thead><tr>'
        '<th>需求</th><th>覆盖</th><th>组件</th><th>接口</th><th>数据模型</th><th>备注</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
    )


# ---------------------------------------------------------------------------
# Architecture decisions section (SAD)
# ---------------------------------------------------------------------------

def _render_adr_list(adrs: list) -> str:
    """Render architecture decision records. Accepts dicts or plain strings."""
    if not adrs:
        return "<p>暂无架构决策</p>"
    schemes = [
        ("rgba(52,211,153,0.15)", "var(--c-green)"),
        ("rgba(91,141,239,0.15)", "var(--c-accent)"),
        ("rgba(251,191,36,0.12)", "var(--c-amber)"),
        ("rgba(124,111,247,0.15)", "var(--c-accent2)"),
    ]
    cards = []
    for idx, adr in enumerate(adrs):
        if isinstance(adr, str):
            adr_id = f"ADR-{idx + 1:03d}"
            title = _esc(adr)
            decision = ""
            reason = ""
            impacts = []
        else:
            adr_id = _esc(adr.get("id", f"ADR-{idx + 1:03d}"))
            title = _esc(adr.get("title", str(adr)))
            decision = _esc(adr.get("decision", ""))
            reason = _esc(adr.get("reason", ""))
            impacts = adr.get("impacts", [])
        bg, color = schemes[idx % len(schemes)]
        imp_html = ""
        if impacts:
            tags = " ".join(
                f'<span class="cn-tag prop">{_esc(imp)}</span>' for imp in impacts
            )
            imp_html = f'<div style="margin-top:8px"><strong style="font-size:0.82em;color:var(--c-muted)">影响范围: </strong>{tags}</div>'
        cards.append(
            '<div class="flow-card">'
            '<div class="flow-card-header">'
            f'<div class="flow-num" style="background:{bg};color:{color}">{idx + 1}</div>'
            f'<div class="flow-name">{adr_id}: {title}</div>'
            '</div>'
            f'<p style="font-size:0.88em;color:var(--c-text);margin-bottom:6px"><strong>决策:</strong> {decision}</p>'
            f'<p style="font-size:0.85em;color:var(--c-muted)"><strong>原因:</strong> {reason}</p>'
            f'{imp_html}'
            '</div>'
        )
    return f'<div class="flow-cards">{"".join(cards)}</div>'


# ---------------------------------------------------------------------------
# Risks section (SAD)
# ---------------------------------------------------------------------------

def _render_risks_section(risks: list) -> str:
    """Render technical risks table. Accepts dicts or plain strings."""
    if not risks:
        return "<p>暂无技术风险</p>"
    level_colors = {
        "高": ("rgba(248,113,113,0.15)", "#fca5a5"),
        "中": ("rgba(251,191,36,0.12)", "#fcd34d"),
        "低": ("rgba(107,115,148,0.15)", "#9ca3af"),
    }
    rows = []
    for i, r in enumerate(risks, 1):
        if isinstance(r, str):
            rid = f"RSK-{i:03d}"
            desc = _esc(r)
            level = "中"
            mitigation = ""
        else:
            rid = _esc(r.get("id", f"RSK-{i:03d}"))
            desc = _esc(r.get("description", str(r)))
            level = r.get("level", "中")
            mitigation = _esc(r.get("mitigation", ""))
        lv_bg, lv_color = level_colors.get(level, level_colors["中"])
        level_badge = (
            f'<span style="font-size:0.82em;padding:2px 10px;border-radius:10px;'
            f'background:{lv_bg};color:{lv_color};font-weight:600;">{_esc(level)}</span>'
        )
        rows.append(
            f'<tr>'
            f'<td style="font-family:monospace">{rid}</td>'
            f'<td>{desc}</td>'
            f'<td>{level_badge}</td>'
            f'<td style="font-size:0.88em">{mitigation}</td>'
            f'</tr>'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:0.9em">'
        '<thead><tr>'
        '<th>ID</th><th>描述</th><th>等级</th><th>缓解措施</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
    )


# ---------------------------------------------------------------------------
# Open questions section (SAD)
# ---------------------------------------------------------------------------

def _render_open_questions_section(questions: list) -> str:
    """Render open architecture questions. Accepts dicts or plain strings."""
    if not questions:
        return "<p>暂无待澄清问题</p>"
    items = []
    for i, q in enumerate(questions, 1):
        if isinstance(q, str):
            qid = f"Q-{i:03d}"
            question = _esc(q)
            status = "open"
        else:
            qid = _esc(q.get("id", f"Q-{i:03d}"))
            question = _esc(q.get("question", str(q)))
            status = q.get("status", "open")
        status_color = "var(--c-amber)" if status == "open" else "var(--c-green)"
        status_bg = "rgba(251,191,36,0.1)" if status == "open" else "rgba(52,211,153,0.1)"
        status_badge = (
            f'<span style="font-size:0.75em;padding:2px 10px;border-radius:10px;'
            f'background:{status_bg};color:{status_color};margin-left:8px;">{_esc(status)}</span>'
        )
        items.append(
            f'<div class="req-item">'
            f'<h3><span style="font-family:monospace;font-size:0.85em;color:var(--c-muted)">{qid}</span>'
            f'{status_badge}</h3>'
            f'<p>{question}</p>'
            f'</div>'
        )
    return "\n".join(items)


# ---------------------------------------------------------------------------
# Sidebar-aware page wrappers
# ---------------------------------------------------------------------------

_SIDEBAR_SCRIPT = """
<script>
(function() {
  var links = document.querySelectorAll('.sidebar-link');
  var sections = [];
  links.forEach(function(l) { var s = document.getElementById(l.getAttribute('href').slice(1)); if (s) sections.push([s, l]); });
  function update() {
    var top = window.scrollY + 80;
    var active = null;
    sections.forEach(function(p) { if (p[0].offsetTop <= top) active = p[1]; });
    links.forEach(function(l) { l.classList.remove('active'); });
    if (active) active.classList.add('active');
  }
  window.addEventListener('scroll', update, {passive: true});
  update();

  var toggle = document.getElementById('sidebar-toggle');
  var sidebar = document.getElementById('sidebar');
  if (toggle && sidebar) {
    toggle.addEventListener('click', function() { sidebar.classList.toggle('mobile-open'); });
  }
})();
</script>
"""


def _render_sidebar(doc_id: str, title: str, sections: list) -> str:
    """Generate sidebar nav HTML. sections: list of (id, icon, label)."""
    links = []
    for sid, icon, label in sections:
        links.append(
            f'<a href="#{sid}" class="sidebar-link">'
            f'<span class="sl-icon">{icon}</span>{_esc(label)}'
            f'</a>'
        )
    return (
        '<nav class="sidebar" id="sidebar">'
        '<div class="sidebar-header">'
        f'<div class="sid">{_esc(doc_id)}</div>'
        f'<div class="stitle">{_esc(title)}</div>'
        '</div>'
        f'<div class="sidebar-nav">{"".join(links)}</div>'
        '</nav>'
    )


def _page_start_sidebar(title: str, doc_id: str, badge_label: str,
                        created: str, author: str, sections: list) -> str:
    """Page start with sidebar layout. sections: list of (id, icon, label)."""
    sidebar_html = _render_sidebar(doc_id, title, sections)
    return (
        f"<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        f"<meta charset=\"UTF-8\">\n"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"<title>{_esc(title)} — {_esc(doc_id)}</title>\n"
        f"<style>{_SHARED_CSS}</style>\n"
        f"</head>\n<body>\n"
        f"<div class=\"page-layout\">\n"
        + sidebar_html
        + '<button id="sidebar-toggle" class="sidebar-toggle" aria-label="菜单">☰</button>\n'
        + '<div class="main-content">\n'
        f'<div class="top-bar">\n'
        f'  <div class="doc-id">{_esc(doc_id)}</div>\n'
        f'  <div><span class="badge accent">{_esc(badge_label)}</span></div>\n'
        f'</div>\n'
        f'<h1><span>{_esc(badge_label)}</span> {_esc(title)}</h1>\n'
        f'<div class="meta">{_esc(created)} &middot; 作者: {_esc(author)}</div>\n'
    )


_PAGE_END_SIDEBAR = (
    '<div class="footer">CogniForge 文档驱动系统</div>\n'
    "</div>\n"  # .main-content
    "</div>\n"  # .page-layout
    + _SIDEBAR_SCRIPT
    + "</body>\n</html>"
)


def _render_contracts_section(contracts: list) -> str:
    """Render contracts grouped by provider with collapsible groups."""
    if not contracts:
        return ""

    # Group by provider
    from collections import OrderedDict
    groups: dict[str, list] = OrderedDict()
    for c in contracts:
        provider = c.get("provider", "Other")
        groups.setdefault(provider, []).append(c)

    parts = []
    for provider, items in groups.items():
        cards = []
        for c in items:
            ctype = c.get("type", "REST")
            endpoint = c.get("endpoint", "")
            # Extract HTTP method for badge
            method = ""
            ep_path = endpoint
            parts_ep = endpoint.split(" ", 1)
            if len(parts_ep) == 2 and parts_ep[0] in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                method = parts_ep[0]
                ep_path = parts_ep[1]
            elif ctype == "MQ":
                method = "MQ"

            consumers = c.get("consumers", [])
            consumers_html = " ".join(
                f'<span class="cc-consumer">{_esc(x)}</span>' for x in consumers
            )

            # Build request body table
            req_body = c.get("request", {}).get("body", {})
            req_html = ""
            if isinstance(req_body, dict) and req_body:
                rows = ""
                for k, v in req_body.items():
                    rows += (
                        f'<tr><td>{_esc(k)}</td>'
                        f'<td class="field-type">{_esc(v)}</td></tr>'
                    )
                req_html = (
                    '<div class="body-label">Request</div>'
                    '<table class="body-table"><thead><tr>'
                    '<th>字段</th><th>类型</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )

            # Build response body table
            resp_body = c.get("response", {}).get("body", {})
            resp_html = ""
            if isinstance(resp_body, dict) and resp_body:
                rows = ""
                for k, v in resp_body.items():
                    rows += (
                        f'<tr><td>{_esc(k)}</td>'
                        f'<td class="field-type">{_esc(v)}</td></tr>'
                    )
                resp_html = (
                    '<div class="body-label">Response</div>'
                    '<table class="body-table"><thead><tr>'
                    '<th>字段</th><th>类型</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )

            method_cls = method.lower() if method else ""
            cards.append(
                '<div class="contract-card">'
                '<div class="cc-head">'
                + (f'<span class="method-badge {method_cls}">{_esc(method)}</span>' if method else "")
                + f'<span class="cc-endpoint">{_esc(ep_path)}</span>'
                + f'<span class="cc-type-tag">{_esc(ctype)}</span>'
                + f'<span class="cc-name">{_esc(c.get("interface", ""))}</span>'
                '</div>'
                f'<div class="cc-desc">{_esc(c.get("description", ""))}</div>'
                + (f'<div class="cc-meta">→ {consumers_html}</div>' if consumers_html else "")
                + req_html + resp_html
                + '</div>'
            )

        parts.append(
            '<details class="contract-group" open>'
            f'<summary>{_esc(provider)} <span class="cg-count">{len(items)}</span></summary>'
            f'{"".join(cards)}'
            '</details>'
        )

    return "\n".join(parts)


def _render_sad(d: dict) -> str:
    m = d.get("meta", {})
    title = m.get("title", "SAD")
    doc_id = m.get("doc_id", "")
    comps = d.get("components", [])
    contracts = d.get("contracts", [])
    arch_data = d.get("architecture", "")

    # Build section list for sidebar
    sections = [
        ("overview", "📄", "系统概述"),
        ("architecture", "🏗️", "架构设计"),
    ]
    if d.get("tech_stack"):
        sections.append(("techstack", "🛠️", "技术选型"))
    sections.append(("components", "🧩", f"组件设计 ({len(comps)})"))
    if contracts:
        sections.append(("contracts", "🔗", f"接口契约 ({len(contracts)})"))
    if d.get("data_flow"):
        sections.append(("dataflow", "📊", "数据流"))
    if d.get("data_models"):
        sections.append(("models", "🗄️", f"数据模型 ({len(d['data_models'])})"))
    if d.get("requirement_traceability"):
        sections.append(("traceability", "🔍", "需求追溯"))
    if d.get("architecture_decisions"):
        sections.append(("decisions", "📋", f"架构决策 ({len(d['architecture_decisions'])})"))
    if d.get("risks"):
        sections.append(("risks", "⚠️", f"技术风险 ({len(d['risks'])})"))
    if d.get("open_questions"):
        sections.append(("questions", "❓", "待澄清问题"))

    parts = [_page_start_sidebar(
        title, doc_id, "系统架构文档",
        m.get("created", ""), m.get("author", "architect_agent"),
        sections,
    )]

    # Version + source_prd info line
    version = m.get("version", 1)
    sp = d.get("source_prd", {})
    meta_extra = f'版本 v{version}'
    if sp:
        prd_id = _esc(sp.get("doc_id", ""))
        prd_ver = sp.get("version", "?")
        pm_turn = _esc(sp.get("last_pm_turn_id", ""))
        meta_extra += f' &middot; 源自 PRD: {prd_id} v{prd_ver}'
        if pm_turn:
            meta_extra += f' ({pm_turn})'
    parts.append(f'<div class="meta">{meta_extra}</div>')

    overview_text = d.get("system_overview", "")
    parts.append(_section_header("📄", "系统概述", "rgba(124,111,247,0.12)", "overview"))
    parts.append(_render_overview_section(overview_text))
    parts.append(_SECTION_FOOT)

    # Architecture
    parts.append(_section_header("🏗️", "架构设计", "rgba(91,141,239,0.12)", "architecture"))
    parts.append(_render_architecture_section(arch_data, comps))
    parts.append(_SECTION_FOOT)

    # Tech Stack
    if d.get("tech_stack"):
        parts.append(_section_header("🛠️", "技术选型", "rgba(52,211,153,0.12)", "techstack"))
        parts.append(_render_techstack_section(d["tech_stack"]))
        parts.append(_SECTION_FOOT)

    # Components — enhanced with status/version/source_requirements/change_history
    parts.append(_section_header("🧩", f"组件设计 ({len(comps)})", "rgba(34,211,238,0.12)", "components"))
    if comps:
        layer_for: dict[str, str] = {}
        if isinstance(arch_data, dict):
            for layer in arch_data.get("layers", []):
                for cname in layer.get("components", []):
                    layer_for[cname] = layer.get("name", "")

        grouped_comps: dict[str, list] = {}
        unlayered: list = []
        for c in comps:
            cname = c.get("name", "")
            lname = layer_for.get(cname, "")
            if lname:
                grouped_comps.setdefault(lname, []).append(c)
            else:
                unlayered.append(c)

        type_icons = {
            "frontend": "🖥️", "backend": "⚙️", "gateway": "🔀", "service": "⚙️",
            "database": "🗄️", "infrastructure": "⚡", "integration": "🔌", "security": "🔐",
        }
        layer_order = list(dict.fromkeys(layer_for.values()))
        for lname in layer_order:
            items = grouped_comps.get(lname, [])
            if not items:
                continue
            cards = [_render_component_card(c, type_icons) for c in items]
            parts.append(
                '<details class="contract-group" open>'
                f'<summary>{_esc(lname)} <span class="cg-count">{len(cards)}</span></summary>'
                f'{"".join(cards)}'
                '</details>'
            )
        for c in unlayered:
            parts.append(_render_component_card(c, type_icons))
    parts.append(_SECTION_FOOT)

    # Contracts — enhanced with status/errors/source_requirements/change_history
    if contracts:
        parts.append(_section_header("🔗", f"接口契约 ({len(contracts)})", "rgba(52,211,153,0.12)", "contracts"))
        parts.append(_render_contracts_section_enhanced(contracts))
        parts.append(_SECTION_FOOT)

    # Data Flow
    if d.get("data_flow"):
        parts.append(_section_header("📊", "数据流", "rgba(251,191,36,0.12)", "dataflow"))
        parts.append(_render_dataflow_section(d["data_flow"]))
        parts.append(_SECTION_FOOT)

    # Data Models
    if d.get("data_models"):
        models = d["data_models"]
        parts.append(_section_header("🗄️", f"数据模型 ({len(models)})", "rgba(91,141,239,0.12)", "models"))
        parts.append(_render_sad_data_models(models))
        parts.append(_SECTION_FOOT)

    # Requirement Traceability
    if d.get("requirement_traceability"):
        traces = d["requirement_traceability"]
        parts.append(_section_header("🔍", f"需求追溯 ({len(traces)})", "rgba(124,111,247,0.12)", "traceability"))
        parts.append(_render_traceability_section(traces))
        parts.append(_SECTION_FOOT)

    # Architecture Decisions
    if d.get("architecture_decisions"):
        adrs = d["architecture_decisions"]
        parts.append(_section_header("📋", f"架构决策 ({len(adrs)})", "rgba(251,191,36,0.12)", "decisions"))
        parts.append(_render_adr_list(adrs))
        parts.append(_SECTION_FOOT)

    # Risks
    if d.get("risks"):
        risks = d["risks"]
        parts.append(_section_header("⚠️", f"技术风险 ({len(risks)})", "rgba(248,113,113,0.12)", "risks"))
        parts.append(_render_risks_section(risks))
        parts.append(_SECTION_FOOT)

    # Open Questions
    if d.get("open_questions"):
        questions = d["open_questions"]
        parts.append(_section_header("❓", f"待澄清问题 ({len(questions)})", "rgba(107,115,148,0.12)", "questions"))
        parts.append(_render_open_questions_section(questions))
        parts.append(_SECTION_FOOT)

    parts.append(_PAGE_END_SIDEBAR)
    return "\n".join(parts)


def _render_lld(d: dict) -> str:
    m = d.get("meta", {})
    title = m.get("title", "LLD")
    doc_id = m.get("doc_id", "")
    module = m.get("module", "")
    module_type = m.get("module_type", "")
    models = d.get("data_models", [])
    ifaces = d.get("interfaces", [])
    workflow = d.get("workflow")
    domain_objects = d.get("domain_objects", [])
    service_contracts = d.get("service_contracts", [])
    # Defend against LLM generating this as a dict instead of a list
    if isinstance(service_contracts, dict):
        # Common variants: {"name": ...} (single object) or {"service": {...}} (extra wrapper)
        if "service" in service_contracts and isinstance(service_contracts["service"], dict):
            service_contracts = [service_contracts["service"]]
        else:
            service_contracts = [service_contracts]
    business_rules = d.get("business_rules")
    component_tree = d.get("component_tree", [])
    state_design = d.get("state_design")
    route_design = d.get("route_design", [])
    interaction_flows = d.get("interaction_flows", [])
    api_integration = d.get("api_integration", [])

    # —— Build sidebar sections dynamically ——
    sections = [("overview", "📄", "概述")]

    # Frontend-specific sections (before data_models)
    if module_type == "frontend":
        if component_tree:
            sections.append(("component-tree", "🧩", f"组件树 ({len(component_tree)})"))
        if state_design:
            sections.append(("state-design", "🗃️", "状态设计"))
        if route_design:
            sections.append(("route-design", "🗺️", f"路由 ({len(route_design)})"))
        if interaction_flows:
            sections.append(("interaction-flows", "🔄", f"交互流 ({len(interaction_flows)})"))
        if api_integration:
            sections.append(("api-integration", "🔗", f"API 映射 ({len(api_integration)})"))

    # Gateway-specific sections
    if module_type == "gateway":
        if d.get("route_table"):
            sections.append(("route-table", "🔀", f"路由表 ({len(d['route_table'])})"))
        if d.get("middleware_chain"):
            sections.append(("middleware-chain", "⛓️", "中间件链"))
        if d.get("auth_policy"):
            sections.append(("auth-policy", "🔐", "认证授权"))
        if d.get("rate_limiting"):
            sections.append(("rate-limiting", "🚦", "限流规则"))

    # Infrastructure-specific sections
    if module_type == "infrastructure":
        if d.get("topology"):
            sections.append(("infra-topology", "🌐", "拓扑结构"))
        if d.get("message_contracts"):
            sections.append(("message-contracts", "📨", f"消息契约 ({len(d.get('message_contracts', []))})"))
        if d.get("reliability_strategy"):
            sections.append(("reliability", "🛡️", "可靠性策略"))

    sections.append(("models", "🗄️", f"数据模型 ({len(models)})"))

    # Service sections (after data_models — service only, not gateway)
    if module_type == "service":
        if domain_objects:
            sections.append(("domain-objects", "📦", f"领域对象 ({len(domain_objects)})"))
        if service_contracts:
            sections.append(("service-contracts", "🔧", f"服务接口 ({len(service_contracts)})"))
        if business_rules:
            sections.append(("business-rules", "📐", "业务规则"))

    # Database-specific sections
    if module_type == "database":
        if d.get("index_strategy"):
            sections.append(("index-strategy", "📊", "索引策略"))
        if d.get("migration_strategy"):
            sections.append(("migration", "📜", "迁移策略"))
        if d.get("capacity_estimation"):
            sections.append(("capacity", "📈", "容量估算"))
        if d.get("connection_contracts"):
            sections.append(("connections", "🔗", "连接配置"))

    if workflow:
        sections.append(("workflow", "🔄", "编排流程"))
    if ifaces:
        sections.append(("interfaces", "🔌", f"接口定义 ({len(ifaces)})"))
    if d.get("error_handling"):
        sections.append(("errors", "⚠️", "错误处理"))

    parts = [_page_start_sidebar(
        title, doc_id, "详细设计文档",
        m.get("created", ""), m.get("author", "design_agent"),
        sections,
    )]

    # ── 1. Overview ──
    overview = d.get("overview", "")
    parts.append(_section_header("📄", "概述", "rgba(124,111,247,0.12)", "overview"))

    # Module type badge
    mt_labels = {
        "database": "🗄️ 数据库层", "service": "⚙️ 业务服务", "gateway": "🔀 网关层",
        "frontend": "🖥️ 前端", "infrastructure": "⚡ 基础设施",
    }
    mt_badge = mt_labels.get(module_type, "")
    if module and module_type:
        parts.append(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">'
            f'<div class="arch-style-badge">{_esc(module)}</div>'
            + (f'<span class="badge accent">{_esc(mt_badge)}</span>' if mt_badge else "")
            + '</div>'
        )
    elif module:
        parts.append(
            f'<div class="arch-style-badge" style="margin-bottom:12px">'
            f'模块: {_esc(module)}</div>'
        )

    overview = overview if isinstance(overview, dict) else {}
    desc = overview.get("description", "")
    deps = overview.get("dependencies", [])
    tech = overview.get("tech_stack", [])
    if desc:
        parts.append(f'<div class="arch-desc">{_esc(desc)}</div>')
    if deps:
        tags = "".join(
            f'<span class="cc-consumer" style="margin:2px">{_esc(dep)}</span>'
            for dep in deps
        )
        parts.append(f'<div style="margin-bottom:12px"><span style="font-size:0.82em;color:var(--c-muted)">依赖: </span>{tags}</div>')
    if tech:
        tags = "".join(
            f'<span class="arch-feature-tag" style="margin:2px"><span class="dot" style="background:var(--c-accent)"></span>{_esc(t)}</span>'
            for t in tech
        )
        parts.append(f'<div style="margin-bottom:8px">{tags}</div>')

    # Source info
    src = d.get("source", {})
    if src:
        prd_info = src.get("prd", {})
        sad_info = src.get("sad", {})
        src_parts = []
        if prd_info:
            src_parts.append(f'PRD {_esc(prd_info.get("doc_id","?"))} v{prd_info.get("version","?")}')
        if sad_info:
            src_parts.append(f'SAD {_esc(sad_info.get("doc_id","?"))} v{sad_info.get("version","?")}')
        se_turn = src.get("se_turn_id", "")
        if se_turn:
            src_parts.append(f'SE: {_esc(se_turn)}')
        if src_parts:
            parts.append(f'<div style="font-size:0.82em;color:var(--c-muted);margin-bottom:8px">'
                         f'基于: {" · ".join(src_parts)}</div>')

    # Module boundary
    boundary = d.get("module_boundary", {})
    if boundary:
        in_scope = boundary.get("in_scope", [])
        out_scope = boundary.get("out_of_scope", [])
        owned_comps = boundary.get("owned_components", [])
        owned_ctrs = boundary.get("owned_contracts", [])
        consumed_ctrs = boundary.get("consumed_contracts", [])
        if in_scope or out_scope or owned_comps or owned_ctrs:
            b_parts = []
            if in_scope:
                tags = " ".join(f'<span class="cn-tag prop">{_esc(s)}</span>' for s in in_scope)
                b_parts.append(f'<div style="margin:4px 0"><strong style="font-size:0.8em;color:var(--c-green)">范围内: </strong>{tags}</div>')
            if out_scope:
                tags = " ".join(f'<span class="cn-tag">{_esc(s)}</span>' for s in out_scope)
                b_parts.append(f'<div style="margin:4px 0"><strong style="font-size:0.8em;color:var(--c-red)">范围外: </strong>{tags}</div>')
            if owned_comps:
                tags = " ".join(f'<span style="font-family:monospace;font-size:0.82em;color:var(--c-accent)">{_esc(c)}</span>' for c in owned_comps)
                b_parts.append(f'<div style="margin:4px 0"><strong style="font-size:0.8em;color:var(--c-muted)">拥有组件: </strong>{tags}</div>')
            if owned_ctrs:
                tags = " ".join(f'<span style="font-family:monospace;font-size:0.82em;color:var(--c-accent)">{_esc(c)}</span>' for c in owned_ctrs)
                b_parts.append(f'<div style="margin:4px 0"><strong style="font-size:0.8em;color:var(--c-muted)">实现契约: </strong>{tags}</div>')
            if consumed_ctrs:
                tags = " ".join(f'<span style="font-family:monospace;font-size:0.82em;color:var(--c-accent2)">{_esc(c)}</span>' for c in consumed_ctrs)
                b_parts.append(f'<div style="margin:4px 0"><strong style="font-size:0.8em;color:var(--c-muted)">消费契约: </strong>{tags}</div>')
            parts.append(f'<details class="contract-group" style="margin-bottom:12px"><summary>📐 模块边界</summary>'
                         f'<div style="padding:8px 16px">{"".join(b_parts)}</div></details>')
    parts.append(_SECTION_FOOT)

    # ═══════════════════════════════════════════════════════════
    # Module-type-specific sections BEFORE data models
    # ═══════════════════════════════════════════════════════════

    # ── Frontend: Component Tree ──
    if module_type == "frontend" and component_tree:
        parts.append(_section_header("🧩", f"组件树 ({len(component_tree)})",
                                      "rgba(34,211,238,0.12)", "component-tree"))
        parts.extend(_render_component_nodes(component_tree))
        parts.append(_SECTION_FOOT)

    # ── Frontend: State Design ──
    if module_type == "frontend" and state_design:
        parts.append(_section_header("🗃️", "状态设计", "rgba(251,191,36,0.12)", "state-design"))
        global_states = state_design.get("global", [])
        if global_states:
            parts.append('<div class="body-label" style="margin-bottom:8px">全局状态</div>')
            for gs in global_states:
                consumers_html = " ".join(
                    f'<span class="cn-tag state">{_esc(c)}</span>' for c in gs.get("consumers", [])
                )
                parts.append(
                    f'<div class="state-global-item">'
                    f'<div style="flex:1">'
                    f'<div class="sg-name">{_esc(gs.get("name",""))}</div>'
                    f'<div style="font-size:0.84em;color:var(--c-muted);margin-top:2px">{_esc(gs.get("description",""))}</div>'
                    f'</div>'
                    f'<span class="sg-type">{_esc(gs.get("type",""))}</span>'
                    f'<div style="margin-top:4px">{consumers_html}</div>'
                    f'</div>'
                )
        caching = state_design.get("caching_strategy", "")
        if caching:
            parts.append(
                f'<div class="body-label" style="margin-top:12px">缓存策略</div>'
                f'<p style="font-size:0.88em;color:var(--c-muted)">{_esc(str(caching))}</p>'
            )
        parts.append(_SECTION_FOOT)

    # ── Frontend: Route Design ──
    if module_type == "frontend" and route_design:
        parts.append(_section_header("🗺️", f"路由设计 ({len(route_design)})",
                                      "rgba(52,211,153,0.12)", "route-design"))
        rows_html = ""
        for r in route_design:
            auth = r.get("auth", "")
            auth_tag = f'<span class="role-tag">{_esc(auth)}</span>' if auth else ""
            rows_html += (
                f'<div class="route-row">'
                f'<span class="cc-endpoint" style="min-width:180px">{_esc(r.get("path",""))}</span>'
                f'<span style="font-weight:600;font-size:0.9em;color:var(--c-heading);flex:1">{_esc(r.get("page",""))}</span>'
                f'{auth_tag}'
                f'</div>'
            )
        parts.append(
            f'<div style="background:var(--c-surface);border:1px solid var(--c-border);'
            f'border-radius:var(--radius);padding:4px 0">'
            f'{rows_html}'
            f'</div>'
        )
        parts.append(_SECTION_FOOT)

    # ── Frontend: Interaction Flows ──
    if module_type == "frontend" and interaction_flows:
        parts.append(_section_header("🔄", f"交互流程 ({len(interaction_flows)})",
                                      "rgba(124,111,247,0.12)", "interaction-flows"))
        for flow in interaction_flows:
            ft_steps = ""
            for i, step in enumerate(flow.get("steps", [])):
                ft_steps += (
                    f'<div class="ft-step">'
                    f'<div class="ft-num">{i + 1}</div>'
                    f'<div class="ft-text">{_esc(step)}</div>'
                    f'</div>'
                )
            parts.append(
                f'<div class="flow-timeline">'
                f'<div class="ft-title">{_esc(flow.get("name",""))}</div>'
                + (f'<p style="font-size:0.84em;color:var(--c-muted);margin-bottom:8px">{_esc(flow.get("description",""))}</p>' if flow.get("description") else "")
                + ft_steps
                + '</div>'
            )
        parts.append(_SECTION_FOOT)

    # ── Frontend: API Integration ──
    if module_type == "frontend" and api_integration:
        parts.append(_section_header("🔗", f"API 集成映射 ({len(api_integration)})",
                                      "rgba(34,211,238,0.12)", "api-integration"))
        api_rows = ""
        for a in api_integration:
            api_rows += (
                f'<tr><td><strong>{_esc(a.get("page",""))}</strong></td>'
                f'<td style="font-family:monospace;font-size:0.85em">{_esc(a.get("endpoint",""))}</td>'
                f'<td>{_esc(a.get("maps_to",""))}</td></tr>'
            )
        parts.append(
            f'<table class="body-table"><thead><tr><th>页面</th><th>API / Endpoint</th><th>映射到</th></tr></thead>'
            f'<tbody>{api_rows}</tbody></table>'
        )
        parts.append(_SECTION_FOOT)

    # ── Gateway: Route Table ──
    if module_type == "gateway" and d.get("route_table"):
        parts.append(_section_header("🔀", f"路由表 ({len(d['route_table'])})",
                                      "rgba(124,111,247,0.12)", "route-table"))
        rt_rows = ""
        for rt in d["route_table"]:
            rt_rows += (
                f'<tr><td style="font-family:monospace">{_esc(rt.get("path_pattern",""))}</td>'
                f'<td><strong>{_esc(rt.get("upstream",""))}</strong></td>'
                f'<td style="color:var(--c-muted)">{_esc(rt.get("description",""))}</td></tr>'
            )
        parts.append(
            f'<table style="width:100%;border-collapse:collapse;font-size:0.9em">'
            f'<thead><tr><th>Path Pattern</th><th>Upstream</th><th>说明</th></tr></thead>'
            f'<tbody>{rt_rows}</tbody></table>'
        )
        parts.append(_SECTION_FOOT)

    # ── Gateway: Middleware Chain ──
    if module_type == "gateway" and d.get("middleware_chain"):
        parts.append(_section_header("⛓️", "中间件链", "rgba(91,141,239,0.12)", "middleware-chain"))
        mw_nodes = ""
        chain = d["middleware_chain"]
        if isinstance(chain, list):
            for i, node in enumerate(chain):
                mw_nodes += f'<span class="mw-node special">{_esc(node)}</span>'
                if i < len(chain) - 1:
                    mw_nodes += '<span class="mw-arrow">→</span>'
        parts.append(f'<div class="mw-flow">{mw_nodes}</div>')
        parts.append(_SECTION_FOOT)

    # ── Gateway: Auth Policy ──
    if module_type == "gateway" and d.get("auth_policy"):
        ap = d["auth_policy"]
        parts.append(_section_header("🔐", "认证授权", "rgba(251,191,36,0.12)", "auth-policy"))
        pub_eps = ap.get("public_endpoints", [])
        auth_method = ap.get("auth_method", "")
        token_exp = ap.get("token_expiry", "")
        role_map = ap.get("role_path_map", [])

        info_parts = []
        if pub_eps:
            tags = " ".join(f'<span class="cn-tag">{_esc(e)}</span>' for e in pub_eps)
            info_parts.append(f'<div style="margin-bottom:8px"><strong style="font-size:0.82em;color:var(--c-muted)">公开端点: </strong>{tags}</div>')
        if auth_method:
            info_parts.append(f'<div style="margin-bottom:8px"><strong style="font-size:0.82em;color:var(--c-muted)">认证方式: </strong><span class="role-tag">{_esc(auth_method)}</span></div>')
        if token_exp:
            info_parts.append(f'<div style="margin-bottom:12px"><strong style="font-size:0.82em;color:var(--c-muted)">Token 策略: </strong><span class="cn-tag">{_esc(token_exp)}</span></div>')
        parts.extend(info_parts)

        if role_map:
            rows = ""
            for r in role_map:
                roles_html = " ".join(f'<span class="role-tag">{_esc(role)}</span>' for role in r.get("roles", []))
                rows += f'<tr><td style="font-family:monospace;font-size:0.85em">{_esc(r.get("path",""))}</td><td>{roles_html}</td></tr>'
            parts.append(
                f'<table class="auth-matrix"><thead><tr><th>路径</th><th>允许角色</th></tr></thead><tbody>{rows}</tbody></table>'
            )
        parts.append(_SECTION_FOOT)

    # ── Gateway: Rate Limiting ──
    if module_type == "gateway" and d.get("rate_limiting"):
        rl = d["rate_limiting"]
        parts.append(_section_header("🚦", "限流规则", "rgba(248,113,113,0.12)", "rate-limiting"))
        global_l = rl.get("global", "")
        per_user = rl.get("per_user", "")
        special = rl.get("special_endpoints", [])

        if global_l:
            parts.append(f'<div style="margin-bottom:8px"><span class="cn-tag">全局</span> {_esc(global_l)}</div>')
        if per_user:
            parts.append(f'<div style="margin-bottom:8px"><span class="cn-tag">每用户</span> {_esc(per_user)}</div>')
        if special:
            sp_rows = ""
            for s in special:
                sp_rows += f'<tr><td style="font-family:monospace">{_esc(s.get("endpoint",""))}</td><td>{_esc(s.get("limit",""))}</td></tr>'
            parts.append(
                f'<table class="body-table"><thead><tr><th>端点</th><th>限制</th></tr></thead><tbody>{sp_rows}</tbody></table>'
            )
        parts.append(_SECTION_FOOT)

    # ── Infrastructure: Topology ──
    if module_type == "infrastructure" and d.get("topology"):
        parts.append(_section_header("🌐", "拓扑结构", "rgba(124,111,247,0.12)", "infra-topology"))
        topo = d["topology"]
        exchanges = topo.get("exchanges", [])
        queues = topo.get("queues", [])
        pc_map = topo.get("producer_consumer_map", [])
        namespaces = topo.get("namespaces", [])
        buckets = topo.get("buckets", [])

        if exchanges:
            parts.append('<div class="body-label">Exchanges</div>')
            ex_rows = ""
            for ex in exchanges:
                bindings = ex.get("bindings", [])
                bind_str = ", ".join(f'{b.get("queue","")} (rk: {b.get("routing_key","")})' for b in bindings)
                ex_rows += (
                    f'<tr><td style="font-family:monospace">{_esc(ex.get("name",""))}</td>'
                    f'<td>{_esc(ex.get("type",""))}</td>'
                    f'<td>{"✓" if ex.get("durable") else ""}</td>'
                    f'<td style="font-size:0.85em">{_esc(bind_str)}</td></tr>'
                )
            parts.append(
                f'<table class="body-table"><thead><tr><th>名称</th><th>类型</th><th>持久</th><th>绑定</th></tr></thead><tbody>{ex_rows}</tbody></table>'
            )

        if queues:
            parts.append('<div class="body-label" style="margin-top:12px">Queues</div>')
            q_rows = ""
            for q in queues:
                q_rows += (
                    f'<tr><td style="font-family:monospace">{_esc(q.get("name",""))}</td>'
                    f'<td>{"✓" if q.get("durable") else ""}</td>'
                    f'<td>{_esc(str(q.get("ttl_seconds","")))}s</td>'
                    f'<td>{_esc(str(q.get("max_length","")))}</td></tr>'
                )
            parts.append(
                f'<table class="body-table"><thead><tr><th>名称</th><th>持久</th><th>TTL</th><th>最大长度</th></tr></thead><tbody>{q_rows}</tbody></table>'
            )

        if pc_map:
            parts.append('<div class="body-label" style="margin-top:12px">生产者/消费者</div>')
            pc_rows = ""
            for p in pc_map:
                pc_rows += (
                    f'<tr><td><strong>{_esc(p.get("producer",""))}</strong></td>'
                    f'<td>→</td>'
                    f'<td><strong>{_esc(p.get("consumer",""))}</strong></td>'
                    f'<td style="font-family:monospace;font-size:0.85em">{_esc(p.get("exchange",""))}</td></tr>'
                )
            parts.append(
                f'<table class="body-table"><thead><tr><th>生产者</th><th></th><th>消费者</th><th>Exchange</th></tr></thead><tbody>{pc_rows}</tbody></table>'
            )

        if namespaces:
            parts.append(
                f'<div class="body-label">Namespaces</div>'
                f'<p style="font-size:0.9em">{_esc(", ".join(str(n) for n in namespaces))}</p>'
            )
        if buckets:
            parts.append(
                f'<div class="body-label">Buckets</div>'
                f'<p style="font-size:0.9em">{_esc(", ".join(str(b) for b in buckets))}</p>'
            )

        # Cache-specific sub-fields
        key_patterns = topo.get("key_patterns", [])
        expiry = topo.get("expiry_strategy", "")
        if key_patterns:
            kp_rows = ""
            for kp in key_patterns:
                kp_rows += (
                    f'<tr><td style="font-family:monospace">{_esc(kp.get("pattern",""))}</td>'
                    f'<td>{_esc(kp.get("description",""))}</td></tr>'
                )
            parts.append(
                f'<div class="body-label" style="margin-top:12px">Key Patterns</div>'
                f'<table class="body-table"><thead><tr><th>Pattern</th><th>说明</th></tr></thead><tbody>{kp_rows}</tbody></table>'
            )
        if expiry:
            parts.append(
                f'<div style="margin-top:8px;font-size:0.88em;color:var(--c-muted)">'
                f'<strong>过期策略:</strong> {_esc(str(expiry))}'
                f'</div>'
            )

        # File-storage-specific sub-fields
        path_conventions = topo.get("path_conventions", "")
        if path_conventions:
            parts.append(
                f'<div style="margin-top:8px;font-size:0.88em;color:var(--c-muted)">'
                f'<strong>路径规范:</strong> {_esc(str(path_conventions))}'
                f'</div>'
            )

        parts.append(_SECTION_FOOT)

    # ── Infrastructure: Message Contracts ──
    if module_type == "infrastructure" and d.get("message_contracts"):
        parts.append(_section_header("📨", f"消息契约 ({len(d['message_contracts'])})",
                                      "rgba(91,141,239,0.12)", "message-contracts"))
        for mc in d["message_contracts"]:
            schema_rows = ""
            for k, v in mc.get("schema", {}).items():
                schema_rows += f'<tr><td>{_esc(k)}</td><td class="field-type">{_esc(v)}</td></tr>'
            required = ", ".join(mc.get("required_fields", []))
            parts.append(
                f'<div class="contract-card">'
                f'<div class="cc-head">'
                f'<span class="cc-endpoint">{_esc(mc.get("exchange",""))}</span>'
                f'<span class="method-badge mq">MQ</span>'
                f'<span class="cc-name">{_esc(mc.get("name",""))}</span>'
                f'</div>'
                f'<div style="font-size:0.82em;color:var(--c-muted);margin-bottom:8px">'
                f'Routing Key: {_esc(mc.get("routing_key",""))}'
                + (f' · Max: {mc.get("max_size_bytes", "")} bytes' if mc.get("max_size_bytes") else "")
                + f'</div>'
                f'<div class="body-label">Schema</div>'
                f'<table class="body-table"><thead><tr><th>字段</th><th>类型</th></tr></thead><tbody>{schema_rows}</tbody></table>'
                + (f'<div style="font-size:0.82em;color:var(--c-muted);margin-top:6px"><strong>必填:</strong> {_esc(required)}</div>' if required else "")
                + '</div>'
            )
        parts.append(_SECTION_FOOT)

    # ── Infrastructure: Reliability Strategy ──
    if module_type == "infrastructure" and d.get("reliability_strategy"):
        rs = d["reliability_strategy"]
        parts.append(_section_header("🛡️", "可靠性策略", "rgba(251,191,36,0.12)", "reliability"))
        ack = rs.get("ack_mode", "")
        dlq = rs.get("dead_letter", "")
        idem = rs.get("idempotency", "")
        retry = rs.get("retry", {})

        items = []
        if ack:
            items.append(f'<span class="cn-tag">Ack: {_esc(ack)}</span>')
        if dlq:
            items.append(f'<span class="cn-tag">DLQ: {_esc(dlq)}</span>')
        if idem:
            items.append(f'<span class="cn-tag">幂等: {_esc(idem)}</span>')
        if retry:
            items.append(
                f'<span class="cn-tag">重试: max {retry.get("max_retries","?")}x, '
                f'backoff {retry.get("backoff","?")}</span>'
            )
        parts.append(f'<div style="display:flex;flex-wrap:wrap;gap:8px">{" ".join(items)}</div>')
        parts.append(_SECTION_FOOT)

    # ── 2. Data Models ──
    parts.append(_section_header("🗄️", f"数据模型 ({len(models)})", "rgba(91,141,239,0.12)", "models"))
    if models:
        from collections import OrderedDict
        type_labels = {
            "table": "数据库表", "reference": "引用模型", "interface": "数据接口",
            "struct": "数据结构", "store": "状态存储", "config": "配置定义",
        }
        type_icons = {
            "table": "🗄️", "reference": "🔗", "interface": "📋",
            "struct": "📦", "store": "🗃️", "config": "⚙️",
        }
        ownership_labels = {
            "canonical": ("权威定义", "rgba(52,211,153,0.15)", "var(--c-green)"),
            "derived": ("引用", "rgba(91,141,239,0.12)", "var(--c-accent)"),
            "owned": ("自有", "rgba(107,115,148,0.12)", "var(--c-muted)"),
        }
        grouped: dict[str, list] = OrderedDict()
        for dm in models:
            t = dm.get("type", "other")
            grouped.setdefault(t, []).append(dm)

        for t, items in grouped.items():
            label = type_labels.get(t, t)
            icon = type_icons.get(t, "📄")
            cards = []
            for dm in items:
                ownership = dm.get("ownership", "")
                own_label, own_bg, own_color = ownership_labels.get(ownership, ("", "", ""))
                own_badge = (
                    f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                    f'font-size:0.72em;font-weight:600;background:{own_bg};color:{own_color};'
                    f'margin-left:6px">{_esc(own_label)}</span>'
                ) if own_label else ""

                # Source reference for derived models
                source_html = ""
                source = dm.get("source")
                if source and isinstance(source, dict):
                    src_doc = source.get("doc_id", "")
                    src_model = source.get("model_name", "")
                    if src_doc or src_model:
                        source_html = (
                            f'<div style="font-size:0.78em;color:var(--c-muted);margin-bottom:6px">'
                            f'↳ 引用自: {_esc(src_doc)} / {_esc(src_model)}'
                            f'</div>'
                        )

                # Fields table
                rows = ""
                for f in dm.get("fields", []):
                    required = f.get("required", False)
                    req_mark = ' <span style="color:var(--c-red);font-size:0.75em">*</span>' if required else ""
                    rows += (
                        f"<tr>"
                        f"<td>{_esc(f.get('name',''))}{req_mark}</td>"
                        f"<td class=\"field-type\">{_esc(f.get('type',''))}</td>"
                        f"<td>{_esc(f.get('description',''))}</td>"
                        f"</tr>"
                    )

                # Indexes table (for canonical tables)
                indexes = dm.get("indexes", [])
                idx_html = ""
                if indexes:
                    idx_rows = ""
                    for idx in indexes:
                        unique = "✓" if idx.get("unique") else ""
                        cols = ", ".join(idx.get("columns", []))
                        idx_rows += (
                            f"<tr><td>{_esc(idx.get('name',''))}</td>"
                            f"<td>{unique}</td>"
                            f"<td style=\"font-family:monospace;font-size:0.85em\">{_esc(cols)}</td></tr>"
                        )
                    idx_html = (
                        '<div class="body-label" style="margin-top:8px">索引</div>'
                        '<table class="body-table"><thead><tr><th>索引名</th><th>唯一</th><th>列</th></tr></thead>'
                        f'<tbody>{idx_rows}</tbody></table>'
                    )

                desc_html = f'<p style="font-size:0.85em;color:var(--c-muted);margin-bottom:8px">{_esc(dm.get("description",""))}</p>' if dm.get("description") else ""
                cards.append(
                    f'<div class="contract-card" style="border-top:none">'
                    f'<h3 style="font-size:0.95em;font-weight:600;color:var(--c-heading);margin-bottom:4px">'
                    f'{icon} {_esc(dm.get("name",""))}{own_badge}</h3>'
                    f'{source_html}'
                    f'{desc_html}'
                    f'<div class="body-label">字段</div>'
                    f'<table class="body-table"><thead><tr><th>字段名</th><th>类型</th><th>描述</th></tr></thead><tbody>{rows}</tbody></table>'
                    f'{idx_html}'
                    f'</div>'
                )
            parts.append(
                '<details class="contract-group" open>'
                f'<summary>{_esc(label)} <span class="cg-count">{len(cards)}</span></summary>'
                f'{"".join(cards)}'
                '</details>'
            )
    parts.append(_SECTION_FOOT)

    # ═══════════════════════════════════════════════════════════
    # Module-type-specific sections AFTER data models
    # ═══════════════════════════════════════════════════════════

    # ── Service / Gateway: Domain Objects ──
    if module_type == "service" and domain_objects:
        parts.append(_section_header("📦", f"领域对象 ({len(domain_objects)})",
                                      "rgba(91,141,239,0.12)", "domain-objects"))
        obj_type_icons = {"entity": "🏷️", "value_object": "📌", "dto": "📋", "enum": "🔢"}
        obj_type_labels = {"entity": "实体", "value_object": "值对象", "dto": "DTO", "enum": "枚举"}
        source_labels = {"db": "DB 透传", "computed": "计算", "input": "输入", "derived": "派生"}

        for dobj in domain_objects:
            ot = dobj.get("object_type", "entity")
            oicon = obj_type_icons.get(ot, "📄")
            olabel = obj_type_labels.get(ot, ot)
            tag_cls = ot if ot in ("entity", "dto", "value_object", "enum") else ""

            # Enum: show values as tags
            if ot == "enum":
                vals = dobj.get("values", [])
                val_tags = " ".join(
                    f'<span class="cn-tag prop">{_esc(v)}</span>' for v in vals
                )
                parts.append(
                    f'<div class="domain-obj">'
                    f'<h3>{oicon} {_esc(dobj.get("name",""))}'
                    f'<span class="obj-tag {tag_cls}">{_esc(olabel)}</span></h3>'
                    f'<p style="font-size:0.85em;color:var(--c-muted);margin-bottom:8px">{_esc(dobj.get("description",""))}</p>'
                    f'<div class="body-label">值</div><div>{val_tags}</div>'
                    f'</div>'
                )
            else:
                # Entity / Value Object / DTO
                attrs = dobj.get("attributes", [])
                attr_rows = ""
                for a in attrs:
                    required = a.get("required", False)
                    req_mark = ' <span style="color:var(--c-red);font-size:0.75em">*</span>' if required else ""
                    src = a.get("source", "")
                    src_tag = f' <span class="attr-source-tag">{_esc(source_labels.get(src, src))}</span>' if src else ""
                    attr_rows += (
                        f"<tr>"
                        f"<td>{_esc(a.get('name',''))}{req_mark}{src_tag}</td>"
                        f"<td class=\"field-type\">{_esc(a.get('type',''))}</td>"
                        f"<td>{_esc(a.get('description',''))}</td>"
                        f"</tr>"
                    )

                maps_to = dobj.get("maps_to_entity", "")
                maps_html = f'<div style="font-size:0.78em;color:var(--c-muted);margin-bottom:6px">↦ {_esc(maps_to)}</div>' if maps_to else ""

                parts.append(
                    f'<div class="domain-obj">'
                    f'<h3>{oicon} {_esc(dobj.get("name",""))}'
                    f'<span class="obj-tag {tag_cls}">{_esc(olabel)}</span></h3>'
                    f'{maps_html}'
                    f'<p style="font-size:0.85em;color:var(--c-muted);margin-bottom:8px">{_esc(dobj.get("description",""))}</p>'
                    + (f'<div class="body-label">属性</div>'
                       f'<table class="body-table"><thead><tr><th>属性名</th><th>类型</th><th>描述</th></tr></thead><tbody>{attr_rows}</tbody></table>' if attrs else "")
                    + '</div>'
                )
        parts.append(_SECTION_FOOT)

    # ── Service: Service Contracts ──
    if module_type == "service" and service_contracts:
        parts.append(_section_header("🔧", f"服务接口 ({len(service_contracts)})",
                                      "rgba(124,111,247,0.12)", "service-contracts"))
        for svc in service_contracts:
            methods = svc.get("methods", [])
            method_cards = ""
            for meth in methods:
                excs = meth.get("exceptions", [])
                exc_tags = ""
                for e in excs:
                    exc_tags += (
                        f'<span class="exc-item">'
                        f'<span class="exc-name">{_esc(e.get("name",""))}</span>'
                        f'<span class="exc-http">→ {_esc(str(e.get("http_status","")))}</span>'
                        f'<span style="font-size:0.82em;color:var(--c-muted)">{_esc(e.get("trigger",""))}</span>'
                        f'</span>'
                    )

                pre = meth.get("precondition", "")
                post = meth.get("postcondition", "")
                pre_post_html = ""
                if pre or post:
                    pre_post_html = '<div class="pre-post">'
                    if pre:
                        pre_post_html += f'<div class="pre-post-item pre"><div class="pp-label">前置条件</div><div class="pp-text">{_esc(pre)}</div></div>'
                    if post:
                        pre_post_html += f'<div class="pre-post-item post"><div class="pp-label">后置条件</div><div class="pp-text">{_esc(post)}</div></div>'
                    pre_post_html += '</div>'

                method_cards += (
                    f'<div class="svc-method">'
                    f'<div class="svc-method-header">'
                    f'<span class="method-name">{_esc(meth.get("name",""))}</span>'
                    f'</div>'
                    + (f'<div class="sig-block">{_esc(meth.get("signature",""))}</div>' if meth.get("signature") else "")
                    + (f'<div class="cc-desc">{_esc(meth.get("description",""))}</div>' if meth.get("description") else "")
                    + pre_post_html
                    + (f'<div style="margin-top:6px">{exc_tags}</div>' if exc_tags else "")
                    + '</div>'
                )

            # Repository dependencies
            repo_deps = svc.get("repository_dependencies", [])
            repo_html = ""
            if repo_deps:
                repo_items = "".join(f'<div class="repo-dep">{_esc(d)}</div>' for d in repo_deps)
                repo_html = (
                    f'<div style="padding:16px 20px;border-top:1px solid var(--c-border)">'
                    f'<div class="body-label">数据访问依赖</div>'
                    f'{repo_items}'
                    f'</div>'
                )

            parts.append(
                '<details class="svc-contract" open>'
                f'<summary>🔧 {_esc(svc.get("name",""))} '
                f'<span class="cg-count">{len(methods)} 方法</span></summary>'
                f'{method_cards}'
                f'{repo_html}'
                '</details>'
            )
        parts.append(_SECTION_FOOT)

    # ── Service: Business Rules ──
    if module_type == "service" and business_rules:
        parts.append(_section_header("📐", "业务规则", "rgba(251,191,36,0.12)", "business-rules"))

        # Invariants
        invariants = business_rules.get("invariants", [])
        if invariants:
            inv_items = ""
            for inv in invariants:
                inv_items += f'<li><span class="inv-icon">!</span><span>{_esc(inv)}</span></li>'
            parts.append(
                f'<div class="body-label">不变量</div>'
                f'<ul class="invariant-list">{inv_items}</ul>'
            )

        # State Machines
        machines = business_rules.get("state_machines", [])
        if machines:
            parts.append('<div class="body-label" style="margin-top:16px">状态机</div>')
            for sm in machines:
                states = sm.get("states", [])
                transitions = sm.get("transitions", [])
                state_nodes = ""
                for s in states:
                    cls = ""
                    if s in ("completed", "failed", "deleted"):
                        cls = "terminal" if s == "completed" else "error"
                    elif s == "running":
                        cls = "active"
                    state_nodes += f'<span class="state-node {cls}">{_esc(s)}</span>'

                trans_html = ""
                for t in transitions:
                    trans_html += (
                        f'<div class="state-arrow">'
                        f'<span>→</span>'
                        f'<span class="trigger-text">{_esc(t.get("trigger",""))}</span>'
                        f'<span style="font-size:0.78em;color:var(--c-muted)">by {_esc(t.get("actor",""))}</span>'
                        f'</div>'
                    )

                irreversible = sm.get("irreversible_rules", [])
                irrev_tags = ""
                for ir in irreversible:
                    irrev_tags += f'<span class="irrev-rule">🚫 {_esc(ir)}</span>'

                concurrency = sm.get("concurrency", "")

                parts.append(
                    f'<div class="state-diagram">'
                    f'<div class="sd-title">🎯 {_esc(sm.get("entity",""))}</div>'
                    f'<div class="state-row">{state_nodes}</div>'
                    f'<div style="margin:8px 0">{trans_html}</div>'
                    + (f'<div style="margin-top:8px">{irrev_tags}</div>' if irrev_tags else "")
                    + (f'<div style="margin-top:8px;font-size:0.84em;color:var(--c-muted)">⚡ {_esc(concurrency)}</div>' if concurrency else "")
                    + '</div>'
                )

        # Cross-service rules
        cross_rules = business_rules.get("cross_service_rules", [])
        if cross_rules:
            cross_items = ""
            for cr in cross_rules:
                cross_items += f'<div class="cross-svc-rule">{_esc(cr)}</div>'
            parts.append(
                f'<div class="body-label" style="margin-top:16px">跨服务规则</div>'
                f'{cross_items}'
            )

        parts.append(_SECTION_FOOT)

    # ── Database: Index Strategy ──
    if module_type == "database" and d.get("index_strategy"):
        parts.append(_section_header("📊", "索引策略", "rgba(52,211,153,0.12)", "index-strategy"))
        for table in d["index_strategy"]:
            idx_rows = ""
            for idx in table.get("indexes", []):
                cols = ", ".join(idx.get("columns", []))
                idx_rows += (
                    f'<tr><td><strong>{_esc(idx.get("name",""))}</strong></td>'
                    f'<td style="font-family:monospace;font-size:0.85em">{_esc(cols)}</td>'
                    f'<td>{"✓" if idx.get("unique") else ""}</td>'
                    f'<td>{_esc(idx.get("type","B-tree"))}</td>'
                    f'<td style="color:var(--c-muted);font-size:0.85em">{_esc(idx.get("purpose",""))}</td></tr>'
                )
            parts.append(
                f'<div class="body-label">{_esc(table.get("table",""))}</div>'
                f'<table class="body-table"><thead><tr><th>索引名</th><th>列</th><th>唯一</th><th>类型</th><th>用途</th></tr></thead><tbody>{idx_rows}</tbody></table>'
            )
        parts.append(_SECTION_FOOT)

    # ── Database: Migration Strategy ──
    if module_type == "database" and d.get("migration_strategy"):
        ms = d["migration_strategy"]
        parts.append(_section_header("📜", "迁移策略", "rgba(124,111,247,0.12)", "migration"))
        parts.append(
            f'<div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:12px">'
            f'<span class="cn-tag">工具: {_esc(str(ms.get("tool","")))}</span>'
            f'<span class="cn-tag">命名: {_esc(str(ms.get("naming","")))}</span>'
            f'</div>'
            f'<p style="font-size:0.88em;color:var(--c-muted)"><strong>回滚策略:</strong> {_esc(str(ms.get("rollback","")))}</p>'
        )
        parts.append(_SECTION_FOOT)

    # ── Database: Capacity Estimation ──
    if module_type == "database" and d.get("capacity_estimation"):
        ce = d["capacity_estimation"]
        parts.append(_section_header("📈", "容量估算", "rgba(34,211,238,0.12)", "capacity"))
        hot = ce.get("hot_tables", [])
        hot_tags = " ".join(f'<span class="cn-tag prop">{_esc(t)}</span>' for t in hot)
        parts.append(
            f'<div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:8px">'
            f'<span class="cn-tag">1年: {_esc(str(ce.get("estimated_rows_1y","")))}</span>'
            f'<span class="cn-tag">3年: {_esc(str(ce.get("estimated_rows_3y","")))}</span>'
            f'</div>'
            + (f'<div style="margin-bottom:8px"><strong style="font-size:0.82em;color:var(--c-muted)">热表: </strong>{hot_tags}</div>' if hot else "")
            + (f'<p style="font-size:0.88em;color:var(--c-muted)"><strong>分区策略:</strong> {_esc(str(ce.get("partition_strategy","")))}</p>' if ce.get("partition_strategy") else "")
        )
        parts.append(_SECTION_FOOT)

    # ── Database / Infra: Connection Contracts ──
    if module_type in ("database", "infrastructure") and d.get("connection_contracts"):
        cc = d["connection_contracts"]
        parts.append(_section_header("🔗", "连接配置", "rgba(124,111,247,0.12)", "connections"))
        parts.append(
            f'<div style="margin-bottom:8px">'
            f'<span class="cn-tag">连接池: {_esc(str(cc.get("pool_size","")))}</span>'
            f'<span class="cn-tag" style="margin-left:8px">超时: {_esc(str(cc.get("timeout","")))}</span>'
            f'</div>'
        )
        accounts = cc.get("service_accounts", [])
        if accounts:
            acc_rows = ""
            for a in accounts:
                privs = " ".join(f'<span class="role-tag">{_esc(p)}</span>' for p in a.get("privileges", []))
                acc_rows += (
                    f'<tr><td><strong>{_esc(a.get("service",""))}</strong></td>'
                    f'<td style="font-family:monospace">{_esc(a.get("db_user",""))}</td>'
                    f'<td>{privs}</td></tr>'
                )
            parts.append(
                f'<table class="auth-matrix"><thead><tr><th>服务</th><th>账号</th><th>权限</th></tr></thead><tbody>{acc_rows}</tbody></table>'
            )
        parts.append(_SECTION_FOOT)

    # ── 3. Workflow (if present) ──
    if workflow:
        parts.append(_section_header("🔄", "编排流程", "rgba(251,191,36,0.12)", "workflow"))
        wf_name = workflow.get("name", "")
        wf_desc = workflow.get("description", "")
        if wf_name:
            parts.append(f'<h3 style="font-size:1.05em;font-weight:700;color:var(--c-heading);margin-bottom:4px">{_esc(wf_name)}</h3>')
        if wf_desc:
            parts.append(f'<p style="font-size:0.9em;color:var(--c-muted);margin-bottom:16px">{_esc(wf_desc)}</p>')

        steps = workflow.get("steps", [])
        if steps:
            # Render steps as a visual flow
            step_htmls = []
            for i, step in enumerate(steps):
                order = step.get("order", i + 1)
                name = step.get("name", f"Step {order}")
                action = step.get("action", "")
                timeout = step.get("timeout_seconds")
                on_failure = step.get("on_failure", "")

                timeout_str = f' <span style="font-size:0.78em;color:var(--c-amber)">({timeout}s 超时)</span>' if timeout else ""

                step_htmls.append(
                    f'<div style="display:flex;align-items:flex-start;gap:12px;padding:12px 0;'
                    f'border-bottom:1px solid var(--c-border)">'
                    f'<div style="width:32px;height:32px;border-radius:50%;'
                    f'background:rgba(251,191,36,0.15);color:var(--c-amber);'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'font-weight:700;font-size:0.85em;flex-shrink:0">{order}</div>'
                    f'<div style="flex:1">'
                    f'<div style="font-weight:600;color:var(--c-heading);margin-bottom:4px">'
                    f'{_esc(name)}{timeout_str}</div>'
                    f'<div style="font-size:0.88em;color:var(--c-text);margin-bottom:4px">{_esc(action)}</div>'
                    + (f'<div style="font-size:0.82em;color:var(--c-red)">失败处理: {_esc(on_failure)}</div>' if on_failure else "")
                    + '</div></div>'
                )

            parts.append(
                f'<div style="background:var(--c-surface);border:1px solid var(--c-border);'
                f'border-radius:var(--radius);padding:8px 16px">{"".join(step_htmls)}</div>'
            )

        # Retry strategy
        retry = workflow.get("retry_strategy")
        if retry:
            parts.append(
                f'<div style="margin-top:16px;font-size:0.88em;color:var(--c-muted)">'
                f'<strong>重试策略:</strong> 最多 {retry.get("max_retries", "?")} 次，'
                f'间隔 {retry.get("retry_interval_seconds", "?")}s<br>'
                f'可重试错误: {", ".join(retry.get("retryable_errors", [])) or "无"}<br>'
                f'不可重试错误: {", ".join(retry.get("non_retryable_errors", [])) or "无"}'
                f'</div>'
            )

        parts.append(_SECTION_FOOT)

    # ── 4. Interfaces ──
    if ifaces:
        parts.append(_section_header("🔌", f"接口定义 ({len(ifaces)})", "rgba(34,211,238,0.12)", "interfaces"))
        for iface in ifaces:
            endpoint = iface.get("endpoint", "")
            method = iface.get("method", "")

            method_cls = method.lower() if method else ""

            # Parameters table
            params_rows = ""
            for p in iface.get("parameters", []):
                params_rows += (
                    f"<tr><td>{_esc(p.get('name',''))}</td>"
                    f"<td class=\"field-type\">{_esc(p.get('type',''))}</td>"
                    f"<td>{_esc(p.get('description',''))}</td></tr>"
                )

            # Response body table
            resp = iface.get("response", {})
            resp_html = ""
            if isinstance(resp, dict):
                status = resp.get("status", "")
                body = resp.get("body", {})
                if isinstance(body, dict) and body:
                    rows = ""
                    for k, v in body.items():
                        rows += (
                            f"<tr><td>{_esc(k)}</td>"
                            f"<td class=\"field-type\">{_esc(v)}</td></tr>"
                        )
                    resp_html = (
                        f'<div class="body-label">Response {_esc(str(status)) if status else ""}</div>'
                        f'<table class="body-table"><thead><tr><th>字段</th><th>类型</th></tr></thead><tbody>{rows}</tbody></table>'
                    )

            # Error codes table
            err_codes = iface.get("error_codes", [])
            err_html = ""
            if err_codes:
                rows = ""
                for e in err_codes:
                    rows += (
                        f"<tr><td>{_esc(str(e.get('code','')))}</td>"
                        f"<td>{_esc(e.get('message',''))}</td></tr>"
                    )
                err_html = (
                    '<div class="body-label">错误码</div>'
                    '<table class="body-table"><thead><tr><th>状态码</th><th>说明</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )

            parts.append(
                '<div class="contract-card">'
                '<div class="cc-head">'
                + (f'<span class="method-badge {method_cls}">{_esc(method)}</span>' if method else "")
                + (f'<span class="cc-endpoint">{_esc(endpoint)}</span>' if endpoint else "")
                + f'<span class="cc-name">{_esc(iface.get("name",""))}</span>'
                '</div>'
                f'<div class="cc-desc">{_esc(iface.get("description",""))}</div>'
                + (f'<table class="body-table"><thead><tr><th>参数</th><th>类型</th><th>描述</th></tr></thead><tbody>{params_rows}</tbody></table>' if params_rows else "")
                + resp_html
                + err_html
                + '</div>'
            )
        parts.append(_SECTION_FOOT)

    # ── 5. Error Handling ──
    eh = d.get("error_handling")
    if eh:
        parts.append(_section_header("⚠️", "错误处理", "rgba(251,191,36,0.12)", "errors"))
        if isinstance(eh, dict):
            # Strategy
            if eh.get("strategy"):
                parts.append(
                    '<div class="err-strategy">'
                    '<div class="err-label">处理策略</div>'
                    f'<p>{_esc(eh["strategy"])}</p>'
                    '</div>'
                )
            # Unified response format
            rf = eh.get("response_format")
            if rf and isinstance(rf, dict) and rf.get("body"):
                body_rows = ""
                for k, v in rf["body"].items():
                    body_rows += f"<tr><td class=\"field-type\">{_esc(k)}</td><td class=\"field-type\">{_esc(v)}</td></tr>"
                parts.append(
                    '<div class="err-format-box">'
                    '<div class="err-label">统一错误响应体</div>'
                    f'<table class="body-table"><thead><tr><th>字段</th><th>类型</th></tr></thead><tbody>{body_rows}</tbody></table>'
                    '</div>'
                )
            # Error categories
            cats = eh.get("categories", [])
            if cats:
                cat_html = '<div class="err-categories">'
                for c in cats:
                    code = str(c.get("code", ""))
                    if code.startswith("4"):
                        cls = "_4xx"
                    elif code.startswith("5"):
                        cls = "_5xx"
                    else:
                        cls = "_other"
                    cat_html += (
                        '<div class="err-category">'
                        f'<span class="err-code-badge {cls}">{_esc(code)}</span>'
                        '<div class="err-category-body">'
                        f'<div class="err-cat-name">{_esc(c.get("name", ""))}</div>'
                        f'<div class="err-cat-desc">{_esc(c.get("description", ""))}</div>'
                        '</div>'
                        '</div>'
                    )
                cat_html += '</div>'
                parts.append(cat_html)
        parts.append(_SECTION_FOOT)

    # ── Traceability ──
    traces = d.get("traceability", [])
    if traces:
        parts.append(_section_header("🔍", f"需求追溯 ({len(traces)})", "rgba(124,111,247,0.12)", "traceability"))
        parts.append(_render_traceability_section(traces))
        parts.append(_SECTION_FOOT)

    parts.append(_PAGE_END_SIDEBAR)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Component tree renderer (recursive)
# ---------------------------------------------------------------------------

def _render_component_nodes(nodes: list, depth: int = 0) -> list:
    """Recursively render component tree nodes as HTML."""
    parts = []
    for node in nodes:
        child_cls = " child" if depth > 0 else ""

        # Props
        props = node.get("props", [])
        prop_tags = ""
        for p in props:
            req = " *" if p.get("required") else ""
            prop_tags += f'<span class="cn-tag prop">{_esc(p.get("name",""))}: {_esc(p.get("type",""))}{req}</span>'

        # Events
        events = node.get("events", [])
        event_tags = ""
        for e in events:
            event_tags += f'<span class="cn-tag event">@{_esc(e.get("name",""))}({_esc(e.get("payload_type",""))})</span>'

        # State
        state_fields = node.get("state", [])
        state_tags = ""
        for s in state_fields:
            state_tags += f'<span class="cn-tag state">{_esc(s.get("name",""))}: {_esc(s.get("type",""))}</span>'

        # Behavior
        behaviors = node.get("behavior", [])
        behavior_html = ""
        if behaviors:
            items = "".join(f"<li>{_esc(b)}</li>" for b in behaviors)
            behavior_html = (
                f'<div class="cn-section">'
                f'<div class="cn-label">行为</div>'
                f'<ul class="cn-behavior" style="list-style:disc;padding-left:20px">{items}</ul>'
                f'</div>'
            )

        # Edge cases
        edge_cases = node.get("edge_cases", [])
        edge_html = ""
        if edge_cases:
            items = "".join(
                f'<li><span class="edge-icon">⚠️</span> {_esc(ec)}</li>'
                for ec in edge_cases
            )
            edge_html = (
                f'<div class="cn-section">'
                f'<div class="cn-label">边界情况</div>'
                f'<ul class="cn-edge" style="list-style:none;padding-left:0">{items}</ul>'
                f'</div>'
            )

        parts.append(
            f'<div class="comp-node{child_cls}">'
            f'<div class="cn-header">'
            f'<span class="cn-name">{_esc(node.get("name",""))}</span>'
            + (f'<span class="cn-path">{_esc(node.get("path",""))}</span>' if node.get("path") else "")
            + f'</div>'
            f'<p style="font-size:0.84em;color:var(--c-muted);margin-bottom:8px">{_esc(node.get("description",""))}</p>'
            + (f'<div class="cn-section"><div class="cn-label">Props</div><div>{prop_tags}</div></div>' if prop_tags else "")
            + (f'<div class="cn-section"><div class="cn-label">Events</div><div>{event_tags}</div></div>' if event_tags else "")
            + (f'<div class="cn-section"><div class="cn-label">State</div><div>{state_tags}</div></div>' if state_tags else "")
            + behavior_html
            + edge_html
            + '</div>'
        )

        children = node.get("children", [])
        if children:
            parts.extend(_render_component_nodes(children, depth + 1))
    return parts


def _render_report(d: dict) -> str:
    m = d.get("meta", {})
    parts = [_page_start(
        m.get("title", "Report"), m.get("doc_id", ""), "报告",
        m.get("created", ""), m.get("author", ""),
    )]
    parts.append(_section_header("📋", "内容", "rgba(91,141,239,0.12)"))
    parts.append(f"<pre>{_esc(d.get('content', d.get('body', '')))}</pre>")
    parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
    return "\n".join(parts)


def _render_test_case(d: dict) -> str:
    m = d.get("meta", {})
    parts = [_page_start(
        m.get("title", "Test Cases"), m.get("doc_id", ""), "测试用例",
        m.get("created", ""), m.get("author", "qa_agent"),
    )]
    cases = d.get("test_cases", [])
    parts.append(_section_header("🧪", f"测试用例 ({len(cases)})", "rgba(91,141,239,0.12)"))
    for tc in cases:
        steps = "".join(f"<li>{_esc(s)}</li>" for s in tc.get("steps", []))
        parts.append(
            f'<div class="req-item">\n'
            f'  <h3>{_esc(tc.get("name",""))}</h3>\n'
            f'  <div class="comp-type">{_esc(tc.get("type",""))} · 优先级: {_esc(tc.get("priority",""))}</div>\n'
            f'  <p>{_esc(tc.get("description",""))}</p>\n'
            f'  <span class="ac-label">步骤</span>\n'
            f'  <ol>{steps}</ol>\n'
            f'  <p><strong>预期结果:</strong> {_esc(tc.get("expected_result",""))}</p>\n'
            f'</div>'
        )
    parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
    return "\n".join(parts)


def _render_deploy(d: dict) -> str:
    m = d.get("meta", {})
    parts = [_page_start(
        m.get("title", "Deploy Config"), m.get("doc_id", ""), "部署配置",
        m.get("created", ""), m.get("author", "devops_agent"),
    )]
    parts.append(_section_header("🚀", "部署配置", "rgba(91,141,239,0.12)"))
    parts.append(f"<pre>{_esc(json.dumps(d.get('config', d), ensure_ascii=False, indent=2))}</pre>")
    parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
    return "\n".join(parts)


def _render_adr(d: dict) -> str:
    m = d.get("meta", {})
    parts = [_page_start(
        m.get("title", "ADR"), m.get("doc_id", ""), "架构决策记录",
        m.get("created", ""), m.get("author", "architect_agent"),
    )]
    parts.append(_section_header("📋", "背景", "rgba(124,111,247,0.12)"))
    parts.append(f"<p>{_esc(d.get('context', ''))}</p>")
    parts.append(_SECTION_FOOT)
    parts.append(_section_header("✅", "决策", "rgba(52,211,153,0.12)"))
    parts.append(f"<p>{_esc(d.get('decision', ''))}</p>")
    parts.append(_SECTION_FOOT)
    parts.append(_section_header("⚠️", "后果", "rgba(251,191,36,0.12)"))
    parts.append(f"<p>{_esc(d.get('consequences', ''))}</p>")
    parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
    return "\n".join(parts)


PRIORITY_LABELS = {0: "P0 阻塞", 1: "P1 高", 2: "P2 中", 3: "P3 低"}
PRIORITY_COLORS = {0: "#ef4444", 1: "#f59e0b", 2: "#3b82f6", 3: "#9ca3af"}
STATUS_LABELS = {"pending": "待开始", "in_progress": "进行中", "done": "已完成",
                  "blocked": "被阻塞", "failed": "失败"}
STATUS_COLORS = {"pending": "#9ca3af", "in_progress": "#3b82f6", "done": "#22c55e",
                 "blocked": "#f59e0b", "failed": "#ef4444"}


def _render_task(d: dict) -> str:
    """Render single task or WBS aggregate JSON to HTML."""
    # Detect: WBS aggregate has "tasks" array; individual task has "task_id"
    if "tasks" in d:
        return _render_wbs_aggregate(d)
    return _render_single_task(d)


def _render_wbs_aggregate(d: dict) -> str:
    m = d.get("meta", {})
    tasks = d.get("tasks", [])
    parts = [_page_start(
        m.get("title", "WBS"), m.get("doc_id", ""), "WBS",
        m.get("created", ""), m.get("author", "techlead_agent"),
    )]

    # Summary stats
    total = len(tasks)
    total_hours = sum(t.get("estimated_hours", 0) or 0 for t in tasks)
    cats = {}
    for t in tasks:
        cat = t.get("category", "未分类")
        cats[cat] = cats.get(cat, 0) + 1
    cat_badges = " ".join(f'<span class="badge">{c} ({n})</span>' for c, n in sorted(cats.items()))

    parts.append(_section_header("📊", f"概览 — {total} 个任务，共 {total_hours:.0f}h", "rgba(91,141,239,0.12)"))
    parts.append(f"<div style='margin-bottom:12px'>{cat_badges}</div>")
    parts.append(_SECTION_FOOT)

    # Task list
    parts.append(_section_header("📋", "任务列表", "rgba(124,111,247,0.12)"))
    parts.append('<div class="req-list">')
    for i, t in enumerate(tasks, 1):
        name = _esc(t.get("name", f"任务 {i}"))
        desc = _esc(t.get("description", ""))
        prio = t.get("priority", 2)
        prio_label = PRIORITY_LABELS.get(prio, f"P{prio}")
        prio_color = PRIORITY_COLORS.get(prio, "#9ca3af")
        cat = _esc(t.get("category", "未分类"))
        hours = t.get("estimated_hours", 0) or 0
        deps = t.get("deps", [])
        deps_str = ", ".join(deps) if deps else "无"
        assignee = _esc(t.get("assignee", "未分配"))
        layer = t.get("layer", 0)
        exp_files = t.get("expected_output_files", [])
        refs_count = len(t.get("lld_refs", []))
        ac_count = len(t.get("acceptance_criteria", []))

        LAYER_SHORT = {0: "M", 1: "S", 2: "E", 3: "T"}
        layer_label = LAYER_SHORT.get(layer, str(layer))

        meta_parts = [
            f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            f'background:{prio_color};margin-right:4px"></span>'
            f'{prio_label}',
            f'<span class="layer-badge layer-{layer if layer in (0,1,2,3) else "other"}">L{layer}</span>',
            f'{cat}',
            f'{hours}h',
            f'{assignee}',
        ]
        if refs_count:
            meta_parts.append(f'{refs_count} LLD引用')
        if ac_count:
            meta_parts.append(f'{ac_count} 验收标准')

        parts.append(
            f'<div class="req-item">\n'
            f'  <h3>{i}. {name}</h3>\n'
            f'  <div class="comp-type">{" · ".join(meta_parts)}</div>\n'
            f'  <p>{desc}</p>\n'
        )

        if exp_files:
            file_items = "".join(f"<li>{_esc(f)}</li>" for f in exp_files[:5])
            more = f" ... (+{len(exp_files) - 5})" if len(exp_files) > 5 else ""
            parts.append(
                f'  <ul class="file-list" style="margin:8px 0">{file_items}{more}</ul>\n'
            )

        parts.append(
            f'  <p><strong>依赖:</strong> {_esc(deps_str)}</p>\n'
            f'</div>'
        )
    parts.append("</div>")
    parts.append(_SECTION_FOOT)

    # Dependency graph (simple text-based)
    parts.append(_section_header("🔗", "依赖关系图", "rgba(52,211,153,0.12)"))
    parts.append("<pre>")
    for i, t in enumerate(tasks, 1):
        name = t.get("name", f"任务 {i}")
        deps = t.get("deps", [])
        if deps:
            for dep in deps:
                dep_name = dep
                for dt in tasks:
                    if dt.get("name") == dep:
                        dep_name = f"{dep} ({dt.get('name', dep)})"
                        break
                parts.append(f"{_esc(dep)} → {_esc(name)}")
        else:
            parts.append(f"(入口) → {_esc(name)}")
    parts.append("</pre>")
    parts.append(_SECTION_FOOT)

    parts.append(_PAGE_END)
    return "\n".join(parts)


def _render_single_task(d: dict) -> str:
    """Render a single task JSON to HTML."""
    task_id = _esc(d.get("task_id", ""))
    name = _esc(d.get("name", ""))
    module = _esc(d.get("module", ""))
    status_val = d.get("status", "pending")
    status_label = STATUS_LABELS.get(status_val, status_val)
    status_color = STATUS_COLORS.get(status_val, "#9ca3af")
    prio = d.get("priority", 2)
    prio_label = PRIORITY_LABELS.get(prio, f"P{prio}")
    prio_color = PRIORITY_COLORS.get(prio, "#9ca3af")
    cat = _esc(d.get("category", "未分类"))
    assignee = _esc(d.get("assignee") or "未分配")
    est_h = d.get("estimated_hours")
    act_h = d.get("actual_hours")
    deps = d.get("deps", [])
    changed = d.get("changed_files", [])
    desc = _esc(d.get("description", ""))
    result = d.get("result")
    error = d.get("error")
    created = d.get("created_at", "")
    updated = d.get("updated_at", "")

    parts = [_page_start(name, task_id, "任务", created, assignee)]

    # Status bar
    parts.append(
        f'<div style="margin-bottom:16px">'
        f'<span style="display:inline-block;padding:4px 12px;border-radius:4px;'
        f'background:{status_color}22;color:{status_color};font-weight:600;margin-right:8px">'
        f'{status_label}</span>'
        f'<span style="display:inline-block;padding:4px 12px;border-radius:4px;'
        f'background:{prio_color}22;color:{prio_color};font-weight:600;margin-right:8px">'
        f'{prio_label}</span>'
        f'<span class="badge">{cat}</span>'
        f'<span style="margin-left:8px;color:#9ca3af">{module} · {assignee}</span>'
        f'</div>'
    )

    # New fields
    layer = d.get("layer", 0)
    exp_files = d.get("expected_output_files", [])
    lld_refs = d.get("lld_refs", [])
    ac_list = d.get("acceptance_criteria", [])
    ctx = d.get("context")

    LAYER_LABELS = {0: "Model", 1: "Service", 2: "Endpoint", 3: "Test"}
    LAYER_CSS = {0: "layer-0", 1: "layer-1", 2: "layer-2", 3: "layer-3"}

    # Key info
    parts.append(_section_header("📋", "基本信息", "rgba(91,141,239,0.12)"))
    parts.append(f"<p><strong>Task ID:</strong> {task_id}</p>")
    parts.append(f"<p><strong>模块:</strong> {module}</p>")
    layer_label = LAYER_LABELS.get(layer, f"L{layer}")
    layer_css = LAYER_CSS.get(layer, "layer-other")
    parts.append(
        f'<p><strong>层级:</strong> '
        f'<span class="layer-badge {layer_css}">L{layer} — {layer_label}</span></p>'
    )
    if est_h is not None:
        parts.append(f"<p><strong>预估工时:</strong> {est_h}h</p>")
    if act_h is not None:
        parts.append(f"<p><strong>实际工时:</strong> {act_h}h</p>")
    if deps:
        parts.append(f"<p><strong>依赖:</strong> {_esc(', '.join(deps))}</p>")
    else:
        parts.append("<p><strong>依赖:</strong> 无</p>")
    parts.append(_SECTION_FOOT)

    # Expected output files
    if exp_files:
        parts.append(_section_header("📁", "预期产出文件", "rgba(52,211,153,0.12)"))
        parts.append('<ul class="file-list">')
        for f in exp_files:
            parts.append(f"<li>{_esc(f)}</li>")
        parts.append("</ul>")
        parts.append(_SECTION_FOOT)

    # LLD references
    if lld_refs:
        parts.append(_section_header("🔗", f"LLD 设计追溯 ({len(lld_refs)} 项)", "rgba(124,111,247,0.12)"))
        parts.append('<table class="ref-table"><thead><tr>'
                     '<th>章节</th><th>条目</th><th>类型</th><th>子条目</th>'
                     '</tr></thead><tbody>')
        for ref in lld_refs:
            section = _esc(ref.get("section", ""))
            item = _esc(ref.get("item_name", ""))
            atype = _esc(ref.get("artifact_type", ""))
            sub = _esc(ref.get("sub_item") or "—")
            parts.append(f"<tr><td>{section}</td><td>{item}</td>"
                         f"<td><span class='badge'>{atype}</span></td>"
                         f"<td>{sub}</td></tr>")
        parts.append("</tbody></table>")
        parts.append(_SECTION_FOOT)

    # Acceptance criteria
    if ac_list:
        parts.append(_section_header("✓", f"验收标准 ({len(ac_list)} 项)", "rgba(34,197,94,0.12)"))
        for ac in ac_list:
            vtype = ac.get("verification_type", "")
            desc = _esc(ac.get("description", ""))
            expected = _esc(str(ac.get("expected", "")))
            css_vtype = f"ac-vtype-{vtype}" if vtype else ""
            parts.append(
                f'<div class="ac-item">'
                f'<span class="ac-vtype {css_vtype}">{_esc(vtype)}</span>'
                f'{desc}'
                f'</div>'
            )
        parts.append(_SECTION_FOOT)

    # Context — scope summary
    if ctx:
        parts.append(_section_header("🎯", "设计上下文", "rgba(91,141,239,0.12)"))
        scope = ctx.get("scope", {})
        if scope:
            parts.append('<div class="scope-summary">')
            scope_sections = [
                ("接口", len(scope.get("interfaces", []))),
                ("数据模型", len(scope.get("data_models", []))),
                ("领域对象", len(scope.get("domain_objects", []))),
                ("服务契约", len(scope.get("service_contracts", []))),
                ("业务规则", len(scope.get("business_rules", {}).get("invariants", []))
                              + len(scope.get("business_rules", {}).get("state_machines", []))),
                ("外部契约", len(ctx.get("external_contracts", []))),
                ("技术栈", len(ctx.get("tech_stack", []))),
            ]
            for label, count in scope_sections:
                if count:
                    parts.append(
                        f'<div class="scope-card">'
                        f'<div class="sc-count">{count}</div>'
                        f'<div class="sc-label">{label}</div>'
                        f'</div>'
                    )
            parts.append("</div>")

        # Cross-module deps
        cross = ctx.get("cross_module_deps", [])
        if cross:
            parts.append("<p style='margin-top:10px'><strong>跨模块依赖:</strong> "
                         f"{_esc(', '.join(cross))}</p>")

        # Tech stack
        tech = ctx.get("tech_stack", [])
        if tech:
            badges = " ".join(f'<span class="badge">{_esc(t)}</span>' for t in tech)
            parts.append(f"<p style='margin-top:6px'>{badges}</p>")

        # upstream_artifacts
        upstream = ctx.get("upstream_artifacts", [])
        if upstream:
            parts.append("<p style='margin-top:10px'><strong>上游已完成产物:</strong></p>")
            for up in upstream:
                name = _esc(up.get("name", up.get("task_id", "?")))
                cat = _esc(up.get("category", ""))
                files = up.get("files", [])
                file_str = "<br>".join(
                    f'<code style="font-size:0.85em;color:var(--c-accent)">{_esc(f)}</code>'
                    for f in files
                )
                parts.append(
                    f'<div class="upstream-item">'
                    f'<span class="up-name">{name}</span>'
                    f'<span class="badge" style="margin-left:6px">{cat}</span>'
                    f'<div style="margin-top:4px">{file_str}</div>'
                    f'</div>'
                )

        parts.append(_SECTION_FOOT)

    # Description
    parts.append(_section_header("📝", "描述", "rgba(124,111,247,0.12)"))
    parts.append(f"<p>{desc}</p>")
    parts.append(_SECTION_FOOT)

    # Changed files
    if changed:
        parts.append(_section_header("📁", "变更文件", "rgba(52,211,153,0.12)"))
        parts.append("<ul>")
        for f in changed:
            parts.append(f"<li>{_esc(f)}</li>")
        parts.append("</ul>")
        parts.append(_SECTION_FOOT)

    # Result
    if result:
        parts.append(_section_header("✅", "执行结果", "rgba(34,197,94,0.12)"))
        parts.append("<pre>")
        for k, v in result.items():
            parts.append(f"{_esc(k)}: {_esc(str(v))}")
        parts.append("</pre>")
        parts.append(_SECTION_FOOT)

    # Error
    if error:
        parts.append(_section_header("❌", "错误信息", "rgba(239,68,68,0.12)"))
        parts.append(f"<pre>{_esc(error)}</pre>")
        parts.append(_SECTION_FOOT)

    # Timestamps
    parts.append(f'<div class="meta" style="margin-top:24px">创建: {created} · 更新: {updated}</div>')

    parts.append(_PAGE_END)
    return "\n".join(parts)


def _render_generic(doc_type: str, d: dict) -> str:
    m = d.get("meta", {})
    parts = [_page_start(
        m.get("title", doc_type.upper()), m.get("doc_id", ""), doc_type.upper(),
        m.get("created", ""), m.get("author", ""),
    )]
    parts.append(_section_header("📄", "内容", "rgba(91,141,239,0.12)"))
    parts.append(f"<pre>{_esc(json.dumps(d, ensure_ascii=False, indent=2))}</pre>")
    parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Combined WBS module HTML (sidebar + all tasks in one page)
# ---------------------------------------------------------------------------

# Priority / status labels (shared with _render_single_task)
_PRIO: dict[int, str] = {0: "P0 阻塞", 1: "P1 高", 2: "P2 中", 3: "P3 低"}
_PRIO_C: dict[int, str] = {0: "#f87171", 1: "#fbbf24", 2: "#5b8def", 3: "#6b7394"}
_LAYER: dict[int, str] = {0: "Model", 1: "Service", 2: "Endpoint", 3: "Test"}
_LAYER_CSS: dict[int, str] = {0: "layer-0", 1: "layer-1", 2: "layer-2", 3: "layer-3"}


def render_wbs_module_html(module: str, tasks: list[dict],
                           created: str = "", repo_path: Path | None = None) -> Path | None:
    """Render all tasks for one module into a single sidebar-navigated HTML page.

    Returns the Path to the generated HTML file, or None on failure.
    """
    if not tasks:
        return None

    total_hours = sum(t.get("estimated_hours", 0) or 0 for t in tasks)
    doc_id = f"wbs-{module}"
    title = f"WBS - {module}"

    # ── Sidebar sections ──
    sections: list[tuple[str, str, str]] = [("overview", "📊", "概览")]
    for i, t in enumerate(tasks):
        tid = f"task-{i}"
        sections.append((tid, "", _esc(t.get("name", f"任务{i+1}")[:28])))

    # ── Page start with sidebar ──
    parts: list[str] = []
    sidebar_html = _render_sidebar(doc_id, title, sections)
    parts.append(
        f"<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        f"<meta charset=\"UTF-8\">\n"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"<title>{_esc(title)} — {_esc(doc_id)}</title>\n"
        f"<style>{_SHARED_CSS}</style>\n"
        f"</head>\n<body>\n"
        f"<div class=\"page-layout\">\n"
        + sidebar_html
        + "<button id=\"sidebar-toggle\" class=\"sidebar-toggle\" aria-label=\"菜单\">☰</button>\n"
        + "<div class=\"main-content\">\n"
        f"<div class=\"top-bar\">\n"
        f"  <div class=\"doc-id\">{_esc(doc_id)}</div>\n"
        f"  <div><span class=\"badge accent\">WBS</span></div>\n"
        f"</div>\n"
        f"<h1><span>WBS</span> {_esc(title)}</h1>\n"
        f"<div class=\"meta\">{_esc(created)} &middot; 作者: techlead_agent</div>\n"
    )

    # ── Overview section ──
    parts.append(_section_header("📊", f"概览 — {len(tasks)} 个任务，共 {total_hours:.0f}h",
                                 "rgba(91,141,239,0.12)", "overview"))
    cats: dict[str, int] = {}
    for t in tasks:
        cat = t.get("category", "未分类")
        cats[cat] = cats.get(cat, 0) + 1
    cat_badges = " ".join(
        f'<span class="badge">{_esc(c)} ({n})</span>'
        for c, n in sorted(cats.items())
    )
    layer_counts: dict[int, int] = {}
    for t in tasks:
        l = t.get("layer", 0)
        layer_counts[l] = layer_counts.get(l, 0) + 1
    layer_info = " · ".join(
        f'<span class="layer-badge {_LAYER_CSS.get(l, "layer-other")}">'
        f'L{l} {_LAYER.get(l, "?")}: {n}</span>'
        for l, n in sorted(layer_counts.items())
    )
    parts.append(f"<p>{cat_badges}</p>")
    parts.append(f"<p>{layer_info}</p>")
    parts.append(_SECTION_FOOT)

    # ── Task sections ──
    for i, t in enumerate(tasks):
        tid = f"task-{i}"
        name = _esc(t.get("name", f"任务 {i+1}"))
        desc = _esc(t.get("description", "") or "(无描述)")
        task_id = _esc(t.get("task_id", ""))
        prio = t.get("priority", 2)
        prio_label = _PRIO.get(prio, f"P{prio}")
        prio_color = _PRIO_C.get(prio, "#6b7394")
        cat = _esc(t.get("category", "未分类"))
        hours = t.get("estimated_hours", 0) or 0
        deps = t.get("deps", [])
        layer = t.get("layer", 0)
        layer_label = _LAYER.get(layer, f"L{layer}")
        layer_css = _LAYER_CSS.get(layer, "layer-other")
        exp_files = t.get("expected_output_files", [])
        lld_refs = t.get("lld_refs", [])
        ac_list = t.get("acceptance_criteria", [])
        assignee = _esc(t.get("assignee") or "未分配")

        parts.append(_section_header(
            f"{i+1}.",
            f"{name}",
            "rgba(124,111,247,0.12)",
            tid,
        ))

        # Meta row
        meta_items = [
            f'<span class="badge">{task_id}</span>',
            f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            f'background:{prio_color};margin:0 2px 0 8px"></span> {prio_label}',
            f'<span class="layer-badge {layer_css}">L{layer} — {layer_label}</span>',
            f'<span class="badge">{cat}</span>',
            f'<span style="color:var(--c-muted)">{hours}h · {assignee}</span>',
        ]
        parts.append(
            f'<p style="margin-bottom:12px">{" ".join(meta_items)}</p>'
        )
        parts.append(f"<p>{desc}</p>")

        # Dependencies
        if deps:
            dep_tags = " ".join(
                f'<span class="cc-consumer">{_esc(d)}</span>' for d in deps
            )
            parts.append(
                f'<p style="margin-top:10px"><strong>依赖:</strong> {dep_tags}</p>'
            )

        # Expected output files
        if exp_files:
            file_items = "".join(
                f"<li>{_esc(f)}</li>" for f in exp_files[:6]
            )
            more = f"\n<li>... (+{len(exp_files) - 6} 更多)</li>" if len(exp_files) > 6 else ""
            parts.append(
                f'<div class="body-label" style="margin-top:12px">预期产出文件</div>'
                f'<ul class="file-list">{file_items}{more}</ul>'
            )

        # LLD references
        if lld_refs:
            parts.append(
                f'<div class="body-label" style="margin-top:12px">'
                f'LLD 设计追溯 ({len(lld_refs)} 项)</div>'
            )
            parts.append(
                '<table class="body-table"><thead><tr>'
                '<th>章节</th><th>条目</th><th>类型</th></tr></thead><tbody>'
            )
            for ref in lld_refs[:10]:
                section = _esc(ref.get("section", ""))
                item = _esc(ref.get("item_name", ""))
                atype = _esc(ref.get("artifact_type", ""))
                parts.append(
                    f"<tr><td>{section}</td><td>{item}</td>"
                    f"<td><span class=\"badge\">{atype}</span></td></tr>"
                )
            if len(lld_refs) > 10:
                parts.append(
                    f'<tr><td colspan="3">... (+{len(lld_refs) - 10} 更多)</td></tr>'
                )
            parts.append("</tbody></table>")

        # Acceptance criteria
        if ac_list:
            parts.append(
                f'<div class="body-label" style="margin-top:12px">'
                f'验收标准 ({len(ac_list)} 项)</div>'
            )
            ac_items = ""
            for ac in ac_list:
                if isinstance(ac, dict):
                    ac_items += (
                        f'<li>'
                        f'<span class="ac-vtype-{ac.get("vtype", "invariant")}">'
                        f'{_esc(ac.get("vtype", ""))}</span> '
                        f'{_esc(ac.get("criterion", str(ac)))}</li>'
                    )
                else:
                    ac_items += f"<li>{_esc(str(ac))}</li>"
            parts.append(f'<ul class="ac-list">{ac_items}</ul>')

        parts.append(_SECTION_FOOT)

    # ── Dependency graph ──
    parts.append(_section_header("🔗", "依赖关系图", "rgba(52,211,153,0.12)", "dep-graph"))
    parts.append('<pre style="font-size:0.85em;line-height:1.8">')
    for i, t in enumerate(tasks):
        name = t.get("name", f"任务 {i+1}")
        task_deps = t.get("deps", [])
        if task_deps:
            for d in task_deps:
                parts.append(f"{_esc(d)}  →  {_esc(name)}")
        else:
            parts.append(f"(入口)  →  {_esc(name)}")
    parts.append("</pre>")
    parts.append(_SECTION_FOOT)

    parts.append(_PAGE_END_SIDEBAR)
    html = "\n".join(parts)

    # Write to .cogniforge/html/tasks/wbs-{module}.html
    base = repo_path or Path.cwd()
    out_dir = base / ".cogniforge" / "html" / "tasks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"wbs-{module}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
