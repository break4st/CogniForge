# CogniForge 设计文档

## 版本

```
Version: 1.0
Author: System Design
Scope: OpenX + Document-Driven + Multi-Agent Dev System
```

---

# 一、系统概述

## 1.1 背景

传统 AI Coding 存在问题：

* 上下文不可控（依赖 RAG）
* 长周期开发不稳定
* 无流程约束（vibe coding）
* 无法对齐企业研发体系

本系统目标：

```
构建一个"可持续运行"的 AI 软件开发系统
```

---

## 1.2 核心目标

系统具备：

```
PRD → 架构 → 设计 → 代码 → 测试 → 上线 → 复盘
```

全流程自动化能力。

---

## 1.3 核心原则

### 1️⃣ 文档即状态（Document as State）

```
所有系统状态必须持久化为结构化文档（Git）
```

---

### 2️⃣ 无 RAG（Deterministic Context）

```
上下文由规则加载，而非语义检索
```

---

### 3️⃣ 多 Agent 协作

```
每个 Agent 只做一件事
```

---

### 4️⃣ DAG 驱动流程

```
系统执行必须遵循明确流程图
```

---

### 5️⃣ 人工审批（Human-in-the-Loop）

```
每个阶段必须人工审批，系统不能连续黑盒执行
```

**关键约束**：
- 每个 DAG 步骤执行后必须等待人工审批
- 人工审批通过后才能进入下一步骤
- 人工可以批准、拒绝或要求返工
- 系统在审批点暂停，不会自动连续执行

---

### 6️⃣ 可审核（Reviewability）

```
所有 AI 输出必须可被人工审查
```

**关键要求**：
- 所有 AI 产物必须记录输入、输出、推理过程
- 每个操作生成审计日志条目
- 审计日志包含：操作者、操作类型、输入、输出、耗时、状态
- 所有产物必须经过人工审核才能认为完成

---

# 二、系统架构

## 2.1 分层架构

```
┌──────────────────────────────┐
│ Orchestration Layer (OpenX)  │
├──────────────────────────────┤
│ Agent Layer                  │
├──────────────────────────────┤
│ Context Layer (Docs/Wiki)    │
├──────────────────────────────┤
│ Execution Layer              │
├──────────────────────────────┤
│ Storage Layer (Git FS)       │
└──────────────────────────────┘
```

---

## 2.2 核心组件

| 组件             | 作用    |
| -------------- | ----- |
| OpenX Workflow | 流程编排  |
| Agent System   | 多角色执行 |
| Wiki System    | 知识存储  |
| Context Loader | 上下文加载 |
| Task Engine    | 任务调度  |
| Git            | 持久化   |

---

# 三、角色与 Agent 设计

## 3.1 角色映射

| 角色       | Agent           | 职责    |
| -------- | --------------- | ----- |
| PM       | pm_agent        | PRD   |
| SE       | architect_agent | SAD   |
| MDE      | design_agent    | LLD   |
| TL       | tech_lead_agent | 调度/决策 |
| Dev      | dev_agent       | 编码    |
| Reviewer | review_agent    | CR    |
| QA       | qa_agent        | 测试    |
| DevOps   | devops_agent    | 部署    |

---

## 3.2 Agent 设计原则

```
- 单一职责
- 输入输出明确
- 必须读写文档
- 不允许跨职责修改
```

---

# 四、开发流程（DAG）

## 4.1 流程阶段

```
需求 → 架构 → 设计 → 实现 → 验证 → 交付
```

---

## 4.2 DAG 定义

```
PRD → REQ_REVIEW → SAD → ARCH_REVIEW → LLD → DES_REVIEW
→ WBS → CODING → CR → TEST → FIX → UAT → RETRO
```

---

## 4.3 OpenX Workflow

```yaml
steps:

  - prd
  - req_review
  - sad
  - arch_review
  - lld
  - design_review
  - wbs
  - coding
  - code_review
  - test
  - fix
  - uat
  - retro
```

---

# 五、文档系统（核心）

## 5.1 目录结构

```
wiki/

  prd/
    prd.md

  sad/
    system.md
    topology.md

  lld/
    modules/

  decisions/
    ADR-001.md

  tasks/
    tasks.json

  qa/
    test_cases.md

  reports/
    cr.md
    test.md

  ops/
    deploy.md
```

---

## 5.2 文档约束

每个 Agent 必须：

```
读取 → 修改 → 持久化
```

---

## 5.3 ADR（关键）

```
所有架构决策必须记录
```

---

# 六、Context System（无RAG）

## 6.1 Context 加载规则

```python
context = [
  "wiki/prd/prd.md",
  "wiki/sad/*.md",
  "wiki/lld/*.md",
  "wiki/decisions/*.md",
  "task.md",
  "related_code"
]
```

---

## 6.2 加载策略

```
全局 → 模块 → 任务 → 代码
```

---

## 6.3 模块路由

```
task → module → 加载对应路径
```

---

# 七、任务系统

## 7.1 Task 定义

```json
{
  "id": "001",
  "name": "create_user",
  "deps": [],
  "module": "user"
}
```

---

## 7.2 Task DAG

```
任务之间必须存在依赖关系
```

---

## 7.3 调度策略

```
可并行任务 → 并行执行
有依赖 → 顺序执行
```

---

# 八、Agent 实现设计

## 8.1 Dev Agent

```python
class DevAgent:

    def run(self, task):
        context = load_context(task)

        code = llm.generate(context)

        write_code(code)

        return run_tests()
```

---

## 8.2 QA Agent

```python
class QAAgent:

    def run(self):
        generate_tests()
        execute_tests()
```

---

