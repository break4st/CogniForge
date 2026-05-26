"""Interface contract consistency checker.

Cross-references SAD contracts against all LLD interface definitions to detect
mismatches before the design_review gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from cogniforge.core.constants import ModuleType
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


def check_data_models(repo_path: Path) -> dict:
    """Check data model ownership consistency across all LLDs.

    Validates:
      - Only ``module_type=database`` modules use ``ownership=canonical`` on tables
      - All ``ownership=derived`` models have valid ``source`` references
      - No two modules claim ``canonical`` ownership of the same model name
      - ``source`` references point to existing documents and model names
    """
    llds = _all_llds(repo_path)
    violations: list[dict] = []
    canonical_models: dict[str, str] = {}  # model_name -> module

    for mod_name, mod_lld in llds.items():
        meta = mod_lld.get("meta", {})
        mod_type = meta.get("module_type", "service")

        for dm in mod_lld.get("data_models", []):
            model_name = dm.get("name", "?")
            dm_type = dm.get("type", "")
            ownership = dm.get("ownership", "")

            # Rule 1: only database modules can declare canonical tables
            if ownership == "canonical" and dm_type == "table" and mod_type != ModuleType.DATABASE:
                violations.append({
                    "contract": model_name,
                    "module": mod_name,
                    "detail": (
                        f"module_type={mod_type} 不可对 table '{model_name}' 使用 "
                        f"ownership=canonical。仅 module_type=database 有此权限。"
                        f"应改为 type=reference + ownership=derived + source 指向 Primary Database LLD"
                    ),
                })

            # Rule 2: canonical name must be unique across all modules
            if ownership == "canonical":
                if model_name in canonical_models:
                    violations.append({
                        "contract": model_name,
                        "module": mod_name,
                        "detail": (
                            f"模型 '{model_name}' 已被 '{canonical_models[model_name]}' 声明为 canonical。"
                            f"每个模型名只能有一个 canonical 定义"
                        ),
                    })
                else:
                    canonical_models[model_name] = mod_name

            # Rule 3: derived models must have a valid source
            if ownership == "derived":
                source = dm.get("source")
                if not source or not isinstance(source, dict):
                    violations.append({
                        "contract": model_name,
                        "module": mod_name,
                        "detail": (
                            f"模型 '{model_name}' ownership=derived 但缺少 source 字段。"
                            f"必须提供 {{doc_id, model_name}} 指向 canonical 定义"
                        ),
                    })
                    continue

                src_doc_id = source.get("doc_id", "")
                src_model = source.get("model_name", "")
                if not src_doc_id or not src_model:
                    violations.append({
                        "contract": model_name,
                        "module": mod_name,
                        "detail": (
                            f"模型 '{model_name}' 的 source 不完整，需要 doc_id 和 model_name"
                        ),
                    })
                    continue

                # Verify source doc exists
                target_lld = _find_lld_by_doc_id(llds, src_doc_id)
                if not target_lld:
                    violations.append({
                        "contract": model_name,
                        "module": mod_name,
                        "detail": (
                            f"模型 '{model_name}' 引用的 source.doc_id='{src_doc_id}' 不存在"
                        ),
                    })
                    continue

                # Verify source model exists in target
                target_models = target_lld.get("data_models", [])
                if not any(m.get("name") == src_model for m in target_models):
                    violations.append({
                        "contract": model_name,
                        "module": mod_name,
                        "detail": (
                            f"模型 '{model_name}' 引用的 source.model_name='{src_model}' "
                            f"在 '{src_doc_id}' 中不存在"
                        ),
                    })

    return {
        "status": "conflict" if violations else "ok",
        "violations": violations,
        "canonical_models": canonical_models,
    }


def format_data_model_report(result: dict) -> str:
    """Render a human-readable data model ownership report."""
    lines = []
    status = result["status"]
    violations = result.get("violations", [])
    canonical = result.get("canonical_models", {})

    if status == "ok":
        lines.append("✓ 数据模型所有权检查通过")
    else:
        lines.append(f"✗ 数据模型所有权检查失败 — {len(violations)} 个冲突")

    if canonical:
        lines.append(f"\n权威模型注册表 ({len(canonical)}):")
        for name, mod in sorted(canonical.items()):
            lines.append(f"  • {name} → {mod}")

    if violations:
        lines.append("\n--- 冲突 (必须修复) ---")
        for v in violations:
            lines.append(f"  ✗ [{v['module']}] {v['contract']}: {v['detail']}")

    return "\n".join(lines)


def _find_lld_by_doc_id(llds: dict[str, dict], doc_id: str) -> dict | None:
    """Find an LLD dict by its meta.doc_id."""
    target = doc_id.strip()
    for mod_lld in llds.values():
        if mod_lld.get("meta", {}).get("doc_id", "") == target:
            return mod_lld
    return None


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


# =============================================================================
# Cross-LLD consistency checks
# =============================================================================


def _latest_prd(repo_path: Path) -> Optional[dict]:
    import glob
    pattern = str(repo_path / ".cogniforge/wiki/prd/*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    try:
        return json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except Exception:
        return None


def _scan_lld_module_names(repo_path: Path) -> set[str]:
    """Scan all LLD files and return the set of registered module names."""
    import glob as _glob
    pattern = str(repo_path / ".cogniforge" / "wiki" / "lld" / "*" / "lld-*.json")
    names: set[str] = set()
    for fpath in sorted(_glob.glob(pattern)):
        try:
            data = json.loads(Path(fpath).read_text(encoding="utf-8"))
            mod = data.get("meta", {}).get("module", "")
            if mod:
                names.add(mod)
        except Exception:
            pass
    return names


def _merge_results(violations: list, warnings: list, result: dict) -> None:
    violations.extend(result.get("violations", []))
    warnings.extend(result.get("warnings", []))


# ------------------------------------------------------------------ sub-check 1

def _check_lld_prd_version(llds: dict[str, dict], prd_ver) -> dict:
    violations = []
    for mod_name, mod_lld in llds.items():
        source_prd = mod_lld.get("source", {}).get("prd", {})
        lld_prd_ver = source_prd.get("version")
        if lld_prd_ver is not None and lld_prd_ver != prd_ver:
            violations.append({
                "contract": "source.prd.version",
                "module": mod_name,
                "detail": (
                    f"LLD 'source.prd.version' ({lld_prd_ver}) 不等于 "
                    f"当前 PRD version ({prd_ver})"
                ),
            })
    return {"violations": violations, "warnings": []}


# ------------------------------------------------------------------ sub-check 2

def _check_lld_sad_version(llds: dict[str, dict], sad_ver) -> dict:
    violations = []
    for mod_name, mod_lld in llds.items():
        source_sad = mod_lld.get("source", {}).get("sad", {})
        lld_sad_ver = source_sad.get("version")
        if lld_sad_ver is not None and lld_sad_ver != sad_ver:
            violations.append({
                "contract": "source.sad.version",
                "module": mod_name,
                "detail": (
                    f"LLD 'source.sad.version' ({lld_sad_ver}) 不等于 "
                    f"当前 SAD version ({sad_ver})"
                ),
            })
    return {"violations": violations, "warnings": []}


# ------------------------------------------------------------------ sub-check 3

def _check_endpoint_ownership(llds: dict[str, dict]) -> dict:
    violations = []
    endpoint_to_module: dict[str, str] = {}
    for mod_name, mod_lld in llds.items():
        meta = mod_lld.get("meta", {})
        if meta.get("module_type") != "service":
            continue
        for iface in mod_lld.get("interfaces", []):
            if iface.get("status", "active") not in ("active", "changed"):
                continue
            ep = iface.get("endpoint", "")
            if not ep:
                continue
            if ep in endpoint_to_module:
                violations.append({
                    "contract": ep,
                    "module": mod_name,
                    "detail": (
                        f"Endpoint '{ep}' 被多个 service LLD 同时声明为活动接口: "
                        f"'{endpoint_to_module[ep]}' 和 '{mod_name}'"
                    ),
                })
            else:
                endpoint_to_module[ep] = mod_name
    return {"violations": violations, "warnings": []}


# ------------------------------------------------------------------ sub-check 4

def _check_frontend_contract_refs(llds: dict[str, dict],
                                  sad_contract_ids: set[str]) -> dict:
    violations = []
    for mod_name, mod_lld in llds.items():
        meta = mod_lld.get("meta", {})
        if meta.get("module_type") != "frontend":
            continue
        for entry in mod_lld.get("api_integration", []):
            ctr_id = entry.get("source_contract_id", "")
            if ctr_id and ctr_id not in sad_contract_ids:
                violations.append({
                    "contract": ctr_id,
                    "module": mod_name,
                    "detail": (
                        f"前端模块 api_integration 引用的 source_contract_id "
                        f"'{ctr_id}' 在 SAD contracts 中不存在"
                    ),
                })
    return {"violations": violations, "warnings": []}


# ------------------------------------------------------------------ sub-check 5

def _check_db_contract_refs(llds: dict[str, dict],
                            registry_modules: set[str]) -> dict:
    violations = []
    for mod_name, mod_lld in llds.items():
        meta = mod_lld.get("meta", {})
        if meta.get("module_type") not in ("database", "infrastructure"):
            continue
        cc = mod_lld.get("connection_contracts", {})
        if not isinstance(cc, dict):
            continue
        # service_accounts[].service
        for sa in cc.get("service_accounts", []):
            if not isinstance(sa, dict):
                continue
            svc = sa.get("service", "")
            if svc and svc not in registry_modules:
                violations.append({
                    "contract": svc,
                    "module": mod_name,
                    "detail": (
                        f"connection_contracts.service_accounts 引用服务 "
                        f"'{svc}'，但该模块在 module_registry 中不存在"
                    ),
                })
        # direct consumer_module field
        cm = cc.get("consumer_module", "")
        if isinstance(cm, str) and cm and cm not in registry_modules:
            violations.append({
                "contract": cm,
                "module": mod_name,
                "detail": (
                    f"connection_contracts.consumer_module 引用模块 "
                    f"'{cm}'，但该模块在 module_registry 中不存在"
                ),
            })
    return {"violations": violations, "warnings": []}


# ------------------------------------------------------------------ orchestrator

def check_cross_lld(repo_path: Path) -> dict:
    """Run all cross-LLD consistency checks.

    Returns:
        {"status": "ok"|"conflict", "violations": list, "warnings": list}
    """
    llds = _all_llds(repo_path)
    prd = _latest_prd(repo_path)
    sad = _latest_sad(repo_path)
    registry_modules = _scan_lld_module_names(repo_path)

    all_violations: list[dict] = []
    all_warnings: list[dict] = []

    if prd:
        prd_ver = prd.get("meta", {}).get("version")
        r = _check_lld_prd_version(llds, prd_ver)
        _merge_results(all_violations, all_warnings, r)

    if sad:
        sad_ver = sad.get("meta", {}).get("version")
        r = _check_lld_sad_version(llds, sad_ver)
        _merge_results(all_violations, all_warnings, r)

    r = _check_endpoint_ownership(llds)
    _merge_results(all_violations, all_warnings, r)

    if sad:
        sad_contract_ids = {c.get("id") for c in sad.get("contracts", []) if c.get("id")}
        r = _check_frontend_contract_refs(llds, sad_contract_ids)
        _merge_results(all_violations, all_warnings, r)

    if registry_modules:
        r = _check_db_contract_refs(llds, registry_modules)
        _merge_results(all_violations, all_warnings, r)

    return {
        "status": "conflict" if all_violations else "ok",
        "violations": all_violations,
        "warnings": all_warnings,
    }


def format_cross_lld_report(result: dict) -> str:
    """Render a human-readable cross-LLD consistency report."""
    lines = []
    status = result["status"]
    violations = result.get("violations", [])
    warnings = result.get("warnings", [])

    if status == "ok":
        lines.append("✓ 跨 LLD 一致性检查通过")
        if not warnings:
            return "\n".join(lines)
    else:
        lines.append(f"✗ 跨 LLD 一致性检查失败 — {len(violations)} 个冲突")

    if violations:
        lines.append("\n--- 冲突 (必须修复) ---")
        for v in violations:
            lines.append(f"  ✗ [{v['module']}] {v['contract']}: {v['detail']}")

    if warnings:
        lines.append(f"\n--- 警告 ({len(warnings)}) ---")
        for w in warnings:
            lines.append(f"  ⚠ [{w['module']}] {w['contract']}: {w['detail']}")

    return "\n".join(lines)
