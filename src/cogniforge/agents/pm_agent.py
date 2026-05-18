"""PM Agent - Product Manager Agent for PRD creation"""

from datetime import datetime
from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.models.document import Document


class PMAgent(BaseAgent):
    """
    PM Agent - Product Manager.

    Responsibilities:
    - Write PRD documents
    - Define user stories
    - Prioritize requirements
    """

    # Priority labels
    PRIORITY_CN = {"高": "High", "中": "Medium", "低": "Low"}

    def run(self, input_data: dict) -> dict:
        """
        Create or update PRD document.

        Args:
            input_data: {
                "title": str,
                "overview": str,
                "requirements": list[dict],
                "user_stories": list[dict],
                "priorities": dict,
            }
        """
        try:
            title = input_data.get("title", "未命名PRD")
            overview = input_data.get("overview", "")
            requirements = input_data.get("requirements", [])
            user_stories = input_data.get("user_stories", [])
            priorities = input_data.get("priorities", {})

            # Generate doc_id
            existing = self.wiki_system.list_documents(DocumentType.PRD)
            seq = len(existing) + 1
            doc_id = f"prd-{seq:03d}"

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            content = self._format_prd(
                title, overview, requirements, user_stories, priorities,
                doc_id=doc_id, created_at=now
            )

            doc = Document(
                doc_id=doc_id,
                doc_type=DocumentType.PRD,
                title=title,
                content=content,
                path=f".cogniforge/wiki/prd/{doc_id}.html",
                author="pm_agent"
            )

            self.write_document(doc, f"feat: add PRD - {title}")

            return self.format_result(
                status="success",
                message=f"PRD created: {doc_id}",
                artifacts=[doc.path]
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _format_prd(
        self,
        title: str,
        overview: str,
        requirements: list,
        user_stories: list,
        priorities: dict,
        doc_id: str = "",
        created_at: str = "",
    ) -> str:
        """Format PRD content as a self-contained HTML page."""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self._esc(title)} — 产品需求文档</title>
