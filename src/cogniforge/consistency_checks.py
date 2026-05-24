"""PRD ↔ SAD cross-document consistency checks.

JSON Schema alone cannot catch cross-document violations (e.g. a
contract references a component ID that does not exist).  This module
provides programmatic checks that the orchestrator runs before
committing an updated SAD.
"""

from __future__ import annotations

from typing import List


def run_all(prd: dict, sad: dict, sad_before: dict | None = None) -> List[str]:
    """Run all consistency checks.  Returns a list of error messages (empty = valid)."""
    errors: List[str] = []
    errors.extend(check_traceability_coverage(prd, sad))
    errors.extend(check_component_requirements_exist(prd, sad))
    errors.extend(check_contract_requirements_exist(prd, sad))
    errors.extend(check_contract_provider_exists(sad))
    errors.extend(check_active_contracts_complete(sad))
    errors.extend(check_no_duplicate_endpoints(sad))
    errors.extend(check_version_incremented(sad, sad_before))
    errors.extend(check_source_prd_version(prd, sad))
    return errors


# ---------------------------------------------------------------------------
# 1. Every active requirement must appear in requirement_traceability
# ---------------------------------------------------------------------------

def check_traceability_coverage(prd: dict, sad: dict) -> List[str]:
    errors = []
    trace_map = _build_trace_map(sad)
    for req in prd.get("requirements", []):
        if req.get("status", "draft") in ("active", "changed"):
            req_id = req.get("id", "")
            if req_id and req_id not in trace_map:
                errors.append(
                    f"Active requirement {req_id} is missing from "
                    f"SAD requirement_traceability"
                )
    return errors


# ---------------------------------------------------------------------------
# 2. Source requirements referenced by components must exist in PRD
# ---------------------------------------------------------------------------

def check_component_requirements_exist(prd: dict, sad: dict) -> List[str]:
    errors = []
    prd_req_ids = {r.get("id") for r in prd.get("requirements", []) if r.get("id")}
    for comp in sad.get("components", []):
        for req_id in comp.get("source_requirements", []):
            if req_id not in prd_req_ids:
                errors.append(
                    f"Component {comp.get('id', '?')} references unknown "
                    f"requirement {req_id}"
                )
    return errors


# ---------------------------------------------------------------------------
# 3. Source requirements referenced by contracts must exist in PRD
# ---------------------------------------------------------------------------

def check_contract_requirements_exist(prd: dict, sad: dict) -> List[str]:
    errors = []
    prd_req_ids = {r.get("id") for r in prd.get("requirements", []) if r.get("id")}
    for ctr in sad.get("contracts", []):
        for req_id in ctr.get("source_requirements", []):
            if req_id not in prd_req_ids:
                errors.append(
                    f"Contract {ctr.get('id', '?')} references unknown "
                    f"requirement {req_id}"
                )
    return errors


# ---------------------------------------------------------------------------
# 4. Every active contract's provider_component_id must exist
# ---------------------------------------------------------------------------

def check_contract_provider_exists(sad: dict) -> List[str]:
    errors = []
    comp_ids = {c.get("id") for c in sad.get("components", []) if c.get("id")}
    for ctr in sad.get("contracts", []):
        pid = ctr.get("provider_component_id", "")
        if pid and pid not in comp_ids:
            errors.append(
                f"Contract {ctr.get('id', '?')} references non-existent "
                f"provider_component_id {pid}"
            )
    return errors


# ---------------------------------------------------------------------------
# 5. Active contracts must have request, response and description
# ---------------------------------------------------------------------------

def check_active_contracts_complete(sad: dict) -> List[str]:
    errors = []
    for ctr in sad.get("contracts", []):
        status = ctr.get("status", "active")
        if status in ("active", "changed"):
            cid = ctr.get("id", "?")
            if not ctr.get("request"):
                errors.append(f"Active contract {cid} has no request definition")
            if not ctr.get("response"):
                errors.append(f"Active contract {cid} has no response definition")
            if not ctr.get("description"):
                errors.append(f"Active contract {cid} has no description")
    return errors


# ---------------------------------------------------------------------------
# 6. No duplicate active endpoint + method combinations
# ---------------------------------------------------------------------------

def check_no_duplicate_endpoints(sad: dict) -> List[str]:
    errors = []
    seen: dict[str, str] = {}  # endpoint → contract_id
    for ctr in sad.get("contracts", []):
        status = ctr.get("status", "active")
        if status in ("active", "changed"):
            ep = ctr.get("endpoint", "")
            cid = ctr.get("id", "?")
            if ep:
                if ep in seen:
                    errors.append(
                        f"Duplicate endpoint '{ep}' on contracts "
                        f"{seen[ep]} and {cid}"
                    )
                else:
                    seen[ep] = cid
    return errors


# ---------------------------------------------------------------------------
# 7. SAD meta.version must be incremented when doc changed
# ---------------------------------------------------------------------------

def check_version_incremented(sad: dict, sad_before: dict | None = None) -> List[str]:
    if sad_before is None:
        return []
    before_ver = sad_before.get("meta", {}).get("version", 0)
    after_ver = sad.get("meta", {}).get("version", 0)
    if after_ver != before_ver + 1:
        return [
            f"SAD version should increment from {before_ver} to {before_ver + 1}, "
            f"but got {after_ver}"
        ]
    return []


# ---------------------------------------------------------------------------
# 8. SAD source_prd.version must equal current PRD version
# ---------------------------------------------------------------------------

def check_source_prd_version(prd: dict, sad: dict) -> List[str]:
    sp = sad.get("source_prd", {})
    if not sp:
        return []
    sad_prd_ver = sp.get("version")
    prd_ver = prd.get("meta", {}).get("version")
    if sad_prd_ver is not None and prd_ver is not None and sad_prd_ver != prd_ver:
        return [
            f"SAD source_prd.version ({sad_prd_ver}) does not match "
            f"PRD version ({prd_ver})"
        ]
    return []


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_trace_map(sad: dict) -> dict[str, dict]:
    """Build {REQ-ID: trace_entry} lookup."""
    trace: dict[str, dict] = {}
    for entry in sad.get("requirement_traceability", []):
        rid = entry.get("requirement_id", "")
        if rid:
            trace[rid] = entry
    return trace
