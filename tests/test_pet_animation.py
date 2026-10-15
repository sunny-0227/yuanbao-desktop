import json
from pathlib import Path

import pytest

from app.pet_animation import PET_STATES, advance_ping_pong, load_animation


def test_ping_pong_returns_to_start_without_repeating_endpoints():
    index, direction = 0, 1
    visited = [index]
    for _ in range(6):
        index, direction = advance_ping_pong(index, direction, 4)
        visited.append(index)
    assert visited == [0, 1, 2, 3, 2, 1, 0]
    assert direction == 1
    assert advance_ping_pong(0, 1, 1) == (0, 1)


@pytest.mark.parametrize("state", PET_STATES)
def test_shipped_animations_have_valid_metadata_and_transparent_png_format(state):
    root = Path(__file__).resolve().parent.parent / "assets/pet/default"
    clip = load_animation(root, state)
    assert clip and len(clip.frames) > 1
    assert clip.animated == (state != "sleep")
    assert clip.delay_ms(1) >= 40
    assert clip.delay_ms(0) >= clip.delay_ms(1)
    for frame in clip.frames:
        # PNG IHDR 的色彩类型6是RGBA；同时确认画布统一，不依赖GUI或Pillow。
        header = frame.read_bytes()[:26]
        assert header[:8] == b"\x89PNG\r\n\x1a\n"
        assert int.from_bytes(header[16:20], "big") == 480
        assert int.from_bytes(header[20:24], "big") == 480
        assert header[25] == 6


def test_missing_or_invalid_manifest_falls_back_to_static(tmp_path):
    assert load_animation(tmp_path, "idle") is None
    assert load_animation(tmp_path, "../../other") is None
    folder = tmp_path / "idle-animation"
    folder.mkdir()
    (folder / "frame-001.png").touch()
    manifest = folder / "metadata.json"
    for data in ([], {"frames": 2, "fps": 12, "pause_ms": 0},
                 {"frames": 1, "fps": 0, "pause_ms": 0}):
        manifest.write_text(json.dumps(data), encoding="utf-8")
        assert load_animation(tmp_path, "idle") is None


def test_sleep_never_starts_refresh_even_if_manifest_requests_animation(tmp_path):
    folder = tmp_path / "sleep-animation"
    folder.mkdir()
    (folder / "frame-001.png").touch()
    (folder / "metadata.json").write_text(
        json.dumps({"frames": 1, "fps": 12, "pause_ms": 0, "animated": True}),
        encoding="utf-8",
    )
    clip = load_animation(tmp_path, "sleep")
    assert clip is not None and not clip.animated
