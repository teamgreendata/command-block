from pathlib import Path

import pytest

from app.main import MAX_LOG_LINES, parse_list, parse_tps, parse_whitelist, strip_colors, tail_lines


def test_parse_list_with_players():
    raw = "There are 2 of a max of 20 players online: alice, bob_the_2nd"
    assert parse_list(raw) == {
        "online": 2,
        "max": 20,
        "players": ["alice", "bob_the_2nd"],
        "raw": raw,
    }


def test_parse_list_empty_server():
    parsed = parse_list("There are 0 of a max of 20 players online:")
    assert parsed["online"] == 0
    assert parsed["players"] == []


def test_parse_list_unrecognized_falls_back_to_raw():
    parsed = parse_list("some future format")
    assert parsed["online"] is None
    assert parsed["raw"] == "some future format"


def test_parse_whitelist_commas():
    assert parse_whitelist("There are 2 whitelisted player(s): alice, bob") == ["alice", "bob"]


def test_parse_whitelist_and_separator():
    assert parse_whitelist("There are 2 whitelisted players: alice and bob") == ["alice", "bob"]


def test_parse_whitelist_empty():
    assert parse_whitelist("There are no whitelisted players") == []


def test_strip_colors():
    assert strip_colors("§aGreen§r plain §l§6gold") == "Green plain gold"


def test_parse_tps_paper_classic():
    parsed = parse_tps("§6TPS from last 1m, 5m, 15m: §a20.0§6, §a19.98§6, §a18.5")
    assert parsed["tps_1m"] == 20.0
    assert parsed["tps_5m"] == 19.98
    assert parsed["tps_15m"] == 18.5


def test_parse_tps_newer_paper_with_5s_column():
    parsed = parse_tps("TPS from last 5s, 1m, 5m, 15m: 20.0, 20.0, 19.9, 19.5")
    assert (parsed["tps_1m"], parsed["tps_5m"], parsed["tps_15m"]) == (20.0, 19.9, 19.5)


def test_parse_tps_unknown_format_returns_raw_not_error():
    parsed = parse_tps("Unknown command. Type \"/help\" for help.")
    assert "tps_1m" not in parsed
    assert parsed["raw"].startswith("Unknown command")


def test_tail_lines_caps_at_500(tmp_path: Path):
    log = tmp_path / "latest.log"
    log.write_text("".join(f"line {i}\n" for i in range(600)))
    lines = tail_lines(log, 10_000)
    assert len(lines) == MAX_LOG_LINES
    assert lines[-1] == "line 599"


def test_tail_lines_short_file(tmp_path: Path):
    log = tmp_path / "latest.log"
    log.write_text("a\nb\n")
    assert tail_lines(log, 100) == ["a", "b"]


def test_tail_lines_missing_file_raises_oserror(tmp_path: Path):
    with pytest.raises(OSError):
        tail_lines(tmp_path / "nope.log", 100)
