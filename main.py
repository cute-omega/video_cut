#!/usr/bin/env python3
"""
video_cut - 用 ffmpeg 在 Windows 上按开始时间剪切视频（支持 GPU 加速）

桌面GUI版本：使用tkinter和ttk提供图形界面，支持深色模式。
"""

from __future__ import annotations
import os
import shlex
import subprocess
import logging
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import win32api

from Args import Args
from utils import is_ffmpeg_exist
import state


class VideoCutterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Video Cutter")
        # self.root.geometry("500x400")
        self.process: subprocess.Popen | None = None
        self._cancelled: bool = False

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
        main_frame.grid(row=0, column=0, sticky="nsew")

        # 输入文件
        ttk.Label(main_frame, text="输入文件:").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.input_entry = ttk.Entry(main_frame, width=40)
        self.input_entry.grid(row=0, column=1, sticky="we", pady=5)
        ttk.Button(main_frame, text="选择文件", command=self.select_video).grid(
            row=0, column=2, padx=5, pady=5
        )

        # 开始时间
        ttk.Label(main_frame, text="开始时间 (HH:MM:SS or 秒数):").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.start_entry = ttk.Entry(main_frame)
        self.start_entry.grid(row=1, column=1, columnspan=2, sticky="we", pady=5)

        # 持续时间
        ttk.Label(main_frame, text="持续时间 (可选):").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        self.duration_entry = ttk.Entry(main_frame)
        self.duration_entry.grid(row=2, column=1, columnspan=2, sticky="we", pady=5)

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
        self.output_entry.grid(row=4, column=1, columnspan=2, sticky="we", pady=5)

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
        self.ffmpeg_entry.insert(0, state.FFMPEG_PATH)
        self.ffmpeg_entry.state(["disabled"])
        self.ffmpeg_entry.grid(row=6, column=1, sticky="we", pady=5)
        ttk.Button(
            main_frame, text="重新检测环境", command=self.redetect_environment
        ).grid(row=6, column=2, padx=5, pady=5)

        # Dry run
        self.dry_run_var = tk.BooleanVar()
        ttk.Checkbutton(main_frame, text="Dry run", variable=self.dry_run_var).grid(
            row=7, column=0, columnspan=2, sticky=tk.W, pady=5
        )

        # 剪切按钮
        ttk.Button(main_frame, text="剪切视频", command=self.cut_video).grid(
            row=8, column=0, columnspan=3, pady=10
        )

        # 中断按钮（仅运行时可用）
        self.cancel_button = ttk.Button(
            main_frame,
            text="中断任务",
            command=self.cancel_run,
            state="disabled",
        )
        self.cancel_button.grid(row=9, column=0, columnspan=3, sticky="we")

        # 进度状态栏，在主界面常驻展示
        self.status_var = tk.StringVar(value="状态: 就绪")
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=10, column=0, columnspan=3, sticky="we", pady=(10, 0))
        ttk.Label(status_frame, textvariable=self.status_var).grid(
            row=0, column=0, sticky="w"
        )
        self.progress_bar = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress_bar.grid(row=1, column=0, sticky="we", pady=5)
        status_frame.columnconfigure(0, weight=1)

        # 配置网格权重
        # main_frame.columnconfigure(1, weight=1)
        # root.columnconfigure(0, weight=1)
        # root.rowconfigure(0, weight=1)

        # 初始化环境：先尝试读取缓存，再必要时探测
        self._init_environment()

    def _init_environment(self):
        self._detect_environment(allow_cache=True)

    def _detect_environment(self, allow_cache: bool = False):
        # 优先读取缓存
        if allow_cache and state.load_environment():
            self._refresh_ffmpeg_entry()
            return

        ffmpeg_path = state.FFMPEG_PATH or "ffmpeg"
        while not is_ffmpeg_exist(ffmpeg_path):
            selected = filedialog.askopenfilename(
                title="选择 ffmpeg 可执行文件",
                filetypes=[("FFmpeg", "ffmpeg ffmpeg.exe"), ("All files", "*.*")],
            )
            if not selected:
                messagebox.showerror("错误", "未选择 FFmpeg，程序将退出。")
                raise SystemExit(1)
            ffmpeg_path = selected

        state.set_environment(ffmpeg_path)
        self._refresh_ffmpeg_entry()

    def _refresh_ffmpeg_entry(self):
        self.ffmpeg_entry.state(["!disabled"])
        self.ffmpeg_entry.delete(0, tk.END)
        self.ffmpeg_entry.insert(0, state.FFMPEG_PATH)
        self.ffmpeg_entry.state(["disabled"])

    def redetect_environment(self):
        try:
            self._detect_environment(allow_cache=False)
            messagebox.showinfo("完成", "已重新检测环境并更新缓存。")
        except SystemExit:
            pass
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def select_video(self):
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

    def _set_progress_indicator(self, running: bool):
        if running:
            self.status_var.set("状态: 正在剪切视频...")
            self.progress_bar.start(10)
            self.cancel_button.state(["!disabled"])
        else:
            self.progress_bar.stop()
            self.status_var.set("状态: 就绪")
            self.cancel_button.state(["disabled"])
        self.root.update_idletasks()

    def cancel_run(self):
        if self.process and self.process.poll() is None:
            self._cancelled = True
            try:
                self.process.terminate()
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

    def cut_video(self):
        # 获取值
        input = self.input_entry.get().strip()
        start = self.start_entry.get().strip()
        duration = self.duration_entry.get().strip() or "0"
        mode = self.mode_var.get()
        output = self.output_entry.get().strip() or ""
        convert_mp4 = self.convert_var.get()
        dry_run = self.dry_run_var.get()

        if not input or not start:
            messagebox.showerror("错误", "请输入输入文件和开始时间")
            return

        if not os.path.isfile(input):
            messagebox.showerror("错误", "输入文件不存在或不可读")
            return

        # 创建args对象
        try:
            args = Args(
                input,
                start,
                duration,
                mode,
                output,
                convert_mp4,
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
            self._cancelled = False
            try:
                self._set_progress_indicator(True)
                self.process = subprocess.Popen(cmd)
            except Exception as e:
                self.process = None
                self._set_progress_indicator(False)
                messagebox.showerror("错误", str(e))
                return

            threading.Thread(
                target=self._wait_process, args=(args,), daemon=True
            ).start()

    def _wait_process(self, args: Args):
        ret = -1
        success = False
        try:
            ret = self.process.wait() if self.process else -1
            success = ret == 0
        except KeyboardInterrupt:
            # 用户在终端 Ctrl+C 时避免抛出到 Tk 主线程
            ret = -1
            success = False
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
            ret = -1
            success = False

        self.root.after(0, lambda: self._on_process_finished(success, ret, args.output))

    def _on_process_finished(self, success: bool, ret: int, output: str):
        self.process = None
        self._set_progress_indicator(False)

        if self._cancelled:
            self.status_var.set("状态: 已取消")
            self._cancelled = False
            return

        if not success:
            messagebox.showerror("错误", f"ffmpeg 运行失败, 返回码 {ret}")
            return

        message = f"完成. 输出: {output}"
        try:
            win32api.ShellExecute(
                0,
                "open",
                "explorer.exe",
                f'/select,"{output}"',
                "",
                1,
            )
        except Exception as e:
            message += f"\n但打开文件夹失败: {e}"
        messagebox.showinfo("成功", message)


def main():
    root = tk.Tk()
    app = VideoCutterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
