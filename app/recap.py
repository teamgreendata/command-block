"""Automated email recaps: daily/weekly player stat digests.

A snapshot of every player's raw stat sections lands in CB_DATA/snapshots once
a day; a recap email diffs two snapshots and celebrates the difference. SMTP
config comes from the environment (SMTP_HOST/PORT/USER/PASS/FROM); recipients
and cadence live in CB_DATA/recap.json, edited on the Settings tab. All the
date/delta/rendering logic here is pure and unit-tested; main.py wires it to
the world files and an asyncio loop.
"""

import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
CADENCES = ("none", "daily", "weekly", "both")


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _data_dir() -> Path:
    return Path(_env("CB_DATA", "/cb-data"))


def snapshots_dir() -> Path:
    return _data_dir() / "snapshots"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


# ---------------------------------------------------------------- config & state

def load_recipients() -> dict:
    return _read_json(_data_dir() / "recap.json", {})


def store_recipients(recipients: dict) -> None:
    _write_json(_data_dir() / "recap.json", recipients)


def validate_recipients(recipients: dict) -> str | None:
    if len(recipients) > 50:
        return "Too many recipients."
    for name, cfg in recipients.items():
        if not re.match(r"^[A-Za-z0-9_]{1,16}$", name):
            return f"Invalid player name {name!r}."
        if not isinstance(cfg, dict) or set(cfg) - {"email", "cadence"}:
            return f"Bad entry for {name}."
        if cfg.get("cadence", "none") not in CADENCES:
            return f"Bad cadence for {name}."
        email = cfg.get("email", "")
        if email and (len(email) > 254 or not EMAIL_RE.match(email)):
            return f"Bad email for {name}."
    return None


def load_state() -> dict:
    return _read_json(_data_dir() / "recap_state.json", {})


def save_state(state: dict) -> None:
    _write_json(_data_dir() / "recap_state.json", state)


def smtp_configured() -> bool:
    return bool(_env("SMTP_HOST") and (_env("SMTP_FROM") or _env("SMTP_USER")))


# ---------------------------------------------------------------- scheduling (pure)

def plan_actions(now, state: dict, hour: int, weekly_day: int) -> list[str]:
    """Which of snapshot/daily/weekly are due at `now`. Sends only ever happen
    on a day whose snapshot exists, so deltas are between fixed points."""
    acts = []
    today = now.date().isoformat()
    if now.hour >= hour and state.get("snapshot") != today:
        acts.append("snapshot")
    if state.get("snapshot") == today or "snapshot" in acts:
        if state.get("daily") != today:
            acts.append("daily")
        iso = now.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        if now.weekday() == weekly_day and state.get("weekly") != week:
            acts.append("weekly")
    return acts


# ---------------------------------------------------------------- snapshots

def write_snapshot(day_iso: str, players: dict) -> None:
    _write_json(snapshots_dir() / f"{day_iso}.json", {"date": day_iso, "players": players})
    kept = sorted(p.name for p in snapshots_dir().glob("*.json"))
    for name in kept[:-40]:  # ~6 weeks of history is plenty
        try:
            (snapshots_dir() / name).unlink()
        except OSError:
            pass


def load_snapshot(day_iso: str) -> dict | None:
    data = _read_json(snapshots_dir() / f"{day_iso}.json", None)
    return data


def closest_snapshot_before(day_iso: str) -> dict | None:
    """Newest snapshot strictly older than day_iso (recaps tolerate gaps —
    the period label tells the truth about the actual span)."""
    older = sorted(p.stem for p in snapshots_dir().glob("*.json") if p.stem < day_iso)
    return load_snapshot(older[-1]) if older else None


# ---------------------------------------------------------------- period math (pure)

def _num_delta(cur: dict, prev: dict) -> dict:
    out = {}
    for k, v in cur.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            d = v - prev.get(k, 0)
            if d > 0:
                out[k] = d
    return out


def _top(d: dict):
    if not d:
        return None
    k, v = max(d.items(), key=lambda kv: kv[1])
    return {"id": k, "count": v}


