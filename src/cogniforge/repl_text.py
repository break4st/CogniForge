"""REPL 显示文本与 Agent schema 描述 — 全中文，独立配置。"""

# ═══════════════════════════════════════════════════════════════════════════
# Agent schema — 发给 LLM 的字段说明（中文，便于 LLM 理解）
# ═══════════════════════════════════════════════════════════════════════════

AGENT_SCHEMAS: dict[str, dict] = {
    "prd": {
        "agent": "pm",
        "hint": "项目名称、概述、功能需求、用户故事、优先级",
        "fields": (
            "title（项目名称）, overview（项目概述）, "
            "requirements: [{name（需求名称）, description（需求描述）, acceptance_criteria: [string（验收条件）]}], "
            "user_stories: [{role（角色）, action（想要做的事）, goal（达成的目标）}], "
            "priorities: {需求名称: 优先级（高/中/低）}"
        ),
    },
    "sad": {
        "agent": "architect",
        "hint": "系统概述、架构描述、组件列表、拓扑结构、数据流",
        "fields": (
            "title, system_overview（系统概述）, architecture（架构描述）, "
            "components: [{name, type（service/db/cache/mq等）, description, responsibilities: [string]}], "
            "topology（拓扑描述）, data_flow（数据流描述）"
        ),
    },
    "lld": {
        "agent": "design",
        "hint": "模块名、数据模型、接口定义、错误处理策略",
        "fields": (
            "module（模块名）, title, overview, "
            "data_models: [{name, type, fields: [{name, type, description}]}], "
            "interfaces: [{name, endpoint, description, parameters: [{name, type, description}]}], "
            "error_handling（错误处理策略）"
        ),
    },
    "wbs": {
        "agent": "techlead",
        "hint": "模块名、任务列表（含名称、描述、依赖、优先级、执行人）",
        "fields": (
            "module, action='create_wbs', "
            "tasks: [{name, description, deps: [依赖任务名], priority（0=阻塞 1=高 2=中 3=低）, assignee（执行人）}]"
        ),
    },
    "coding": {
        "agent": "dev",
        "hint": "模块名、要生成的代码（可选，为空则由 agent 自动生成）",
        "fields": "module（模块名）, code（可选，要写入的代码，为空则由 agent 生成）",
    },
    "code_review": {
        "agent": "reviewer",
        "hint": "模块名、要评审的文件列表",
        "fields": "module, files: [文件路径列表], cr_report（可选，评审报告内容）",
    },
    "test": {
        "agent": "qa",
        "hint": "测试动作（生成/执行/报告）、模块名、测试用例",
        "fields": (
            "action（generate_tests | execute_tests | report）, module, "
            "test_cases: [{name, type, priority, description, steps: [string], expected_result}]"
        ),
    },
    "fix": {
        "agent": "dev",
        "hint": "模块名、修复后的代码",
        "fields": "module, code（修复后的代码）",
    },
    "uat": {
        "agent": "devops",
        "hint": "部署动作（准备/部署/回滚）、模块、环境、版本号",
        "fields": (
            "action（prepare_deploy | deploy | rollback）, module, "
            "environment（dev | staging | prod）, version（回滚时需要）"
        ),
    },
}

# 纯评审步骤（无 agent 执行）
REVIEW_STEPS: set[str] = {"req_review", "arch_review", "design_review", "retro"}

# ═══════════════════════════════════════════════════════════════════════════
# 启动 / 恢复 / 退出
# ═══════════════════════════════════════════════════════════════════════════

WELCOME_LINE_1 = "  CogniForge REPL"
WELCOME_LINE_2 = "  当前步骤: {step_label}"
WELCOME_LINE_3 = "  输入 /help 查看命令，/quit 退出"

WORKFLOW_COMPLETE = "  ✓ 工作流已完成。输入 /quit 退出。"

PAUSE_MESSAGE = """\

  REPL 已暂停。运行 'cogniforge repl' 可随时恢复。
  当前步骤: {step_label}"""

QUIT_MESSAGE = "  再见。运行 'cogniforge repl' 即可恢复（当前: {step_label}）。"

# ═══════════════════════════════════════════════════════════════════════════
# 加载动画文字
# ═══════════════════════════════════════════════════════════════════════════

