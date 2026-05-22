import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import datetime
import os
import threading

# ドラッグ＆ドロップ
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

# SSIM
try:
    from skimage.metrics import structural_similarity as ssim
    HAS_SSIM = True
except ImportError:
    HAS_SSIM = False

class LoopMakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ループアニメーションメーカー")
        self.video_path = None
        self.cap = None
        self.total_frames = 0
        self.current_frame_idx = 0

        self.canvas_width = 1280
        self.canvas_height = 720

        # UI
        self.canvas = tk.Canvas(root, width=self.canvas_width, height=self.canvas_height, bg='black')
        self.canvas.pack(pady=10)

        controls_frame = tk.Frame(root)
        controls_frame.pack(fill=tk.X, padx=20, pady=10)

        self.btn_load = tk.Button(controls_frame, text="動画を読み込む", command=self.load_video_btn, bg="cyan", fg="black")
        self.btn_load.pack(side=tk.LEFT, padx=10)

        self.slider = tk.Scale(controls_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.on_slider_move)
        self.slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # 検索範囲（10%刻み）
        search_frame = tk.Frame(controls_frame)
        search_frame.pack(side=tk.LEFT, padx=10)
        tk.Label(search_frame, text="検索範囲(末尾):").pack(side=tk.LEFT)
        self.search_range_cb = ttk.Combobox(search_frame, 
                                           values=["10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%", "90%", "100%"], 
                                           width=5)
        self.search_range_cb.set("10%")
        self.search_range_cb.pack(side=tk.LEFT)

        # フェード合成（デフォルトOFF）
        self.fade_var = tk.IntVar(value=0)
        self.fade_check = ttk.Checkbutton(controls_frame, text="フェード合成を適用", variable=self.fade_var)
        self.fade_check.pack(side=tk.LEFT, padx=10)

        # ★ 新機能：エッジ比較モード（デフォルトOFF）
        self.edge_var = tk.IntVar(value=0)
        self.edge_check = ttk.Checkbutton(controls_frame, text="エッジ（輪郭）比較モード", variable=self.edge_var)
        self.edge_check.pack(side=tk.LEFT, padx=10)

        self.btn_export = tk.Button(controls_frame, text="出力", command=self.start_export, bg="magenta", fg="white")
        self.btn_export.pack(side=tk.LEFT, padx=10)
        self.btn_export.config(state=tk.DISABLED)

        self.status_var = tk.StringVar()
        self.status_var.set("動画をドラッグ＆ドロップするか、ボタンから読み込んでください。")
        self.status_label = tk.Label(root, textvariable=self.status_var, font=("Arial", 10, "bold"))
        self.status_label.pack(pady=5)

        self.photo = None

        if HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_drop)

    # 以下は変更なし（load_video, on_slider_move, update_preview は前回と同じ）
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
        self.status_var.set(f"動画ロード完了: {os.path.basename(file_path)}")
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
        if not self.cap:
            return
        if not HAS_SSIM:
            messagebox.showerror("エラー", "SSIM機能を使うには `pip install scikit-image` を実行してください！")
            return
        self.btn_export.config(state=tk.DISABLED)
        threading.Thread(target=self.export_loop, daemon=True).start()

    def export_loop(self):
        self.status_var.set("計算中…SSIMで一番似ているフレームを検索しています！")
        start_idx = self.current_frame_idx
        
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_idx)
        ret, start_frame = self.cap.read()
        if not ret:
            self.status_var.set("エラー：開始フレームが読み込めません。")
            self.btn_export.config(state=tk.NORMAL)
            return

        # エッジモードかどうかで前処理を切り替え
        use_edge = self.edge_var.get() == 1
        if use_edge:
            gray_start = cv2.Canny(cv2.cvtColor(start_frame, cv2.COLOR_BGR2GRAY), 50, 150)
            mode_text = "エッジ比較"
        else:
            gray_start = cv2.cvtColor(start_frame, cv2.COLOR_BGR2GRAY)
            mode_text = "通常比較"

        best_score = -1.0
        best_idx = -1

        range_str = self.search_range_cb.get().replace("%", "")
        try:
            search_percent = float(range_str)
        except ValueError:
            search_percent = 10.0
            
        min_loop_length = 10
        remaining_frames = self.total_frames - start_idx
        search_target_frames = int(remaining_frames * (search_percent / 100.0))
        search_start_idx = self.total_frames - search_target_frames
        search_start_idx = max(start_idx + min_loop_length, search_start_idx)

        if search_start_idx >= self.total_frames:
            self.status_var.set("エラー：検索範囲が狭すぎるか、開始フレームが後ろすぎます！")
            self.btn_export.config(state=tk.NORMAL)
            return

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, search_start_idx)

        for i in range(search_start_idx, self.total_frames):
            ret, frame = self.cap.read()
            if not ret:
                break
            
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if use_edge:
                gray_frame = cv2.Canny(gray_frame, 50, 150)
            
            score = ssim(gray_start, gray_frame)

            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx == -1:
            self.status_var.set("似ているフレームが見つかりませんでした。")
            self.btn_export.config(state=tk.NORMAL)
            return

        self.status_var.set(f"フレーム {best_idx} がベストマッチ！（{mode_text} SSIM={best_score:.4f}） 書き出しています...")

        # 以降は前回と同じ（出力＋フェード部分）
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        out_path = f"loop-{timestamp}.mp4"
        
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_idx)
        for _ in range(start_idx, best_idx + 1):
            ret, frame = self.cap.read()
            if ret:
                out.write(frame)

        if self.fade_var.get() == 1:
            fade_length = 8
            self.status_var.set("フェード合成中…")
            self.root.update()

            end_frames = []
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, best_idx - fade_length + 1)
            for _ in range(fade_length):
                ret, f = self.cap.read()
                if ret: end_frames.append(f)

            start_frames = []
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_idx)
            for _ in range(fade_length):
                ret, f = self.cap.read()
                if ret: start_frames.append(f)

            for i in range(fade_length):
                alpha = i / (fade_length - 1) if fade_length > 1 else 0
                blended = cv2.addWeighted(end_frames[i], 1 - alpha, start_frames[i], alpha, 0)
                out.write(blended)

        out.release()
        self.status_var.set(f"完了！ 【 {out_path} 】 を保存しました！（{'エッジ' if use_edge else '通常'} / フェード{'ON' if self.fade_var.get() else 'OFF'}）")
        self.btn_export.config(state=tk.NORMAL)

if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        print("注意: D&D機能を使うには 'pip install tkinterdnd2' をインストールしてください。")
    
    app = LoopMakerApp(root)
    root.mainloop()