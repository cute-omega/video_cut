from dataclasses import dataclass
import os
from logging import getLogger
from tkinter import messagebox

from utils import default_output_path, probe_source_bitrate_bps, probe_source_codec
import state

PREFERRED_ENCODERS = {
    "nvenc": "Nvidia NVENC",
    "amf": "AMD AMF",
    "qsv": "Intel Quick Sync",
    "vaapi": "VAAPI (Linux/WSL)",
    "videotoolbox": "VideoToolbox (macOS)",
    "cpu": "CPU (libx264)",
}

logger = getLogger(__name__)


@dataclass
class Args:
    input: str
    start: str
    duration: str
    mode: str
    output: str
    convert_mp4: bool
    dry_run: bool
    source_bitrate_bps: int = 0
    source_codec_name: str | None = None
    chosen_hwaccel: str | None = None
    chosen_hwdecoder: str | None = None

    def __post_init__(self):
        # 规范化路径
        self.input = os.path.abspath(self.input)
        if not self.output:
            self.output = default_output_path(
                self.input, self.start, self.duration, self.convert_mp4
            )

        if self.convert_mp4 and os.path.splitext(self.output)[1].lower() != ".mp4":
            self.output = os.path.splitext(self.output)[0] + ".mp4"

        # 使用启动阶段统一探测的 ffmpeg/ffprobe 路径
        if not state.FFMPEG_PATH:
            messagebox.showerror("错误", "FFmpeg 路径未设置。")
            raise FileNotFoundError("FFmpeg 路径未设置。")

        if not state.HARDWARE_INFO.get("encoders"):
            # 启动时如果未探测到硬件加速，再尝试一次，避免误判为仅 CPU
            state.set_environment(state.FFMPEG_PATH, state.FFPROBE_PATH)

        # 按有序字典定义的优先级选择编码器
        for encoder in PREFERRED_ENCODERS:
            if encoder in state.HARDWARE_INFO["encoders"]:
                self.chosen_encoder = encoder
                break
        else:
            self.chosen_encoder = "cpu"

        logger.info(
            f"Chosen encoder: {PREFERRED_ENCODERS[self.chosen_encoder]}",
        )
        if self.chosen_encoder == "cpu":
            logger.warning(
                "未检测到可用的硬件加速，将回退到 CPU 编码。",
            )

        # 需要匹配码率则尝试探测
        if self.mode == "precise":
            self.source_bitrate_bps = probe_source_bitrate_bps(
                state.FFPROBE_PATH, self.input
            )
            if not self.source_bitrate_bps:
                logger.warning("无法探测源视频码率，将使用100kbps作为默认。")
                self.source_bitrate_bps = 100000  # 100 kbps

        # 记录源视频 codec，用于选择解码路径
        self.source_codec_name = probe_source_codec(state.FFPROBE_PATH, self.input)

        # 基于编码器与可用加速框架推导解码路径
        self.chosen_hwaccel = self._select_hwaccel()
        self.chosen_hwdecoder = self._select_hwdecoder()

    def _select_hwaccel(self) -> str | None:
        priorities = {
            "nvenc": ["cuda"],
            "amf": ["d3d11va", "dxva2"],
            "qsv": ["qsv", "d3d11va", "dxva2"],
            "vaapi": ["vaapi"],
            "videotoolbox": ["videotoolbox"],
        }
        if not state.HARDWARE_INFO.get("hwaccels"):
            return None
        for cand in priorities.get(self.chosen_encoder, []):
            if cand in state.HARDWARE_INFO.get("hwaccels", set()):
                return cand
        return None

    def _select_hwdecoder(self) -> str | None:
        if not self.source_codec_name or not state.HARDWARE_INFO.get("hwdecoders"):
            return None
        codec = self.source_codec_name
        preferred: list[str] = []
        if self.chosen_hwaccel == "cuda":
            preferred.append(f"{codec}_cuvid")
        elif self.chosen_hwaccel in ("d3d11va", "dxva2"):
            preferred.append(f"{codec}_d3d11va")
            preferred.append(f"{codec}_dxva2")
        elif self.chosen_hwaccel in ("qsv", "vaapi", "videotoolbox"):
            preferred.append(f"{codec}_{self.chosen_hwaccel}")
        for name in preferred:
            if name in state.HARDWARE_INFO.get("hwdecoders", set()):
                return name
        return None

    def build_command(self) -> list[str]:
        cmd: list[str] = [state.FFMPEG_PATH]

        match self.mode:
            case "fast":
                # 快速模式：输入前 seek，复制视频流（或快速转码）
                cmd += ["-ss", self.start, "-i", self.input]
                if self.duration:
                    cmd += ["-t", self.duration]
                if self.convert_mp4:
                    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
                else:
                    cmd += ["-c:v", "copy"]

            case "precise":
                # 精确模式：先打开输入再 seek，必要时回退到 CPU 编码
                pre_input: list[str] = []
                if self.chosen_hwaccel:
                    pre_input += ["-hwaccel", self.chosen_hwaccel]
                    match self.chosen_hwaccel:
                        case "cuda":
                            pre_input += ["-hwaccel_output_format", "cuda"]
                        case "vaapi":
                            pre_input += ["-hwaccel_output_format", "vaapi"]
                        case "qsv":
                            pre_input += ["-hwaccel_output_format", "qsv"]
                        case "d3d11va" | "dxva2":
                            # D3D11/DXVA2 默认也会走 GPU surface，但显式声明格式可避免隐式拷贝
                            pre_input += ["-hwaccel_output_format", "d3d11"]
                if self.chosen_hwdecoder:
                    pre_input += ["-c:v", self.chosen_hwdecoder]

                cmd += pre_input + ["-i", self.input, "-ss", self.start]
                if self.duration:
                    cmd += ["-t", self.duration]
                # 选择具体编码器名：非兼容模式默认 HEVC，兼容模式（mp4）强制 H.264
                if self.chosen_encoder == "cpu":
                    enc_name = "libx264" if self.convert_mp4 else "libx265"
                else:
                    codec_tag = "h264" if self.convert_mp4 else "hevc"
                    enc_name = f"{codec_tag}_{self.chosen_encoder}"

                cmd += ["-c:v", enc_name]

                kbps = self.source_bitrate_bps // 1000

                cmd += [
                    "-b:v",
                    f"{kbps}k",
                    "-maxrate",
                    f"{int(kbps * 12 // 10)}k",
                    "-bufsize",
                    f"{int(kbps * 2)}k",
                ]
                match self.chosen_encoder:
                    case "nvenc":
                        cmd += ["-rc", "vbr_hq", "-preset", "p5"]
                    case "amf":
                        cmd += ["-quality", "balanced"]
                    case "qsv":
                        cmd += ["-preset", "medium"]
                    case "vaapi":
                        cmd += ["-vf", "format=nv12,hwupload"]
                    case "videotoolbox":
                        # VideoToolbox 默认参数即刻可用，通常无需额外 flag
                        pass
                    case "cpu":
                        cmd += ["-preset", "slow"]

        if self.convert_mp4:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        else:
            cmd += ["-c:a", "copy"]

        cmd += [
            "-y",
            "-fflags",
            "+genpts",
            "-avoid_negative_ts",
            "make_zero",
            "-reset_timestamps",
            "1",
            "-movflags",
            "+faststart",
            self.output,
        ]
        return cmd
