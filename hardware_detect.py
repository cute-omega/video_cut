import subprocess


def detect_hardware_encoders(ffmpeg_cmd: str):
    """返回硬件编码器支持情况。"""
    result: set[str] = set()
    try:
        proc = subprocess.run(
            [ffmpeg_cmd, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        out = (proc.stdout + proc.stderr).lower()

        codecs = ("h264", "hevc")
        encoders = ("nvenc", "amf", "qsv", "vaapi", "videotoolbox")

        for codec in codecs:
            for encoder in encoders:
                if f"{codec}_{encoder}" in out:
                    result.add(encoder)

    except Exception:
        pass
    return result


def detect_hwaccels(ffmpeg_cmd: str) -> set[str]:
    """列出 ffmpeg 编译可用的硬件加速框架。"""
    try:
        proc = subprocess.run(
            [ffmpeg_cmd, "-hide_banner", "-hwaccels"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        lines = (proc.stdout or "").splitlines()
        accels = {
            ln.strip()
            for ln in lines
            if ln.strip() and ln.strip() != "Hardware acceleration methods:"
        }
        return accels
    except Exception:
        return set()


def detect_hardware_decoders(ffmpeg_cmd: str) -> set[str]:
    """收集常见硬件解码器名称，便于后续选择。"""
    suffixes = ("_qsv", "_cuvid", "_vaapi", "_videotoolbox", "_dxva2", "_d3d11va")
    try:
        proc = subprocess.run(
            [ffmpeg_cmd, "-hide_banner", "-decoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        decs: set[str] = set()
        for line in (proc.stdout or "").splitlines():
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            name = parts[1]
            if name.endswith(suffixes):
                decs.add(name)
        return decs
    except Exception:
        return set()


def detect_all_hardwares(ffmpeg_cmd: str):
    """一次性探测，加快后续使用。"""
    return {
        "encoders": detect_hardware_encoders(ffmpeg_cmd),
        "hwaccels": detect_hwaccels(ffmpeg_cmd),
        "hwdecoders": detect_hardware_decoders(ffmpeg_cmd),
    }
