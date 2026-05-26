"""DeepSeek API adapter — text mode via chat completions, agent mode via tool-calling loop."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import glob as _glob
from pathlib import Path

from openai import OpenAI

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage

# ---------------------------------------------------------------------------
# Per-role system prompts (mirrored from claude_code_adapter to avoid circular import)
# ---------------------------------------------------------------------------

ROLE_PROMPTS: dict[str, str] = {
    "pm": (
        "你是 CogniForge 系统的 PM (Product Manager) Agent。\n"
        "职责: 根据用户数据生成产品需求文档 (PRD)。\n\n"
        "## 输出格式\n"
        "必须输出一个 JSON 对象，包含以下顶层字段。\n"
        "所有文字使用中文。requirements 和 user_stories 的 id 使用稳定编号"
        "（REQ-001, REQ-002... 和 US-001, US-002...）。\n"
        "时间戳字段使用 <created_at> 占位符，程序会在落盘时自动替换为实际时间。\n\n"
        "EXAMPLE JSON OUTPUT:\n"
        "```json\n"
        "{\n"
        '  "meta": {\n'
        '    "doc_id": "prd-current",\n'
        '    "type": "prd",\n'
        '    "title": "...",\n'
        '    "author": "pm_agent",\n'
        '    "created": "<created_at>",\n'
        '    "version": 1,\n'
        '    "last_modified": "<created_at>",\n'
        '    "last_author": "pm_agent"\n'
        '  },\n'
        '  "overview": "项目概述文本（3-5句）",\n'
        '  "requirements": [{\n'
        '    "id": "REQ-001",\n'
        '    "name": "需求名",\n'
        '    "description": "描述",\n'
        '    "status": "draft",\n'
        '    "version": 1,\n'
        '    "acceptance_criteria": ["条件1", "条件2"],\n'
        '    "priority": "高/中/低",\n'
        '    "depends_on": [],\n'
        '    "supersedes": [],\n'
        '    "related_user_stories": [],\n'
        '    "change_history": [{\n'
        '      "version": 1,\n'
        '      "change_type": "created",\n'
        '      "summary": "初始创建",\n'
        '      "reason": "首次生成 PRD"\n'
        '    }]\n'
        '  }],\n'
        '  "user_stories": [{\n'
        '    "id": "US-001",\n'
        '    "role": "角色",\n'
        '    "action": "动作",\n'
        '    "goal": "目标",\n'
        '    "related_requirements": []\n'
        '  }],\n'
        '  "priorities": {"REQ-001": "高"}\n'
        '}\n'
        "```"
    ),
    "architect": (
        "你是 CogniForge 系统的 Architect Agent。\n"
        "职责: 根据 PRD 生成系统架构文档 (SAD) JSON。\n\n"
        "## 输出格式\n"
        "必须输出一个 JSON 对象，包含以下顶层字段。\n"
        "所有文字使用中文。时间戳字段使用 <created_at> 占位符，程序会在落盘时自动替换。\n\n"
        "## 重要规则\n"
        "- 每个 component 分配唯一 id（CMP-001, CMP-002...）\n"
        "- 每个 contract 分配唯一 id（CTR-001, CTR-002...）\n"
        "- 每个 data_model 分配唯一 id（DM-001, DM-002...）\n"
        "- components 类型限定: frontend, backend, gateway, service, database, infrastructure\n"
        "- system_overview.roles: 从 PRD 中提取用户角色及其权限\n"
        "- architecture.layers: 按系统分层列出每层包含的组件\n"
        "- architecture.connections: 相邻层之间的通信协议\n"
        "- architecture.features: 列出架构的关键技术特征\n"
        "- tech_stack: 根据架构设计明确定义技术选型\n"
        "- components: 每个组件需要 status/version/source_requirements/change_history\n"
        "- contracts: 每个契约需要 status/version/source_requirements/provider_component_id/errors/change_history\n"
        "- data_models: 每个模型的 fields 必须是对象数组，每个 field 有 name/type/required/description\n"
        "- requirement_traceability: 每个 PRD 需求必须有一条覆盖记录\n\n"
        "EXAMPLE JSON OUTPUT:\n"
        "```json\n"
        "{\n"
        '  "meta": {\n'
        '    "doc_id": "sad-001",\n'
        '    "type": "sad",\n'
        '    "title": "...",\n'
        '    "author": "architect_agent",\n'
        '    "created": "<created_at>",\n'
        '    "version": 1\n'
        '  },\n'
        '  "title": "...",\n'
        '  "source_prd": {"doc_id": "prd-current", "version": 1},\n'
        '  "system_overview": {\n'
        '    "description": "系统整体描述",\n'
        '    "roles": [{"name": "角色名", "permissions": ["权限1"]}]\n'
        '  },\n'
        '  "architecture": {\n'
        '    "style": "微服务架构",\n'
        '    "description": "架构设计描述",\n'
        '    "layers": [{"name": "层名", "components": ["组件名"]}],\n'
        '    "connections": [{"protocol": "REST", "description": "通信说明"}],\n'
        '    "features": ["架构特征"]\n'
        '  },\n'
        '  "tech_stack": {\n'
        '    "backend": {"language": "Python", "framework": "FastAPI"},\n'
        '    "frontend": {"framework": "React", "ui_library": "Ant Design"},\n'
        '    "database": "PostgreSQL"\n'
        '  },\n'
        '  "components": [{\n'
        '    "id": "CMP-001",\n'
        '    "name": "组件名",\n'
        '    "type": "service",\n'
        '    "status": "active",\n'
        '    "version": 1,\n'
        '    "description": "组件描述",\n'
        '    "responsibilities": ["职责1"],\n'
        '    "source_requirements": ["REQ-001"],\n'
        '    "contracts": ["CTR-001"],\n'
        '    "depends_on_components": [],\n'
        '    "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 SAD"}]\n'
        '  }],\n'
        '  "contracts": [{\n'
        '    "id": "CTR-001",\n'
        '    "interface": "接口名称",\n'
        '    "provider_component_id": "CMP-001",\n'
        '    "provider": "提供者组件名",\n'
        '    "consumers": ["消费者组件名"],\n'
        '    "type": "REST",\n'
        '    "status": "active",\n'
        '    "version": 1,\n'
        '    "endpoint": "GET /api/resource",\n'
        '    "request": {"path_params": [], "query_params": [], "body": {}},\n'
        '    "response": {"status": 200, "body": {}},\n'
        '    "errors": [{"status": 404, "code": "NOT_FOUND", "message": "资源不存在"}],\n'
        '    "description": "接口说明",\n'
        '    "source_requirements": ["REQ-001"],\n'
        '    "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 SAD"}]\n'
        '  }],\n'
        '  "data_flow": [{\n'
        '    "name": "数据流名称",\n'
        '    "steps": ["步骤1"]\n'
        '  }],\n'
        '  "data_models": [{\n'
        '    "id": "DM-001",\n'
        '    "name": "模型名",\n'
        '    "description": "数据模型描述",\n'
        '    "source_requirements": ["REQ-001"],\n'
        '    "fields": [{"name": "字段名", "type": "字段类型", "required": false, "description": "字段说明"}]\n'
        '  }],\n'
        '  "requirement_traceability": [{\n'
        '    "requirement_id": "REQ-001",\n'
        '    "coverage": "full",\n'
        '    "components": ["CMP-001"],\n'
        '    "contracts": ["CTR-001"],\n'
        '    "data_models": [],\n'
        '    "notes": ""\n'
        '  }],\n'
        '  "architecture_decisions": [],\n'
        '  "risks": [],\n'
        '  "open_questions": []\n'
        '}\n'
        "```"
    ),
    "design": (
        "你是 CogniForge 系统的 Design (MDE) Agent。\n"
        "职责: 根据 PRD + SAD 生成模块的详细设计文档 (LLD) JSON。\n\n"
        "## 输出格式\n"
        "必须输出一个 JSON 对象，包含以下顶层字段。\n"
        "所有数组字段用 [] 表示，对象字段用 {} 表示，切勿混用。\n\n"
        "EXAMPLE JSON OUTPUT (module_type=service):\n"
        "```json\n"
        "{\n"
        '  "meta": {\n'
        '    "doc_id": "lld-MyService-001",\n'
        '    "type": "lld",\n'
        '    "module_type": "service",\n'
        '    "module": "MyService",\n'
        '    "title": "MyService 详细设计",\n'
        '    "author": "design_agent",\n'
        '    "created": "2025-01-01T00:00:00Z",\n'
        '    "version": 1,\n'
        '    "status": "active"\n'
        '  },\n'
        '  "source": {\n'
        '    "prd": {"doc_id": "prd-current", "version": 1, "requirements": ["REQ-001"]},\n'
        '    "sad": {"doc_id": "sad-001", "version": 1, "components": ["CMP-001"], "contracts": ["CTR-001"], "data_models": []},\n'
        '    "pm_turn_id": "", "se_turn_id": ""\n'
        '  },\n'
        '  "module_boundary": {\n'
        '    "in_scope": ["范围1"],\n'
        '    "out_of_scope": ["不属于本模块的"],\n'
        '    "owned_components": ["CMP-001"],\n'
        '    "owned_contracts": [],\n'
        '    "consumed_contracts": ["CTR-002"],\n'
        '    "owned_data_models": [],\n'
        '    "consumed_data_models": ["DM-001"]\n'
        '  },\n'
        '  "overview": {\n'
        '    "description": "模块概述",\n'
        '    "dependencies": ["依赖的模块名"],\n'
        '    "tech_stack": ["Python 3.12", "FastAPI"]\n'
        '  },\n'
        '  "traceability": [\n'
        '    {\n'
        '      "requirement_id": "REQ-001",\n'
        '      "sad_component_ids": ["CMP-001"],\n'
        '      "sad_contract_ids": ["CTR-001"],\n'
        '      "lld_objects": {"data_models": ["DM-001"], "interfaces": ["IF-001"], "domain_objects": ["DO-001"], "service_contracts": ["SC-001"]},\n'
        '      "coverage": "full",\n'
        '      "notes": ""\n'
        '    }\n'
        '  ],\n'
        '  "data_models": [\n'
        '    {\n'
        '      "id": "DM-001",\n'
        '      "name": "ModelName",\n'
        '      "type": "table",\n'
        '      "status": "active", "version": 1,\n'
        '      "ownership": "canonical",\n'
        '      "description": "数据模型描述",\n'
        '      "fields": [\n'
        '        {"name": "id", "type": "integer", "required": true, "description": "主键"},\n'
        '        {"name": "name", "type": "varchar(255)", "required": true, "description": "名称"}\n'
        '      ],\n'
        '      "indexes": [{"name": "idx_name", "unique": false, "columns": ["name"]}],\n'
        '      "source_requirements": ["REQ-001"],\n'
        '      "source_components": ["CMP-001"],\n'
        '      "source_contracts": [],\n'
        '      "constraints": [],\n'
        '      "lifecycle": {"create": "", "update": "", "delete": "", "retention": ""},\n'
        '      "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 LLD"}]\n'
        '    }\n'
        '  ],\n'
        '  "interfaces": [\n'
        '    {\n'
        '      "id": "IF-001",\n'
        '      "name": "接口名称",\n'
        '      "status": "active", "version": 1,\n'
        '      "source_contract_id": "CTR-001",\n'
        '      "provider_component_id": "CMP-001",\n'
        '      "method": "GET",\n'
        '      "endpoint": "/api/resource",\n'
        '      "description": "接口描述",\n'
        '      "parameters": [\n'
        '        {"name": "id", "type": "integer", "in": "path", "required": true, "description": "资源ID"}\n'
        '      ],\n'
        '      "request_body": {},\n'
        '      "response": {"status": 200, "body": {"id": "integer", "name": "string"}},\n'
        '      "error_codes": [{"status": 404, "code": "NOT_FOUND", "message": "资源不存在"}],\n'
        '      "auth": {"required": false, "policy": ""},\n'
        '      "validation_rules": [],\n'
        '      "idempotency": "not_applicable",\n'
        '      "pagination": "not_applicable",\n'
        '      "source_requirements": ["REQ-001"],\n'
        '      "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 LLD"}]\n'
        '    }\n'
        '  ],\n'
        '  "error_handling": {\n'
        '    "strategy": "统一错误响应格式",\n'
        '    "response_format": {"body": {"code": "integer", "error": "string", "detail": "string"}},\n'
        '    "categories": [\n'
        '      {"code": "4xx", "name": "客户端错误", "description": "请求参数错误等"},\n'
        '      {"code": "5xx", "name": "服务端错误", "description": "内部异常等"}\n'
        '    ]\n'
        '  },\n'
        '  "workflow": {\n'
        '    "name": "流程名",\n'
        '    "description": "流程描述",\n'
        '    "steps": [\n'
        '      {"order": 1, "name": "步骤名", "action": "具体操作", "timeout_seconds": 60, "on_failure": "重试"}\n'
        '    ],\n'
        '    "retry_strategy": {"max_retries": 3, "retry_interval_seconds": 30, "retryable_errors": [], "non_retryable_errors": []}\n'
        '  },\n'
        '  "domain_objects": [\n'
        '    {\n'
        '      "name": "EntityName",\n'
        '      "object_type": "entity",\n'
        '      "description": "实体描述",\n'
        '      "attributes": [\n'
        '        {"name": "id", "type": "integer", "required": true, "source": "db", "description": "主键"}\n'
        '      ]\n'
        '    },\n'
        '    {\n'
        '      "name": "StatusEnum",\n'
        '      "object_type": "enum",\n'
        '      "description": "状态枚举",\n'
        '      "values": ["ACTIVE", "INACTIVE"]\n'
        '    }\n'
        '  ],\n'
        '  "service_contracts": [\n'
        '    {\n'
        '      "name": "MyService",\n'
        '      "description": "服务描述",\n'
        '      "methods": [\n'
        '        {\n'
        '          "name": "methodName",\n'
        '          "signature": "methodName(param: Type) -> ReturnType",\n'
        '          "precondition": "前置条件",\n'
        '          "postcondition": "后置条件",\n'
        '          "description": "方法描述",\n'
        '          "exceptions": [\n'
        '            {"name": "NotFoundError", "trigger": "资源不存在", "http_status": 404}\n'
        '          ]\n'
        '        }\n'
        '      ],\n'
        '      "repository_dependencies": ["findById(id) -> Entity?"]\n'
        '    }\n'
        '  ],\n'
        '  "business_rules": {\n'
        '    "invariants": ["名称必须唯一"],\n'
        '    "state_machines": [],\n'
        '    "cross_service_rules": []\n'
        '  }\n'
        '}\n'
        '```\n\n'
        '## 类型约束（严格遵守）\n'
        '- methods 必须是数组 []，不要用方法名作 key 写成对象 {}\n'
        '- domain_objects 必须是数组 []，不要用 ID 作 key 写成对象 {}\n'
        '- workflow 必须是对象 {}，不要写成数组 []\n'
        '- business_rules 必须是对象 {}，不要写成数组 []\n'
        '- 所有数组元素必须是对象，不能混入裸字符串\n'
        '- 内层对象同理：response.body 的字段必须展开到具体类型，不能写空 {}'
    ),
    "dev": (
        "你是 CogniForge 系统的 Dev Agent。\n"
        "职责: 根据 LLD 编写代码和测试，运行 pytest 验证。"
    ),
    "reviewer": (
        "你是 CogniForge 系统的 Reviewer Agent。\n"
        "职责: 代码评审，生成 CR 报告 JSON。"
    ),
    "qa": (
        "你是 CogniForge 系统的 QA Agent。\n"
        "职责: 生成测试用例 JSON，执行测试，生成报告。"
    ),
    "techlead": (
        "你是 CogniForge 系统的 Tech Lead Agent。\n"
        "职责: 工作分解 (WBS)，质量评估。"
    ),
    "devops": (
        "你是 CogniForge 系统的 DevOps Agent。\n"
        "职责: 生成部署配置 JSON。"
    ),
}

# ---------------------------------------------------------------------------
# Per-role per-phase max_tokens configuration
# Step 1 (thinking): natural-language analysis, enough space for thorough reasoning
# Step 2 (JSON): structured output — PRD can hit ~20 reqs, LLD is most complex
# ---------------------------------------------------------------------------

MAX_TOKENS_CONFIG: dict[str, int] = {
    "pm_think": 16_000,
    "pm_json": 32_000,
    "architect_think": 20_000,
    "architect_json": 40_000,
    "design_think": 24_000,
    "design_json": 64_000,
}

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "读取文件内容。用于查看已有文档、代码或配置文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于项目根目录的文件路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "将内容写入文件。如果文件所在目录不存在会自动创建。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于项目根目录的文件路径"},
                    "content": {"type": "string", "description": "要写入的完整内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "在文件中查找并替换文本。old_string 必须在文件中唯一或首次出现。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于项目根目录的文件路径"},
                    "old_string": {"type": "string", "description": "要替换的原文本"},
                    "new_string": {"type": "string", "description": "替换后的新文本"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "执行 shell 命令。用于运行测试、查看 git 状态、安装依赖等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "按模式搜索文件。支持 ** 递归匹配。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "文件匹配模式，如 **/*.py"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "在文件中搜索文本模式。返回匹配的行及文件名和行号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "要搜索的正则表达式或文本"},
                    "path": {"type": "string", "description": "搜索路径，默认为项目根目录"},
                },
                "required": ["pattern"],
            },
        },
    },
]

# User-friendly tool names for progress display
_TOOL_DISPLAY: dict[str, str] = {
    "Read": "读取文件",
    "Write": "写入文件",
    "Edit": "编辑文件",
    "Bash": "执行命令",
    "Glob": "搜索文件",
    "Grep": "搜索内容",
}

# Dangerous command patterns blocked by _tool_bash
_FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/", r":\s*\(\s*\)\s*\{", r">\s*/dev/sda",
    r"mkfs\.", r"dd\s+if=", r"sudo\s+rm", r"chmod\s+777\s+/",
]


class DeepSeekAdapter(BaseLLMAdapter):
    """Two-mode adapter via DeepSeek HTTP API.

    - **Text mode** (``generate``): chat completions + response_format json_object.
    - **Agent mode** (``generate_agentic``): self-implemented tool-calling loop
      supporting Read / Write / Edit / Bash / Glob / Grep tools.
    """

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        self.model = (
            self.config.get("model")
            or os.environ.get("DEEPSEEK_MODEL", "")
            or "deepseek-v4-pro"
        )
        self.api_key = (
            self.config.get("api_key")
            or os.environ.get("DEEPSEEK_API_KEY", "")
        )
        self.api_base = (
            self.config.get("api_base")
            or os.environ.get("DEEPSEEK_API_BASE", "")
            or "https://api.deepseek.com/v1"
        )
        self.repo_path = Path(self.config.get("repo_path", Path.cwd())).resolve()
        self.max_tokens = int(self.config.get("max_tokens", 4096))
        self.timeout = int(self.config.get("timeout", 600))

        self._client = OpenAI(api_key=self.api_key, base_url=self.api_base)

    def _chat_completion(self, **kwargs) -> object:
        """Wrapper around the API call with error context."""
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            model = kwargs.get("model", self.model)
            raise RuntimeError(
                f"DeepSeek API 调用失败 (model={model}): {e}\n"
                f"请检查 API Key 是否有效、网络是否可达、账户余额是否充足。"
            ) from e
        if response is None:
            raise RuntimeError("DeepSeek API 返回空响应，请重试")
        if not getattr(response, "choices", None):
            raise RuntimeError(
                f"DeepSeek API 响应缺少 choices 字段，可能是模型不支持或请求格式错误。"
                f"响应: {str(response)[:300]}"
            )
        return response

    # ------------------------------------------------------------------
    # Text mode
    # ------------------------------------------------------------------

    # DeepSeek JSON mode requires non-thinking for reliable structured output
    # See: https://api-docs.deepseek.com/zh-cn/guides/json_mode
    _JSON_KWARGS = {
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "disabled"}},
    }

    def generate(
        self, prompt: str, context: dict = None, **kwargs
    ) -> LLMResponse:
        full_prompt = self._build_prompt(prompt, context)
        model = kwargs.pop("model", self.model)
        response = self._chat_completion(
            model=model,
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=kwargs.pop("max_tokens", self.max_tokens),
            timeout=self.timeout,
            **self._JSON_KWARGS,
        )
        return self._to_llm_response(response)

    def generate_messages(
        self, messages: list[LLMMessage], **kwargs
    ) -> LLMResponse:
        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        model = kwargs.pop("model", self.model)
        response = self._chat_completion(
            model=model,
            messages=api_messages,
            max_tokens=kwargs.pop("max_tokens", self.max_tokens),
            timeout=self.timeout,
            **self._JSON_KWARGS,
        )
        return self._to_llm_response(response)

    # ------------------------------------------------------------------
    # Two-step generation: think first → format JSON
    # Step 1: thinking enabled, free-form analysis
    # Step 2: thinking disabled + JSON mode, structured output
    # See: https://api-docs.deepseek.com/zh-cn/guides/multi_round_chat
    # ------------------------------------------------------------------

    def generate_think_then_json(
        self,
        prompt: str,
        *,
        role: str | None = None,
        progress_callback: callable | None = None,
        **kwargs,
    ) -> LLMResponse:
        model = kwargs.pop("model", self.model)

        # Per-role per-phase token budget: explicit override > config > default
        caller_max_tokens = kwargs.pop("max_tokens", None)
        if caller_max_tokens is not None:
            think_tokens = json_tokens = caller_max_tokens
        elif role and f"{role}_think" in MAX_TOKENS_CONFIG:
            think_tokens = MAX_TOKENS_CONFIG[f"{role}_think"]
            json_tokens = MAX_TOKENS_CONFIG[f"{role}_json"]
        else:
            think_tokens = json_tokens = self.max_tokens

        # Step 1: build messages with thinking instruction
        if progress_callback:
            progress_callback("LLM 分析中")
        think_prompt = prompt + "\n\n请先深入分析思考，输出详细的设计方案。用自然语言描述，不要输出 JSON。"
        messages = self._build_agentic_messages(think_prompt, role)

        t1_start = time.time()
        resp1 = self._chat_completion(
            model=model,
            messages=messages,
            max_tokens=think_tokens,
            timeout=self.timeout,
            extra_body={"thinking": {"type": "enabled"}},
        )
        t1 = time.time() - t1_start
        content1 = resp1.choices[0].message.content or ""

        # Step 2: append thinking result + JSON formatting instruction
        if progress_callback:
            progress_callback("LLM 生成 JSON")
        messages.append({"role": "assistant", "content": content1})
        messages.append({
            "role": "user",
            "content": (
                "请将上述分析结果整理为指定的 JSON 结构输出。\n"
                "只返回纯 JSON 对象，不要 markdown 代码块包裹，不要任何解释文字。"
            ),
        })

        t2_start = time.time()
        resp2 = self._chat_completion(
            model=model,
            messages=messages,
            max_tokens=json_tokens,
            timeout=self.timeout,
            **self._JSON_KWARGS,
        )
        t2 = time.time() - t2_start
        label = {"pm": "PM", "architect": "架构", "design": "设计"}.get(role, role.upper() if role else "LLM")
        result = self._to_llm_response(resp2)
        result.timings = [
            {"phase": f"{label}分析", "duration_s": round(t1, 1)},
            {"phase": f"{label}生成", "duration_s": round(t2, 1)},
        ]
        return result

    # ------------------------------------------------------------------
    # Agent mode — tool-calling loop
    # ------------------------------------------------------------------

    def generate_agentic(
        self,
        prompt: str,
        *,
        role: str | None = None,
        tools: list[dict] | None = None,
        max_turns: int = 20,
        progress_callback: callable = None,
        **kwargs,
    ) -> LLMResponse:
        messages = self._build_agentic_messages(prompt, role)
        tool_defs = tools or TOOL_DEFINITIONS
        model = kwargs.get("model", self.model)
        cb = progress_callback

        for _turn in range(max_turns):
            if cb and _turn == 0:
                cb("正在分析需求...")
            response = self._chat_completion(
                model=model,
                messages=messages,
                tools=tool_defs,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                timeout=self.timeout,
            )
            choice = response.choices[0]
            msg = choice.message

            # No tool calls → final response
            if not msg.tool_calls:
                if cb:
                    cb("正在生成最终回复...")
                return LLMResponse(
                    content=msg.content or "",
                    model=self.model,
                    provider="deepseek",
                    usage=self._extract_usage(response),
                )

            # Append assistant message with tool_calls, preserving any
            # extra fields (e.g. reasoning_content for DeepSeek thinking mode)
            assistant_msg: dict = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
            for field in ("reasoning_content",):
                val = getattr(msg, field, None)
                if val:
                    assistant_msg[field] = val
            messages.append(assistant_msg)

            # Execute each tool call
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                file_hint = args.get("path", args.get("pattern",
                             args.get("command", "")))
                display = _TOOL_DISPLAY.get(name, name)
                if file_hint:
                    # Truncate long command/pattern strings
                    short = file_hint if len(file_hint) <= 60 else file_hint[:57] + "..."
                    display = f"{display}: {short}"
                if cb:
                    cb(display)
                try:
                    result = self._execute_tool(name, tc.function.arguments)
                    result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                except Exception as exc:
                    result_str = f"Error: {exc}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Reached max_turns
        return LLMResponse(
            content="(reached max turns without final response)",
            model=self.model,
            provider="deepseek",
            usage={},
        )

    def _build_agentic_messages(self, prompt: str, role: str | None) -> list[dict]:
        messages: list[dict] = []
        system_parts: list[str] = []

        if role and role in ROLE_PROMPTS:
            system_parts.append(ROLE_PROMPTS[role])

        constraint_loader = self.config.get("constraint_loader")
        if constraint_loader and role:
            constraints = constraint_loader.load(role)
            if constraints:
                system_parts.append(f"# 约束\n{constraints}")

        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        full_prompt = prompt + f"\n\n工作目录: {self.repo_path}\n完成后用中文回复。"
        messages.append({"role": "user", "content": full_prompt})
        return messages

    # ------------------------------------------------------------------
    # Interactive modification
    # ------------------------------------------------------------------

    def generate_interactive(
        self,
        current_document: str,
        user_request: str,
        system_prompt: str = "",
        **kwargs,
    ) -> LLMResponse:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": (
                f"当前文档 JSON:\n{current_document}\n\n"
                f"用户修改要求: {user_request}\n\n"
                f"请根据用户要求修改文档，返回完整的修改后 JSON。\n"
                f"只返回纯 JSON，不要 markdown 代码块包裹，不要多余解释文字。"
            ),
        })
        model = kwargs.pop("model", self.model)
        response = self._chat_completion(
            model=model,
            messages=messages,
            max_tokens=kwargs.pop("max_tokens", self.max_tokens),
            timeout=self.timeout,
            **self._JSON_KWARGS,
        )
        return self._to_llm_response(response)

    def generate_interactive_patch(
        self,
        current_document: str,
        user_request: str,
        system_prompt: str = "",
        turn_schema: dict | None = None,
        role: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Two-step interactive modification producing a structured turn result.

        Step 1 (thinking enabled): analyzes the current document and user request.
        Step 2 (thinking disabled, JSON mode): outputs the turn-result structure
        with patches array.
        """
        model = kwargs.pop("model", self.model)
        max_toks = kwargs.pop("max_tokens", self.max_tokens)

        schema_desc = json.dumps(turn_schema, ensure_ascii=False, indent=2) if turn_schema else ""

        think_prompt = (
            f"当前文档 JSON:\n{current_document}\n\n"
            f"用户修改要求: {user_request}\n\n"
            f"请先分析当前文档结构，确认需要修改的条目、变更类型。\n"
            f"思考需要应用哪些 JSON Patch 操作（add/replace/remove）。\n"
            f"注意路径格式为 JSON Pointer（如 /components/0/name）。\n"
            f"输出你的分析，不要输出 JSON。"
        )

        messages: list[dict] = []
        system_parts: list[str] = []
        if system_prompt:
            system_parts.append(system_prompt)
        constraint_loader = self.config.get("constraint_loader")
        if constraint_loader and role:
            constraints = constraint_loader.load(role)
            if constraints:
                system_parts.append(f"# 约束\n{constraints}")
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        messages.append({"role": "user", "content": think_prompt})

        # Step 1: thinking
        t1_start = time.time()
        resp1 = self._chat_completion(
            model=model,
            messages=messages,
            max_tokens=max_toks,
            timeout=self.timeout,
            extra_body={"thinking": {"type": "enabled"}},
        )
        t1 = time.time() - t1_start
        content1 = resp1.choices[0].message.content or ""

        # Step 2: structured output
        messages.append({"role": "assistant", "content": content1})
        schema_block = (
            f"\n\n输出 JSON Schema:\n{schema_desc}\n\n" if schema_desc else ""
        )
        messages.append({
            "role": "user",
            "content": (
                f"请将上述分析结果整理为以下结构的 JSON 输出。\n"
                f"{schema_block}"
                f"只返回纯 JSON 对象，不要 markdown 代码块，不要任何解释文字。"
            ),
        })

        t2_start = time.time()
        resp2 = self._chat_completion(
            model=model,
            messages=messages,
            max_tokens=max_toks,
            timeout=self.timeout,
            **self._JSON_KWARGS,
        )
        t2 = time.time() - t2_start
        result = self._to_llm_response(resp2)
        result.timings = [
            {"phase": "PM分析", "duration_s": round(t1, 1)},
            {"phase": "PM生成", "duration_s": round(t2, 1)},
        ]
        return result

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, args_json: str) -> str:
        args = json.loads(args_json)
        tool_map = {
            "Read": self._tool_read,
            "Write": self._tool_write,
            "Edit": self._tool_edit,
            "Bash": self._tool_bash,
            "Glob": self._tool_glob,
            "Grep": self._tool_grep,
        }
        fn = tool_map.get(name)
        if fn is None:
            return f"Unknown tool: {name}"
        return fn(**args)

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.repo_path / p
        p = p.resolve()
        if not str(p).startswith(str(self.repo_path)):
            raise PermissionError(f"路径超出项目范围: {path}")
        return p

    def _tool_read(self, path: str) -> str:
        full = self._resolve_path(path)
        if not full.exists():
            return f"Error: 文件不存在: {path}"
        return full.read_text(encoding="utf-8")

    def _tool_write(self, path: str, content: str) -> str:
        full = self._resolve_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return f"已写入: {path}"

    def _tool_edit(self, path: str, old_string: str, new_string: str) -> str:
        full = self._resolve_path(path)
        if not full.exists():
            return f"Error: 文件不存在: {path}"
        content = full.read_text(encoding="utf-8")
        if old_string not in content:
            return f"Error: 在 {path} 中未找到指定文本"
        content = content.replace(old_string, new_string, 1)
        full.write_text(content, encoding="utf-8")
        return f"已编辑: {path}"

    def _tool_bash(self, command: str) -> str:
        for pat in _FORBIDDEN_PATTERNS:
            if re.search(pat, command):
                return f"Error: 命令被安全策略拦截: {command[:80]}"
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["cmd", "/c", command],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(self.repo_path),
                )
            else:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=30, cwd=str(self.repo_path),
                )
        except subprocess.TimeoutExpired:
            return "Error: 命令执行超时 (30s)"
        output = (result.stdout or "") + (result.stderr or "")
        if len(output) > 10000:
            output = output[:10000] + "\n... (输出已截断)"
        return output or "(无输出)"

    def _tool_glob(self, pattern: str) -> str:
        matches = _glob.glob(pattern, root_dir=str(self.repo_path), recursive=True)
        if not matches:
            return "(无匹配文件)"
        return json.dumps(sorted(matches), ensure_ascii=False, indent=2)

    def _tool_grep(self, pattern: str, path: str = ".") -> str:
        search_path = self._resolve_path(path)
        try:
            result = subprocess.run(
                ["grep", "-rn", pattern, str(search_path)],
                capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            # Fallback: Python implementation for Windows
            return self._grep_python(pattern, search_path)
        except subprocess.TimeoutExpired:
            return "Error: 搜索超时 (10s)"
        output = result.stdout
        if len(output) > 10000:
            output = output[:10000] + "\n... (输出已截断)"
        return output or "(无匹配)"

    @staticmethod
    def _grep_python(pattern: str, search_path: Path) -> str:
        lines: list[str] = []
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = re.compile(re.escape(pattern))
        for f in search_path.rglob("*"):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(search_path)
                    lines.append(f"{rel}:{lineno}:{line.rstrip()}")
        if len(lines) > 200:
            lines = lines[:200]
            lines.append("... (结果已截断)")
        return "\n".join(lines) if lines else "(无匹配)"

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        if not context:
            return prompt
        parts = ["# Context"]
        for k, v in context.items():
            if isinstance(v, dict):
                parts.append(f"\n## {k}")
                for kv, vv in v.items():
                    parts.append(f"- {kv}: {vv}")
            elif isinstance(v, list):
                parts.append(f"\n## {k}")
                for item in v:
                    parts.append(f"- {item}")
            else:
                parts.append(f"- {k}: {v}")
        parts.append(f"\n# Prompt\n{prompt}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _to_llm_response(self, response) -> LLMResponse:
        choice = response.choices[0]
        content = choice.message.content or ""
        return LLMResponse(
            content=content,
            model=self.model,
            provider="deepseek",
            usage=self._extract_usage(response),
        )

    @staticmethod
    def _extract_usage(response) -> dict:
        if response.usage is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return {
            "input_tokens": response.usage.prompt_tokens or 0,
            "output_tokens": response.usage.completion_tokens or 0,
            "total_tokens": (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0),
        }

    # ------------------------------------------------------------------
    # Provider metadata
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def supported_models(self) -> list[str]:
        return ["deepseek-v4-pro", "deepseek-v4", "deepseek-chat", "deepseek-reasoner"]
