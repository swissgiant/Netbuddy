# ruff: noqa: E501 — GraphQL-Feldlisten bleiben am Stück lesbar
"""Cato-Policies lesen (read-only): Internet-Firewall, WAN-Firewall, Socket-LAN-Firewall,
Socket-Bypass und WAN-Network-Regeln — vereinheitlicht als :class:`CatoRule`.

Die fünf Policy-Typen haben in der GraphQL-API unterschiedliche Formen (WAN/Internet: flache Regeln
mit Quelle/Ziel/App/Service; Socket-LAN: Site-gebundene Regeln mit Firewall-Subregeln; Bypass:
Site-gebundene Ausnahmen, deren Traffic am Cato-Tunnel vorbeigeht; WAN-Network: Routing-/QoS-
Regeln). Hier werden sie in ein gemeinsames Zeilenformat gebracht, damit UI und Analyse eine
einzige Tabelle haben. Nichts wird geschrieben.
"""

from typing import Any, Literal

from pydantic import BaseModel

from netbuddy.services.cato_inventory import CatoApi

PolicyKind = Literal["internet", "wan", "lan", "bypass", "wan_network"]

_REF = (
    "{ host { name } site { name } subnet ip ipRange { from to } globalIpRange { name } "
    "networkInterface { name } siteNetworkSubnet { name } floatingSubnet { name } user { name } "
    "usersGroup { name } group { name } systemGroup { name } }"
)
_APP = (
    "{ application { name } appCategory { name } customApp { name } customCategory { name } "
    "sanctionedAppsCategory { name } domain fqdn ip subnet ipRange { from to } globalIpRange { name } }"
)
_SVC_STD = "{ standard { name } custom { port portRange { from to } protocol } }"
_SVC_SIMPLE = "{ simple { name } custom { port portRange { from to } protocol } }"
_SVC_LAN = "{ simple { name } standard { name } custom { port portRange { from to } protocol } }"
_LAN_REF = (
    "{ vlan ipRange { from to } group { name } subnet networkInterface { name } systemGroup { name } "
    "host { name } ip globalIpRange { name } floatingSubnet { name } siteNetworkSubnet { name } }"
)
_LAN_FW_SRC = (
    "{ vlan mac ipRange { from to } group { name } subnet site { name } networkInterface { name } "
    "systemGroup { name } host { name } ip globalIpRange { name } floatingSubnet { name } "
    "siteNetworkSubnet { name } }"
)
_LAN_FW_DST = (
    "{ vlan ipRange { from to } subnet site { name } networkInterface { name } systemGroup { name } "
    "host { name } ip globalIpRange { name } group { name } floatingSubnet { name } "
    "siteNetworkSubnet { name } }"
)
_LAN_APP = (
    "{ application { name } customApp { name } domain fqdn ip subnet ipRange { from to } "
    "globalIpRange { name } }"
)
_INET_DST = (
    "{ application { name } customApp { name } appCategory { name } customCategory { name } "
    "sanctionedAppsCategory { name } country { name } domain fqdn ip subnet ipRange { from to } "
    "globalIpRange { name } remoteAsn }"
)
_BYP_SRC = (
    "{ ipRange { from to } group { name } subnet ip floatingSubnet { name } globalIpRange { name } "
    "vlan networkInterface { name } host { name } siteNetworkSubnet { name } }"
)
_BYP_DST = (
    "{ application { name } customApp { name } domain fqdn ipRange { from to } subnet ip "
    "globalIpRange { name } }"
)
_WN_REF = (
    "{ user { name } floatingSubnet { name } globalIpRange { name } group { name } host { name } ip "
    "ipRange { from to } networkInterface { name } subnet site { name } siteNetworkSubnet { name } "
    "systemGroup { name } usersGroup { name } }"
)
_WN_APP = (
    "{ application { name } appCategory { name } customApp { name } customCategory { name } "
    "customServiceIp { name ip } customService { port portRange { from to } protocol } domain fqdn "
    "service { name } }"
)
_SITE = "{ site { name } group { name } }"
_AUDIT = "audit { publishedTime publishedBy }"