def compute_period(cur: dict, prev: dict) -> dict:
    """Fun fields for one player between two snapshot entries
    ({"sections": ..., "xp_level": ...} each; prev may be {} = all time)."""
    cs, ps = cur.get("sections", {}), prev.get("sections", {})

    def sec(name):
        return _num_delta(cs.get(name, {}), ps.get(name, {}))

    custom = sec("minecraft:custom")
    mined = sec("minecraft:mined")
    return {
        "hours": round(custom.get("minecraft:play_time",
                                  custom.get("minecraft:play_one_minute", 0)) / 72000, 1),
        "mined": sum(mined.values()),
        "top_mined": _top(mined),
        "diamonds": (mined.get("minecraft:diamond_ore", 0)
                     + mined.get("minecraft:deepslate_diamond_ore", 0)),
        "deaths": custom.get("minecraft:deaths", 0),
        "nemesis": _top(sec("minecraft:killed_by")),
        "mob_kills": custom.get("minecraft:mob_kills", 0),
        "top_victim": _top(sec("minecraft:killed")),
        "distance_cm": sum(v for k, v in custom.items()
                           if k.endswith("_one_cm") and k != "minecraft:aviate_one_cm"),
        "aviate_cm": custom.get("minecraft:aviate_one_cm", 0),
        "crafted": sum(sec("minecraft:crafted").values()),
        "sleeps": custom.get("minecraft:sleep_in_bed", 0),
        "xp_from": prev.get("xp_level"),
        "xp_to": cur.get("xp_level"),
    }


AWARDS = [
    ("mined", "⛏️ Top Miner", "blocks mined"),
    ("distance_cm", "🗺️ Road Warrior", "distance traveled"),
    ("mob_kills", "⚔️ Monster Slayer", "mob kills"),
    ("diamonds", "💎 Diamond Hound", "diamonds"),
]


def compute_awards(periods: dict) -> list[dict]:
    """periods: {player: compute_period result}. An award needs a strict,
    non-zero winner — ties and idle weeks earn nobody bragging rights."""
    out = []
    for key, title, what in AWARDS:
        ranked = sorted(periods.items(), key=lambda kv: kv[1].get(key, 0), reverse=True)
        if len(ranked) >= 2 and ranked[0][1].get(key, 0) > ranked[1][1].get(key, 0):
            out.append({"title": title, "player": ranked[0][0],
                        "value": ranked[0][1][key], "what": what})
        elif len(ranked) == 1 and ranked[0][1].get(key, 0) > 0:
            out.append({"title": title, "player": ranked[0][0],
                        "value": ranked[0][1][key], "what": what})
    return out


# ---------------------------------------------------------------- rendering (pure)

def _pretty(mc_id: str) -> str:
    return mc_id.split(":")[-1].replace("_", " ").title()


def _fmt_dist(cm: float) -> str:
    return f"{cm / 100000:.1f} km" if cm >= 100000 else f"{round(cm / 100)} m"


def _n(v) -> str:
    return f"{int(v):,}"


_ROW = ('<tr><td style="padding:4px 12px 4px 0;color:#555">{label}</td>'
        '<td style="padding:4px 0;font-weight:bold;color:#1a1a1a">{value}</td></tr>')


def _stat_rows(p: dict) -> list[tuple[str, str]]:
    rows = []
    if p["hours"]:
        rows.append(("Time played", f'{p["hours"]} h'))
    if p["mined"]:
        top = f' (mostly {_pretty(p["top_mined"]["id"])})' if p["top_mined"] else ""
        rows.append(("Blocks mined", _n(p["mined"]) + top))
    if p["diamonds"]:
        rows.append(("Diamonds", f'{_n(p["diamonds"])} 💎'))
    if p["mob_kills"]:
        top = f' — favorite target: {_pretty(p["top_victim"]["id"])}' if p["top_victim"] else ""
        rows.append(("Mobs slain", _n(p["mob_kills"]) + top))
    if p["deaths"]:
        nem = (f' ({_pretty(p["nemesis"]["id"])} got you '
               f'{_n(p["nemesis"]["count"])}×)') if p["nemesis"] else ""
        rows.append(("Deaths", _n(p["deaths"]) + nem))
    else:
        rows.append(("Deaths", "0 — untouchable ✨"))
    if p["distance_cm"]:
        rows.append(("Distance traveled", _fmt_dist(p["distance_cm"])))
    if p["aviate_cm"]:
        rows.append(("Elytra flight", _fmt_dist(p["aviate_cm"])))
    if p["crafted"]:
        rows.append(("Items crafted", _n(p["crafted"])))
    if p["sleeps"]:
        rows.append(("Nights slept", _n(p["sleeps"])))
    if p.get("xp_to") is not None and p.get("xp_from") is not None and p["xp_to"] != p["xp_from"]:
        rows.append(("XP level", f'{p["xp_from"]} → {p["xp_to"]}'))
    return rows


