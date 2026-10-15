"""透明动作序列的资源约定和播放边界，不依赖 Qt。"""

import json
from dataclasses import dataclass
from pathlib import Path

PET_STATES = ("idle", "listening", "thinking", "speaking", "working", "sleep")


@dataclass(frozen=True)
class PetAnimation:
    frames: tuple[Path, ...]
    fps: int
    pause_ms: int
    animated: bool

    def delay_ms(self, index: int) -> int:
        interval = round(1000 / self.fps)
        return max(interval, self.pause_ms) if index == 0 else interval


def load_animation(root: Path, state: str) -> PetAnimation | None:
    if state not in PET_STATES:
        return None
    folder = root / f"{state}-animation"
    try:
        data = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        frames = tuple(sorted(folder.glob("frame-*.png")))
        fps, pause = data.get("fps"), data.get("pause_ms")
        if (
            not frames or len(frames) > 240 or data.get("frames") != len(frames)
            or type(fps) is not int or not 1 <= fps <= 24
            or type(pause) is not int or not 0 <= pause <= 60000
        ):
            return None
        # 休眠无论素材元数据如何声明，都不开启持续刷新。
        animated = state != "sleep" and data.get("animated", True) is True
        return PetAnimation(frames, fps, pause, animated)
    except (OSError, ValueError):
        return None


def advance_ping_pong(index: int, direction: int, count: int) -> tuple[int, int]:
    if count <= 1:
        return 0, 1
    index += direction
    if index >= count - 1:
        return count - 1, -1
    if index <= 0:
        return 0, 1
    return index, direction