SPINNER_INTERPRETING = "正在理解你的意图"
SPINNER_RUNNING = "正在运行 {agent} agent (Claude Code 执行中)"

# ═══════════════════════════════════════════════════════════════════════════
# 审批交互
# ═══════════════════════════════════════════════════════════════════════════

CHOICE_APPROVE = "审批通过，进入下一步"
CHOICE_REJECT = "拒绝，返回修改"
CHOICE_RETRY = "提出修改意见，在上一版基础上修改"
APPROVE_CONFIRM = "  确认审批通过？"

REJECT_PROMPT = "  拒绝原因"
REJECT_DEFAULT = "需要改进"

# ═══════════════════════════════════════════════════════════════════════════
# SAD / 架构设计 — 选择自己描述还是 Agent 自主设计
# ═══════════════════════════════════════════════════════════════════════════

SAD_CHOICE_TITLE = "SAD（architect agent）— 选择架构设计方式"
SAD_CHOICE_AUTO = "让 Agent 基于 PRD 自主设计架构"
SAD_CHOICE_MANUAL = "我自己描述架构设计"
SAD_AUTO_PROMPT = "基于已批准的 PRD 文档，自动设计系统架构方案，包括组件划分、拓扑结构和数据流设计。不需要反问用户。"

LLD_CHOICE_TITLE = "LLD（design agent）— 选择详细设计方式"
LLD_CHOICE_AUTO = "让 Agent 基于 SAD 自主设计模块详情"
LLD_CHOICE_MANUAL = "我自己描述模块设计"
LLD_AUTO_PROMPT = "基于已批准的 PRD 和 SAD 文档，自动设计模块详细方案，包括数据模型、接口定义和错误处理策略。不需要反问用户。"

# Multi-module LLD
LLD_MODULES_FOUND = "  SAD 定义了 {count} 个模块: {modules}"
LLD_AUTO_ALL_CHOICE = "让 Agent 自动生成全部 {count} 个模块的 LLD"
LLD_PROGRESS = "正在生成 LLD: {module}"

WBS_CHOICE_TITLE = "WBS（techlead agent）— 选择任务分解方式"
WBS_CHOICE_AUTO = "让 Agent 基于已有设计文档自主分解任务"
WBS_CHOICE_MANUAL = "我自己描述任务分解"
WBS_AUTO_PROMPT = "基于已批准的 PRD、SAD 和 LLD 文档，自动分解工作包，包括任务依赖关系和优先级。不需要反问用户。"

# Mapping: step -> (title, auto_label, manual_label, auto_prompt)
DESIGN_STEP_CHOICES: dict[str, tuple[str, str, str, str]] = {
    "sad": (SAD_CHOICE_TITLE, SAD_CHOICE_AUTO, SAD_CHOICE_MANUAL, SAD_AUTO_PROMPT),
    "lld": (LLD_CHOICE_TITLE, LLD_CHOICE_AUTO, LLD_CHOICE_MANUAL, LLD_AUTO_PROMPT),
    "wbs": (WBS_CHOICE_TITLE, WBS_CHOICE_AUTO, WBS_CHOICE_MANUAL, WBS_AUTO_PROMPT),
}

# ═══════════════════════════════════════════════════════════════════════════
# 结果文字
# ═══════════════════════════════════════════════════════════════════════════

AGENT_NO_ROLE = "  未找到对应 agent: {role}"
AGENT_EXEC_ERROR = "  执行失败: {error}"

APPROVE_OK = "  ✓ 已审批: {step}"
APPROVE_NEXT = "  → 下一步: {step_label}"
APPROVE_DONE = "  工作流已完成！"

REJECT_OK = "  ✗ 已拒绝: {step}"
REJECT_REASON = "  原因: {reason}"
REJECT_HINT = "  停留在当前步骤，请描述需要修改的地方。"

NO_STEP_APPROVE = "  当前没有可审批的步骤。"
NO_STEP_REJECT = "  当前没有可拒绝的步骤。"

UNKNOWN_ACTION = "  未知操作: {action}"

# ═══════════════════════════════════════════════════════════════════════════
# 斜杠命令
# ═══════════════════════════════════════════════════════════════════════════

