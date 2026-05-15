"""CLI - Command line interface with human approval gates"""

import click
import logging
from pathlib import Path

from cogniforge.core.config import Config
from cogniforge.core.constants import AgentRole, TaskStatus
from cogniforge.storage.git_storage import GitStorage
from cogniforge.context.context_loader import ContextLoader
from cogniforge.wiki.wiki_system import WikiSystem
from cogniforge.wiki.adr import ADRManager
from cogniforge.task_engine.task_engine import TaskEngine
from cogniforge.task_engine.dag import DAGStep, DAGDefinition, ApprovalStatus
from cogniforge.agents.base import BaseAgent
from cogniforge.agents.pm_agent import PMAgent
from cogniforge.agents.architect_agent import ArchitectAgent
from cogniforge.agents.design_agent import DesignAgent
from cogniforge.agents.techlead_agent import TechLeadAgent
from cogniforge.agents.dev_agent import DevAgent
from cogniforge.agents.review_agent import ReviewAgent
from cogniforge.agents.qa_agent import QAAgent
from cogniforge.agents.devops_agent import DevOpsAgent
from cogniforge.orchestration.workflow import Workflow, StepResult
from cogniforge.execution.execution_engine import ExecutionEngine
from cogniforge.execution.worker_pool import WorkerPool


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Context:
    """CLI context object"""

    def __init__(self):
        self.config: Config = None
        self.git_storage: GitStorage = None
        self.wiki_system: WikiSystem = None
        self.context_loader: ContextLoader = None
        self.task_engine: TaskEngine = None
        self.workflow: Workflow = None
        self.agents: dict = {}


pass_context = click.make_pass_decorator(Context, ensure=True)


def init_context(ctx: Context) -> None:
    """Initialize CLI context"""
    ctx.config = Config(repo_path=Path.cwd())
    ctx.git_storage = GitStorage(ctx.config.repo_path)
    ctx.wiki_system = WikiSystem(ctx.config, ctx.git_storage)
    ctx.context_loader = ContextLoader(ctx.config)
    ctx.task_engine = TaskEngine(ctx.config, ctx.git_storage)
    ctx.workflow = Workflow(DAGDefinition(), repo_path=ctx.config.repo_path)

    # Initialize agents
    ctx.agents = {
        AgentRole.PM.value: PMAgent(
            AgentRole.PM, ctx.wiki_system, ctx.context_loader, ctx.config
        ),
        AgentRole.ARCHITECT.value: ArchitectAgent(
            AgentRole.ARCHITECT, ctx.wiki_system, ctx.context_loader, ctx.config
        ),
        AgentRole.DESIGN.value: DesignAgent(
            AgentRole.DESIGN, ctx.wiki_system, ctx.context_loader, ctx.config
        ),
        AgentRole.TECHLEAD.value: TechLeadAgent(
            AgentRole.TECHLEAD, ctx.wiki_system, ctx.context_loader, ctx.config,
            task_engine=ctx.task_engine
        ),
        AgentRole.DEV.value: DevAgent(
            AgentRole.DEV, ctx.wiki_system, ctx.context_loader, ctx.config
        ),
        AgentRole.REVIEWER.value: ReviewAgent(
            AgentRole.REVIEWER, ctx.wiki_system, ctx.context_loader, ctx.config
        ),
        AgentRole.QA.value: QAAgent(
            AgentRole.QA, ctx.wiki_system, ctx.context_loader, ctx.config
        ),
        AgentRole.DEVOPS.value: DevOpsAgent(
            AgentRole.DEVOPS, ctx.wiki_system, ctx.context_loader, ctx.config
        ),
    }


@click.group()
@pass_context
def cli(ctx: Context):
    """CogniForge - 文档驱动的多Agent软件工厂

    每个步骤都需要人工审批，系统不会自动连续执行。
    """
    init_context(ctx)


