"""Recap logic + endpoints: schedule math, deltas, rendering, sending."""
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.recap as recap
from app.main import app

from tests.test_api import UUID_A, mc_data  # noqa: F401  (fixture reuse)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("DASH_USER", raising=False)
    monkeypatch.delenv("DASH_PASS", raising=False)
    monkeypatch.setenv("CB_DATA", str(tmp_path / "cb"))
    return TestClient(app)


@pytest.fixture
def sent_mails(monkeypatch):
    mails = []
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USER", "cb@test")
    monkeypatch.setenv("SMTP_PASS", "x")
    monkeypatch.setattr(recap, "send_email",
                        lambda to, subject, html, plain: mails.append(
                            {"to": to, "subject": subject, "html": html, "plain": plain}))
    return mails


# ---------------------------------------------------------------- schedule math

def test_plan_actions_daily_and_weekly(monkeypatch, tmp_path):
    monkeypatch.setenv("CB_DATA", str(tmp_path))
    hour, weekly_day = 7, 0
    early = datetime(2026, 9, 7, 6, 59)   # a Monday, before the hour
    assert recap.plan_actions(early, {}, hour, weekly_day) == []
    monday = datetime(2026, 9, 7, 7, 5)
    assert recap.plan_actions(monday, {}, hour, weekly_day) == [
        "snapshot", "daily", "weekly"]
    done = {"snapshot": "2026-09-07", "daily": "2026-09-07", "weekly": "2026-W37"}
    assert recap.plan_actions(monday, done, hour, weekly_day) == []
    tuesday = datetime(2026, 9, 8, 9, 0)
    assert recap.plan_actions(tuesday, done, hour, weekly_day) == ["snapshot", "daily"]


# ---------------------------------------------------------------- period math

CUR = {"sections": {
    "minecraft:custom": {"minecraft:play_time": 288000, "minecraft:deaths": 5,
                         "minecraft:mob_kills": 60, "minecraft:walk_one_cm": 900000,
                         "minecraft:aviate_one_cm": 500000,
                         "minecraft:sleep_in_bed": 9},
    "minecraft:mined": {"minecraft:stone": 900, "minecraft:deepslate_diamond_ore": 7},
    "minecraft:killed": {"minecraft:zombie": 40, "minecraft:creeper": 2},
    "minecraft:killed_by": {"minecraft:skeleton": 3},
    "minecraft:crafted": {"minecraft:stick": 30},
}, "xp_level": 31}

PREV = {"sections": {
    "minecraft:custom": {"minecraft:play_time": 144000, "minecraft:deaths": 3,
                         "minecraft:mob_kills": 25, "minecraft:walk_one_cm": 400000,
                         "minecraft:aviate_one_cm": 500000,
                         "minecraft:sleep_in_bed": 9},
    "minecraft:mined": {"minecraft:stone": 500, "minecraft:deepslate_diamond_ore": 2},
    "minecraft:killed": {"minecraft:zombie": 15, "minecraft:creeper": 2},
    "minecraft:killed_by": {"minecraft:skeleton": 1},
    "minecraft:crafted": {"minecraft:stick": 10},
}, "xp_level": 27}


def test_compute_period_deltas():
    p = recap.compute_period(CUR, PREV)
    assert p["hours"] == 2.0
    assert p["mined"] == 405
    assert p["top_mined"] == {"id": "minecraft:stone", "count": 400}
    assert p["diamonds"] == 5
    assert p["deaths"] == 2
    assert p["nemesis"] == {"id": "minecraft:skeleton", "count": 2}
    assert p["mob_kills"] == 35
    assert p["top_victim"] == {"id": "minecraft:zombie", "count": 25}
    assert p["distance_cm"] == 500000  # aviate unchanged, excluded anyway
    assert p["aviate_cm"] == 0
    assert p["crafted"] == 20
    assert p["sleeps"] == 0
    assert (p["xp_from"], p["xp_to"]) == (27, 31)


def test_compute_period_all_time_and_idle():
    p = recap.compute_period(CUR, {})
    assert p["mined"] == 907 and p["hours"] == 4.0
    idle = recap.compute_period(CUR, CUR)
    assert idle["hours"] == 0 and idle["mined"] == 0 and idle["nemesis"] is None


def test_awards_need_a_strict_winner():
    a = recap.compute_period(CUR, PREV)
    b = recap.compute_period(CUR, CUR)  # idle player
    awards = recap.compute_awards({"rob": a, "alex": b})
    assert {aw["title"] for aw in awards} >= {"⛏️ Top Miner", "💎 Diamond Hound"}
    assert all(aw["player"] == "rob" for aw in awards)
    assert recap.compute_awards({"rob": a, "alex": a}) == []  # ties: nobody brags