<style>
  :root {{
    --c-bg: #0b0f19;
    --c-surface: #131926;
    --c-card: #191e2e;
    --c-border: #252b3d;
    --c-text: #c8d2e0;
    --c-heading: #e2e8f4;
    --c-muted: #6b7394;
    --c-accent: #5b8def;
    --c-accent2: #7c6ff7;
    --c-green: #34d399;
    --c-amber: #fbbf24;
    --c-red: #f87171;
    --c-cyan: #22d3ee;
    --radius: 10px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
    background: var(--c-bg);
    color: var(--c-text);
    line-height: 1.75;
    font-size: 15px;
    max-width: 860px;
    margin: 0 auto;
    padding: 48px 40px 80px;
  }}
  .top-bar {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 40px; padding-bottom: 24px;
    border-bottom: 1px solid var(--c-border);
  }}
  .top-bar .doc-id {{
    font-size: 0.8em; color: var(--c-muted);
    font-family: "SF Mono", "JetBrains Mono", monospace;
  }}
  .badge {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 14px; border-radius: 20px;
    font-size: 0.78em; font-weight: 500;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--c-border);
    color: var(--c-muted);
  }}
  .badge.accent {{ border-color: rgba(91,141,239,0.3); color: var(--c-accent); }}
  .badge.green  {{ border-color: rgba(52,211,153,0.3); color: var(--c-green); }}

  h1 {{
    font-size: 2.4em; font-weight: 800; color: #fff;
    letter-spacing: -1px; line-height: 1.2; margin-bottom: 6px;
  }}
  h1 span {{
    background: linear-gradient(135deg, var(--c-accent), var(--c-cyan));
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .meta {{ font-size: 0.85em; color: var(--c-muted); margin-bottom: 4px; }}

  .section {{ margin-bottom: 36px; }}
  .section-header {{
    display: flex; align-items: center; gap: 12px; margin-bottom: 18px;
  }}
  .section-header .icon {{
    width: 40px; height: 40px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.2em; flex-shrink: 0;
  }}
  .section-header h2 {{
    font-size: 1.25em; font-weight: 700;
    color: var(--c-heading); letter-spacing: -0.2px;
  }}
  .section-body {{
    background: var(--c-card); border: 1px solid var(--c-border);
    border-radius: var(--radius); padding: 28px 32px;
  }}
  .section-body p {{ margin-bottom: 12px; }}
  .section-body p:last-child {{ margin-bottom: 0; }}

  .req-item {{
    background: var(--c-surface); border: 1px solid var(--c-border);
    border-radius: 8px; padding: 18px 22px; margin-bottom: 10px;
  }}
  .req-item:last-child {{ margin-bottom: 0; }}
  .req-item h3 {{
    font-size: 1em; font-weight: 600; color: var(--c-heading);
    margin-bottom: 6px;
  }}
  .req-item .req-desc {{ font-size: 0.9em; color: var(--c-muted); margin-bottom: 10px; }}
  .ac-list {{
    list-style: none; padding: 0; margin: 0;
  }}
  .ac-list li {{
    padding: 4px 0 4px 18px; position: relative;
    font-size: 0.88em; color: var(--c-text);
  }}
  .ac-list li::before {{
    content: ""; position: absolute; left: 0; top: 12px;
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--c-green);
  }}
  .ac-label {{
    font-size: 0.75em; font-weight: 600; color: var(--c-muted);
    text-transform: uppercase; letter-spacing: 0.5px;
    margin-bottom: 4px; display: block;
  }}

  .story-list {{ display: flex; flex-direction: column; gap: 8px; }}
  .story-item {{
    display: flex; align-items: flex-start; gap: 12px;
    padding: 14px 18px; border-radius: 8px;
    background: var(--c-surface); border: 1px solid var(--c-border);
  }}
  .story-role {{
    font-size: 0.8em; font-weight: 600; color: var(--c-accent);
    background: rgba(91,141,239,0.1); padding: 2px 10px;
    border-radius: 12px; white-space: nowrap; flex-shrink: 0;
    margin-top: 1px;
  }}
  .story-text {{ font-size: 0.92em; }}
  .story-text .goal {{ color: var(--c-muted); font-size: 0.88em; }}

  .priority-grid {{
    display: flex; flex-wrap: wrap; gap: 8px;
  }}
  .priority-tag {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 14px; border-radius: 6px;
    font-size: 0.85em; font-weight: 500;
  }}
  .priority-tag.high   {{ background: rgba(248,113,113,0.1);  color: #fca5a5; border: 1px solid rgba(248,113,113,0.2); }}
  .priority-tag.medium {{ background: rgba(251,191,36,0.1);  color: #fcd34d; border: 1px solid rgba(251,191,36,0.2); }}
  .priority-tag.low    {{ background: rgba(107,115,148,0.15); color: #9ca3af; border: 1px solid rgba(107,115,148,0.2); }}

  .footer {{
    margin-top: 48px; padding-top: 20px;
    border-top: 1px solid var(--c-border);
    text-align: center; color: var(--c-muted); font-size: 0.8em;
  }}

  @media (max-width: 700px) {{
    body {{ padding: 24px 16px 48px; }}
    h1 {{ font-size: 1.6em; }}
    .section-body {{ padding: 20px 16px; }}
  }}

  @media print {{
    body {{ background: #fff; color: #222; }}
    .section-body, .req-item, .story-item {{ background: #fff; border: 1px solid #ddd; }}
    h1 {{ color: #111; }}
  }}
</style>
</head>
<body>

<div class="top-bar">
  <div class="doc-id">{self._esc(doc_id)}</div>
  <div class="badges">
    <span class="badge accent">产品需求文档</span>
    <span class="badge green">产品需求</span>
  </div>
</div>

<h1><span>产品需求文档</span> {self._esc(title)}</h1>
<div class="meta">{created_at} &middot; 作者: pm_agent</div>

<div class="section">
  <div class="section-header">
    <div class="icon" style="background:rgba(124,111,247,0.12)">&#x1F4CB;</div>
    <h2>概述</h2>
  </div>
  <div class="section-body">
    <p>{self._esc(overview)}</p>
  </div>
</div>

<div class="section">
  <div class="section-header">
    <div class="icon" style="background:rgba(91,141,239,0.12)">&#x1F4CB;</div>
    <h2>功能需求{self._build_req_count(len(requirements))}</h2>
  </div>
  <div class="section-body">
    {self._build_requirements(requirements)}
  </div>
</div>

<div class="section">
  <div class="section-header">
    <div class="icon" style="background:rgba(34,211,238,0.12)">&#x1F9D1;&#x200D;&#x1F91D;&#x200D;&#x1F9D1;</div>
    <h2>用户故事{self._build_story_count(len(user_stories))}</h2>
  </div>
  <div class="section-body">
    {self._build_user_stories(user_stories)}
  </div>
</div>

<div class="section">
  <div class="section-header">
    <div class="icon" style="background:rgba(251,191,36,0.12)">&#x1F3AF;</div>
    <h2>优先级</h2>
  </div>
  <div class="section-body">
    {self._build_priorities(priorities)}
  </div>
</div>

<div class="footer">
  {self._esc(doc_id)} &middot; CogniForge 文档驱动系统
</div>

</body>
</html>"""

    @staticmethod
    def _esc(text: str) -> str:
        """HTML-escape a string."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    @staticmethod
    def _build_req_count(n: int) -> str:
        return f' <span style="font-size:0.7em;color:var(--c-muted);font-weight:400">({n})</span>' if n else ""

    @staticmethod
    def _build_story_count(n: int) -> str:
        return f' <span style="font-size:0.7em;color:var(--c-muted);font-weight:400">({n})</span>' if n else ""

    def _build_requirements(self, requirements: list) -> str:
        if not requirements:
            return '<p style="color:var(--c-muted)">暂无需求定义。</p>'

        items = []
        for i, req in enumerate(requirements, 1):
            name = self._esc(req.get("name", f"Requirement {i}"))
            desc = self._esc(req.get("description", ""))
            ac_list = req.get("acceptance_criteria", [])

            ac_html = ""
            if ac_list:
                ac_items = "\n".join(
                    f'<li>{self._esc(ac)}</li>' for ac in ac_list
                )
                ac_html = (
                    f'<span class="ac-label">验收条件</span>\n'
                    f'<ul class="ac-list">\n{ac_items}\n</ul>\n'
                )

            items.append(
                f'<div class="req-item">\n'
                f'<h3>{i}. {name}</h3>\n'
                f'<div class="req-desc">{desc}</div>\n'
                f'{ac_html}'
                f'</div>'
            )

        return "\n".join(items)

    def _build_user_stories(self, user_stories: list) -> str:
        if not user_stories:
            return '<p style="color:var(--c-muted)">暂无用户故事。</p>'

        items = []
        for story in user_stories:
            role = self._esc(story.get("role", "user"))
            action = self._esc(story.get("action", "do something"))
            goal = self._esc(story.get("goal", ""))
            items.append(
                f'<div class="story-item">\n'
                f'<span class="story-role">{role}</span>\n'
                f'<div class="story-text">\n'
                f'作为 <strong>{role}</strong>，我想要 <strong>{action}</strong>'
                f'<br><span class="goal">以便：{goal}</span>\n'
                f'</div>\n'
                f'</div>'
            )

        return "\n".join(items)

    def _build_priorities(self, priorities: dict) -> str:
        if not priorities:
            return '<p style="color:var(--c-muted)">暂无优先级定义。</p>'

        tags = []
        for item, priority in priorities.items():
            p_lower = priority.strip().lower() if priority else ""
            en = self.PRIORITY_CN.get(priority, priority)
            css_class = "high" if "高" in priority else ("medium" if "中" in priority else "low")
            tags.append(
                f'<span class="priority-tag {css_class}">'
                f'{self._esc(item)} &middot; {self._esc(priority)}'
                f'</span>'
            )

        return f'<div class="priority-grid">\n{"".join(tags)}\n</div>'