def render_recap(player: str, period_label: str, periods: dict, server_name: str,
                 kind: str) -> tuple[str, str, str]:
    """-> (subject, html, plain). periods holds every player's numbers; the
    email leads with `player`'s and compares against the rest."""
    mine = periods[player]
    active = mine["hours"] > 0 or mine["mined"] > 0 or mine["deaths"] > 0
    if mine["diamonds"]:
        headline = f'{_n(mine["diamonds"])} diamond{"s" if mine["diamonds"] != 1 else ""}!'
    elif mine["mined"]:
        headline = f'{_n(mine["mined"])} blocks mined'
    elif active:
        headline = f'{mine["hours"]} hours in the mines'
    else:
        headline = "the world missed you"
    short = "today" if kind == "daily" else "this week"
    if "story so far" in period_label:
        short = "so far"
    subject = f"⛏️ {server_name} — {headline} ({short})"

    parts = [
        '<div style="background:#2a1f16;padding:24px;font-family:Courier New,monospace">',
        '<div style="max-width:560px;margin:auto;background:#c6c6c6;'
        'border:3px solid #000;padding:24px">',
        f'<h2 style="margin:0 0 4px;color:#1a1a1a">⛏️ {server_name}</h2>',
        f'<p style="margin:0 0 16px;color:#555">Hey {player} — your {period_label}.</p>',
    ]
    if active:
        parts.append('<table style="border-collapse:collapse;font-size:14px;'
                     'font-family:inherit">')
        for label, value in _stat_rows(mine):
            parts.append(_ROW.format(label=label, value=value))
        parts.append("</table>")
    else:
        parts.append('<p style="color:#1a1a1a">No blocks were harmed — you didn’t play '
                     "this time. The creepers are getting restless. 🌱</p>")

    awards = compute_awards(periods) if kind == "weekly" and len(periods) > 1 else []
    if awards:
        parts.append('<h3 style="margin:18px 0 6px;color:#1a1a1a">🏆 Server awards</h3>')
        for a in awards:
            yours = " — that’s you!" if a["player"] == player else ""
            shown = (f'{_fmt_dist(a["value"])} traveled' if a["what"] == "distance traveled"
                     else f'{_n(a["value"])} {a["what"]}')
            parts.append(f'<p style="margin:2px 0;color:#1a1a1a">{a["title"]}: '
                         f'<b>{a["player"]}</b> ({shown}){yours}</p>')
    rivals = {n: p for n, p in periods.items() if n != player and p["hours"] > 0}
    if rivals:
        parts.append('<h3 style="margin:18px 0 6px;color:#1a1a1a">Meanwhile…</h3>')
        for n, p in rivals.items():
            bits = [f'{p["hours"]} h']
            if p["mined"]:
                bits.append(f'{_n(p["mined"])} blocks')
            if p["deaths"]:
                bits.append(f'{_n(p["deaths"])} deaths')
            parts.append(f'<p style="margin:2px 0;color:#1a1a1a">'
                         f'<b>{n}</b>: {", ".join(bits)}</p>')
    parts.append('<p style="margin:18px 0 0;font-size:11px;color:#777">'
                 "sent by command-block, your server’s little helper</p></div></div>")
    html = "".join(parts)

    plain_lines = [f"{server_name} — {player}'s {period_label}", ""]
    plain_lines += [f"{label}: {value}" for label, value in _stat_rows(mine)] if active \
        else ["You didn't play this time."]
    return subject, html, "\n".join(plain_lines)


# ---------------------------------------------------------------- sending

def send_email(to: str, subject: str, html: str, plain: str) -> None:
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "587"))
    user, password = _env("SMTP_USER"), _env("SMTP_PASS")
    sender = _env("SMTP_FROM") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
    try:
        if port != 465:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls()
                server.ehlo()
        if user and password:
            server.login(user, password)
        server.sendmail(sender, [to], msg.as_string())
    finally:
        server.quit()