@cli.command()
@click.option("--prd", help="PRD文件路径导入")
@pass_context
def init(ctx: Context, prd: str):
    """初始化新项目"""
    click.echo("正在初始化 CogniForge 项目...")

    # 确保wiki结构
    for subdir in ["prd", "sad", "lld", "decisions", "tasks", "qa", "reports", "ops"]:
        (ctx.config.repo_path / "wiki" / subdir).mkdir(parents=True, exist_ok=True)
    (ctx.config.repo_path / "src").mkdir(parents=True, exist_ok=True)
    (ctx.config.repo_path / "tests").mkdir(parents=True, exist_ok=True)

    click.echo("✓ 项目结构已创建")
    click.echo("\n下一步: 使用 'cogniforge start' 启动工作流")


@cli.command()
@pass_context
def status(ctx: Context):
    """显示当前工作流状态（包括持久化的中断恢复信息）"""
    workflow_state = ctx.workflow.get_state()
    task_stats = ctx.task_engine.get_statistics()

    click.echo("\n" + "=" * 50)
    click.echo("  CogniForge 工作流状态")
    click.echo("=" * 50)

    # 工作流基本信息
    click.echo(f"\n工作流ID: {workflow_state.get('workflow_id', 'N/A')}")
    click.echo(f"启动状态: {'✓ 已启动' if workflow_state['started'] else '✗ 未启动'}")
    click.echo(f"当前步骤: {workflow_state['current_step'] or '无'}")
    click.echo(f"等待审批: {'是' if workflow_state.get('awaiting_approval') else '否'}")

    if workflow_state.get('updated_at'):
        click.echo(f"最后更新: {workflow_state['updated_at']}")

    # 显示当前步骤审批状态
    current_approval = workflow_state.get('current_approval')
    if current_approval:
        status_icon = {
            'approved': '✓',
            'rejected': '✗',
            'pending': '⏳'
        }.get(current_approval['status'], '?')
        click.echo(f"\n当前步骤审批状态: {status_icon} {current_approval['status']}")
        if current_approval.get('approver'):
            click.echo(f"审批人: {current_approval['approver']}")
        if current_approval.get('comment'):
            click.echo(f"审批备注: {current_approval['comment']}")
        if current_approval.get('timestamp'):
            click.echo(f"审批时间: {current_approval['timestamp']}")
    else:
        click.echo(f"\n当前步骤审批状态: ⏳ 待审批")

    # 显示所有审批记录
    approval_records = workflow_state.get('approval_records', {})
    if approval_records:
        click.echo(f"\n--- 审批历史 ---")
        for step, record in approval_records.items():
            status_icon = {'approved': '✓', 'rejected': '✗'}.get(record['status'], '?')
            click.echo(f"  [{step}] {status_icon} {record['status']} by {record['approver']}")

    # 显示已完成步骤
    completed = workflow_state.get('completed_steps', [])
    if completed:
        click.echo(f"\n已完成步骤: {', '.join(completed)}")

    # 显示任务统计
    click.echo("\n" + "-" * 50)
    click.echo("  任务统计")
    click.echo("-" * 50)
    click.echo(f"总数: {task_stats['total']}")
    click.echo(f"待处理: {task_stats['pending']}")
    click.echo(f"进行中: {task_stats['in_progress']}")
    click.echo(f"已完成: {task_stats['done']}")
    click.echo(f"失败: {task_stats['failed']}")

    # 操作历史
    history = workflow_state.get('history', [])
    if history:
        click.echo(f"\n--- 最近操作 ---")
        for entry in history[-5:]:
            click.echo(f"  {entry['timestamp'][:19]} {entry['action']}")

    # 审批提示
    click.echo("\n" + "=" * 50)
    click.echo(ctx.workflow.get_approval_prompt())
    click.echo("=" * 50)


@cli.command()
@pass_context
def start(ctx: Context):
    """启动工作流 (从PRD开始)"""
    if ctx.workflow.is_started:
        click.echo("工作流已经启动，请使用 status 查看当前状态")
        return

    current = ctx.workflow.start()
    click.echo(f"\n✓ 工作流已启动")
    click.echo(f"当前步骤: {current.value}")
    click.echo(f"\n{current.get_approval_prompt()}")
    click.echo("\n使用 approve 命令审批此步骤，或使用 agent 命令执行具体工作")


