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
  .method-badge.get    { background: rgba(52,211,153,0.15);  color: var(--c-green); }
  .method-badge.post   { background: rgba(91,141,239,0.15);  color: var(--c-accent); }
  .method-badge.put    { background: rgba(251,191,36,0.12);  color: var(--c-amber); }
  .method-badge.delete { background: rgba(248,113,113,0.12); color: var(--c-red); }
  .method-badge.mq     { background: rgba(124,111,247,0.13); color: var(--c-accent2); }
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
        name = _esc(r.get("name", f"需求 {i}"))
        desc = _esc(r.get("description", ""))
        ac = r.get("acceptance_criteria", [])
        ac_html = ""
        if ac:
            ac_items = "\n".join(f"<li>{_esc(a)}</li>" for a in ac)
            ac_html = (
                '<span class="ac-label">验收条件</span>\n'
                f'<ul class="ac-list">\n{ac_items}\n</ul>'
            )
        items.append(
            f'<div class="req-item">\n'
            f'  <h3>{i}. {name}</h3>\n'
            f'  <div class="req-desc">{desc}</div>\n'
            f'  {ac_html}\n'
            f'</div>'
        )
    return "\n".join(items)


def _render_stories(stories: list) -> str:
    if not stories:
        return "<p>暂无用户故事</p>"
    items = []
    for s in stories:
        role = _esc(s.get("role", "用户"))
        action = _esc(s.get("action", "做某事"))
        goal = _esc(s.get("goal", ""))
        items.append(
            f'<div class="story-item">\n'
            f'  <span class="story-role">{role}</span>\n'
            f'  <div class="story-text">\n'
            f'    作为 <strong>{role}</strong>，我想要 <strong>{action}</strong>\n'
            f'    <br><span class="goal">以便：{goal}</span>\n'
            f'  </div>\n'
            f'</div>'
        )
    return "\n".join(items)


def _render_priorities(priorities: dict) -> str:
    if not priorities:
        return "<p>暂无优先级定义</p>"
    tags = []
    for name, pri in priorities.items():
        css = "high" if "高" in pri else ("medium" if "中" in pri else "low")
        tags.append(
            f'<span class="priority-tag {css}">{_esc(name)} &middot; {_esc(pri)}</span>'
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
    else:
        return _render_generic(doc_type, data)


def render_file(json_path: Path, wiki_root: Path | None = None) -> Optional[Path]:
    """Read a JSON file, render to HTML under html/ subdir.  Returns the HTML path."""
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None

    meta = data.get("meta", {})
    doc_type = meta.get("type", "prd")

    try:
        html = render_to_html(doc_type, data)
    except Exception:
        return None

    # Map .cogniforge/wiki/{type}[/{module}]/file.json → .cogniforge/html/{type}[/{module}]/file.html
    path_str = str(json_path)
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
    parts = [_page_start(
        m.get("title", "PRD"), m.get("doc_id", ""), "产品需求文档",
        m.get("created", ""), m.get("author", "pm_agent"),
    )]
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
    parts.append(_render_priorities(d.get("priorities", {})))
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
            "db": "db", "cache": "cache", "mq": "mq",
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

    # Build section list for sidebar (topology merged into architecture)
    sections = [
        ("overview", "📄", "系统概述"),
        ("architecture", "🏗️", "架构设计"),
        ("components", "🧩", f"组件设计 ({len(comps)})"),
    ]
    if contracts:
        sections.append(("contracts", "🔗", f"接口契约 ({len(contracts)})"))
    if d.get("data_flow"):
        sections.append(("dataflow", "📊", "数据流"))

    parts = [_page_start_sidebar(
        title, doc_id, "系统架构文档",
        m.get("created", ""), m.get("author", "architect_agent"),
        sections,
    )]
    overview_text = d.get("system_overview", "")
    parts.append(_section_header("📄", "系统概述", "rgba(124,111,247,0.12)", "overview"))
    parts.append(_render_overview_section(overview_text))
    parts.append(_SECTION_FOOT)

    # Architecture → includes topology layers + protocols
    arch_data = d.get("architecture", "")
    parts.append(_section_header("🏗️", "架构设计", "rgba(91,141,239,0.12)", "architecture"))
    parts.append(_render_architecture_section(arch_data, comps))
    parts.append(_SECTION_FOOT)

    # Components → grouped by architecture layers
    parts.append(_section_header("🧩", f"组件设计 ({len(comps)})", "rgba(34,211,238,0.12)", "components"))
    if comps:
        # Build layer lookup from architecture data
        layer_for: dict[str, str] = {}
        if isinstance(arch_data, dict):
            for layer in arch_data.get("layers", []):
                for cname in layer.get("components", []):
                    layer_for[cname] = layer.get("name", "")

        # Group components by layer
        grouped_comps: dict[str, list] = {}
        unlayered: list = []
        for c in comps:
            cname = c.get("name", "")
            lname = layer_for.get(cname, "")
            if lname:
                grouped_comps.setdefault(lname, []).append(c)
            else:
                unlayered.append(c)

        # Render groups (preserve layer order from architecture)
        type_icons = {
            "frontend": "🖥️", "gateway": "🔀", "service": "⚙️",
            "db": "🗄️", "cache": "⚡", "mq": "📨",
        }
        layer_order = list(dict.fromkeys(layer_for.values()))  # unique, insertion order
        for lname in layer_order:
            items = grouped_comps.get(lname, [])
            if not items:
                continue
            cards = []
            for c in items:
                items_html = "".join(f"<li>{_esc(r)}</li>" for r in c.get("responsibilities", []))
                ctype = c.get("type", "")
                icon = type_icons.get(ctype, "📦")
                cards.append(
                    f'<div class="comp-item">\n'
                    f'  <h3>{icon} {_esc(c.get("name", ""))}</h3>\n'
                    f'  <div class="comp-type">{_esc(ctype)}</div>\n'
                    f'  <p>{_esc(c.get("description", ""))}</p>\n'
                    f'  <ul class="comp-resp">{items_html}</ul>\n'
                    f'</div>'
                )
            if cards:
                parts.append(
                    '<details class="contract-group" open>'
                    f'<summary>{_esc(lname)} <span class="cg-count">{len(cards)}</span></summary>'
                    f'{"".join(cards)}'
                    '</details>'
                )

        # Any components not in any layer
        for c in unlayered:
            items_html = "".join(f"<li>{_esc(r)}</li>" for r in c.get("responsibilities", []))
            ctype = c.get("type", "")
            icon = type_icons.get(ctype, "📦")
            parts.append(
                f'<div class="comp-item">\n'
                f'  <h3>{icon} {_esc(c.get("name", ""))}</h3>\n'
                f'  <div class="comp-type">{_esc(ctype)}</div>\n'
                f'  <p>{_esc(c.get("description", ""))}</p>\n'
                f'  <ul class="comp-resp">{items_html}</ul>\n'
                f'</div>'
            )
    parts.append(_SECTION_FOOT)

    if contracts:
        parts.append(_section_header("🔗", f"接口契约 ({len(contracts)})", "rgba(52,211,153,0.12)", "contracts"))
        parts.append(_render_contracts_section(contracts))
        parts.append(_SECTION_FOOT)
    if d.get("data_flow"):
        parts.append(_section_header("📊", "数据流", "rgba(251,191,36,0.12)", "dataflow"))
        parts.append(_render_dataflow_section(d["data_flow"]))
        parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END_SIDEBAR)
    return "\n".join(parts)


