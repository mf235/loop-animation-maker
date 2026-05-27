import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import datetime
import os
import threading
import heapq
import subprocess
import sys

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

try:
    from skimage.metrics import structural_similarity as ssim
    HAS_SSIM = True
except ImportError:
    HAS_SSIM = False

class LoopMakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ループアニメーションメーカー - 自動最適区間検索（超高速版）")
        self.video_path = None
        self.cap = None
        self.total_frames = 0
        self.canvas_width = 1280
        self.canvas_height = 720
        self.max_match_rank = 30

        self.canvas = tk.Canvas(root, width=self.canvas_width, height=self.canvas_height, bg='black')
        self.canvas.pack(pady=10)

        controls_frame = tk.Frame(root)
        controls_frame.pack(fill=tk.X, padx=20, pady=10)

        self.btn_load = tk.Button(controls_frame, text="動画を読み込む", command=self.load_video_btn, bg="cyan", fg="black")
        self.btn_load.pack(side=tk.LEFT, padx=10)

        self.slider = tk.Scale(controls_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.on_slider_move)
        self.slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # パラメータ
        param_frame = tk.Frame(controls_frame)
        param_frame.pack(side=tk.LEFT, padx=15)

        tk.Label(param_frame, text="最小ループ長:").pack(side=tk.LEFT)
        self.min_loop_var = tk.IntVar(value=60)
        self.min_loop_spin = ttk.Spinbox(param_frame, from_=10, to=1000, width=5, textvariable=self.min_loop_var)
        self.min_loop_spin.pack(side=tk.LEFT, padx=(0,5))

        tk.Label(param_frame, text="最大ループ長:").pack(side=tk.LEFT)
        self.max_loop_var = tk.IntVar(value=300)
        self.max_loop_spin = ttk.Spinbox(param_frame, from_=1, to=2000, width=5, textvariable=self.max_loop_var)
        self.max_loop_spin.pack(side=tk.LEFT, padx=(0,5))

        tk.Label(param_frame, text="検索間隔:").pack(side=tk.LEFT)
        self.step_var = tk.IntVar(value=1)
        self.step_spin = ttk.Spinbox(param_frame, from_=1, to=50, width=5, textvariable=self.step_var)
        self.step_spin.pack(side=tk.LEFT, padx=(0,5))

        tk.Label(param_frame, text="生成候補:").pack(side=tk.LEFT)
        self.match_rank_var = tk.StringVar(value="BEST")
        self.match_rank_combo = ttk.Combobox(
            param_frame,
            width=6,
            state="readonly",
            textvariable=self.match_rank_var,
            values=["BEST"] + [str(i) for i in range(2, self.max_match_rank + 1)]
        )
        self.match_rank_combo.pack(side=tk.LEFT)

        self.fade_var = tk.IntVar(value=0)
        self.fade_check = ttk.Checkbutton(controls_frame, text="フェード合成", variable=self.fade_var)
        self.fade_check.pack(side=tk.LEFT, padx=(10, 3))

        tk.Label(controls_frame, text="フェード長:").pack(side=tk.LEFT)
        self.fade_length_var = tk.IntVar(value=6)
        self.fade_length_spin = ttk.Spinbox(controls_frame, from_=1, to=120, width=5, textvariable=self.fade_length_var)
        self.fade_length_spin.pack(side=tk.LEFT, padx=(0, 10))

        self.edge_var = tk.IntVar(value=0)
        self.edge_check = ttk.Checkbutton(controls_frame, text="エッジ比較", variable=self.edge_var)
        self.edge_check.pack(side=tk.LEFT, padx=10)

        self.btn_export = tk.Button(controls_frame, text="最適ループを自動検索して出力", command=self.start_export, bg="magenta", fg="white", font=("Arial", 10, "bold"))
        self.btn_export.pack(side=tk.LEFT, padx=10)
        self.btn_export.config(state=tk.DISABLED)

        self.status_var = tk.StringVar()
        self.status_var.set("動画を読み込んで「最適ループを自動検索して出力」を押してください")
        self.status_label = tk.Label(root, textvariable=self.status_var, font=("Arial", 10, "bold"))
        self.status_label.pack(pady=5)

        self.photo = None

        if HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_drop)

    def on_drop(self, event):
        file_path = event.data.strip('{}')
        self.load_video(file_path)

    def load_video_btn(self):
        file_path = filedialog.askopenfilename(filetypes=[("MP4 files", "*.mp4")])
        if file_path:
            self.load_video(file_path)

    def load_video(self, file_path):
        if self.cap:
            self.cap.release()
        self.video_path = file_path
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            self.status_var.set("エラー：動画が開けませんでした。")
            return
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        max_frames = max(1, self.total_frames)
        self.slider.config(to=max_frames - 1)
        self.slider.set(0)

        # 動画を読み込んだら、最大ループ長は動画全体のフレーム数に合わせる
        self.max_loop_spin.config(to=max_frames)
        self.max_loop_var.set(max_frames)

        # 短い動画でも入力範囲が破綻しないように調整
        self.min_loop_spin.config(to=max_frames)
        if self.min_loop_var.get() >= max_frames:
            self.min_loop_var.set(max(1, max_frames // 2))

        # フェード長も動画の長さに合わせて上限を調整
        self.fade_length_spin.config(to=max(1, min(120, max_frames // 2)))
        if self.fade_length_var.get() > max_frames // 2:
            self.fade_length_var.set(max(1, max_frames // 2))

        self.btn_export.config(state=tk.NORMAL)
        self.status_var.set(f"動画ロード完了: {os.path.basename(file_path)} （{self.total_frames}フレーム）")
        self.update_preview(0)

    def on_slider_move(self, val):
        if self.cap:
            self.current_frame_idx = int(val)
            self.update_preview(self.current_frame_idx)

    def update_preview(self, frame_idx):
        if not self.cap: return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            img.thumbnail((self.canvas_width, self.canvas_height), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(image=img)
            self.canvas.delete("all")
            x = (self.canvas_width - self.photo.width()) // 2
            y = (self.canvas_height - self.photo.height()) // 2
            self.canvas.create_image(x, y, image=self.photo, anchor=tk.NW)

    def start_export(self):
        if not self.cap or not HAS_SSIM:
            messagebox.showerror("エラー", "SSIM機能を使うには `pip install scikit-image` を実行してください！")
            return
        self.btn_export.config(state=tk.DISABLED)
        threading.Thread(target=self.export_loop, daemon=True).start()


    def get_app_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def get_ffmpeg_path(self):
        app_dir = self.get_app_dir()
        candidates = [
            os.path.join(app_dir, "ffmpeg.exe"),
            os.path.join(app_dir, "ffmpeg"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    def open_ffmpeg_writer(self, out_path, fps, width, height):
        ffmpeg_path = self.get_ffmpeg_path()
        if not ffmpeg_path:
            raise FileNotFoundError("ffmpeg.exe がスクリプトと同じフォルダにありません。")

        # X投稿で弾かれにくい H.264 / yuv420p / faststart のMP4を直接生成する。
        # rawvideoとしてOpenCVのBGRフレームをstdinへ流し込む。
        safe_fps = float(fps) if fps and fps > 0 else 60.0
        cmd = [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", f"{safe_fps:.6f}",
            "-i", "-",
            "-an",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-preset", "medium",
            "-crf", "18",
            "-movflags", "+faststart",
            out_path,
        ]
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def write_frame_to_ffmpeg(self, proc, frame):
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"ffmpeg が途中で停止しました。\n{stderr}")
        proc.stdin.write(frame.tobytes())

    def close_ffmpeg_writer(self, proc):
        if proc.stdin:
            proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"ffmpeg の書き出しに失敗しました。\n{stderr}")

    def export_loop(self):
        self.status_var.set("全フレームを高速読み込み中…")
        self.root.update()

        min_length = max(1, self.min_loop_var.get())
        max_length = max(1, self.max_loop_var.get())
        step = max(1, self.step_var.get())
        use_edge = self.edge_var.get() == 1

        selected_rank_label = self.match_rank_var.get()
        selected_rank_index = 0 if selected_rank_label == "BEST" else max(0, int(selected_rank_label) - 1)

        if max_length < min_length:
            self.status_var.set("エラー：最大ループ長は最小ループ長以上にしてください。")
            self.btn_export.config(state=tk.NORMAL)
            return

        COMPARE_SIZE = (160, 90)   # ← さらに小さくして高速化

        # ★★★ ここが大幅高速化ポイント ★★★
        # 最初に全フレームを小さくしてメモリに保持
        small_frames = []
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        for i in range(self.total_frames):
            ret, frame = self.cap.read()
            if not ret:
                break
            small = cv2.resize(frame, COMPARE_SIZE)
            gray = cv2.Canny(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), 50, 150) if use_edge else cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            small_frames.append(gray)
            if i % 100 == 0:
                self.status_var.set(f"読み込み中… {i}/{self.total_frames}")
                self.root.update()

        # ==========================================
        # 修正ポイント：実際に読み込めたフレーム数を取得する
        # ==========================================
        actual_total_frames = len(small_frames)

        self.status_var.set("最適ループ区間を検索中…")
        self.root.update()

        if actual_total_frames <= min_length:
            self.status_var.set("エラー：動画が短すぎます。最小ループ長を短くしてください。")
            self.btn_export.config(state=tk.NORMAL)
            return

        # 上位候補を多めに保持してから、ほぼ同じ区間を間引く。
        # これで「2」「3」などを選んだ時に、BESTの1フレーム違いばかりになるのを避ける。
        raw_pool_size = max(self.max_match_rank * 30, selected_rank_index + 1)
        top_candidates = []  # (score, start, end) の最小ヒープ
        best_score = -1.0
        progress_interval = max(50, step * 10)

        # 検索ループのベースを self.total_frames から actual_total_frames に変更
        for start in range(0, actual_total_frames - min_length, step):
            gray_start = small_frames[start]

            # max_lengthを「最大ループ長」として含めるため、end側は +1 する
            end_max = min(start + max_length, actual_total_frames - 1)
            for end in range(start + min_length, end_max + 1):
                gray_end = small_frames[end]
                score = float(ssim(gray_start, gray_end))

                candidate = (score, start, end)
                if len(top_candidates) < raw_pool_size:
                    heapq.heappush(top_candidates, candidate)
                elif score > top_candidates[0][0]:
                    heapq.heapreplace(top_candidates, candidate)

                if score > best_score:
                    best_score = score

            if start % progress_interval == 0:
                self.status_var.set(f"検索中… {start}/{actual_total_frames}（ベスト: {best_score:.4f}）")
                self.root.update()

        if not top_candidates:
            self.status_var.set("適切なループ区間が見つかりませんでした。")
            self.btn_export.config(state=tk.NORMAL)
            return

        raw_ranked_candidates = sorted(top_candidates, key=lambda x: x[0], reverse=True)

        # 近すぎる候補を同じ候補として扱い、実用的なランキングにする
        distinct_margin = max(3, step * 2, min_length // 10)
        ranked_candidates = []
        for score, start, end in raw_ranked_candidates:
            is_too_close = any(
                abs(start - picked_start) <= distinct_margin and abs(end - picked_end) <= distinct_margin
                for _, picked_start, picked_end in ranked_candidates
            )
            if not is_too_close:
                ranked_candidates.append((score, start, end))
            if len(ranked_candidates) >= self.max_match_rank:
                break

        # 間引き後に指定順位が足りない場合だけ、生のスコア順へフォールバック
        if selected_rank_index >= len(ranked_candidates):
            ranked_candidates = raw_ranked_candidates

        if selected_rank_index >= len(ranked_candidates):
            self.status_var.set(f"エラー：{selected_rank_label}位の候補が見つかりませんでした。")
            self.btn_export.config(state=tk.NORMAL)
            return

        best_score, best_start, best_end = ranked_candidates[selected_rank_index]
        rank_name = "BEST" if selected_rank_index == 0 else f"{selected_rank_index + 1}位"

        self.status_var.set(f"{rank_name}候補を使用！ {best_start}→{best_end} （SSIM={best_score:.4f}） 書き出しています...")

        # 出力処理
        # フェードOFF: 検出した区間をそのまま書き出す
        # フェードON : 先頭Nフレームを削り、末尾Nフレームへ先頭Nフレームをクロスフェード合成して書き出す
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        rank_for_file = "best" if selected_rank_index == 0 else f"rank{selected_rank_index + 1:02d}"
        fade_suffix = "-xfade" if self.fade_var.get() == 1 else ""
        out_path = f"{rank_for_file}-loop{fade_suffix}-{timestamp}.mp4"
        
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        try:
            out = self.open_ffmpeg_writer(out_path, fps, width, height)
        except Exception as e:
            self.status_var.set(f"エラー：{e}")
            self.btn_export.config(state=tk.NORMAL)
            return

        loop_length = best_end - best_start + 1
        wrote_frames = 0
        used_fade_length = 0

        write_error = None
        try:
            if self.fade_var.get() == 1:
                requested_fade_length = max(1, self.fade_length_var.get())
                # 先頭Nフレームを削り、末尾Nフレームを置き換えるので、最低でも2N+1程度の余裕が必要。
                # 短い区間では自動的にフェード長を短くする。
                used_fade_length = min(requested_fade_length, max(1, (loop_length - 1) // 2))

                if used_fade_length < 1 or loop_length <= used_fade_length:
                    used_fade_length = 0

            if used_fade_length == 0:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_start)
                for _ in range(best_start, best_end + 1):
                    ret, frame = self.cap.read()
                    if ret:
                        self.write_frame_to_ffmpeg(out, frame)
                        wrote_frames += 1
            else:
                fade_length = used_fade_length

                # 合成に使う先頭Nフレームを先に保持
                start_frames = []
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_start)
                for _ in range(fade_length):
                    ret, frame = self.cap.read()
                    if ret:
                        start_frames.append(frame)

                # 合成に使う末尾Nフレームを保持
                end_frames = []
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_end - fade_length + 1)
                for _ in range(fade_length):
                    ret, frame = self.cap.read()
                    if ret:
                        end_frames.append(frame)

                actual_fade_length = min(len(start_frames), len(end_frames))

                if actual_fade_length < 1:
                    # 念のため。読み込みに失敗した場合は通常書き出しへフォールバック。
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_start)
                    for _ in range(best_start, best_end + 1):
                        ret, frame = self.cap.read()
                        if ret:
                            self.write_frame_to_ffmpeg(out, frame)
                            wrote_frames += 1
                    used_fade_length = 0
                else:
                    fade_length = actual_fade_length
                    used_fade_length = actual_fade_length

                    # 先頭Nフレームは末尾でフェードインさせるため、通常部分からは削る。
                    normal_start = best_start + fade_length
                    normal_end = best_end - fade_length

                    if normal_start <= normal_end:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, normal_start)
                        for _ in range(normal_start, normal_end + 1):
                            ret, frame = self.cap.read()
                            if ret:
                                self.write_frame_to_ffmpeg(out, frame)
                                wrote_frames += 1

                    # 末尾Nフレームを、先頭Nフレームへ向かってクロスフェード。
                    # 最後の合成フレームは先頭側100%にすることで、ループ後の先頭に自然につなげる。
                    for i in range(fade_length):
                        alpha = (i + 1) / fade_length
                        blended = cv2.addWeighted(end_frames[i], 1 - alpha, start_frames[i], alpha, 0)
                        self.write_frame_to_ffmpeg(out, blended)
                        wrote_frames += 1

            self.close_ffmpeg_writer(out)
        except Exception as e:
            write_error = e
            try:
                if out.stdin:
                    out.stdin.close()
            except Exception:
                pass
            try:
                out.kill()
            except Exception:
                pass

        if write_error:
            self.status_var.set(f"エラー：{write_error}")
            self.btn_export.config(state=tk.NORMAL)
            return

        fade_note = f" / フェード{used_fade_length}F" if used_fade_length > 0 else ""
        self.status_var.set(f"完了！ 【 {out_path} 】 保存しました（{rank_name} / {wrote_frames}フレーム{fade_note} / SSIM={best_score:.4f}）")
        self.btn_export.config(state=tk.NORMAL)

if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        print("注意: D&D機能を使うには 'pip install tkinterdnd2' をインストールしてください。")
    
    app = LoopMakerApp(root)
    root.mainloop()