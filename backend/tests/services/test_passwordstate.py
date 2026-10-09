from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netbuddy.db.models import Credential, Device, DeviceCredential, DeviceType
from netbuddy.services.passwordstate import (
    _list_ids_from_extra,
    credential_names,
    import_entries,
    parse_entries,
    parse_lists,
    preview,
)

_RAW = [
    {
        "PasswordID": 101,
        "PasswordListID": 7,
        "PasswordList": "Netzwerk Belimed",
        "Title": "B-HQ Core Switches",
        "UserName": "admin",
        "Password": "s3cret",
        "Description": "ArubaOS-Switch Stack",
        "URL": "https://10.131.63.212",
        "HostName": "sw-bhq-core1.corp.belimed.com",
        "Notes": "",
    },
    {
        "PasswordID": 102,
        "PasswordListID": 7,
        "PasswordList": "Netzwerk Belimed",
        "Title": "UniFi Controller",
        "UserName": "",
        "Password": "x",
        "Description": None,
        "URL": "https://unifi.corp.belimed.com",
        "HostName": None,
        "Notes": None,
    },
    {"irrelevant": True},
]


def test_parse_entries_skips_rows_without_id() -> None:
    entries = parse_entries(_RAW)
    assert [e.password_id for e in entries] == [101, 102]
    assert entries[0].list_name == "Netzwerk Belimed" and entries[0].hostname.startswith("sw-bhq")
    assert entries[1].username is None


async def test_preview_and_import_links_devices(db_session: AsyncSession) -> None:
    db_session.add(
        Device(
            hostname="sw-bhq-core1",
            mgmt_ip="10.131.63.212",
            vendor="hp",
            adapter_id="aruba_cx",
            device_type=DeviceType.SWITCH,
        )
    )
    await db_session.flush()
    entries = parse_entries(_RAW)

    rows = await preview(db_session, entries)
    assert [r.action for r in rows] == ["anlegen", "überspringen"]
    assert rows[0].devices == ["sw-bhq-core1"] and rows[0].credential_name == "B-HQ Core Switches"

    dry = await import_entries(db_session, entries, dry_run=True)
    assert dry.created == ["B-HQ Core Switches"] and dry.linked == [
        "B-HQ Core Switches → sw-bhq-core1"
    ]
    assert (await db_session.execute(select(Credential))).scalars().all() == []

    applied = await import_entries(db_session, entries, dry_run=False)
    assert applied.created == ["B-HQ Core Switches"] and applied.skipped == [
        "UniFi Controller (ohne User/Passwort)"
    ]
    cred = (await db_session.execute(select(Credential))).scalar_one()
    assert cred.username == "admin" and cred.password == "s3cret" and cred.ssh_port == 22
    assert cred.extra["source"] == "passwordstate" and cred.extra["password_id"] == 101
    links = (await db_session.execute(select(DeviceCredential))).scalars().all()
    assert len(links) == 1 and links[0].credential_id == cred.id

    # zweiter Lauf: aktualisiert statt dupliziert, Link nicht doppelt
    entries[0].password = "n3w"
    again = await import_entries(db_session, entries, dry_run=False)
    assert again.updated == ["B-HQ Core Switches"] and again.created == []
    assert (await db_session.execute(select(Credential))).scalar_one().password == "n3w"
    assert len((await db_session.execute(select(DeviceCredential))).scalars().all()) == 1


def test_list_ids_from_extra_accepts_form_field_and_list() -> None:
    assert _list_ids_from_extra({"site": "412", "org_id": "412", "account_id": "412"}) == [412]
    assert _list_ids_from_extra({"list_ids": [1, "2", "x"], "site": "2"}) == [1, 2]
    assert _list_ids_from_extra({"site": ""}) == []


def test_list_ids_from_form_field_accept_several() -> None:
    assert _list_ids_from_extra({"site": "12, 15 18;19"}) == [12, 15, 18, 19]


def test_parse_lists() -> None:
    raw = [
        {"PasswordListID": 7, "PasswordList": "B-HQ Switch", "TreePath": "\\IT Network"},
        {"PasswordListID": 0},
        {"foo": 1},
    ]
    lists = parse_lists(raw)
    assert [(x.list_id, x.name, x.tree_path) for x in lists] == [(7, "B-HQ Switch", "\\IT Network")]


def test_credential_names_disambiguate_same_title_other_user() -> None:
    raw = [
        {"PasswordID": 1, "Title": "swbat01", "UserName": "admin ", "Password": "a"},
        {"PasswordID": 2, "Title": "swbat01", "UserName": "bmdadm", "Password": "b"},
        {"PasswordID": 3, "Title": "fwbat01", "UserName": "admin", "Password": "c"},
        {"PasswordID": 4, "Title": "fwbat01", "UserName": "admin", "Password": "c"},
    ]
    entries = parse_entries(raw)
    assert entries[0].username == "admin"
    assert credential_names(entries) == {
        1: "swbat01 (admin)",
        2: "swbat01 (bmdadm)",
        3: "fwbat01",
        4: "fwbat01",
    }
