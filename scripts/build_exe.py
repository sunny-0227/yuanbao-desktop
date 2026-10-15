"""唯一 Windows 构建入口，排除真实用户数据和环境变量。"""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.identity import APP_ID  # noqa: E402


def build():
    parser = argparse.ArgumentParser()
    parser.add_argument("--onefile", action="store_true", help="单文件；默认目录模式启动更快")
    parser.add_argument("--voice", action="store_true", help="包含录音和播报依赖")
    parser.add_argument(
        "--local-voice", action="store_true", help="包含 Whisper 和 Vosk 依赖，模型仍外置"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Windows exe 必须在 Windows 构建")
    for name in ("PyInstaller", "PySide6", "httpx", "psutil", "PIL", "pythoncom", "pycaw"):
        if importlib.util.find_spec(name) is None:
            raise SystemExit(f"缺少依赖 {name}，请按 README 安装后重试")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile" if args.onefile else "--onedir",
        "--name",
        APP_ID,
        "--add-data",
        f"{ROOT / 'assets/icons'};assets/icons",
        "--add-data",
        f"{ROOT / 'assets/pet'};assets/pet",
        "--add-data",
        f"{ROOT / 'config.json'};.",
        "--collect-submodules",
        "pycaw",
        "--hidden-import",
        "pythoncom",
        "--hidden-import",
        "win32com.client",
        "--hidden-import",
        "comtypes",
    ]
    icon = ROOT / "assets/icons/app_icon.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]
    if args.voice or args.local_voice:
        for name in ("sounddevice", "numpy", "edge_tts", "pygame", "pyttsx3"):
            if importlib.util.find_spec(name) is None:
                raise SystemExit(f"缺少语音依赖 {name}")
            cmd += ["--collect-all", name]
    else:
        for name in (
            "sounddevice",
            "numpy",
            "edge_tts",
            "pygame",
            "pyttsx3",
            "faster_whisper",
            "vosk",
        ):
            cmd += ["--exclude-module", name]
    if args.local_voice:
        for name in ("faster_whisper", "ctranslate2", "vosk"):
            if importlib.util.find_spec(name) is None:
                raise SystemExit(f"缺少本地识别依赖 {name}")
            cmd += ["--collect-all", name]
    elif args.voice:
        cmd += ["--exclude-module", "faster_whisper", "--exclude-module", "vosk"]
    cmd += [str(ROOT / "main.py")]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print("构建完成。请运行 docs/windows-acceptance.md 中的验收流程。")


if __name__ == "__main__":
    build()