_QUERIES: dict[PolicyKind, str] = {
    "wan": f"""query wanFw($a: ID!) {{ policy(accountId: $a) {{ wanFirewall {{ policy {{ enabled {_AUDIT}
      rules {{ rule {{ id name description index enabled section {{ name }} direction action connectionOrigin
        source {_REF} destination {_REF} application {_APP} service {_SVC_STD}
        tracking {{ event {{ enabled }} }} exceptions {{ name }} }} }} }} }} }} }}""",
    "internet": f"""query inetFw($a: ID!) {{ policy(accountId: $a) {{ internetFirewall {{ policy {{ enabled {_AUDIT}
      rules {{ rule {{ id name description index enabled section {{ name }} action connectionOrigin
        source {_REF} destination {_INET_DST} service {_SVC_STD}
        tracking {{ event {{ enabled }} }} exceptions {{ name }} }} }} }} }} }} }}""",
    "lan": f"""query lanFw($a: ID!) {{ policy(accountId: $a) {{ socketLan {{ policy {{ enabled {_AUDIT}
      rules {{ rule {{ id name description index enabled section {{ name }} site {_SITE}
        source {_LAN_REF} destination {_LAN_REF} direction service {_SVC_SIMPLE}
        nat {{ enabled natType }} transport
        firewall {{ rule {{ id name description index enabled section {{ name }}
          source {_LAN_FW_SRC} destination {_LAN_FW_DST} direction application {_LAN_APP}
          service {_SVC_LAN} action tracking {{ event {{ enabled }} }} }} }} }} }} }} }} }} }}""",
    "bypass": f"""query bypass($a: ID!) {{ policy(accountId: $a) {{ socketBypass {{ policy {{ enabled {_AUDIT}
      rules {{ rule {{ id name description index enabled section {{ name }} site {_SITE}
        source {_BYP_SRC} destination {_BYP_DST} service {_SVC_SIMPLE}
        action {{ port event {{ enabled }} }} exception {{ name }} }} }} }} }} }} }}""",
    "wan_network": f"""query wanNet($a: ID!) {{ policy(accountId: $a) {{ wanNetwork {{ policy {{ enabled {_AUDIT}
      rules {{ rule {{ id name description index enabled section {{ name }} ruleType routeType
        source {_WN_REF} destination {_WN_REF} application {_WN_APP}
        configuration {{ activeTcpAcceleration packetLossMitigation preserveSourcePort
          primaryTransport {{ transportType primaryInterfaceRole secondaryInterfaceRole }}
          secondaryTransport {{ transportType primaryInterfaceRole secondaryInterfaceRole }}
          popLocation {{ name }} backhaulingSite {{ name }} }}
        bandwidthPriority {{ name }} exceptions {{ name }} }} }} }} }} }} }}""",
}
_ROOT: dict[PolicyKind, str] = {
    "wan": "wanFirewall",
    "internet": "internetFirewall",
    "lan": "socketLan",
    "bypass": "socketBypass",
    "wan_network": "wanNetwork",
}


class CatoRule(BaseModel):
    kind: PolicyKind
    index: int | None
    name: str
    description: str | None = None
    section: str | None
    enabled: bool
    action: str | None  # ALLOW/BLOCK/PROMPT, BYPASS, Route-Typ
    direction: str | None
    sites: str | None  # Site-Bindung (LAN/Bypass)
    source: str
    destination: str
    application: str | None
    service: str | None
    extra: str | None  # NAT/Transport/Konfiguration/Ausnahmen


class CatoPolicy(BaseModel):
    kind: PolicyKind
    enabled: bool | None
    published_at: str | None
    published_by: str | None
    rules: list[CatoRule]


def _val(x: Any) -> str:
    if isinstance(x, dict):
        if "name" in x and x["name"] is not None:
            return str(x["name"])
        if "from" in x:
            return f"{x.get('from')}-{x.get('to')}"
        if "port" in x or "portRange" in x:
            proto = x.get("protocol") or ""
            port = x.get("port") or x.get("portRange")
            return f"{proto}/{_val(port)}"
        return ",".join(f"{k}={_val(v)}" for k, v in x.items() if v not in (None, "", [], {}))
    if isinstance(x, list):
        return ",".join(_val(i) for i in x)
    return str(x)


def ref(obj: dict[str, Any] | None) -> str:
    """Quelle/Ziel/App als kompakte Zeile: ``site:BLS user:Alex ip:10.1.2.3`` — leer = ``any``."""
    if not obj:
        return "any"
    parts = [f"{k}:{_val(v)}" for k, v in obj.items() if v not in (None, "", [], {}, False)]
    return " ".join(parts) or "any"


def _svc(obj: dict[str, Any] | None) -> str | None:
    if not obj:
        return None
    out = [_val(x) for key in ("simple", "standard") for x in (obj.get(key) or [])]
    out += [_val(c) for c in (obj.get("custom") or [])]
    return ",".join(out) or None


def _audit(policy: dict[str, Any]) -> tuple[str | None, str | None]:
    audit = policy.get("audit") or {}
    return audit.get("publishedTime"), audit.get("publishedBy")


