"""AST 驱动的代码扫描器 — 无 LLM 参与，生成 codebase manifest。

使用 Python 标准库 ``ast`` 模块提取符号、依赖和入口点。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def scan_project(root: Path) -> dict:
    """扫描项目目录，返回 manifest dict。"""
    py_files = _find_py_files(root)
    symbols_map: dict[str, list[dict]] = {}
    imports_map: dict[str, list[str]] = {}
    total_lines = 0

    for fpath in py_files:
        rel = _rel(root, fpath)
        try:
            tree = ast.parse(fpath.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        symbols_map[rel] = _extract_symbols(tree)
        imports_map[rel] = _extract_imports(tree)
        total_lines += _count_lines(fpath)

    return {
        "root": str(root.resolve()),
        "tech_stack": _detect_tech_stack(root),
        "entry_points": _find_entry_points(root),
        "symbols": _aggregate_symbols(symbols_map),
        "dependency_graph": _build_dependency_graph(root, imports_map),
        "total_tokens_est": total_lines * 4,
        "file_count": len(py_files),
        "file_tree": [
            {"path": _rel(root, f), "language": "python", "lines": _count_lines(f)}
            for f in py_files
        ],
    }


# ---------------------------------------------------------------------------
# 文件发现
# ---------------------------------------------------------------------------

def _find_py_files(root: Path) -> list[Path]:
    """递归查找所有 .py 文件，排除 .gitignore 匹配的路径。"""
    ignore_patterns = _read_gitignore(root)
    py_files: list[Path] = []

    def _walk(d: Path):
        for child in sorted(d.iterdir()):
            rel = _rel(root, child)
            parts = rel.split("/")
            if any(p.startswith(".") or p.startswith("__pycache__") or p in ("venv", "node_modules")
                   for p in parts):
                continue
            if child.is_dir():
                _walk(child)
            elif child.suffix == ".py":
                if not _is_ignored(rel, ignore_patterns):
                    py_files.append(child)
    _walk(root)
    return py_files


def _read_gitignore(root: Path) -> list[re.Pattern]:
    """读取 .gitignore，返回编译后的正则列表。"""
    gi = root / ".gitignore"
    if not gi.exists():
        return []
    patterns: list[re.Pattern] = []
    for line in gi.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern = line.replace(".", r"\.").replace("*", ".*").replace("?", ".")
        if pattern.endswith("/"):
            pattern += ".*"
        patterns.append(re.compile(pattern))
    return patterns


def _is_ignored(path: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(path) for p in patterns)


def _count_lines(fpath: Path) -> int:
    try:
        return sum(1 for _ in open(fpath, encoding="utf-8"))
    except Exception:
        return 0


def _rel(root: Path, fpath: Path) -> str:
    return fpath.resolve().relative_to(root.resolve()).as_posix()


# ---------------------------------------------------------------------------
# AST 符号提取
# ---------------------------------------------------------------------------

def _extract_symbols(tree: ast.AST) -> list[dict]:
    """从 AST 提取类、函数和路由定义。"""
    extractor = _SymbolExtractor()
    extractor.visit(tree)
    return extractor.symbols


class _SymbolExtractor(ast.NodeVisitor):
    def __init__(self):
        self.symbols: list[dict] = []
        self._current_class: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef):
        prev = self._current_class
        self._current_class = node.name
        bases = [ast.unparse(b) for b in node.bases]
        decos = [ast.unparse(d) for d in node.decorator_list]
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append({
                    "kind": "method",
                    "name": item.name,
                    "signature": _func_sig(item),
                    "range": _range(node=item),
                })
        self.symbols.append({
            "kind": "class",
            "name": node.name,
            "bases": bases,
            "decorators": decos,
            "range": _range(node=node),
            "children": methods,
        })
        self.generic_visit(node)
        self._current_class = prev

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if self._current_class is None:
            decos = [ast.unparse(d) for d in node.decorator_list]
            self.symbols.append({
                "kind": "function",
                "name": node.name,
                "signature": _func_sig(node),
                "decorators": decos,
                "range": _range(node=node),
            })
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def visit_Call(self, node: ast.Call):
        # 检测 FastAPI 路由注册: app.get("/path", handler) / router.post(...)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}
            router_vars = {"app", "router", "api", "application"}
            if node.func.attr in http_methods and node.func.value.id in router_vars and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    handler = ""
                    for kw in node.keywords:
                        if kw.arg is None:
                            if isinstance(kw.value, ast.Name):
                                handler = kw.value.id
                    self.symbols.append({
                        "kind": "route",
                        "method": node.func.attr.upper(),
                        "path": first_arg.value,
                        "handler": handler,
                        "parent": node.func.value.id,
                    })
        # 检测 Click 命令注册: @cli.command()
        self.generic_visit(node)


def _func_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = []
    for a in node.args.args:
        if a.arg == "self":
            continue
        ann = ast.unparse(a.annotation) if a.annotation else "Any"
        args.append(f"{a.arg}: {ann}")
    returns = ast.unparse(node.returns) if node.returns else "None"
    return f"({', '.join(args)}) -> {returns}"


def _range(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    return {"start": [node.lineno, node.col_offset], "end": [node.end_lineno or node.lineno, node.end_col_offset or 0]}


# ---------------------------------------------------------------------------
# import 提取
# ---------------------------------------------------------------------------

def _extract_imports(tree: ast.AST) -> list[str]:
    extractor = _ImportExtractor()
    extractor.visit(tree)
    return extractor.imports


class _ImportExtractor(ast.NodeVisitor):
    def __init__(self):
        self.imports: list[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            full = f"{module}.{alias.name}" if module else alias.name
            self.imports.append(full)


# ---------------------------------------------------------------------------
# 依赖图构建
# ---------------------------------------------------------------------------

def _build_dependency_graph(root: Path, imports_map: dict[str, list[str]]) -> dict[str, list[str]]:
    """将 import 列表转为文件级依赖图。

    只追踪项目内部依赖：将 ``cogniforge.agents.base`` 映射为
    ``src/cogniforge/agents/base.py``。
    """
    # 收集所有已知项目文件路径（不含 .py 后缀的短形式）
    known_files: dict[str, str] = {}
    for rel in imports_map:
        known_files[rel] = rel
        # 添加无后缀版本
        no_ext = rel.replace("/", ".").replace(".py", "")
        known_files[no_ext] = rel
        # 分段匹配（用于 from X import Y 的解析）
        parts = no_ext.split(".")
        for i in range(1, len(parts) + 1):
            known_files[".".join(parts[:i])] = rel

    graph: dict[str, list[str]] = {}
    for src_file, imports in imports_map.items():
        deps: list[str] = []
        seen: set[str] = set()
        for imp in imports:
            resolved = _resolve_import(imp, known_files)
            if resolved and resolved != src_file and resolved not in seen:
                deps.append(resolved)
                seen.add(resolved)
        graph[src_file] = sorted(deps)
    return graph


def _resolve_import(imp: str, known: dict[str, str]) -> str | None:
    """尝试将 import 字符串解析为已知项目文件路径。"""
    if imp in known:
        return known[imp]
    # 尝试去掉顶级包名
    parts = imp.split(".")
    for i in range(1, len(parts)):
        candidate = ".".join(parts[i:])
        if candidate in known:
            return known[candidate]
    # 尝试按分段前缀匹配
    for prefix, fpath in known.items():
        if imp.startswith(prefix + ".") or imp == prefix:
            return fpath
    return None


# ---------------------------------------------------------------------------
# 技术栈检测
# ---------------------------------------------------------------------------

def _detect_tech_stack(root: Path) -> dict:
    result: dict[str, list[str]] = {"languages": ["python"], "frameworks": [], "databases": [], "tools": []}
    ppt = root / "pyproject.toml"
    if ppt.exists():
        content = ppt.read_text(encoding="utf-8")
        framework_hints = {
            "fastapi": "fastapi", "flask": "flask", "django": "django",
            "starlette": "starlette", "click": "click",
        }
        for key, val in framework_hints.items():
            if key in content.lower():
                result["frameworks"].append(val)

        db_hints = {"sqlalchemy": "sqlalchemy", "sqlmodel": "sqlmodel",
                     "pymongo": "mongodb", "redis": "redis", "psycopg2": "postgresql"}
        for key, val in db_hints.items():
            if key in content.lower():
                result["databases"].append(val)

        if "pydantic" in content.lower():
            result["frameworks"].append("pydantic")
        if "pytest" in content.lower():
            result["tools"].append("pytest")
    return result


# ---------------------------------------------------------------------------
# 入口点发现
# ---------------------------------------------------------------------------

def _find_entry_points(root: Path) -> list[str]:
    """定位项目入口点。"""
    entries: list[str] = []

    # __main__.py
    main_py = root / "src" / "cogniforge" / "__main__.py"
    if main_py.exists():
        entries.append(_rel(root, main_py))

    # pyproject.toml 中的 script 入口
    ppt = root / "pyproject.toml"
    if ppt.exists():
        content = ppt.read_text(encoding="utf-8")
        entries.append("pyproject.toml [project.scripts]")
        for m in re.finditer(r'"([^"]+)"\s*=\s*"([^"]+):([^"]+)"', content):
            entries.append(f"CLI: {m.group(1)} → {m.group(2)}:{m.group(3)}")

    # cli = click.group()
    for pyfile in root.rglob("*.py"):
        try:
            for node in ast.walk(ast.parse(pyfile.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "cli":
                            if isinstance(node.value, ast.Call):
                                if hasattr(node.value, "func"):
                                    func = node.value.func
                                    if isinstance(func, ast.Attribute) and func.attr == "group":
                                        entries.append(
                                            f"Click group: {_rel(root, pyfile)}:{target.id}")
        except (SyntaxError, UnicodeDecodeError):
            continue

    return entries


# ---------------------------------------------------------------------------
# 符号聚合
# ---------------------------------------------------------------------------

def _aggregate_symbols(symbols_map: dict[str, list[dict]]) -> dict:
    """将逐文件符号汇总为全局视图。"""
    classes: list[dict] = []
    functions: list[dict] = []
    routes: list[dict] = []

    for filepath, syms in symbols_map.items():
        for s in syms:
            entry = dict(s)
            entry["file"] = filepath
            if s["kind"] == "class":
                classes.append(entry)
            elif s["kind"] == "function":
                functions.append(entry)
            elif s["kind"] == "route":
                routes.append(entry)

    return {
        "classes": sorted(classes, key=lambda x: x["name"]),
        "functions": sorted(functions, key=lambda x: x["name"]),
        "routes": sorted(routes, key=lambda x: x.get("path", "")),
    }