## 8.3 Review Agent

```python
class ReviewAgent:

    def run(self):
        return generate_cr_report()
```

---

## 8.4 TL Agent（核心）

```python
class TechLeadAgent:

    def run(self, stage):
        control_flow()
        evaluate_quality()
        decide_next_step()
```

---

# 九、执行引擎（人工审批模式）

## 9.1 步进式执行

```
每个步骤执行后暂停，等待人工审批

步骤:
    1. 执行当前步骤任务
    2. 暂停等待人工审批
    3. 人工审批(approve/reject)
    4. 审批通过则进入下一步
    5. 重复1-4
```

**关键特性**：
- 永远不会自动连续执行多个步骤
- 每个步骤必须有明确的审批记录
- 拒绝(REJECT)需要返工后重新审批

---

## 9.2 并行执行

```
Worker Pool（N个 Dev Agent）
```

注意：并行执行仅用于同一阶段内可并行的任务，阶段之间必须串行并审批

---

## 9.3 CLI 审批命令

```bash
cogniforge status     # 查看当前状态和待审批项
cogniforge start      # 启动工作流
cogniforge approve    # 审批当前步骤
cogniforge reject     # 拒绝当前步骤
cogniforge advance    # 进入下一步骤
cogniforge agent <role>  # 执行指定Agent
cogniforge wait       # 等待人工确认
cogniforge history    # 查看完整操作历史
```

---

## 9.4 状态持久化和中断恢复

工作流状态持久化到 `.cogniforge/workflow_state.json`

**持久化内容**：
- 当前步骤
- 审批状态（已批准/已拒绝/待审批）
- 审批人、审批时间、审批备注
- 所有步骤的执行结果
- 完整操作历史

**中断恢复**：
```
# 中断后，重新运行
cogniforge status     # 查看中断时的状态
cogniforge start      # 自动从上次状态恢复
cogniforge history    # 查看中断前的操作记录
```

**状态文件结构**：
```json
{
  "workflow_id": "wf-20240101120000",
  "current_step": "coding",
  "awaiting_approval": true,
  "approval_records": {
    "prd": {"status": "approved", "approver": "human", "comment": "同意", "timestamp": "..."},
    "req_review": {"status": "approved", ...},
    ...
  },
  "history": [
    {"action": "start", "timestamp": "...", "details": {...}},
    {"action": "approve", "timestamp": "...", "details": {...}},
    ...
  ]
}
```

---

# 十、审计系统

## 10.1 设计目标

**所有 AI 输出必须可被人工审查和追溯**

## 10.2 审计日志结构

```json
{
  "agent_role": "dev",
  "operation": "generate_code",
  "timestamp": "2024-01-01T10:00:00",
  "input_context": {
    "task_id": "user-001",
    "module": "user"
  },
  "input_prompt": "...",
  "output_artifacts": ["src/user/user_service.py"],
  "output_summary": "Generated user service with CRUD operations",
  "reasoning": "Based on LLD specification...",
  "decisions": ["Created UserService class", "Added CRUD methods"],
  "duration_ms": 1500,
  "status": "success",
  "reviewed": false,
  "reviewer": "",
  "review_comment": ""
}
```

## 10.3 审计日志存储

```
wiki/reports/audit/
    20240101_100000_dev_generate_code.json
    20240101_100500_qa_write_tests.json
    ...
    review_report.md  # 汇总报告
```

## 10.4 CLI 审计命令

```bash
cogniforge audit            # 查看审计日志
cogniforge review <index>   # 审核指定条目
cogniforge audit_report     # 生成审核报告
cogniforge pending_reviews  # 查看待审核项
```

## 10.5 审核流程

```
Agent 执行 → 生成审计日志 → 人工审核 → 标记已审核/拒绝

所有产物必须经过审核才能认为完成
```

---

# 十一、Git 持久化

## 11.1 所有操作必须提交

```
code + docs + reports
```

---

## 11.2 提交规范

```
feat: task-001 user entity
fix: bug-002
docs: update ADR
```

---

# 十二、质量控制

## 12.1 人工审批门禁

每个阶段都有人工审批点：

| 阶段 | 审批内容 |
|------|----------|
| PRD | 需求文档评审 |
| SAD | 架构设计评审 |
| LLD | 详细设计评审 |
| WBS | 工作分解评审 |
| CODING | 代码实现确认 |
| CR | 代码评审报告 |
| TEST | 测试结果确认 |
| UAT | 用户验收确认 |

**门禁规则**：
- 必须人工审批通过才能进入下一步骤
- 审批人可以要求返工(reject)
- 拒绝后需要修复重新审批

---

## 12.2 失败处理

```
失败 → 人工决定:
    - 修复后重试 (FIX)
    - 跳过当前步骤
    - 终止工作流
```

人工审批流程确保系统不会在无人监督情况下连续执行

---

# 十三、系统特性

## 13.1 优势

* 可控（无 RAG）
* 可审计（Git）
* 可扩展（Agent）
* 可持续（长运行）

---

## 13.2 限制

* 文档膨胀
* 流程复杂
* 初期成本高

---

# 十四、安全与治理

```
- RBAC
- 操作日志
- Prompt 注入防护
```

---

# 十五、可扩展方向

* 自动 Refactor Agent
* 多项目协同
* 自进化任务生成

---

# 十六、总结

本系统本质是：

```
从 AI Coding Tool
→ AI Software Organization
```

核心能力：

```
结构化知识 + 流程控制 + 多Agent协作
```

---

# 十七、结论

该架构适用于：

* 中大型项目
* 长周期开发
* 高质量要求系统

不适用于：

* 快速 demo
* 单文件脚本
