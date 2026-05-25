"""WBS Index — the master index tying together all tasks in a WBS iteration.

Read/write ``.cogniforge/wiki/wbs/{wbs_id}.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class WBSMeta:
    wbs_id: str = ""
    author: str = "techlead_agent"
    created: str = ""
    project_id: str = ""
    iteration_id: str = ""

    def to_dict(self) -> dict:
        return {
            "wbs_id": self.wbs_id,
            "author": self.author,
            "created": self.created or datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00"),
            "project_id": self.project_id,
            "iteration_id": self.iteration_id,
        }


@dataclass
class WBSSource:
    prd_doc_id: str = ""
    prd_version: int = 0
    sad_doc_id: str = ""
    sad_version: int = 0
    llds: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prd": {"doc_id": self.prd_doc_id, "version": self.prd_version},
            "sad": {"doc_id": self.sad_doc_id, "version": self.sad_version},
            "llds": self.llds,
        }


@dataclass
class TaskGraphNode:
    task_id: str = ""
    name: str = ""
    module: str = ""
    category: str = ""
    layer: int = 0
    path: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "module": self.module,
            "category": self.category,
            "layer": self.layer,
            "path": self.path,
        }


@dataclass
class TaskGraphEdge:
    from_task: str = ""
    to_task: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "from": self.from_task,
            "to": self.to_task,
            "reason": self.reason,
        }


@dataclass
class WBSIndex:
    meta: WBSMeta = field(default_factory=WBSMeta)
    source: WBSSource = field(default_factory=WBSSource)
    nodes: list[TaskGraphNode] = field(default_factory=list)
    edges: list[TaskGraphEdge] = field(default_factory=list)
    execution_batches: list[list[str]] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    quality_gates: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "meta": self.meta.to_dict(),
            "source": self.source.to_dict(),
            "task_graph": {
                "nodes": [n.to_dict() for n in self.nodes],
                "edges": [e.to_dict() for e in self.edges],
            },
            "execution_batches": [
                {"batch": i, "parallel": len(b) > 1, "task_ids": b}
                for i, b in enumerate(self.execution_batches)
            ],
            "coverage": self.coverage,
            "quality_gates": self.quality_gates,
        }


# ═══════════════════════════════════════════════════════════════════════
# Execution-batch computation
# ═══════════════════════════════════════════════════════════════════════


def compute_execution_batches(tasks: list[dict]) -> list[list[str]]:
    """Partition tasks into execution batches.

    Rules:
      - Topological sort by layer then dep count.
      - Kahn's algorithm for initial ordering.
      - Within the same layer, greedily partition by file-lock conflicts
        (two tasks share a lock → they go in separate batches).
    """
    if not tasks:
        return []

    # Build id → task map
    id_to_task: dict[str, dict] = {}
    for t in tasks:
        tid = t.get("task_id", t.get("name", ""))
        id_to_task[tid] = t

    # Build adjacency + in-degree
    adj: dict[str, list[str]] = {tid: [] for tid in id_to_task}
    in_degree: dict[str, int] = {tid: 0 for tid in id_to_task}

    for tid, t in id_to_task.items():
        for dep_id in t.get("deps", []):
            if dep_id in adj:
                adj[dep_id].append(tid)
                in_degree[tid] = in_degree.get(tid, 0) + 1

    # Kahn topological sort
    queue = sorted(
        [tid for tid, deg in in_degree.items() if deg == 0],
        key=lambda tid: (id_to_task[tid].get("layer", 0), tid),
    )
    topo_order: list[str] = []
    while queue:
        node = queue.pop(0)
        topo_order.append(node)
        for neighbor in sorted(adj.get(node, [])):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                queue.sort(key=lambda tid: (id_to_task[tid].get("layer", 0), tid))

    # Group by layer
    layers: dict[int, list[str]] = {}
    for tid in topo_order:
        l = id_to_task[tid].get("layer", 0)
        layers.setdefault(l, []).append(tid)

    # Within each layer, greedy coloring by file-lock conflict
    batches: list[list[str]] = []
    for layer_idx in sorted(layers):
        layer_tasks = layers[layer_idx]
        # Build conflict graph (simple adjacency by shared file locks)
        conflict: dict[str, set[str]] = {tid: set() for tid in layer_tasks}
        for i, tid_a in enumerate(layer_tasks):
            locks_a = set(id_to_task[tid_a].get("file_locks", []))
            for tid_b in layer_tasks[i + 1:]:
                locks_b = set(id_to_task[tid_b].get("file_locks", []))
                if locks_a & locks_b:
                    conflict[tid_a].add(tid_b)
                    conflict[tid_b].add(tid_a)

        # Greedy color (simple: lowest available color index)
        colors: dict[str, int] = {}
        for tid in layer_tasks:
            used = {colors[n] for n in conflict[tid] if n in colors}
            c = 0
            while c in used:
                c += 1
            colors[tid] = c

        # Group by color
        color_to_batch: dict[int, list[str]] = {}
        for tid, c in colors.items():
            color_to_batch.setdefault(c, []).append(tid)

        for c in sorted(color_to_batch):
            batches.append(color_to_batch[c])

    return batches


# ═══════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════

_WBS_DIR = ".cogniforge/wiki/wbs"


def read_wbs_index(repo_path: Path, wbs_id: str) -> dict | None:
    """Read a WBS index JSON file. Returns None if missing."""
    path = repo_path / _WBS_DIR / f"{wbs_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_wbs_index(repo_path: Path, index: WBSIndex) -> Path:
    """Write a WBSIndex to disk. Returns the written path."""
    dir_path = repo_path / _WBS_DIR
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{index.meta.wbs_id}.json"
    path.write_text(
        json.dumps(index.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path.relative_to(repo_path)
