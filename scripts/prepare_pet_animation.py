"""用本地 FFmpeg 将 JoyAI 蓝底视频转为透明动作帧，不修改源文件。"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-color", default="0x0785BA")
    parser.add_argument("--similarity", type=float, default=0.26)
    parser.add_argument("--blend", type=float, default=0.06)
    parser.add_argument("--trim-frames", type=int, default=4)
    parser.add_argument("--pause-ms", type=int, default=4000)
    parser.add_argument("--static", action="store_true", help="运行时只显示第一帧，不开启动画计时")
    args = parser.parse_args()
    if not 0.01 <= args.similarity <= 1 or not 0 <= args.blend <= 1:
        parser.error("抠图参数超出范围")
    if args.trim_frames < 0 or args.pause_ms < 0:
        parser.error("裁切帧数和停顿时间不能为负数")
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("输出目录必须为空，避免混入旧帧")
    output.mkdir(parents=True, exist_ok=True)
    filters = (
        f"trim=start_frame={args.trim_frames},setpts=PTS-STARTPTS,fps=12,format=rgba,"
        f"colorkey={args.key_color}:{args.similarity}:{args.blend},scale=400:400,"
        "pad=480:480:40:40:color=black@0"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source),
         "-vf", filters, "-an", str(output / "frame-%03d.png")],
        check=True,
    )
    with source.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = {
        "source": source.name,
        "source_sha256": source_hash,
        "filter": filters,
        "frames": len(list(output.glob("frame-*.png"))),
        "fps": 12,
        "size": [480, 480],
        "playback": "ping-pong",
        "pause_ms": args.pause_ms,
        "animated": not args.static,
        "note": "正放再倒放，端点不重复；开头留裁切缓冲，去除白底和背景切换。",
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