@cli.command()
@click.option("--comment", default="", help="审批备注")
@click.option("--approver", default="human", help="审批人")
@pass_context
def approve(ctx: Context, comment: str, approver: str):
    """审批当前步骤，允许进入下一步

    示例:
        cogniforge approve --comment "同意进入架构设计阶段"
    """
    if not ctx.workflow.is_started:
        click.echo("错误: 工作流尚未启动。请先运行 'cogniforge start'")
        return

    current = ctx.workflow.current_step
    if current is None:
        click.echo("错误: 无当前步骤")
        return

    # 检查是否已经审批过
    if current in ctx.workflow._approval_records:
        approval = ctx.workflow._approval_records[current]
        if approval.status == ApprovalStatus.APPROVED:
            click.echo(f"步骤 [{current.value}] 已经审批通过")
            return
        elif approval.status == ApprovalStatus.REJECTED:
            click.echo(f"步骤 [{current.value}] 之前被拒绝，需要重新审批")
            # 允许重新审批

    # 执行审批
    success = ctx.workflow.approve(comment=comment, approver=approver)

    if success:
        click.echo(f"\n✓ 步骤 [{current.value}] 审批通过")
        click.echo(f"审批人: {approver}")
        if comment:
            click.echo(f"备注: {comment}")

        # 显示下一步信息
        next_step = ctx.workflow.get_next_step()
        if next_step:
            click.echo(f"\n下一步: {next_step.value}")
            click.echo(f"使用 'cogniforge advance' 进入下一步")
        else:
            click.echo("\n✓ 工作流已完成")
    else:
        click.echo("审批失败")


@cli.command()
@click.option("--comment", required=True, help="拒绝原因 (必须)")
@click.option("--approver", default="human", help="审批人")
@pass_context
def reject(ctx: Context, comment: str, approver: str):
    """拒绝当前步骤，要求返工

    示例:
        cogniforge reject --comment "需求描述不清晰，需要补充用户故事"
    """
    if not ctx.workflow.is_started:
        click.echo("错误: 工作流尚未启动")
        return

    current = ctx.workflow.current_step
    if current is None:
        click.echo("错误: 无当前步骤")
        return

    success = ctx.workflow.reject(comment=comment, approver=approver)

    if success:
        click.echo(f"\n✗ 步骤 [{current.value}] 已拒绝")
        click.echo(f"拒绝原因: {comment}")
        click.echo("\n需要修复后重新提交审批")


@cli.command()
@pass_context
def advance(ctx: Context):
    """进入工作流的下一步 (需要先审批)

    步骤:
        1. 使用 'cogniforge status' 查看当前状态
        2. 使用 'cogniforge agent <role>' 执行工作
        3. 使用 'cogniforge approve' 审批
        4. 使用 'cogniforge advance' 进入下一步
    """
    if not ctx.workflow.is_started:
        click.echo("错误: 工作流尚未启动")
        return

    if not ctx.workflow.can_advance():
        click.echo("错误: 当前步骤尚未审批通过")
        click.echo(f"\n{ctx.workflow.get_approval_prompt()}")
        return

    next_step = ctx.workflow.advance()

    if next_step:
        click.echo(f"\n✓ 已进入步骤: {next_step.value}")
        click.echo(f"\n{next_step.get_approval_prompt()}")
    else:
        click.echo("\n✓ 工作流已完成所有步骤")


@cli.command()
@click.option("--step", help="指定步骤 (可选，默认当前步骤)")
@pass_context
def info(ctx: Context, step: str):
    """查看指定步骤的详细信息"""
    if step:
        target = DAGStep.from_string(step.lower())
        if target:
            click.echo(f"\n步骤: {target.value}")
            click.echo(f"审批要求: {target.requires_approval()}")
            click.echo(f"审批提示: {target.get_approval_prompt()}")
        else:
            click.echo(f"未知步骤: {step}")
    else:
        click.echo("\n" + "=" * 50)
        click.echo("  工作流步骤说明")
        click.echo("=" * 50)

        for s in DAGStep:
            click.echo(f"\n{s.value}:")
            click.echo(f"  {s.get_approval_prompt()}")


