import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import datetime
import os
import threading

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
        self.max_loop_spin = ttk.Spinbox(param_frame, from_=60, to=2000, width=5, textvariable=self.max_loop_var)
        self.max_loop_spin.pack(side=tk.LEFT, padx=(0,5))

        tk.Label(param_frame, text="検索間隔:").pack(side=tk.LEFT)
        self.step_var = tk.IntVar(value=20)   # ← 高速化のため少し大きめに
        self.step_spin = ttk.Spinbox(param_frame, from_=5, to=50, width=5, textvariable=self.step_var)
        self.step_spin.pack(side=tk.LEFT)

        self.fade_var = tk.IntVar(value=0)
        self.fade_check = ttk.Checkbutton(controls_frame, text="フェード合成", variable=self.fade_var)
        self.fade_check.pack(side=tk.LEFT, padx=10)

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
        self.slider.config(to=self.total_frames - 1)
        self.slider.set(0)
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

    def export_loop(self):
        self.status_var.set("全フレームを高速読み込み中…")
        self.root.update()

        min_length = self.min_loop_var.get()
        max_length = self.max_loop_var.get()
        step = self.step_var.get()
        use_edge = self.edge_var.get() == 1

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

        self.status_var.set("最適ループ区間を検索中…")
        self.root.update()

        best_score = -1.0
        best_start = 0
        best_end = 0

        for start in range(0, self.total_frames - min_length, step):
            gray_start = small_frames[start]

            end_max = min(start + max_length, self.total_frames)
            for end in range(start + min_length, end_max):
                gray_end = small_frames[end]
                score = ssim(gray_start, gray_end)

                if score > best_score:
                    best_score = score
                    best_start = start
                    best_end = end

            if start % (step * 2) == 0:   # 進捗更新を少し減らす
                self.status_var.set(f"検索中… {start}/{self.total_frames}（ベスト: {best_score:.4f}）")
                self.root.update()

        if best_score == -1.0:
            self.status_var.set("適切なループ区間が見つかりませんでした。")
            self.btn_export.config(state=tk.NORMAL)
            return

        self.status_var.set(f"最適区間発見！ {best_start}→{best_end} （SSIM={best_score:.4f}） 書き出しています...")

        # 出力処理（本編＋フェード）
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        out_path = f"bestloop-{timestamp}.mp4"
        
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_start)
        for _ in range(best_start, best_end + 1):
            ret, frame = self.cap.read()
            if ret:
                out.write(frame)

        if self.fade_var.get() == 1:
            fade_length = 8
            end_frames = []
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_end - fade_length + 1)
            for _ in range(fade_length):
                ret, f = self.cap.read()
                if ret: end_frames.append(f)

            start_frames = []
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_start)
            for _ in range(fade_length):
                ret, f = self.cap.read()
                if ret: start_frames.append(f)

            for i in range(fade_length):
                alpha = i / (fade_length - 1)
                blended = cv2.addWeighted(end_frames[i], 1 - alpha, start_frames[i], alpha, 0)
                out.write(blended)

        out.release()
        self.status_var.set(f"完了！ 【 {out_path} 】 保存しました（{best_end - best_start + 1}フレーム / SSIM={best_score:.4f}）")
        self.btn_export.config(state=tk.NORMAL)

if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        print("注意: D&D機能を使うには 'pip install tkinterdnd2' をインストールしてください。")
    
    app = LoopMakerApp(root)
    root.mainloop()