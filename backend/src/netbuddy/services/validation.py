import enum

from pydantic import BaseModel

from netbuddy.adapters.base import SwitchAdapter
from netbuddy.adapters.capabilities import Capability
from netbuddy.adapters.connection import params_from_credential
from netbuddy.adapters.registry import build_adapter
from netbuddy.adapters.scrapli_transport import ScrapliTransport
from netbuddy.adapters.transport import RecordingTransport
from netbuddy.db.models import Credential, Device


class CapabilityStatus(enum.StrEnum):
    OK = "ok"  # ≥1 gültiges DTO geparst
    EMPTY = "empty"  # Befehl lief, aber 0 Zeilen geparst
    ERROR = "error"  # Transport-/Parse-/Validierungsfehler


# Capability → (Adapter-Methode, ist Liste?)
_METHODS: dict[Capability, tuple[str, bool]] = {
    Capability.READ_SYSTEM_INFO: ("get_system_info", False),
    Capability.READ_INTERFACES: ("get_interfaces", True),
    Capability.READ_LLDP: ("get_lldp_neighbors", True),
    Capability.READ_MAC_TABLE: ("get_mac_table", True),
    Capability.READ_ARP: ("get_arp", True),
}


class CapabilityReport(BaseModel):
    """Validierungs-Ergebnis einer einzelnen Capability."""

    capability: Capability
    status: CapabilityStatus
    row_count: int
    coverage: dict[str, float]  # DTO-Feld → Anteil befüllter Zeilen (0..1)
    message: str | None = None


class DeviceValidationReport(BaseModel):
    """Gesamtergebnis einer Validierung über alle Capabilities eines Adapters."""

    adapter_id: str
    healthy: bool  # kein ERROR dabei
    capabilities: list[CapabilityReport]


def _coverage(items: list[BaseModel]) -> dict[str, float]:
    """Anteil der Zeilen je DTO-Feld, in denen das Feld befüllt (nicht None/"") ist."""
    if not items:
        return {}
    fields = list(type(items[0]).model_fields)
    total = len(items)
    return {
        field: sum(1 for it in items if getattr(it, field) not in (None, "")) / total
        for field in fields
    }


async def _check_capability(adapter: SwitchAdapter, capability: Capability) -> CapabilityReport:
    method_name, is_list = _METHODS[capability]
    try:
        result = await getattr(adapter, method_name)()
    except Exception as exc:  # jeden Fehler als Status melden, nicht propagieren
        return CapabilityReport(
            capability=capability,
            status=CapabilityStatus.ERROR,
            row_count=0,
            coverage={},
            message=f"{type(exc).__name__}: {exc}",
        )
    items: list[BaseModel] = list(result) if is_list else [result]
    if not items:
        return CapabilityReport(
            capability=capability, status=CapabilityStatus.EMPTY, row_count=0, coverage={}
        )
    return CapabilityReport(
        capability=capability,
        status=CapabilityStatus.OK,
        row_count=len(items),
        coverage=_coverage(items),
    )


async def validate_adapter(adapter: SwitchAdapter) -> DeviceValidationReport:
    """Fährt jede vom Adapter gemeldete Capability und bewertet das Ergebnis.

    Bricht nicht bei der ersten fehlerhaften Capability ab — jede wird einzeln gemeldet,
    damit der Report zeigt, welche gespeicherten Kommandos/Profile wirklich funktionieren.
    """
    # READ_CONFIG (Backup) hat kein DTO-Mapping → nicht Teil der Read-Validierung.
    reports = [
        await _check_capability(adapter, capability)
        for capability in sorted(adapter.capabilities(), key=lambda c: c.value)
        if capability in _METHODS
    ]
    healthy = all(r.status is not CapabilityStatus.ERROR for r in reports)
    return DeviceValidationReport(
        adapter_id=adapter.adapter_id, healthy=healthy, capabilities=reports
    )


async def validate_device(
    device: Device, credential: Credential
) -> tuple[DeviceValidationReport, dict[str, str]]:
    """Live-Pfad: read-only zum Gerät verbinden, validieren, Roh-Output zurückgeben.

    Baut den Adapter über einen `RecordingTransport`, damit der rohe CLI-Output (als
    Referenz-Capture) neben dem Report verfügbar ist. ⚠️ echter Geräte-Zugriff.
    """
    transport = ScrapliTransport(params_from_credential(device, credential))
    recorder = RecordingTransport(transport)
    adapter = build_adapter(device.adapter_id, recorder)
    async with transport:
        report = await validate_adapter(adapter)
    return report, recorder.calls
