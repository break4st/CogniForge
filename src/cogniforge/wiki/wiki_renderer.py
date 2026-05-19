"""WikiRenderer — converts Agent-format JSON into user-facing HTML."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def _esc(text: str) -> str:
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
  @media (max-width: 700px) {
    body { padding: 24px 16px 48px; }
    h1 { font-size: 1.6em; }
    .section-body { padding: 20px 16px; }
  }
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


def _section_header(icon: str, title: str, bg_color: str) -> str:
    return (
        f'<div class="section">\n'
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
    html = render_to_html(doc_type, data)

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


def _render_sad(d: dict) -> str:
    m = d.get("meta", {})
    parts = [_page_start(
        m.get("title", "SAD"), m.get("doc_id", ""), "系统架构文档",
        m.get("created", ""), m.get("author", "architect_agent"),
    )]
    parts.append(_section_header("📄", "系统概述", "rgba(124,111,247,0.12)"))
    parts.append(f"<p>{_esc(d.get('system_overview', ''))}</p>")
    parts.append(_SECTION_FOOT)
    parts.append(_section_header("🏗️", "架构设计", "rgba(91,141,239,0.12)"))
    parts.append(f"<p>{_esc(d.get('architecture', ''))}</p>")
    parts.append(_SECTION_FOOT)
    comps = d.get("components", [])
    parts.append(_section_header("🧩", f"组件设计 ({len(comps)})", "rgba(34,211,238,0.12)"))
    if comps:
        for c in comps:
            items = "".join(f"<li>{_esc(r)}</li>" for r in c.get("responsibilities", []))
            parts.append(
                f'<div class="comp-item">\n'
                f'  <h3>{_esc(c.get("name", ""))}</h3>\n'
                f'  <div class="comp-type">{_esc(c.get("type", ""))}</div>\n'
                f'  <p>{_esc(c.get("description", ""))}</p>\n'
                f'  <ul class="comp-resp">{items}</ul>\n'
                f'</div>'
            )
    parts.append(_SECTION_FOOT)
    if d.get("topology"):
        parts.append(_section_header("🔗", "拓扑结构", "rgba(52,211,153,0.12)"))
        parts.append(f"<p>{_esc(d['topology'])}</p>")
        parts.append(_SECTION_FOOT)
    if d.get("data_flow"):
        parts.append(_section_header("📊", "数据流", "rgba(251,191,36,0.12)"))
        parts.append(f"<p>{_esc(d['data_flow'])}</p>")
        parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
    return "\n".join(parts)


def _render_lld(d: dict) -> str:
    m = d.get("meta", {})
    parts = [_page_start(
        m.get("title", "LLD"), m.get("doc_id", ""), "详细设计文档",
        m.get("created", ""), m.get("author", "design_agent"),
    )]
    parts.append(_section_header("📄", "概述", "rgba(124,111,247,0.12)"))
    parts.append(f"<p>模块: {_esc(m.get('module', ''))}</p>")
    parts.append(f"<p>{_esc(d.get('overview', ''))}</p>")
    parts.append(_SECTION_FOOT)
    models = d.get("data_models", [])
    parts.append(_section_header("🗄️", f"数据模型 ({len(models)})", "rgba(91,141,239,0.12)"))
    for dm in models:
        rows = ""
        for f in dm.get("fields", []):
            rows += (
                f"<tr><td>{_esc(f.get('name',''))}</td>"
                f"<td>{_esc(f.get('type',''))}</td>"
                f"<td>{_esc(f.get('description',''))}</td></tr>"
            )
        parts.append(
            f'<div class="model-item">\n'
            f'  <h3>{_esc(dm.get("name", ""))}</h3>\n'
            f'  <table><thead><tr><th>字段</th><th>类型</th><th>描述</th></tr></thead><tbody>{rows}</tbody></table>\n'
            f'</div>'
        )
    parts.append(_SECTION_FOOT)
    ifaces = d.get("interfaces", [])
    parts.append(_section_header("🔌", f"接口定义 ({len(ifaces)})", "rgba(34,211,238,0.12)"))
    for iface in ifaces:
        parts.append(
            f'<div class="comp-item">\n'
            f'  <h3>{_esc(iface.get("name",""))}</h3>\n'
            f'  <div class="comp-type">{_esc(iface.get("endpoint",""))}</div>\n'
            f'  <p>{_esc(iface.get("description",""))}</p>\n'
            f'</div>'
        )
    parts.append(_SECTION_FOOT)
    if d.get("error_handling"):
        parts.append(_section_header("⚠️", "错误处理", "rgba(251,191,36,0.12)"))
        parts.append(f"<p>{_esc(d['error_handling'])}</p>")
        parts.append(_SECTION_FOOT)
    parts.append(_PAGE_END)
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
