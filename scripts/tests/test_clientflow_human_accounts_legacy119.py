from __future__ import annotations

from types import SimpleNamespace

import pytest

from clientflow_release import accounts


def test_password_prompt_requires_matching_values(monkeypatch):
    answers = iter(["abcdefgh", "abcdefgh"])
    monkeypatch.setattr(accounts.getpass, "getpass", lambda _prompt: next(answers))
    assert accounts._interactive_password() == "abcdefgh"


def test_password_prompt_rejects_mismatch(monkeypatch):
    answers = iter(["abcdefgh", "abcdefghX"])
    monkeypatch.setattr(accounts.getpass, "getpass", lambda _prompt: next(answers))
    with pytest.raises(accounts.AccountProvisioningError, match="ikke ens"):
        accounts._interactive_password()


def test_provision_contract_creates_kiosk_and_admin_and_sets_admin_password(monkeypatch):
    users: dict[str, SimpleNamespace] = {}
    groups: dict[str, set[str]] = {"sudo": set(), "adm": set(), "lxd": set()}
    calls: list[tuple[list[str], str | None]] = []

    def fake_getpwnam(name: str):
        if name not in users:
            raise KeyError(name)
        return users[name]

    def fake_getgrnam(name: str):
        if name not in groups:
            raise KeyError(name)
        return SimpleNamespace(gr_name=name, gr_gid=100 + len(groups), gr_mem=sorted(groups[name]))

    def fake_getgrgid(gid: int):
        # The fake primary group is named after the user and does not alter the
        # privilege assertions under test.
        return SimpleNamespace(gr_name=f"primary-{gid}")

    def fake_getgrouplist(name: str, gid: int):
        ids = [gid]
        for index, (group, members) in enumerate(groups.items(), start=200):
            if name in members:
                ids.append(index)
        return ids

    def fake_run(command, *, input_text=None):
        calls.append((list(command), input_text))
        if command[0].endswith("useradd"):
            name = command[-1]
            users[name] = SimpleNamespace(
                pw_uid=1000 + len(users),
                pw_gid=1000 + len(users),
                pw_dir=f"/home/{name}",
                pw_shell="/bin/bash",
            )
        elif command[0].endswith("usermod") and "--append" in command:
            groups["sudo"].add(command[-1])

    monkeypatch.setattr(accounts.os, "geteuid", lambda: 0)
    monkeypatch.setattr(accounts.pwd, "getpwnam", fake_getpwnam)
    monkeypatch.setattr(accounts.grp, "getgrnam", fake_getgrnam)
    monkeypatch.setattr(accounts.grp, "getgrgid", fake_getgrgid)
    monkeypatch.setattr(accounts.os, "getgrouplist", fake_getgrouplist)
    monkeypatch.setattr(accounts, "_run", fake_run)
    monkeypatch.setattr(accounts, "_remove_group_membership", lambda _u, _g: None)
    monkeypatch.setattr(accounts, "_validate_human_accounts", lambda: None)

    result = accounts.provision_human_accounts(prompt_admin_password=False, admin_password="abcdefgh")

    assert result == {"kiosk_user": "clientflow-kiosk", "admin_user": "cfadmin"}
    assert "clientflow-kiosk" in users
    assert "cfadmin" in users
    assert any(cmd[0].endswith("passwd") and cmd[-1] == "clientflow-kiosk" for cmd, _ in calls)
    assert any(cmd[0].endswith("usermod") and "sudo" in cmd and cmd[-1] == "cfadmin" for cmd, _ in calls)
    assert any(cmd[0].endswith("chpasswd") and data == "cfadmin:abcdefgh\n" for cmd, data in calls)
