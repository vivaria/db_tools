from pathlib import Path

from db_tools.classes import CardRegistry, Replay

JSON_DIR = Path(__file__).resolve().parent.parent / "data" / "json"


def test_load_replay():
    json_path = next(iter(sorted(JSON_DIR.glob("*.json"))))

    registry = CardRegistry()
    replay = Replay.from_json_file(json_path, registry=registry)

    assert replay.plays
    assert len(registry) > 0