def _render_lld(d: dict) -> str:
    m = d.get("meta", {})
    title = m.get("title", "LLD")
    doc_id = m.get("doc_id", "")
    module = m.get("module", "")
    models = d.get("data_models", [])
    ifaces = d.get("interfaces", [])

    # Sidebar sections
    sections = [
        ("overview", "📄", "概述"),
        ("models", "🗄️", f"数据模型 ({len(models)})"),
    ]
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
    if isinstance(overview, dict):
        desc = overview.get("description", "")
        deps = overview.get("dependencies", [])
        tech = overview.get("tech_stack", [])
        if module:
            parts.append(
                f'<div class="arch-style-badge" style="margin-bottom:12px">'
                f'模块: {_esc(module)}</div>'
            )
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
    else:
        # String overview — plain text
        ov_text = str(overview) if overview else ""
        if module:
            parts.append(
                f'<div class="arch-style-badge" style="margin-bottom:12px">'
                f'模块: {_esc(module)}</div>'
            )
        if ov_text:
            parts.append(f"<p>{_esc(ov_text)}</p>")
    parts.append(_SECTION_FOOT)

    # ── 2. Data Models ──
    parts.append(_section_header("🗄️", f"数据模型 ({len(models)})", "rgba(91,141,239,0.12)", "models"))
    if models:
        # Group by type
        from collections import OrderedDict
        type_labels = {
            "table": "数据库表", "interface": "数据接口", "struct": "数据结构",
            "store": "状态存储", "config": "配置定义",
        }
        type_icons = {
            "table": "🗄️", "interface": "📋", "struct": "📦",
            "store": "🗃️", "config": "⚙️",
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
                desc_html = f'<p style="font-size:0.85em;color:var(--c-muted);margin-bottom:8px">{_esc(dm.get("description",""))}</p>' if dm.get("description") else ""
                cards.append(
                    f'<div class="contract-card" style="border-top:none">'
                    f'<h3 style="font-size:0.95em;font-weight:600;color:var(--c-heading);margin-bottom:4px">{icon} {_esc(dm.get("name",""))}</h3>'
                    f'{desc_html}'
                    f'<div class="body-label">字段</div>'
                    f'<table class="body-table"><thead><tr><th>字段名</th><th>类型</th><th>描述</th></tr></thead><tbody>{rows}</tbody></table>'
                    f'</div>'
                )
            parts.append(
                '<details class="contract-group" open>'
                f'<summary>{_esc(label)} <span class="cg-count">{len(cards)}</span></summary>'
                f'{"".join(cards)}'
                '</details>'
            )
    parts.append(_SECTION_FOOT)

    # ── 3. Interfaces ──
    if ifaces:
        parts.append(_section_header("🔌", f"接口定义 ({len(ifaces)})", "rgba(34,211,238,0.12)", "interfaces"))
        for iface in ifaces:
            endpoint = iface.get("endpoint", "")
            method = iface.get("method", "")
            # Auto-extract method from endpoint if not explicitly set
            if not method:
                ep_parts = endpoint.split(" ", 1)
                if len(ep_parts) == 2 and ep_parts[0] in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    method = ep_parts[0]
                    endpoint = ep_parts[1]
                elif endpoint == "INTERNAL":
                    method = "INTERNAL"

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

    # ── 4. Error Handling ──
    if d.get("error_handling"):
        parts.append(_section_header("⚠️", "错误处理", "rgba(251,191,36,0.12)", "errors"))
        parts.append(f"<p>{_esc(d['error_handling'])}</p>")
        parts.append(_SECTION_FOOT)

    parts.append(_PAGE_END_SIDEBAR)
    return "\n".join(parts)


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
