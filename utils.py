import subprocess, os, shutil


def probe_source_codec(ffprobe_cmd: str, input_path: str) -> str | None:
    """读取首个视频流 codec 名称（如 h264/hevc），失败返回 None。"""
    if not ffprobe_cmd:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        name = (proc.stdout or "").strip().lower()
        return name or None
    except Exception:
        return None


def safe_time_str(t: str) -> str:
    return t.replace(":", "-").replace(" ", "_")


def default_output_path(
    input_path: str, start: str, duration: str | None, convert_to_mp4: bool = False
) -> str:
    dname = os.path.dirname(input_path)
    base = os.path.splitext(os.path.basename(input_path))[0]
    ext = ".mp4" if convert_to_mp4 else os.path.splitext(input_path)[1]
    start_safe = safe_time_str(start)
    if duration:
        dur_safe = safe_time_str(duration)
        out_name = f"{base}_{start_safe}_len_{dur_safe}{ext}"
    else:
        out_name = f"{base}_{start_safe}{ext}"
    return os.path.join(dname if dname else ".", out_name)


def is_ffmpeg_exist(ffmpeg_cmd: str):
    try:
        subprocess.run(
            [ffmpeg_cmd, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except Exception:
        return False


def find_ffprobe(ffmpeg_cmd: str) -> str:
    """尽力找到 ffprobe：优先与 ffmpeg 同目录，其次 PATH。失败返回空字符串。"""
    # 与 ffmpeg 同目录
    try:
        ffmpeg_path = shutil.which(ffmpeg_cmd) or ffmpeg_cmd
        base_dir = os.path.dirname(ffmpeg_path)
        if base_dir:
            cand = os.path.join(
                base_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            if os.path.isfile(cand):
                subprocess.run(
                    [cand, "-version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                return cand
    except Exception:
        pass

    # PATH 中
    try:
        cmd = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        subprocess.run(
            [cmd, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return cmd
    except Exception:
        return ""


def probe_source_bitrate_bps(ffprobe_cmd: str, input_path: str) -> int:
    """读取源视频码率（bit/s）。优先视频流，其次容器。失败返回 0。"""
    if not ffprobe_cmd:
        return 0
    try:
        # 视频流级别
        proc = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=bit_rate",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        out = (proc.stdout or "").strip()
        if out.isdigit():
            val = int(out)
            if val > 0:
                return val
    except Exception:
        pass

    try:
        # 容器层
        proc2 = subprocess.run(
            [
                ffprobe_cmd,
                "-v",
                "error",
                "-show_entries",
                "format=bit_rate",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        out2 = (proc2.stdout or "").strip()
        if out2.isdigit():
            val2 = int(out2)
            if val2 > 0:
                return val2
    except Exception:
        pass
    return 0
