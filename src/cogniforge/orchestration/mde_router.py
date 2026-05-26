"""MDE Router — non-LLM orchestrator for fan-out / fan-in of MDE agents.

Scans LLD wiki documents and SAD wiki to decide which MDE modules are
affected by an SE turn result, then generates per-module ``mde-request``
packets containing only the relevant PRD/SAD slices.

The routing table is built at runtime by scanning all LLD files — each
LLD declares its owned components/contracts in ``module_boundary``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class MDERouter:
    """Routes SE turn results to the appropriate MDE (DesignAgent) modules."""

    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path or Path.cwd()

    # ------------------------------------------------------------------
    # Registry (built from LLD scan)
    # ------------------------------------------------------------------

    def _scan_lld_modules(self) -> list[dict]:
        """Scan all LLD files and build the in-memory routing table.

        Each LLD declares what it owns/consumes in ``module_boundary``.
        """
        import glob
        wiki_root = self.repo_path / ".cogniforge" / "wiki" / "lld"
        modules: list[dict] = []
        for fpath in sorted(glob.glob(str(wiki_root / "*" / "lld-*.json"))):
            try:
                lld = json.loads(Path(fpath).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                continue
            meta = lld.get("meta", {})
            boundary = lld.get("module_boundary", {})
            modules.append({
                "module": meta.get("module", ""),
                "module_type": meta.get("module_type", "service"),
                "lld_path": str(Path(fpath).relative_to(self.repo_path)),
                "owned_components": boundary.get("owned_components", []),
                "owned_contracts": boundary.get("owned_contracts", []),
                "consumed_contracts": boundary.get("consumed_contracts", []),
            })
        return modules

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(self, se_turn_result: dict) -> list[dict]:
        """Determine which MDE modules to trigger based on SE turn result.

        Returns a list of target_module dicts (from the registry).
        Returns empty list if any coverage change is "blocked".
        """
        # EARLY RETURN: blocked coverage means the feature cannot proceed —
        # SE/PM must resolve the blockage before MDE agents are triggered.
        coverage = se_turn_result.get("coverage_changes", [])
        if any(isinstance(c, dict) and c.get("after") == "blocked"
               for c in coverage):
            return []

        registry = self._scan_lld_modules()

        affected_comps = {
            item["id"] for item in se_turn_result.get("affected_components", [])
        }
        affected_ctrs = {
            item["id"] for item in se_turn_result.get("affected_contracts", [])
        }

        # If nothing specific is affected, don't trigger any MDE
        if not affected_comps and not affected_ctrs:
            return []

        triggered: list[dict] = []
        for mod in registry:
            owned_comps = set(mod.get("owned_components", []))
            owned_ctrs = set(mod.get("owned_contracts", []))
            consumed_ctrs = set(mod.get("consumed_contracts", []))

            # Trigger if any affected component belongs to this module
            if affected_comps & owned_comps:
                triggered.append(mod)
                continue

            # Trigger if any affected contract is owned by this module
            if affected_ctrs & owned_ctrs:
                triggered.append(mod)
                continue

            # Trigger if any affected contract is consumed by this module
            if affected_ctrs & consumed_ctrs:
                triggered.append(mod)
                continue

        return triggered

    # ------------------------------------------------------------------
    # Slice generation
    # ------------------------------------------------------------------

    def build_mde_request(
        self,
        target_module: dict,
        se_turn_result: dict,
        pm_turn_result: Optional[dict] = None,
    ) -> dict:
        """Build an mde-request packet for a single MDE module.

        Includes PRD slice and SAD slice containing only the data relevant
        to this module.
        """
        prd = self._load_latest_wiki("prd")
        sad = self._load_latest_wiki("sad")
        existing_lld = self._load_latest_wiki("lld", module=target_module.get("module", ""))

        owned_comps = target_module.get("owned_components", [])
        owned_ctrs = target_module.get("owned_contracts", [])
        consumed_ctrs = target_module.get("consumed_contracts", [])

        # Slice PRD: only requirements related to this module's components/contracts
        relevant_req_ids = self._find_relevant_req_ids(sad, owned_comps, owned_ctrs)
        prd_slice = self._slice_prd(prd, relevant_req_ids)

        # Slice SAD: only components/contracts relevant to this module
        sad_slice = self._slice_sad(sad, owned_comps, owned_ctrs, consumed_ctrs)

        # Build upstream change summary
        upstream_change = {
            "summary": se_turn_result.get("message", ""),
            "affected_components": [
                item for item in se_turn_result.get("affected_components", [])
                if item["id"] in owned_comps
            ],
            "affected_contracts": [
                item for item in se_turn_result.get("affected_contracts", [])
                if item["id"] in owned_ctrs or item["id"] in consumed_ctrs
            ],
            "downstream_handoff": se_turn_result.get("downstream_handoff", {}),
        }

        # Build mde-request
        return {
            "input_type": "mde_agent_request",
            "turn_id": se_turn_result.get("source", {}).get("se_turn_id", ""),
            "target_module": {
                "module": target_module["module"],
                "module_type": target_module["module_type"],
                "lld_path": target_module["lld_path"],
            },
            "source": {
                "prd_doc_id": prd.get("meta", {}).get("doc_id", "") if prd else "",
                "prd_version": prd.get("meta", {}).get("version", 1) if prd else 1,
                "sad_doc_id": sad.get("meta", {}).get("doc_id", "") if sad else "",
                "sad_version": sad.get("meta", {}).get("version", 1) if sad else 1,
                "se_turn_id": se_turn_result.get("source", {}).get("se_turn_id", ""),
            },
            "prd_slice": prd_slice,
            "sad_slice": sad_slice,
            "existing_lld": existing_lld or {},
            "upstream_change": upstream_change,
            "constraints": {
                "preserve_existing_ids": True,
                "do_not_modify_prd_or_sad": True,
                "default_deprecation_policy": "deprecate_instead_of_delete",
            },
        }

    # ------------------------------------------------------------------
    # Fan-out / Fan-in
    # ------------------------------------------------------------------

    def fan_out(
        self,
        se_turn_result: dict,
        pm_turn_result: Optional[dict] = None,
    ) -> list[dict]:
        """Fan-out: determine triggered modules and build all mde-requests."""
        triggered = self.route(se_turn_result)
        requests = []
        for mod in triggered:
            req = self.build_mde_request(mod, se_turn_result, pm_turn_result)
            requests.append(req)
        return requests

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_latest_wiki(self, doc_type: str, module: str = "") -> Optional[dict]:
        """Load the latest JSON doc from the wiki path (prd/sad/lld)."""
        import glob
        wiki_root = self.repo_path / ".cogniforge" / "wiki"
        if doc_type == "prd":
            pattern = str(wiki_root / "prd" / "*.json")
        elif doc_type == "sad":
            pattern = str(wiki_root / "sad" / "*.json")
        elif doc_type == "lld" and module:
            pattern = str(wiki_root / "lld" / module / "*.json")
        else:
            return None
        files = sorted(glob.glob(pattern))
        if not files:
            return None
        try:
            return json.loads(Path(files[-1]).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None

    def _find_relevant_req_ids(
        self, sad: Optional[dict], owned_comps: list[str], owned_ctrs: list[str]
    ) -> set[str]:
        """Find all REQ-IDs relevant to a module's owned components and contracts."""
        if not sad:
            return set()
        req_ids: set[str] = set()
        comp_set = set(owned_comps)
        ctr_set = set(owned_ctrs)

        for comp in sad.get("components", []):
            if comp.get("id") in comp_set:
                for req_id in comp.get("source_requirements", []):
                    req_ids.add(req_id)

        for ctr in sad.get("contracts", []):
            if ctr.get("id") in ctr_set:
                for req_id in ctr.get("source_requirements", []):
                    req_ids.add(req_id)

        return req_ids

    def _slice_prd(self, prd: Optional[dict], req_ids: set[str]) -> dict:
        if not prd:
            return {}
        relevant_reqs = [
            r for r in prd.get("requirements", [])
            if r.get("id") in req_ids
        ]
        relevant_story_ids: set[str] = set()
        for r in relevant_reqs:
            for us_id in r.get("related_user_stories", []):
                relevant_story_ids.add(us_id)
        relevant_stories = [
            s for s in prd.get("user_stories", [])
            if s.get("id") in relevant_story_ids
        ]
        relevant_priorities = {
            rid: prd.get("priorities", {}).get(rid, "")
            for rid in req_ids
        }
        return {
            "requirements": relevant_reqs,
            "user_stories": relevant_stories,
            "priorities": relevant_priorities,
            "open_questions": prd.get("open_questions", []),
        }

    def _slice_sad(
        self, sad: Optional[dict],
        owned_comps: list[str], owned_ctrs: list[str], consumed_ctrs: list[str],
    ) -> dict:
        if not sad:
            return {}
        comp_set = set(owned_comps)
        all_ctr_ids = set(owned_ctrs) | set(consumed_ctrs)

        relevant_comps = [
            c for c in sad.get("components", [])
            if c.get("id") in comp_set
        ]
        relevant_ctrs = [
            c for c in sad.get("contracts", [])
            if c.get("id") in all_ctr_ids
        ]
        relevant_adrs = [
            a for a in sad.get("architecture_decisions", [])
            if any(req in comp_set for req in a.get("source_requirements", []))
            or not a.get("source_requirements")
        ]
        relevant_risks = [
            r for r in sad.get("risks", [])
            if any(req in comp_set for req in r.get("related_requirements", []))
            or not r.get("related_requirements")
        ]

        return {
            "components": relevant_comps,
            "contracts": relevant_ctrs,
            "data_models": sad.get("data_models", []),
            "architecture_decisions": relevant_adrs,
            "risks": relevant_risks,
            "requirement_traceability": [
                t for t in sad.get("requirement_traceability", [])
                if (set(t.get("components", [])) & comp_set
                    or set(t.get("contracts", [])) & all_ctr_ids)
            ],
        }