def _flat_rule(kind: PolicyKind, r: dict[str, Any], **over: Any) -> CatoRule:
    exc = [e.get("name") for e in (r.get("exceptions") or r.get("exception") or []) if e]
    extra_parts = [f"ausnahmen:{','.join(map(str, exc))}"] if exc else []
    if r.get("connectionOrigin") and r["connectionOrigin"] != "ANY":
        extra_parts.append(f"origin:{r['connectionOrigin']}")
    if (r.get("tracking") or {}).get("event", {}).get("enabled") is False:
        extra_parts.append("kein-log")
    base: dict[str, Any] = {
        "kind": kind,
        "index": r.get("index"),
        "name": r.get("name") or "",
        "description": r.get("description") or None,
        "section": (r.get("section") or {}).get("name"),
        "enabled": bool(r.get("enabled")),
        "action": r.get("action") if isinstance(r.get("action"), str) else None,
        "direction": r.get("direction"),
        "sites": ref(r.get("site")) if r.get("site") else None,
        "source": ref(r.get("source")),
        "destination": ref(r.get("destination")),
        "application": ref(r["application"]) if r.get("application") else None,
        "service": _svc(r.get("service")),
        "extra": " ".join(extra_parts) or None,
    }
    base.update(over)
    if base["application"] == "any":
        base["application"] = None
    return CatoRule(**base)


def parse_policy(kind: PolicyKind, data: dict[str, Any]) -> CatoPolicy:
    policy = ((data.get("policy") or {}).get(_ROOT[kind]) or {}).get("policy") or {}
    published_at, published_by = _audit(policy)
    rules: list[CatoRule] = []
    for wrapper in policy.get("rules") or []:
        r = wrapper.get("rule") or {}
        if kind == "lan":
            nat = r.get("nat") or {}
            extra = " ".join(
                p
                for p in (
                    f"nat:{nat.get('natType')}" if nat.get("enabled") else "",
                    f"transport:{r['transport']}" if r.get("transport") else "",
                )
                if p
            )
            rules.append(_flat_rule(kind, r, action="LAN-REGEL", extra=extra or None))
            fw = r.get("firewall") or []
            subs = fw.get("rule") or [] if isinstance(fw, dict) else fw
            for wrapper in subs:
                sub = wrapper.get("rule", wrapper) if isinstance(wrapper, dict) else {}
                rules.append(
                    _flat_rule(
                        kind,
                        sub,
                        name=f"{r.get('name') or ''} / {sub.get('name') or ''}",
                        sites=ref(r.get("site")) if r.get("site") else None,
                        section=(r.get("section") or {}).get("name"),
                    )
                )
        elif kind == "bypass":
            act = r.get("action") or {}
            rules.append(_flat_rule(kind, r, action=f"BYPASS {act.get('port') or ''}".strip()))
        elif kind == "wan_network":
            cfg = r.get("configuration") or {}
            pt = cfg.get("primaryTransport") or {}
            st = cfg.get("secondaryTransport") or {}
            extra = " ".join(
                p
                for p in (
                    f"typ:{r.get('ruleType')}" if r.get("ruleType") else "",
                    f"transport:{pt.get('transportType')}/{pt.get('primaryInterfaceRole')}"
                    if pt.get("transportType")
                    else "",
                    f"sekundär:{st.get('transportType')}/{st.get('primaryInterfaceRole')}"
                    if st.get("transportType")
                    else "",
                    f"pop:{(cfg.get('popLocation') or {}).get('name')}"
                    if cfg.get("popLocation")
                    else "",
                    f"backhaul:{(cfg.get('backhaulingSite') or {}).get('name')}"
                    if cfg.get("backhaulingSite")
                    else "",
                    f"prio:{(r.get('bandwidthPriority') or {}).get('name')}"
                    if r.get("bandwidthPriority")
                    else "",
                    "tcp-accel" if cfg.get("activeTcpAcceleration") else "",
                    "loss-mitigation" if cfg.get("packetLossMitigation") else "",
                )
                if p
            )
            rules.append(_flat_rule(kind, r, action=r.get("routeType"), extra=extra or None))
        else:
            rules.append(_flat_rule(kind, r))
    return CatoPolicy(
        kind=kind,
        enabled=policy.get("enabled"),
        published_at=published_at,
        published_by=published_by,
        rules=rules,
    )


async def fetch_policy(api: CatoApi, kind: PolicyKind) -> CatoPolicy:
    """Eine Policy komplett lesen (Cato liefert alle Regeln in einem Aufruf)."""
    return parse_policy(kind, await api.query(_QUERIES[kind], {"a": api.account_id}))
