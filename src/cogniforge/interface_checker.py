"""Interface contract consistency checker.

Cross-references SAD contracts against all LLD interface definitions to detect
mismatches before the design_review gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def check(repo_path: Path) -> dict:
    """Check interface consistency between SAD contracts and LLD definitions.

    Returns a dict with keys:
        status:   "ok" if no violations, "conflict" if mismatches found
        contracts: list of all contracts checked
        violations: list of violation dicts, each with {contract, module, detail}
        warnings: list of warning dicts for non-blocking observations
    """
    sad_data = _latest_sad(repo_path)
    if not sad_data:
        return {"status": "ok", "contracts": [], "violations": [], "warnings": []}

    contracts = sad_data.get("contracts", [])
    llds = _all_llds(repo_path)

    violations: list[dict] = []
    warnings: list[dict] = []

    for c in contracts:
        provider = c.get("provider", "")
        consumers = c.get("consumers", [])
        iface_name = c.get("interface", "")
        endpoint = c.get("endpoint", "")
        expected_response = c.get("response", {}).get("body", {})
        expected_fields = set(expected_response.keys()) if isinstance(expected_response, dict) else set()

        # Check: provider LLD defines this interface
        prov_lld = _find_lld_for_module(llds, provider)
        if not prov_lld:
            violations.append({
                "contract": iface_name,
                "module": provider,
                "detail": f"Provider '{provider}' 没有 LLD 文档"
            })
            continue

        prov_ifaces = prov_lld.get("interfaces", [])
        matched = _find_matching_interface(prov_ifaces, endpoint)
        if not matched:
            violations.append({
                "contract": iface_name,
                "module": provider,
                "detail": f"LLD 未定义接口 {endpoint}（SAD 契约要求）"
            })
            continue

        # Check: provider's response fields match contract
        if expected_fields:
            actual_fields = _extract_response_fields(matched)
            missing = expected_fields - actual_fields
            extra = actual_fields - expected_fields
            if missing:
                violations.append({
                    "contract": iface_name,
                    "module": provider,
                    "detail": f"接口 {endpoint} 的 response 缺少字段: {missing}"
                })
            if extra:
                warnings.append({
                    "contract": iface_name,
                    "module": provider,
                    "detail": f"接口 {endpoint} 的 response 有契约外字段: {extra}"
                })

        # Check: each consumer has an LLD that references this interface correctly
        for consumer in consumers:
            cons_lld = _find_lld_for_module(llds, consumer)
            if not cons_lld:
                warnings.append({
                    "contract": iface_name,
                    "module": consumer,
                    "detail": f"Consumer '{consumer}' 没有 LLD 文档"
                })
                continue
            # Check if consumer LLD references the provider interface
            cons_ifaces = cons_lld.get("interfaces", [])
            if not _references_provider(cons_ifaces, provider, endpoint):
                warnings.append({
                    "contract": iface_name,
                    "module": consumer,
                    "detail": f"LLD 未引用依赖接口 {provider}::{endpoint}"
                })

    # Warn about LLD interfaces not backed by any SAD contract
    for mod_name, mod_lld in llds.items():
        for iface in mod_lld.get("interfaces", []):
            ep = iface.get("endpoint", "")
            if ep and not _has_contract(contracts, mod_name, ep):
                warnings.append({
                    "contract": iface.get("name", ep),
                    "module": mod_name,
                    "detail": f"接口 {ep} 未在 SAD contracts 中声明"
                })

    return {
        "status": "conflict" if violations else "ok",
        "contracts": contracts,
        "violations": violations,
        "warnings": warnings,
    }


def format_report(result: dict) -> str:
    """Render a human-readable consistency report."""
    lines = []
    status = result["status"]
    violations = result.get("violations", [])
    warnings = result.get("warnings", [])

    if status == "ok":
        lines.append("✓ 接口一致性检查通过")
        if not warnings:
            return "\n".join(lines)
    else:
        lines.append(f"✗ 接口一致性检查失败 — {len(violations)} 个冲突")

    if violations:
        lines.append("\n--- 冲突 (必须修复) ---")
        for v in violations:
            lines.append(f"  ✗ [{v['module']}] {v['contract']}: {v['detail']}")

    if warnings:
        lines.append(f"\n--- 警告 ({len(warnings)}) ---")
        for w in warnings:
            lines.append(f"  ⚠ [{w['module']}] {w['contract']}: {w['detail']}")

    return "\n".join(lines)


# ------------------------------------------------------------------ helpers

def _latest_sad(repo_path: Path) -> Optional[dict]:
    import glob
    pattern = str(repo_path / ".cogniforge/wiki/sad/*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    try:
        return json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except Exception:
        return None


def _all_llds(repo_path: Path) -> dict[str, dict]:
    """Return {module_name: lld_json_dict} for all LLD modules."""
    import glob
    result: dict[str, dict] = {}
    pattern = str(repo_path / ".cogniforge/wiki/lld/*/*.json")
    for fpath in sorted(glob.glob(pattern)):
        try:
            data = json.loads(Path(fpath).read_text(encoding="utf-8"))
            module = data.get("meta", {}).get("module", "unknown")
            # Only keep the latest LLD per module (last file wins on sorted glob)
            result[module] = data
        except Exception:
            pass
    return result


def _find_lld_for_module(llds: dict[str, dict], module: str) -> Optional[dict]:
    return llds.get(module)


def _find_matching_interface(interfaces: list[dict], endpoint: str) -> Optional[dict]:
    """Find interface in LLD that matches the contracted endpoint."""
    # Normalize: strip leading/trailing whitespace, lowercase for comparison
    target = endpoint.strip().lower()
    for iface in interfaces:
        if iface.get("endpoint", "").strip().lower() == target:
            return iface
    # Fallback: partial match (e.g., endpoint="/api/students" matches "GET /api/students")
    for iface in interfaces:
        if target in iface.get("endpoint", "").strip().lower():
            return iface
    return None


def _extract_response_fields(interface: dict) -> set[str]:
    """Extract field names from interface response body."""
    response = interface.get("response", {})
    body = response.get("body", {})
    if isinstance(body, dict):
        return set(body.keys())
    return set()


def _references_provider(interfaces: list[dict], provider: str, endpoint: str) -> bool:
    """Check if any interface references the given provider's endpoint."""
    target = endpoint.strip().lower()
    for iface in interfaces:
        desc = iface.get("description", "").lower()
        ep = iface.get("endpoint", "").lower()
        if provider.lower() in desc and target in desc:
            return True
        if provider.lower() in ep or target in ep:
            return True
    return False


def _has_contract(contracts: list[dict], module: str, endpoint: str) -> bool:
    """Check if an endpoint is covered by any SAD contract."""
    target = endpoint.strip().lower()
    for c in contracts:
        if c.get("endpoint", "").strip().lower() == target:
            return True
        # Also check: provider is this module and endpoint matches
        if c.get("provider") == module:
            if target in c.get("endpoint", "").strip().lower():
                return True
    return False
