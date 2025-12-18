import json
import logging
import os

from hardware_detect import detect_all_hardwares
from utils import find_ffprobe, is_ffmpeg_exist

FFMPEG_PATH: str = "ffmpeg"
FFPROBE_PATH: str = "ffprobe"
HARDWARE_INFO: dict[str, set[str]] = {
    "encoders": set(),
    "hwaccels": set(),
    "hwdecoders": set(),
}

_logger = logging.getLogger(__name__)

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "env_cache.json")


def set_environment(
    ffmpeg_path: str,
    ffprobe_path: str | None = None,
    hwinfo: dict[str, set[str]] | None = None,
):
    global FFMPEG_PATH, FFPROBE_PATH, HARDWARE_INFO
    FFMPEG_PATH = ffmpeg_path
    FFPROBE_PATH = ffprobe_path or find_ffprobe(ffmpeg_path)

    detected = hwinfo or detect_all_hardwares(ffmpeg_path)

    if detected.get("encoders"):
        HARDWARE_INFO = detected
    else:
        _logger.warning("硬件加速探测为空，尝试使用缓存结果。")
        cached_ok = load_environment()
        if cached_ok and HARDWARE_INFO.get("encoders"):
            # 允许在更换 ffmpeg 路径后复用缓存的硬件信息
            FFMPEG_PATH = ffmpeg_path
            FFPROBE_PATH = ffprobe_path or find_ffprobe(ffmpeg_path)
        else:
            HARDWARE_INFO = detected

    if HARDWARE_INFO.get("encoders"):
        save_environment()
    else:
        _logger.warning("未找到任何硬件编码器信息，不会更新缓存，将回退到 CPU。")


def save_environment():
    data = {
        "ffmpeg": FFMPEG_PATH,
        "ffprobe": FFPROBE_PATH,
        "encoders": sorted(HARDWARE_INFO.get("encoders", set())),
        "hwaccels": sorted(HARDWARE_INFO.get("hwaccels", set())),
        "hwdecoders": sorted(HARDWARE_INFO.get("hwdecoders", set())),
    }
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_environment() -> bool:
    global FFMPEG_PATH, FFPROBE_PATH, HARDWARE_INFO
    if not os.path.isfile(_CACHE_FILE):
        return False
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ffmpeg_path = data.get("ffmpeg") or "ffmpeg"
        if not is_ffmpeg_exist(ffmpeg_path):
            return False
        FFMPEG_PATH = ffmpeg_path
        FFPROBE_PATH = data.get("ffprobe") or find_ffprobe(ffmpeg_path)
        hwaccels = [
            x for x in data.get("hwaccels", []) if x != "Hardware acceleration methods:"
        ]
        HARDWARE_INFO = {
            "encoders": set(data.get("encoders", [])),
            "hwaccels": set(hwaccels),
            "hwdecoders": set(data.get("hwdecoders", [])),
        }
        # 如果缓存没有编码器信息，视为无效，让外层重新探测
        if not HARDWARE_INFO["encoders"]:
            _logger.warning("缓存中的硬件信息为空，将触发重新探测。")
            return False
        return True
    except Exception:
        return False