def test_render_recap_content():
    periods = {"rob": recap.compute_period(CUR, PREV),
               "alex": recap.compute_period(CUR, PREV)}
    periods["alex"]["mined"] = 4        # break the ties for awards
    periods["alex"]["distance_cm"] = 90
    subject, html, plain = recap.render_recap(
        "rob", "week in review (since 2026-09-01)", periods, "Team Green SMP", "weekly")
    assert "5 diamonds!" in subject and "(this week)" in subject
    assert "405" in html and "Skeleton got you 2×" in html
    assert "⛏️ Top Miner" in html and "that’s you!" in html
    assert "5.0 km traveled" in html  # distance award in km, never raw cm
    assert "Meanwhile…" in html and "alex" in html
    assert "Blocks mined: 405" in plain


def test_render_recap_idle_player():
    periods = {"rob": recap.compute_period(CUR, CUR)}
    subject, html, _ = recap.render_recap("rob", "your day", periods, "SMP", "daily")
    assert "missed you" in subject
    assert "creepers are getting restless" in html


# ---------------------------------------------------------------- storage & endpoints

def test_snapshot_roundtrip_and_pruning(monkeypatch, tmp_path):
    monkeypatch.setenv("CB_DATA", str(tmp_path))
    for i in range(1, 45):
        recap.write_snapshot(f"2026-07-{i:02d}", {})  # not real dates; names sort fine
    kept = sorted(p.stem for p in recap.snapshots_dir().glob("*.json"))
    assert len(kept) == 40 and kept[0] == "2026-07-05"
    recap.write_snapshot("2026-08-01", {"alice": {"sections": {}}})
    assert recap.load_snapshot("2026-08-01")["players"] == {"alice": {"sections": {}}}
    assert recap.closest_snapshot_before("2026-08-01")["date"] == "2026-07-44"
    assert recap.closest_snapshot_before("2026-07-05") is None


def test_recipients_endpoint_validation(client):
    ok = {"recipients": {"RobGreen": {"email": "rob@example.com", "cadence": "both"}}}
    assert client.post("/api/recap/recipients", json=ok).status_code == 200
    assert client.get("/api/recap/config").json()["recipients"] == ok["recipients"]
    for bad in (
        {"BadName!": {"email": "a@b.co", "cadence": "daily"}},
        {"Rob": {"email": "not-an-email", "cadence": "daily"}},
        {"Rob": {"email": "a@b.co", "cadence": "hourly"}},
        {"Rob": {"email": "a@b.co", "cadence": "daily", "extra": 1}},
    ):
        r = client.post("/api/recap/recipients", json={"recipients": bad})
        assert r.status_code == 400, bad


def test_test_send_endpoint(client, mc_data, sent_mails, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RECAP_SERVER_NAME", "Team Green SMP")
    (mc_data / "world" / "stats" / f"{UUID_A}.json").write_text(json.dumps(
        {"stats": CUR["sections"]}))
    client.post("/api/recap/recipients", json={"recipients": {
        "alice": {"email": "alice@example.com", "cadence": "weekly"}}})
    r = client.post("/api/recap/test", json={"player": "alice"})
    assert r.status_code == 200, r.json()
    assert sent_mails and sent_mails[0]["to"] == "alice@example.com"
    assert "Team Green SMP" in sent_mails[0]["subject"]
    assert "story so far (first recap!)" in sent_mails[0]["html"]

    r = client.post("/api/recap/test", json={"player": "nobody"})
    assert r.status_code == 400


def test_test_send_requires_smtp(client, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    r = client.post("/api/recap/test", json={"player": "alice"})
    assert r.status_code == 400
    assert "SMTP" in r.json()["error"]


def test_scheduled_send_filters_cadence(client, mc_data, sent_mails):  # noqa: F811
    (mc_data / "world" / "stats" / f"{UUID_A}.json").write_text(json.dumps(
        {"stats": CUR["sections"]}))
    recap.store_recipients({
        "alice": {"email": "alice@example.com", "cadence": "weekly"},
        "bob": {"email": "bob@example.com", "cadence": "daily"},
    })
    recap.write_snapshot("2026-09-10", main._collect_all_sections())
    lines = main._send_recaps("weekly", "2026-09-10")
    assert lines == ["sent weekly recap to alice"]  # bob is daily-only
    assert sent_mails[0]["to"] == "alice@example.com"