@cli.command()
@click.argument("role")
@click.argument("input_file", required=False)
@pass_context
def agent(ctx: Context, role: str, input_file: str):
    """手动运行指定的Agent

    示例:
        cogniforge agent pm --input prd_input.json
        cogniforge agent dev --input task_input.json
    """
    agent = ctx.agents.get(role.lower())

    if not agent:
        click.echo(f"未知Agent角色: {role}")
        click.echo(f"可用角色: {', '.join(ctx.agents.keys())}")
        return

    # 加载输入数据
    if input_file:
        import json
        with open(input_file, 'r', encoding='utf-8') as f:
            input_data = json.load(f)
    else:
        input_data = {}

    click.echo(f"\n正在执行 {role} Agent...")

    try:
        result = agent.run(input_data)

        click.echo(f"\n状态: {result['status']}")
        click.echo(f"消息: {result['message']}")

        if result.get('artifacts'):
            click.echo(f"产出文件:")
            for artifact in result['artifacts']:
                click.echo(f"  - {artifact}")

        if result.get('data'):
            click.echo(f"\n数据:")
            for key, value in result['data'].items():
                click.echo(f"  {key}: {value}")

    except Exception as e:
        click.echo(f"执行失败: {e}")


@cli.command()
@click.argument("task_id")
@pass_context
def task(ctx: Context, task_id: str):
    """显示任务详情"""
    try:
        task = ctx.task_engine.get_task(task_id)
        click.echo(f"\n=== 任务: {task.task_id} ===")
        click.echo(f"名称: {task.name}")
        click.echo(f"模块: {task.module}")
        click.echo(f"状态: {task.status.value}")
        click.echo(f"优先级: P{task.priority.value}")
        if task.deps:
            click.echo(f"依赖: {', '.join(task.deps)}")
        if task.assignee:
            click.echo(f"负责人: {task.assignee}")
        click.echo(f"\n描述:\n{task.description}")
    except Exception as e:
        click.echo(f"错误: {e}")


@cli.command()
@click.option("--status", help="按状态过滤")
@pass_context
def tasks(ctx: Context, status: str):
    """列出所有任务"""
    all_tasks = ctx.task_engine.list_tasks()

    if not all_tasks:
        click.echo("没有找到任务")
        return

    # 按状态过滤
    if status:
        try:
            status_enum = TaskStatus(status.lower())
            all_tasks = [t for t in all_tasks if t.status == status_enum]
        except ValueError:
            click.echo(f"未知状态: {status}")
            return

    click.echo(f"\n=== 任务列表 ({len(all_tasks)}) ===")

    status_icons = {
        TaskStatus.PENDING: "⏳",
        TaskStatus.IN_PROGRESS: "🔄",
        TaskStatus.DONE: "✅",
        TaskStatus.FAILED: "❌",
        TaskStatus.BLOCKED: "🚫"
    }

    for task in all_tasks:
        icon = status_icons.get(task.status, "?")
        click.echo(f"{icon} {task.task_id} [{task.module}] {task.name} P{task.priority.value}")


@cli.command()
@click.argument("title")
@click.argument("context_text")
@click.argument("decision")
@click.argument("consequences")
@click.option("--status", default="Proposed", help="ADR状态")
@pass_context
def adr(ctx: Context, title: str, context_text: str, decision: str, consequences: str, status: str):
    """创建架构决策记录 (ADR)

    示例:
        cogniforge adr "使用微服务架构" "系统需要高可用" "采用微服务拆分" "增加运维复杂度"
    """
    adr_manager = ADRManager(ctx.wiki_system)

    doc = adr_manager.create_adr(
        title=title,
        context=context_text,
        decision=decision,
        consequences=consequences,
        status=status
    )

    ctx.wiki_system.write_document(doc, f"docs: ADR - {title}")
    click.echo(f"\n✓ ADR已创建: {doc.path}")


