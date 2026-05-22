"""LLD Artifact Registry — parses LLD JSON into an enumerable, queryable
artifact table.  Pure mechanical layer, no LLM involved."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator


@dataclass
class ArtifactEntry:
    """A single artifact extracted from an LLD document."""
    section: str              # "data_models" | "domain_objects" | "service_contracts" | ...
    item_name: str            # e.g. "SSHConnection", "KeyStorageService"
    artifact_type: str        # "data_model_table" | "domain_object_entity" | "service_contract" | ...
    item_data: dict = field(default_factory=dict)     # raw JSON fragment
    sub_items: list[str] = field(default_factory=list)  # e.g. method names, transition triggers
    ownership: str = ""       # "canonical" | "derived" | "owned"


# ── Maps each module_type to the sections it may contain ──
# Mirrors lld_validator._REQUIRED_SECTIONS but includes optional extras.

_KNOWN_SECTIONS: dict[str, list[str]] = {
    "service": [
        "data_models", "domain_objects", "service_contracts",
        "business_rules", "interfaces", "error_handling",
    ],
    "frontend": [
        "data_models", "component_tree", "state_design", "route_design",
        "interaction_flows", "api_integration", "interfaces",
    ],
    "gateway": [
        "data_models", "route_table", "middleware_chain", "auth_policy",
        "rate_limiting", "interfaces", "error_handling",
    ],
    "database": [
        "data_models", "index_strategy", "migration_strategy",
        "capacity_estimation", "connection_contracts", "interfaces",
    ],
    "infrastructure": [
        "data_models", "topology", "message_contracts", "reliability_strategy",
        "interfaces", "error_handling",
    ],
}


class LLDArtifactRegistry:
    """Parse an LLD JSON file and expose every design artifact for iteration.

    Usage::

        registry = LLDArtifactRegistry.from_lld(Path("lld-SSH连接池-001.json"))
        for entry in registry.iter_all():
            print(entry.section, entry.item_name, entry.sub_items)
        print(registry.count_by_type())
    """

    def __init__(self, module: str, module_type: str, doc_id: str):
        self.module = module
        self.module_type = module_type
        self.doc_id = doc_id
        self._entries: list[ArtifactEntry] = []

    # ── factory ────────────────────────────────────────────────────────

    @classmethod
    def from_lld(cls, source: Path | dict) -> "LLDArtifactRegistry":
        """Build registry from a file path or an already-loaded dict."""
        if isinstance(source, Path):
            data = _load_json(source)
        else:
            data = source

        meta = data.get("meta", {})
        module = meta.get("module", "unknown")
        module_type = meta.get("module_type", "service")
        doc_id = meta.get("doc_id", "")

        registry = cls(module=module, module_type=module_type, doc_id=doc_id)
        registry._parse(data)
        return registry

    # ── iteration ──────────────────────────────────────────────────────

    def iter_all(self) -> Generator[ArtifactEntry, None, None]:
        yield from self._entries

    def iter_section(self, section: str) -> Generator[ArtifactEntry, None, None]:
        for e in self._entries:
            if e.section == section:
                yield e

    def get_by_name(self, section: str, name: str) -> ArtifactEntry | None:
        for e in self._entries:
            if e.section == section and e.item_name == name:
                return e
        return None

    def list_all_refs(self) -> list[tuple[str, str]]:
        """Return every (section, item_name) pair for coverage comparison."""
        return [(e.section, e.item_name) for e in self._entries]

    def count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._entries:
            counts[e.artifact_type] = counts.get(e.artifact_type, 0) + 1
        return counts

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return (f"<LLDArtifactRegistry module={self.module!r} "
                f"type={self.module_type!r} entries={len(self._entries)}>")

    # ── internal parsing ───────────────────────────────────────────────

    def _parse(self, data: dict) -> None:
        mt = self.module_type
        known = _KNOWN_SECTIONS.get(mt, _KNOWN_SECTIONS["service"])

        for section in known:
            if section not in data or data[section] is None:
                continue
            handler = getattr(self, f"_parse_{section}", None)
            if handler:
                handler(data[section])
            else:
                # Generic fallback: treat each list item as a named artifact
                self._parse_generic_list(section, data[section])

    # ── section parsers ────────────────────────────────────────────────

    def _parse_data_models(self, items: list) -> None:
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return
        for dm in items:
            name = dm.get("name", "?")
            dtype = dm.get("type", "?")
            ownership = dm.get("ownership", "")
            atype = f"data_model_{dtype}"
            self._entries.append(ArtifactEntry(
                section="data_models", item_name=name,
                artifact_type=atype, item_data=dm,
                sub_items=[f["name"] for f in dm.get("fields", [])],
                ownership=ownership,
            ))

    def _parse_domain_objects(self, items: list) -> None:
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return
        for dobj in items:
            name = dobj.get("name", "?")
            ot = dobj.get("object_type", "?")
            atype = f"domain_object_{ot}"
            sub: list[str] = []
            if ot in ("entity", "value_object", "dto"):
                sub = [a["name"] for a in dobj.get("attributes", [])]
            elif ot == "enum":
                sub = dobj.get("values", [])
            self._entries.append(ArtifactEntry(
                section="domain_objects", item_name=name,
                artifact_type=atype, item_data=dobj, sub_items=sub,
            ))

    def _parse_service_contracts(self, items: list) -> None:
        if isinstance(items, dict):
            # Defend against LLM generating this as a dict instead of a list
            if "service" in items and isinstance(items["service"], dict):
                items = [items["service"]]
            else:
                items = [items]
        if not isinstance(items, list):
            return
        for svc in items:
            name = svc.get("name", "?")
            methods = svc.get("methods", [])
            sub = [m.get("name", "?") for m in methods]
            self._entries.append(ArtifactEntry(
                section="service_contracts", item_name=name,
                artifact_type="service_contract", item_data=svc,
                sub_items=sub,
            ))

    def _parse_business_rules(self, br: dict) -> None:
        if not isinstance(br, dict):
            return
        invariants = br.get("invariants", [])
        for i, inv in enumerate(invariants):
            label = f"invariant-{i + 1}"
            self._entries.append(ArtifactEntry(
                section="business_rules", item_name=label,
                artifact_type="business_rule_invariant",
                item_data={"rule": inv, "index": i},
            ))

        machines = br.get("state_machines", [])
        for sm in machines:
            entity = sm.get("entity", "?")
            transitions = sm.get("transitions", [])
            sub = [f"{t['from']}→{t['to']}" for t in transitions]
            self._entries.append(ArtifactEntry(
                section="business_rules", item_name=entity,
                artifact_type="state_machine", item_data=sm,
                sub_items=sub,
            ))

        cross = br.get("cross_service_rules", [])
        for i, rule in enumerate(cross):
            self._entries.append(ArtifactEntry(
                section="business_rules", item_name=f"cross-service-rule-{i + 1}",
                artifact_type="cross_service_rule",
                item_data={"rule": rule, "index": i},
            ))

    def _parse_interfaces(self, items: list) -> None:
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return
        for iface in items:
            name = iface.get("name", "?")
            method = iface.get("method", "?")
            endpoint = iface.get("endpoint", "")
            full_name = f"{method} {endpoint}" if endpoint else name
            atype = f"interface_{method.lower()}" if method else "interface"
            sub = [p["name"] for p in iface.get("parameters", [])]
            self._entries.append(ArtifactEntry(
                section="interfaces", item_name=name,
                artifact_type=atype, item_data=iface,
                sub_items=sub,
            ))

    def _parse_error_handling(self, eh: dict) -> None:
        if not isinstance(eh, dict):
            return
        cats = eh.get("categories", [])
        for cat in cats:
            code = str(cat.get("code", "?"))
            name = cat.get("name", code)
            self._entries.append(ArtifactEntry(
                section="error_handling", item_name=name,
                artifact_type="error_category", item_data=cat,
            ))

    def _parse_component_tree(self, items: list) -> None:
        for comp in items:
            self._add_component(comp)

    def _add_component(self, comp: dict) -> None:
        name = comp.get("name", "?")
        sub = [c.get("name", "?") for c in comp.get("children", [])]
        self._entries.append(ArtifactEntry(
            section="component_tree", item_name=name,
            artifact_type="component", item_data=comp, sub_items=sub,
        ))
        for child in comp.get("children", []):
            self._add_component(child)

    def _parse_route_table(self, items: list) -> None:
        for rt in items:
            path = rt.get("path_pattern", "?")
            self._entries.append(ArtifactEntry(
                section="route_table", item_name=path,
                artifact_type="route_entry", item_data=rt,
            ))

    def _parse_auth_policy(self, ap: dict) -> None:
        if not isinstance(ap, dict):
            return
        self._entries.append(ArtifactEntry(
            section="auth_policy", item_name="auth_policy",
            artifact_type="auth_policy", item_data=ap,
            sub_items=ap.get("public_endpoints", []),
        ))

    def _parse_rate_limiting(self, rl: dict) -> None:
        if not isinstance(rl, dict):
            return
        self._entries.append(ArtifactEntry(
            section="rate_limiting", item_name="rate_limiting",
            artifact_type="rate_limiting", item_data=rl,
        ))

    def _parse_index_strategy(self, items: list) -> None:
        for idx in items:
            table = idx.get("table", "?")
            self._entries.append(ArtifactEntry(
                section="index_strategy", item_name=table,
                artifact_type="index_strategy", item_data=idx,
                sub_items=[i["name"] for i in idx.get("indexes", [])],
            ))

    def _parse_topology(self, topo: dict) -> None:
        if not isinstance(topo, dict):
            return
        for ex in topo.get("exchanges", []):
            name = ex.get("name", "?")
            self._entries.append(ArtifactEntry(
                section="topology", item_name=name,
                artifact_type="exchange", item_data=ex,
            ))
        for q in topo.get("queues", []):
            name = q.get("name", "?")
            self._entries.append(ArtifactEntry(
                section="topology", item_name=name,
                artifact_type="queue", item_data=q,
            ))
        for ns in topo.get("namespaces", []):
            name = ns.get("name", "?") if isinstance(ns, dict) else str(ns)
            self._entries.append(ArtifactEntry(
                section="topology", item_name=name,
                artifact_type="namespace", item_data=ns if isinstance(ns, dict) else {},
            ))
        for b in topo.get("buckets", []):
            name = b.get("name", "?") if isinstance(b, dict) else str(b)
            self._entries.append(ArtifactEntry(
                section="topology", item_name=name,
                artifact_type="bucket", item_data=b if isinstance(b, dict) else {},
            ))

    def _parse_message_contracts(self, items: list) -> None:
        for mc in items:
            name = mc.get("name", "?")
            self._entries.append(ArtifactEntry(
                section="message_contracts", item_name=name,
                artifact_type="message_contract", item_data=mc,
            ))

    def _parse_state_design(self, sd: dict) -> None:
        if not isinstance(sd, dict):
            return
        self._entries.append(ArtifactEntry(
            section="state_design", item_name="state_design",
            artifact_type="state_design", item_data=sd,
        ))

    def _parse_route_design(self, items: list) -> None:
        for rd in items:
            path = rd.get("path", "?")
            self._entries.append(ArtifactEntry(
                section="route_design", item_name=path,
                artifact_type="route_design", item_data=rd,
            ))

    def _parse_interaction_flows(self, items: list) -> None:
        for flow in items:
            name = flow.get("name", "?")
            self._entries.append(ArtifactEntry(
                section="interaction_flows", item_name=name,
                artifact_type="interaction_flow", item_data=flow,
            ))

    def _parse_api_integration(self, items: list) -> None:
        for ai in items:
            page = ai.get("page", "?")
            endpoint = ai.get("endpoint", "")
            name = f"{page} → {endpoint}" if endpoint else page
            self._entries.append(ArtifactEntry(
                section="api_integration", item_name=name,
                artifact_type="api_integration", item_data=ai,
            ))

    def _parse_middleware_chain(self, chain: list) -> None:
        self._entries.append(ArtifactEntry(
            section="middleware_chain", item_name="middleware_chain",
            artifact_type="middleware_chain",
            item_data={"chain": chain},
        ))

    def _parse_migration_strategy(self, ms: dict) -> None:
        self._entries.append(ArtifactEntry(
            section="migration_strategy", item_name="migration_strategy",
            artifact_type="migration_strategy", item_data=ms,
        ))

    def _parse_capacity_estimation(self, ce: dict) -> None:
        self._entries.append(ArtifactEntry(
            section="capacity_estimation", item_name="capacity_estimation",
            artifact_type="capacity_estimation", item_data=ce,
        ))

    def _parse_connection_contracts(self, cc: dict) -> None:
        self._entries.append(ArtifactEntry(
            section="connection_contracts", item_name="connection_contracts",
            artifact_type="connection_contracts", item_data=cc,
        ))

    def _parse_reliability_strategy(self, rs: dict) -> None:
        self._entries.append(ArtifactEntry(
            section="reliability_strategy", item_name="reliability_strategy",
            artifact_type="reliability_strategy", item_data=rs,
        ))

    def _parse_generic_list(self, section: str, items) -> None:
        """Fallback for sections that are lists of named things."""
        if not isinstance(items, list):
            return
        for item in items:
            name = item.get("name", "?") if isinstance(item, dict) else str(item)
            self._entries.append(ArtifactEntry(
                section=section, item_name=name,
                artifact_type=section,
                item_data=item if isinstance(item, dict) else {},
            ))


def _load_json(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    from cogniforge.wiki.wiki_renderer import load_json_with_repair
    return load_json_with_repair(path)
