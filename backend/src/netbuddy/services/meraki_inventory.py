"""Meraki-Inventarabgleich über die Dashboard-API (read-only gegenüber Meraki).

Ergänzt, was die Geräte-Discovery pro Gerät nicht sieht: **Switch-Stacks** (ein Stack = ein
logischer Switch; nur ein Member trägt den LLDP-Uplink) und veraltete Mgmt-IPs/Namen (die Org
ist die Wahrheit, Match per Seriennummer). Beispiel::

    cred = ...  # Credential "MerakiCloud" (base_url, api_token, extra["org_id"])
    report = await sync_meraki_stacks(session, cred)
    # {"stacks": 14, "members_set": 41, "members_cleared": 0}
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.adapters.api_client import HttpxApiClient
from netbuddy.db.models import Device
from netbuddy.db.models.credential import Credential


async def _org_switch_stacks(client: HttpxApiClient, org_id: str) -> dict[str, str]:
    """Seriennummer → Stack-Name über alle Netze der Org (nur Netze mit Switch-Produkt)."""
    serial_to_stack: dict[str, str] = {}
    networks = await client.get_json(f"/organizations/{org_id}/networks", params={"perPage": 1000})
    for net in networks:
        if "switch" not in (net.get("productTypes") or []):
            continue
        try:
            stacks = await client.get_json(f"/networks/{net['id']}/switch/stacks")
        except Exception:  # Netz ohne Stacks/ohne Berechtigung: überspringen
            continue
        for stack in stacks or []:
            for serial in stack.get("serials") or []:
                serial_to_stack[serial] = str(stack.get("name") or stack.get("id"))
    return serial_to_stack


async def sync_meraki_stacks(session: AsyncSession, credential: Credential) -> dict[str, Any]:
    """Setzt ``Device.stack_name`` für alle Meraki-Geräte anhand der Org-Stacks (per Serial)."""
    org_id = str((credential.extra or {}).get("org_id", ""))
    async with HttpxApiClient(
        credential.base_url or "",
        token=credential.api_token,
        header_name="X-Cisco-Meraki-API-Key",
    ) as client:
        serial_to_stack = await _org_switch_stacks(client, org_id)
    devices = (
        (
            await session.execute(
                select(Device).where(Device.adapter_id == "meraki", Device.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    set_count = cleared = 0
    for device in devices:
        new = serial_to_stack.get(device.serial_number or "")
        if new != device.stack_name:
            if new is None:
                cleared += 1
            else:
                set_count += 1
            device.stack_name = new
    await session.flush()
    return {
        "stacks": len(set(serial_to_stack.values())),
        "members_set": set_count,
        "members_cleared": cleared,
    }