@cli.command()
@pass_context
def lsadr(ctx: Context):
    """列出所有ADR"""
    adr_manager = ADRManager(ctx.wiki_system)
    adrs = adr_manager.list_adrs()

    if not adrs:
        click.echo("没有找到ADR")
        return

    click.echo(f"\n=== ADR列表 ({len(adrs)}) ===")
    for adr_doc in adrs:
        click.echo(f"- {adr_doc.title}")


@cli.command()
@pass_context
def wait(ctx: Context):
    """等待人工确认 (用于脚本中暂停等待人工处理)

    此命令会阻塞直到用户按Enter键继续。
    """
    click.echo("\n" + "=" * 50)
    click.echo("  等待人工确认...")
    click.echo("=" * 50)
    click.echo("\n当前状态:")
    ctx.invoke(status)
    click.echo("\n按 Enter 键继续...")
    input()


@cli.command()
@pass_context
def log(ctx: Context):
    """显示Git提交日志"""
    log_entries = ctx.git_storage.log(max_count=20)

    if not log_entries:
        click.echo("没有提交记录")
        return

    click.echo("\n=== Git 提交历史 ===\n")
    for entry in log_entries:
        click.echo(f"提交: {entry['hexsha'][:8]}")
        click.echo(f"  {entry['message']}")
        click.echo(f"  作者: {entry['author']}")
        click.echo(f"  时间: {entry['committed_date'].strftime('%Y-%m-%d %H:%M')}")
        click.echo()


