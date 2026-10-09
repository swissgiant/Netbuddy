from netbuddy.adapters.connection import ConnectionParams
from netbuddy.adapters.factory import connect
from netbuddy.adapters.raw_shell_transport import (
    DIALECTS,
    RawShellTransport,
    clean_output,
    strip_ansi,
)
from netbuddy.db.models import Credential, Device, DeviceType

_PROCURVE_RAW = (
    "show system\x1bE\x1b[1;24r\x1b[24;1H Status and Counters - General System Information\r\n"
    "\r\n  System Name        : swi-bhq-011\r\n  -- MORE --, next page: Space\x1b[2K"
    "  Serial Number      : SG55FLYMDF\r\nswi-bhq-011# "
)


def test_strip_ansi_turns_esc_e_into_newline() -> None:
    assert strip_ansi("show system\x1bEImage stamp") == "show system\nImage stamp"
    assert strip_ansi("\x1b[1;24r\x1b[24;1Hfoo") == "foo"
    # ESC[2K = Zeile löschen → der Pager-Rest davor verschwindet, der Inhalt danach bleibt
    assert strip_ansi("-- MORE --, next page: Space\x1b[2K  Serial : X") == "  Serial : X"


def test_clean_output_removes_echo_pager_and_prompt() -> None:
    text = clean_output(_PROCURVE_RAW, "show system", DIALECTS["aruba_procurve"].pagers)
    assert text.splitlines()[0].strip() == "Status and Counters - General System Information"
    assert "MORE" not in text and "swi-bhq-011#" not in text and "show system" not in text
    assert "Serial Number      : SG55FLYMDF" in text


def test_clean_output_handles_huawei_prompt_and_cisco_sb_login_echo() -> None:
    raw = "display version\r\nHuawei Versatile Routing Platform Software\r\n<swi-bhq-003>"
    assert clean_output(raw, "display version", ()) == "Huawei Versatile Routing Platform Software"
    raw = "swi-bhq-020# show version\r\nActive-image: flash://x\r\nswi-bhq-020#"
    assert clean_output(raw, "show version", ()) == "Active-image: flash://x"


def test_factory_uses_raw_shell_for_dialect_vendors() -> None:
    cred = Credential(name="c", username="manager", password="x", ssh_port=22)
    for adapter_id, paging in (
        ("aruba_procurve", "no page"),
        ("huawei_vrp", "screen-length 0 temporary"),
        ("cisco_sb", "terminal datadump"),
    ):
        device = Device(
            hostname="h",
            mgmt_ip="10.0.0.1",
            vendor="x",
            device_type=DeviceType.SWITCH,
            adapter_id=adapter_id,
        )
        _adapter, transport = connect(device, cred)
        assert isinstance(transport, RawShellTransport)
        assert transport._dialect.paging_command == paging
    # Aruba CX bleibt beim Scrapli-GenericDriver, aber mit `no page`
    device = Device(
        hostname="h",
        mgmt_ip="10.0.0.1",
        vendor="x",
        device_type=DeviceType.SWITCH,
        adapter_id="aruba_cx",
    )
    _adapter, transport = connect(device, cred)
    assert not isinstance(transport, RawShellTransport)
    assert transport._params.paging_command == "no page"


def test_raw_shell_rejects_write_commands_on_read_path() -> None:
    import pytest

    from netbuddy.adapters.transport import TransportError

    t = RawShellTransport(
        ConnectionParams(host="10.0.0.1", username="u", platform="generic"),
        DIALECTS["aruba_procurve"],
    )
    with pytest.raises(TransportError):
        import asyncio

        asyncio.get_event_loop().run_until_complete(t.send_command("configure"))
