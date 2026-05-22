import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import datetime
import os
import threading

# ドラッグ＆ドロップ対応のためのモジュール
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

class LoopMakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ループアニメーションメーカー")
        self.video_path = None
        self.cap = None
        self.total_frames = 0
        self.current_frame_idx = 0

        # UIセットアップ
        self.canvas = tk.Canvas(root, width=1280, height=720, bg='black')
        self.canvas.pack(pady=10)

        controls_frame = tk.Frame(root)
        controls_frame.pack(fill=tk.X, padx=20, pady=10)

        # 読み込みボタン
        self.btn_load = tk.Button(controls_frame, text="動画を読み込む", command=self.load_video_btn, bg="cyan", fg="black")
        self.btn_load.pack(side=tk.LEFT, padx=10)

        # シークバー
        self.slider = tk.Scale(controls_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.on_slider_move)
        self.slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # 検索範囲コンボボックス
        search_frame = tk.Frame(controls_frame)
        search_frame.pack(side=tk.LEFT, padx=10)
        tk.Label(search_frame, text="検索範囲(末尾):").pack(side=tk.LEFT)
        self.search_range_cb = ttk.Combobox(search_frame, values=["5%", "10%", "15%", "20%", "30%", "50%", "100%"], width=5)
        self.search_range_cb.set("10%")
        self.search_range_cb.pack(side=tk.LEFT)

        # 出力ボタン
        self.btn_export = tk.Button(controls_frame, text="出力", command=self.start_export, bg="magenta", fg="white")
        self.btn_export.pack(side=tk.LEFT, padx=10)
        self.btn_export.config(state=tk.DISABLED)

        # ステータスバー
        self.status_var = tk.StringVar()
        self.status_var.set("動画をドラッグ＆ドロップするか、ボタンから読み込んでください。")
        self.status_label = tk.Label(root, textvariable=self.status_var, font=("Arial", 10, "bold"))
        self.status_label.pack(pady=5)

        # D&Dイベントのバインド
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
        self.status_var.set(f"動画ロード完了: {os.path.basename(file_path)}")
        self.update_preview(0)

    def on_slider_move(self, val):
        if self.cap:
            self.current_frame_idx = int(val)
            self.update_preview(self.current_frame_idx)

    def update_preview(self, frame_idx):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            img = img.resize((1280, 720), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(image=img)
            self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW)

    def start_export(self):
        if not self.cap:
            return
        self.btn_export.config(state=tk.DISABLED)
        threading.Thread(target=self.export_loop, daemon=True).start()

    def export_loop(self):
        self.status_var.set("計算中…対象範囲から一番似ているフレームを検索しています！")
        start_idx = self.current_frame_idx
        
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_idx)
        ret, start_frame = self.cap.read()
        if not ret:
            self.status_var.set("エラー：開始フレームが読み込めません。")
            self.btn_export.config(state=tk.NORMAL)
            return

        gray_start = cv2.cvtColor(start_frame, cv2.COLOR_BGR2GRAY)
        best_diff = float('inf')
        best_idx = -1

        # コンボボックスから検索範囲（%）を取得
        range_str = self.search_range_cb.get().replace("%", "")
        try:
            search_percent = float(range_str)
        except ValueError:
            search_percent = 10.0
            
        min_loop_length = 10
        
        # --- ここから修正 ---
        # 開始位置から最後のフレームまでの「残りフレーム数」を算出
        remaining_frames = self.total_frames - start_idx
        
        # 残りフレーム数に対して、指定された割合（%）を掛ける
        search_target_frames = int(remaining_frames * (search_percent / 100.0))
        
        # 検索開始位置を決定（末尾から search_target_frames 分だけ戻った位置）
        search_start_idx = self.total_frames - search_target_frames
        # --- 修正ここまで ---
        
        # ただし、開始指定フレーム＋最小ループ間隔よりは必ず後ろにする
        search_start_idx = max(start_idx + min_loop_length, search_start_idx)

        # 検索範囲が動画の終端を超えている場合の安全処理
        if search_start_idx >= self.total_frames:
            self.status_var.set("エラー：検索範囲が狭すぎるか、開始フレームが後ろすぎます！")
            self.btn_export.config(state=tk.NORMAL)
            return

        # 不要なフレームを読み飛ばし、検索開始位置へ一気にジャンプ
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, search_start_idx)

        for i in range(search_start_idx, self.total_frames):
            ret, frame = self.cap.read()
            if not ret:
                break
            
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # 画像の差分の平均値を計算
            diff = np.mean(np.abs(gray_start.astype(int) - gray_frame.astype(int)))
            
            if diff < best_diff:
                best_diff = diff
                best_idx = i

        if best_idx == -1:
            self.status_var.set("似ているフレームが見つかりませんでした。")
            self.btn_export.config(state=tk.NORMAL)
            return

        self.status_var.set(f"フレーム {best_idx} がベストマッチ！動画を書き出しています...")

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

        out.release()
        self.status_var.set(f"完了！ 【 {out_path} 】 を保存しました！")
        self.btn_export.config(state=tk.NORMAL)

if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        print("注意: D&D機能を使うには 'pip install tkinterdnd2' をインストールしてください。")
    
    app = LoopMakerApp(root)
    root.mainloop()