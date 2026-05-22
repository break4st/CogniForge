"""Acceptance criteria extractor — pull verifiable conditions from LLD contracts.

Pure data extraction.  No LLM involved.
"""

from __future__ import annotations

from cogniforge.wbs.lld_artifact_registry import ArtifactEntry


def extract_criteria(entry: ArtifactEntry) -> list[dict]:
    """Extract verifiable acceptance criteria from an LLD artifact entry.

    Returns a list of dicts suitable for constructing AcceptanceCriterion objects.
    """
    data = entry.item_data
    criteria: list[dict] = []

    # ── service_contracts methods ──
    if entry.section == "service_contracts":
        for m in data.get("methods", []):
            mn = m.get("name", "?")
            full_name = f"{entry.item_name}.{mn}"

            if m.get("precondition"):
                criteria.append({
                    "source_section": entry.section,
                    "source_item": full_name,
                    "description": m["precondition"],
                    "verification_type": "precondition",
                    "expected": m["precondition"],
                })

            if m.get("postcondition"):
                criteria.append({
                    "source_section": entry.section,
                    "source_item": full_name,
                    "description": m["postcondition"],
                    "verification_type": "postcondition",
                    "expected": m["postcondition"],
                })

            for exc in m.get("exceptions", []):
                criteria.append({
                    "source_section": entry.section,
                    "source_item": full_name,
                    "description": f"异常 {exc.get('name','')}: HTTP {exc.get('http_status','')} — {exc.get('trigger','')}",
                    "verification_type": "http_status",
                    "expected": str(exc.get("http_status", "")),
                })

    # ── interfaces ──
    elif entry.section == "interfaces":
        resp = data.get("response", {})
        if resp.get("status"):
            criteria.append({
                "source_section": entry.section,
                "source_item": entry.item_name,
                "description": f"{data.get('method','')} {data.get('endpoint','')} 返回 {resp['status']}",
                "verification_type": "http_status",
                "expected": str(resp["status"]),
            })

        for ec in data.get("error_codes", []):
            criteria.append({
                "source_section": entry.section,
                "source_item": entry.item_name,
                "description": f"错误码 {ec.get('code','')}: {ec.get('message','')}",
                "verification_type": "http_status",
                "expected": str(ec.get("code", "")),
            })

    # ── business_rules invariants ──
    elif entry.section == "business_rules":
        if entry.artifact_type == "business_rule_invariant":
            rule_text = entry.item_data.get("rule", "")
            criteria.append({
                "source_section": entry.section,
                "source_item": entry.item_name,
                "description": rule_text,
                "verification_type": "invariant",
                "expected": rule_text,
            })

        elif entry.artifact_type == "state_machine":
            for t in entry.item_data.get("transitions", []):
                trigger = t.get("trigger", "")
                criteria.append({
                    "source_section": entry.section,
                    "source_item": entry.item_name,
                    "description": f"状态转换 {t.get('from','')}→{t.get('to','')}: {trigger}",
                    "verification_type": "state_transition",
                    "expected": f"{t.get('from','')}→{t.get('to','')}",
                })

    # ── data_models fields ──
    elif entry.section == "data_models":
        for f in data.get("fields", []):
            criteria.append({
                "source_section": entry.section,
                "source_item": entry.item_name,
                "description": f"字段 {f.get('name','')}: {f.get('type','')}, required={f.get('required', False)}",
                "verification_type": "field_definition",
                "expected": f"{f.get('name','')}:{f.get('type','')}",
            })

    # ── error_handling ──
    elif entry.section == "error_handling":
        criteria.append({
            "source_section": entry.section,
            "source_item": entry.item_name,
            "description": f"{entry.item_name}: {data.get('description','')}",
            "verification_type": "http_status",
            "expected": str(data.get("code", "")),
        })

    return criteria


def extract_all(registry) -> list[dict]:
    """Extract acceptance criteria from every artifact in a registry.

    Returns a flat list of criterion dicts keyed by (section, item_name).
    """
    all_criteria: list[dict] = []
    for entry in registry.iter_all():
        all_criteria.extend(extract_criteria(entry))
    return all_criteria