HELP_TEXT = """\
  命令列表:
    /status   查看工作流状态
    /steps    列出所有步骤及进度
    /skip     跳过当前步骤（审批 + 前进）
    /clear    重置工作流到起点
    /help     显示此帮助
    /quit     退出 REPL

  直接输入自然语言即可创建文档、审批等。"""

SKIP_OK = "  已跳过: {step}"
SKIP_NEXT = "  → 下一步: {step_label}"

CLEAR_OK = "  工作流已重置到初始状态。"
CLEAR_CURRENT = "  当前步骤: {step_label}"

UNKNOWN_CMD = "  未知命令: {cmd}。输入 /help 查看帮助。"

# ═══════════════════════════════════════════════════════════════════════════
# 状态显示
# ═══════════════════════════════════════════════════════════════════════════

STATUS_WORKFLOW = "  工作流: {workflow_id}"
STATUS_STARTED = "  已启动: {started}"
STATUS_STEP = "  当前步骤: {step}"
STATUS_AWAITING = "  等待审批: {awaiting}"
STATUS_COMPLETED = "  已完成步骤: {completed}"
STATUS_TASKS = "  任务: {total} 总计, {pending} 待处理, {done} 已完成, {failed} 失败"

# ═══════════════════════════════════════════════════════════════════════════
# LLM prompt 模板（发给 LLM 的指令文本）
# ═══════════════════════════════════════════════════════════════════════════

PROMPT_REVIEW = (
    "用户当前在审批步骤 '{step_value}'。"
    "判断用户意图，返回 JSON:\n\n"
    '  {{"action": "approve"}}  — 用户想审批通过\n'
    '  {{"action": "reject", "comment": "拒绝原因"}}  — 用户想拒绝\n'
    '  {{"action": "respond", "message": "..."}}  — 不清楚，需要追问\n\n'
    '用户说: "{user_input}"\n\n'
    "只返回合法 JSON。不要 markdown。不要多余文字。"
)

PROMPT_AGENT = (
    "当前工作流步骤: {step_value}\n"
    "要运行的 agent: {agent_name}\n"
    "需要的 JSON 字段: {fields}\n\n"
    '返回 JSON: {{"action": "run_agent", "agent": "{agent_name}", '
    '"input": {{...从用户消息中提取字段...}} }}\n'
    '如果用户想审批通过: {{"action": "approve"}}\n'
    '如果用户想拒绝: {{"action": "reject", "comment": "原因"}}\n'
    '如果信息严重不足无法做任何提取: {{"action": "respond", "message": "追问内容"}}\n\n'
    '用户说: "{user_input}"\n\n'
    "只返回合法 JSON。不要 markdown。不要多余文字。"
)

# PRD step: aggressive extraction — fill what you can, ask only when truly empty
PROMPT_AGENT_PRD = (
    "当前工作流步骤: prd\n"
    "要运行的 agent: pm\n"
    "需要的 JSON 字段: {fields}\n\n"
    "从用户消息中提取所有可用的 PRD 信息。尽力填充每个字段，即使信息不完整。\n"
    "不要反问用户、不要列清单追问。能从用户话里推理出来的就填上。\n\n"
    '信息充足时返回: {{"action": "run_agent", "agent": "pm", '
    '"input": {{title, overview, requirements: [{{name, description, acceptance_criteria}}], '
    'user_stories: [{{role, action, goal}}], priorities}} }}\n'
    '信息严重不足时（用户消息完全不含项目内容）才返回: '
    '{{"action": "respond", "message": "请描述一下项目"}}\n\n'
    '用户说: "{user_input}"\n\n'
    "只返回合法 JSON。不要 markdown。不要多余文字。"
)

PROMPT_RETRY_SUFFIX = "\n\n重要: 只返回合法 JSON。不要 markdown。不要多余文字。"

# ═══════════════════════════════════════════════════════════════════════════
# 解析错误
# ═══════════════════════════════════════════════════════════════════════════

PARSE_RETRY = "  （LLM 返回结果无法解析，正在重试……）"
PARSE_FAIL = "  无法解析 LLM 输出: {raw}..."
INTERPRET_FAIL = "  理解你的输入时出错: {error}"