@cli.command()
@pass_context
def audit(ctx: Context):
    """显示 AI 操作审计日志"""
    from cogniforge.audit.audit_log import AuditLog

    audit_log = AuditLog(ctx.config)

    click.echo("\n=== AI 操作审计日志 ===\n")

    # Show summary
    click.echo(f"总操作数: {len(audit_log.entries)}")
    click.echo(f"已审核: {len([e for e in audit_log.entries if e.reviewed])}")
    click.echo(f"待审核: {len(audit_log.get_unreviewed())}")

    if not audit_log.entries:
        click.echo("\n暂无审计记录")
        return

    click.echo("\n" + "-" * 50)

    for i, entry in enumerate(audit_log.entries):
        status_icon = "✓" if entry.reviewed else "⏳"
        click.echo(f"\n[{i}] {status_icon} {entry.agent_role} - {entry.operation}")
        click.echo(f"    时间: {entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        click.echo(f"    状态: {entry.status}")

        if entry.output_artifacts:
            click.echo(f"    产出: {', '.join(entry.output_artifacts)}")

        if not entry.reviewed:
            click.echo(f"    ⏳ 待人工审核")


@cli.command()
@click.argument("entry_index", type=int)
@click.option("--comment", required=True, help="审核意见")
@click.option("--reviewer", default="human", help="审核人")
@pass_context
def review(ctx: Context, entry_index: int, comment: str, reviewer: str):
    """审核指定的 AI 操作

    示例:
        cogniforge review 0 --comment "代码质量符合要求"
    """
    from cogniforge.audit.audit_log import AuditLog

    audit_log = AuditLog(ctx.config)

    if entry_index < 0 or entry_index >= len(audit_log.entries):
        click.echo(f"错误: 无效的索引 {entry_index}")
        return

    entry = audit_log.entries[entry_index]

    if audit_log.mark_reviewed(entry_index, reviewer, comment):
        click.echo(f"\n✓ 已标记 [{entry_index}] 为已审核")
        click.echo(f"审核人: {reviewer}")
        click.echo(f"意见: {comment}")
    else:
        click.echo("审核失败")


@cli.command()
@pass_context
def audit_report(ctx: Context):
    """生成 AI 输出审核报告

    生成一份完整的报告，列出所有 AI 产出及其审核状态
    """
    from cogniforge.audit.audit_log import AuditLog

    audit_log = AuditLog(ctx.config)

    click.echo("\n正在生成审核报告...")

    report_path = audit_log.save_review_report()

    click.echo(f"\n✓ 报告已生成: {report_path}")
    click.echo("\n" + "=" * 50)

    # Also display summary
    click.echo(audit_log.generate_review_report())


@cli.command()
@pass_context
def history(ctx: Context):
    """显示工作流完整操作历史

    包含所有审批、操作记录，用于中断恢复和审计
    """
    workflow_state = ctx.workflow.get_state()
    history = workflow_state.get('history', [])

    click.echo("\n=== 工作流操作历史 ===\n")
    click.echo(f"工作流ID: {workflow_state.get('workflow_id', 'N/A')}")
    click.echo(f"当前步骤: {workflow_state.get('current_step', 'N/A')}")
    click.echo(f"总操作数: {len(history)}\n")

    if not history:
        click.echo("暂无操作记录")
        return

    click.echo("-" * 60)
    for i, entry in enumerate(history):
        timestamp = entry.get('timestamp', 'N/A')[:19]
        action = entry.get('action', 'N/A')
        details = entry.get('details', {})

        click.echo(f"\n[{i+1}] {timestamp}")
        click.echo(f"    操作: {action}")

        if details:
            for key, value in details.items():
                if value:
                    click.echo(f"    {key}: {value}")

    click.echo("\n" + "-" * 60)

    # Show approval records
    approval_records = workflow_state.get('approval_records', {})
    if approval_records:
        click.echo("\n=== 审批记录 ===\n")
        for step, record in approval_records.items():
            status_icon = {'approved': '✓', 'rejected': '✗'}.get(record['status'], '?')
            click.echo(f"[{step}] {status_icon} {record['status']}")
            click.echo(f"    审批人: {record.get('approver', 'N/A')}")
            click.echo(f"    备注: {record.get('comment', 'N/A')}")
            click.echo(f"    时间: {record.get('timestamp', 'N/A')[:19]}")
            click.echo()


@cli.command()
@click.argument("agent_role", required=False)
@pass_context
def pending_reviews(ctx: Context, agent_role: str):
    """显示待审核的 AI 操作

    示例:
        cogniforge pending_reviews      # 显示所有待审核
        cogniforge pending_reviews dev  # 只显示 dev agent 的待审核项
    """
    from cogniforge.audit.audit_log import AuditLog

    audit_log = AuditLog(ctx.config)

    if agent_role:
        entries = [e for e in audit_log.get_by_agent(agent_role) if not e.reviewed]
        click.echo(f"\n=== {agent_role} 待审核项 ===")
    else:
        entries = audit_log.get_unreviewed()
        click.echo("\n=== 所有待审核项 ===")

    if not entries:
        click.echo("\n✓ 没有待审核项")
        return

    click.echo(f"\n共 {len(entries)} 项待审核\n")

    for i, entry in enumerate(entries):
        click.echo(f"[{i}] {entry.agent_role} - {entry.operation}")
        click.echo(f"    时间: {entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        if entry.output_artifacts:
            click.echo(f"    产出: {', '.join(entry.output_artifacts)}")
        if entry.output_summary:
            summary = entry.output_summary[:100] + "..." if len(entry.output_summary) > 100 else entry.output_summary
            click.echo(f"    摘要: {summary}")
        click.echo()


@cli.command()
@pass_context
def repl(ctx: Context):
    """Start interactive REPL session (Claude Code style).

    Type natural language at each step — the system interprets your
    intent, runs the right agent, and guides you through the workflow.

    Built-in commands:
      /status   Show workflow state
      /steps    List all DAG steps
      /skip     Approve + advance current step
      /help     Show help
      /quit     Exit REPL
    """
    from cogniforge.llm.base import create_llm_adapter, LLMProvider
    from cogniforge.repl import Repl

    adapter = create_llm_adapter(
        LLMProvider(ctx.config.llm_provider),
        config={
            "repo_path": str(ctx.config.repo_path),
            "model": ctx.config.llm_model,
        },
    )

    repl_runner = Repl(
        workflow=ctx.workflow,
        agents=ctx.agents,
        task_engine=ctx.task_engine,
        llm=adapter,
    )
    repl_runner.run()


if __name__ == "__main__":
    cli()
