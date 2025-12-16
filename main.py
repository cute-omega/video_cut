#!/usr/bin/env python3
"""
video_cut - 用 ffmpeg 在 Windows 上按开始时间剪切视频（支持 GPU 加速）

桌面GUI版本：使用tkinter和ttk提供图形界面，支持深色模式。
"""

from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
import os
import shlex
import subprocess
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import win32api

PREFERRED_ENCODERS = OrderedDict(
    [
        ("nvenc", "Nvidia NVENC"),
        ("amf", "AMD AMF"),
        ("qsv", "Intel Quick Sync"),
        ("vaapi", "VAAPI (Linux/WSL)"),
        ("videotoolbox", "VideoToolbox (macOS)"),
        ("cpu", "CPU (libx264)"),
    ]
)


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


def find_ffmpeg(ffmpeg_cmd: str) -> str:
    try:
        subprocess.run(
            [ffmpeg_cmd, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return ffmpeg_cmd
    except Exception:
        raise FileNotFoundError(
            f"ffmpeg 未找到：'{ffmpeg_cmd}'. 请确保 ffmpeg 在 PATH 中或指定其路径."
        )


def detect_hardware_encoders(ffmpeg_cmd: str) -> dict[str, bool]:
    try:
        proc = subprocess.run(
            [ffmpeg_cmd, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        out = proc.stdout + proc.stderr
        has_nvenc = "h264_nvenc" in out or "hevc_nvenc" in out  # Nvidia
        has_amf = "h264_amf" in out or "hevc_amf" in out  # AMD/AMF
        has_qsv = "h264_qsv" in out or "hevc_qsv" in out  # Intel Quick Sync
        has_vaapi = "h264_vaapi" in out or "hevc_vaapi" in out  # VAAPI (Linux/WSL)
        has_vtb = (
            "h264_videotoolbox" in out or "hevc_videotoolbox" in out
        )  # macOS VideoToolbox
        return {
            "nvenc": has_nvenc,
            "amf": has_amf,
            "qsv": has_qsv,
            "vaapi": has_vaapi,
            "videotoolbox": has_vtb,
        }
    except Exception:
        return {
            "nvenc": False,
            "amf": False,
            "qsv": False,
            "vaapi": False,
            "videotoolbox": False,
        }


@dataclass
class Args:
    input: str
    start: str
    duration: str | None
    mode: str
    output: str | None
    convert_mp4: bool
    ffmpeg: str
    dry_run: bool

    def __post_init__(self):
        # 规范化路径
        self.input = os.path.abspath(self.input)
        if not self.output:
            self.output = default_output_path(
                self.input, self.start, self.duration, self.convert_mp4
            )

        if self.convert_mp4 and os.path.splitext(self.output)[1].lower() != ".mp4":
            self.output = os.path.splitext(self.output)[0] + ".mp4"

        try:
            self.ffmpeg = find_ffmpeg(self.ffmpeg)
        except FileNotFoundError as e:
            messagebox.showerror("错误", str(e))
            raise

        self.encoders = detect_hardware_encoders(self.ffmpeg)

        if self.mode == "precise":
            # 按有序字典定义的优先级选择编码器
            for encoder in PREFERRED_ENCODERS:
                if self.encoders.get(encoder, False):
                    self.chosen_encoder = encoder
                    break
            else:
                self.chosen_encoder = "cpu"

            logging.info(
                f"Chosen encoder: {PREFERRED_ENCODERS[self.chosen_encoder]}",
            )
            if self.chosen_encoder == "cpu":
                messagebox.showwarning(
                    "警告",
                    "未检测到可用的硬件加速，将回退到 CPU 编码 (libx264)。",
                )

    def build_command(self) -> list[str]:
        cmd: list[str] = [self.ffmpeg]

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
                if self.chosen_encoder == "nvenc":
                    cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
                elif self.chosen_encoder == "vaapi":
                    cmd += ["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"]

                cmd += ["-i", self.input, "-ss", self.start]
                if self.duration:
                    cmd += ["-t", self.duration]
                match self.chosen_encoder:
                    case "nvenc":
                        cmd += [
                            "-c:v",
                            "h264_nvenc",
                            "-preset",
                            "p5",
                            "-rc",
                            "vbr_hq",
                            "-cq",
                            "19",
                        ]
                    case "amf":
                        cmd += [
                            "-c:v",
                            "h264_amf",
                            "-quality",
                            "balanced",
                            "-rc",
                            "cqp",
                            "-qp_i",
                            "20",
                            "-qp_p",
                            "20",
                        ]
                    case "qsv":
                        cmd += [
                            "-c:v",
                            "h264_qsv",
                            "-preset",
                            "medium",
                            "-global_quality",
                            "23",
                        ]
                    case "vaapi":
                        cmd += [
                            "-vf",
                            "format=nv12,hwupload",
                            "-c:v",
                            "h264_vaapi",
                            "-qp",
                            "21",
                        ]
                    case "videotoolbox":
                        cmd += ["-c:v", "h264_videotoolbox", "-q:v", "35"]
                    case "cpu":
                        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "18"]
                    case _:
                        raise ValueError(f"未知编码器: {self.chosen_encoder}")

            case _:
                raise ValueError(f"未知模式: {self.mode}")

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


class VideoCutterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Video Cutter")
        # self.root.geometry("500x400")

        # 设置深色模式样式
        self.style = ttk.Style()
        self.style.theme_use("clam")  # 使用clam主题作为基础
        self.style.configure("TFrame", background="#2e2e2e")
        self.style.configure("TLabel", background="#2e2e2e", foreground="#ffffff")
        self.style.configure("TEntry", fieldbackground="#4e4e4e", foreground="#ffffff")
        self.style.configure("TButton", background="#4e4e4e", foreground="#ffffff")
        self.style.configure("TCheckbutton", background="#2e2e2e", foreground="#ffffff")
        self.style.configure("TRadiobutton", background="#2e2e2e", foreground="#ffffff")

        # 主框架
        main_frame = ttk.Frame(root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 输入文件
        ttk.Label(main_frame, text="输入文件:").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.input_entry = ttk.Entry(main_frame, width=40)
        self.input_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        ttk.Button(main_frame, text="选择文件", command=self.select_file).grid(
            row=0, column=2, padx=5, pady=5
        )

        # 开始时间
        ttk.Label(main_frame, text="开始时间 (HH:MM:SS or 秒数):").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.start_entry = ttk.Entry(main_frame)
        self.start_entry.grid(
            row=1, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5
        )

        # 持续时间
        ttk.Label(main_frame, text="持续时间 (可选):").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        self.duration_entry = ttk.Entry(main_frame)
        self.duration_entry.grid(
            row=2, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5
        )

        # 模式
        ttk.Label(main_frame, text="模式:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.mode_var = tk.StringVar(value="fast")
        ttk.Radiobutton(
            main_frame, text="fast", variable=self.mode_var, value="fast"
        ).grid(row=3, column=1, sticky=tk.W)
        ttk.Radiobutton(
            main_frame, text="precise", variable=self.mode_var, value="precise"
        ).grid(row=3, column=2, sticky=tk.W)

        # 输出文件
        ttk.Label(main_frame, text="输出文件 (可选):").grid(
            row=4, column=0, sticky=tk.W, pady=5
        )
        self.output_entry = ttk.Entry(main_frame)
        self.output_entry.grid(
            row=4, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5
        )

        # 兼容性选项：转码为 mp4 (h264 + aac)
        self.convert_var = tk.BooleanVar()
        ttk.Checkbutton(
            main_frame,
            text="兼容性选项：输出为 mp4 (h264+aac)",
            variable=self.convert_var,
        ).grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=5)

        # FFmpeg路径
        ttk.Label(main_frame, text="FFmpeg路径:").grid(
            row=6, column=0, sticky=tk.W, pady=5
        )
        self.ffmpeg_entry = ttk.Entry(main_frame)
        self.ffmpeg_entry.insert(0, "ffmpeg")
        self.ffmpeg_entry.grid(
            row=6, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5
        )

        # Dry run
        self.dry_run_var = tk.BooleanVar()
        ttk.Checkbutton(main_frame, text="Dry run", variable=self.dry_run_var).grid(
            row=7, column=0, columnspan=2, sticky=tk.W, pady=5
        )

        # 剪切按钮
        ttk.Button(main_frame, text="剪切视频", command=self.cut_video).grid(
            row=8, column=0, columnspan=3, pady=10
        )

        # 配置网格权重
        # main_frame.columnconfigure(1, weight=1)
        # root.columnconfigure(0, weight=1)
        # root.rowconfigure(0, weight=1)

    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.avi *.mov"),
                ("All files", "*.*"),
            ],
        )
        if file_path:
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, file_path)

    def cut_video(self):
        # 获取值
        input_file = self.input_entry.get().strip()
        start_time = self.start_entry.get().strip()
        duration = self.duration_entry.get().strip() or None
        mode = self.mode_var.get()
        output_file = self.output_entry.get().strip() or None
        convert_mp4 = self.convert_var.get()
        ffmpeg_path = self.ffmpeg_entry.get().strip()
        dry_run = self.dry_run_var.get()

        if not input_file or not start_time:
            messagebox.showerror("错误", "请输入输入文件和开始时间")
            return

        if not os.path.isfile(input_file):
            messagebox.showerror("错误", "输入文件不存在或不可读")
            return

        # 创建args对象
        try:
            args = Args(
                input_file,
                start_time,
                duration,
                mode,
                output_file,
                convert_mp4,
                ffmpeg_path,
                dry_run,
            )

            cmd = args.build_command()
        except Exception as e:
            messagebox.showerror("错误", str(e))
            return

        logging.info(f"将运行的 ffmpeg 命令：{' '.join(shlex.quote(x) for x in cmd)}")
        logging.info(f"输出文件：{args.output}")

        if args.dry_run:
            message = f"dry-run 模式，已停止（未执行 ffmpeg）。\n命令: {' '.join(shlex.quote(x) for x in cmd)}"
            logging.info(message)
            messagebox.showinfo("Dry Run", message)
        else:
            try:
                # 显示进度窗口
                progress_window = tk.Toplevel(self.root)
                progress_window.title("处理中...")
                ttk.Label(progress_window, text="正在剪切视频，请稍候...").pack(pady=20)
                self.root.update()

                subprocess.run(cmd, check=True)

                progress_window.destroy()

                message = f"完成. 输出: {args.output}"
                # 打开并选中输出文件（资源管理器 /select）
                try:
                    win32api.ShellExecute(
                        None,
                        "open",
                        "explorer.exe",
                        f'/select,"{args.output}"',
                        None,
                        1,
                    )
                except Exception as e:
                    message += f"\n但打开文件夹失败: {e}"
                messagebox.showinfo("成功", message)
            except subprocess.CalledProcessError as e:
                progress_window.destroy()
                messagebox.showerror("错误", f"ffmpeg 运行失败, 返回码 {e.returncode}")
            except Exception as e:
                progress_window.destroy()
                messagebox.showerror("错误", str(e))


def main():
    root = tk.Tk()
    app = VideoCutterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
