"""編集の画面 (プレビュー・切り貼り・フェード)。"""
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, core, edit

try:
    import winsound
except ImportError:        # Windows 以外では音なしでプレビュー
    winsound = None

CLIP_COLORS = ('#4a90d9', '#5fb37a', '#d9a04a', '#b37ad9')


def fmt(t):
    t = max(0.0, t)
    return '%d:%04.1f' % (int(t // 60), t - int(t // 60) * 60)


class Player:
    """プレビュー再生: ffmpeg から小さい映像を受け取り、音は WAV にして winsound で鳴らす。"""

    def __init__(self, project, t0):
        self.t0 = t0
        self.t1 = min(project.duration, t0 + edit.PREVIEW_MAX_SEC)
        self.cmd, self.size, self.fps = edit.preview_video_cmd(project, t0, self.t1)
        self.tmp = tempfile.mkdtemp(prefix='tvc_')
        self.wav = Path(self.tmp) / 'preview.wav'
        self.acmd = edit.preview_audio_cmd(project, t0, self.t1, self.wav)
        self.frames = queue.Queue(maxsize=12)
        self.audio_ready = threading.Event()
        self.audio_ok = False
        self.eof = False
        self.stopped = False
        self.proc = None
        threading.Thread(target=self._audio, daemon=True).start()
        threading.Thread(target=self._video, daemon=True).start()

    def _audio(self):
        try:
            if winsound:
                subprocess.run(self.acmd, stdin=subprocess.DEVNULL, capture_output=True, creationflags=core.NOWIN)
                self.audio_ok = self.wav.exists() and self.wav.stat().st_size > 1000
        except Exception:
            pass
        finally:
            self.audio_ready.set()

    def _video(self):
        n = self.size[0] * self.size[1] * 3
        try:
            self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, creationflags=core.NOWIN)
            while not self.stopped:
                buf = self.proc.stdout.read(n)
                if len(buf) < n:
                    break
                while not self.stopped:
                    try:
                        self.frames.put(buf, timeout=0.1)
                        break
                    except queue.Full:
                        pass
        except Exception:
            pass
        finally:
            self.eof = True
            if self.proc and self.proc.poll() is None:
                self.proc.kill()

    def start_sound(self):
        if self.audio_ok and not self.stopped:
            try:
                winsound.PlaySound(str(self.wav), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except RuntimeError:
                pass

    def stop(self):
        self.stopped = True
        if winsound:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except RuntimeError:
                pass
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)


class Editor:
    def __init__(self, parent, project, on_ok):
        self.project = project.copy()
        self.on_ok = on_ok
        self.pos = 0.0
        self.undo_stack = []
        self.player = None
        self.play_start = None
        self.play_read = 0
        self.closed = False
        self.msgs = queue.Queue()
        self.still_req = None
        self.still_seq = 0
        self.still_shown = 0
        self.still_event = threading.Event()
        self.image = None
        self.syncing = False

        win = self.win = tk.Toplevel(parent)
        win.title(f'{APP_NAME} - 編集')
        win.transient(parent)
        win.resizable(False, False)

        bw, bh = edit.PREVIEW_BOX
        box = tk.Frame(win, width=bw, height=bh, bg='black')
        box.pack(padx=8, pady=(8, 4))
        box.pack_propagate(False)
        self.screen = tk.Label(box, bg='black', fg='white', text='読み込み中…')
        self.screen.pack(expand=True)

        self.line = tk.Canvas(win, width=bw, height=44, bg='#202020', highlightthickness=0, cursor='hand2')
        self.line.pack(padx=8)
        self.line.bind('<Button-1>', self.on_line)
        self.line.bind('<B1-Motion>', self.on_line)

        bar = ttk.Frame(win)
        bar.pack(fill='x', padx=8, pady=4)
        self.b_play = ttk.Button(bar, text='▶ 再生', width=9, command=self.toggle_play)
        self.b_play.pack(side='left')
        for text, d in (('◀ 1秒', -1.0), ('◀ 1コマ', -self.frame_step()), ('1コマ ▶', self.frame_step()), ('1秒 ▶', 1.0)):
            ttk.Button(bar, text=text, width=8, command=lambda d=d: self.seek(self.pos + d)).pack(side='left', padx=(6, 0))
        self.v_time = tk.StringVar()
        ttk.Label(bar, textvariable=self.v_time).pack(side='right')

        ops = ttk.LabelFrame(win, text='切り貼り（赤い線の位置が基準です）')
        ops.pack(fill='x', padx=8, pady=4)
        row1 = ttk.Frame(ops)
        row1.pack(fill='x', padx=6, pady=(4, 2))
        row2 = ttk.Frame(ops)
        row2.pack(fill='x', padx=6, pady=(2, 6))
        for row, items in ((row1, (('ここで分ける', self.do_split), ('この部分を消す', self.do_delete),
                                   ('ここより前を消す', self.do_trim_head), ('ここより後ろを消す', self.do_trim_tail))),
                           (row2, (('← この部分を前へ', lambda: self.do_move(-1)), ('この部分を後ろへ →', lambda: self.do_move(1)),
                                   ('別の動画を足す…', self.do_add), ('元に戻す', self.do_undo)))):
            for text, cmd in items:
                ttk.Button(row, text=text, command=cmd).pack(side='left', padx=(0, 6))

        self.tree = ttk.Treeview(win, columns=('no', 'name', 'range', 'len'), show='headings', height=4,
                                 selectmode='browse')
        for c, text, w, anchor in (('no', '順番', 44, 'e'), ('name', '元の動画', 300, 'w'),
                                   ('range', '使っている範囲', 170, 'w'), ('len', '長さ', 80, 'e')):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor)
        self.tree.pack(fill='x', padx=8, pady=4)
        self.tree.bind('<<TreeviewSelect>>', self.on_tree)

        fx = ttk.LabelFrame(win, text='フェード（映像と音の両方。0 でなし）')
        fx.pack(fill='x', padx=8, pady=4)
        self.v_in = tk.StringVar(value='%g' % self.project.fade_in)
        self.v_out = tk.StringVar(value='%g' % self.project.fade_out)
        for label, var in (('最初のフェードイン', self.v_in), ('　最後のフェードアウト', self.v_out)):
            ttk.Label(fx, text=label).pack(side='left', padx=(6, 4), pady=6)
            ttk.Spinbox(fx, textvariable=var, from_=0, to=edit.MAX_FADE, increment=0.5, width=5).pack(side='left')
            ttk.Label(fx, text='秒').pack(side='left', padx=(2, 0))
            var.trace_add('write', lambda *a: self.on_fade())

        end = ttk.Frame(win)
        end.pack(fill='x', padx=8, pady=(4, 10))
        self.v_total = tk.StringVar()
        ttk.Label(end, textvariable=self.v_total).pack(side='left')
        ttk.Button(end, text='取り消し', command=self.close).pack(side='right')
        ttk.Button(end, text='決定', command=self.ok).pack(side='right', padx=6)

        win.bind('<space>', self.on_key_space)
        win.bind('<Left>', lambda e: self.on_key_step(-1))
        win.bind('<Right>', lambda e: self.on_key_step(1))
        win.protocol('WM_DELETE_WINDOW', self.close)
        threading.Thread(target=self._still_loop, daemon=True).start()
        self.refresh()
        win.after(30, self._poll)
        win.grab_set()
        win.focus_set()

    # ---- 表示 ----
    def frame_step(self):
        f = self.project.clips[0].info.fps
        return 1.0 / f if 1.0 <= f <= 240.0 else 1.0 / 30

    def refresh(self):
        """編集内容が変わったときに全部描き直す。"""
        p = self.project
        self.pos = max(0.0, min(self.pos, p.duration))
        self.syncing = True
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(p.clips):
            self.tree.insert('', 'end', iid=str(i), values=(
                i + 1, c.info.path.name, f'{fmt(c.start)} 〜 {fmt(c.end)}', fmt(c.dur)))
        self.syncing = False
        total = p.duration
        text = f'合計 {fmt(total)}'
        if total > core.LIMIT_SEC:
            text += '　※2分20秒を超えています（通常アカウントでは「長い動画の扱い」の設定に従います）'
        self.v_total.set(text)
        self.draw_line()
        self.update_pos()
        self.request_still()

    def draw_line(self):
        cv, p = self.line, self.project
        cv.delete('all')
        w, h = int(cv['width']), int(cv['height'])
        total = p.duration or 1.0
        cur = p.locate(self.pos)[0]
        for i, (a, e) in enumerate(p.bounds()):
            x0, x1 = a / total * w, e / total * w
            cv.create_rectangle(x0, 6, x1 - 1, h - 6, fill=CLIP_COLORS[i % len(CLIP_COLORS)],
                                outline='white' if i == cur else '#202020', width=2 if i == cur else 1)
            if x1 - x0 > 18:
                cv.create_text((x0 + x1) / 2, h / 2, text=str(i + 1), fill='white')
        if p.fade_in > 0:
            x = p.fade_in / total * w
            cv.create_polygon(0, 6, x, 6, 0, h - 6, fill='black', stipple='gray50')
        if p.fade_out > 0:
            x = (total - p.fade_out) / total * w
            cv.create_polygon(x, 6, w, 6, w, h - 6, fill='black', stipple='gray50')
        x = self.pos / total * w
        self.head = cv.create_line(x, 0, x, h, fill='#ff4040', width=2)
        self.line_cur = cur

    def update_pos(self):
        p = self.project
        total = p.duration or 1.0
        i = p.locate(self.pos)[0]
        if i != self.line_cur:
            self.draw_line()
        else:
            x = self.pos / total * int(self.line['width'])
            self.line.coords(self.head, x, 0, x, int(self.line['height']))
        self.v_time.set(f'{fmt(self.pos)} / {fmt(p.duration)}　（{i + 1} 番目の部分）')
        if self.tree.selection() != (str(i),):
            self.tree.selection_set(str(i))
            self.tree.see(str(i))

    def show(self, ppm):
        try:
            self.image = tk.PhotoImage(data=ppm, format='ppm')
            self.screen.configure(image=self.image, text='')
        except tk.TclError:
            pass

    # ---- 1コマのプレビュー (別スレッドで作る) ----
    def request_still(self):
        self.still_seq += 1
        self.still_req = (self.still_seq, self.project.copy(), self.pos)
        self.still_event.set()

    def _still_loop(self):
        while not self.closed:
            self.still_event.wait()
            self.still_event.clear()
            req = self.still_req
            if self.closed or req is None:
                continue
            try:
                res = edit.preview_frame(req[1], req[2])
            except Exception:
                res = None
            self.msgs.put((req[0], res))

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                seq, res = self.msgs.get_nowait()
                if res and seq > self.still_shown and self.player is None:
                    self.still_shown = seq
                    self.show(res[1])
        except queue.Empty:
            pass
        self.win.after(30, self._poll)

    # ---- 位置の移動・再生 ----
    def seek(self, t):
        self.stop_play()
        self.pos = max(0.0, min(t, self.project.duration))
        self.update_pos()
        self.request_still()

    def on_line(self, event):
        self.seek(event.x / int(self.line['width']) * self.project.duration)

    def on_tree(self, event):
        sel = self.tree.selection()     # 赤い線に合わせて選び直しただけのときは何もしない
        if sel and int(sel[0]) < len(self.project.clips) and int(sel[0]) != self.project.locate(self.pos)[0]:
            self.seek(self.project.bounds()[int(sel[0])][0])

    def typing(self):
        return self.win.focus_get().winfo_class() in ('TSpinbox', 'TEntry', 'Entry', 'Spinbox') \
            if self.win.focus_get() else False

    def on_key_space(self, event):
        if not self.typing() and event.widget.winfo_class() != 'TButton':
            self.toggle_play()

    def on_key_step(self, d):
        if not self.typing():
            self.seek(self.pos + d * self.frame_step())

    def toggle_play(self):
        if self.player:
            self.stop_play()
            self.request_still()
            return
        if self.pos >= self.project.duration - 0.1:
            self.pos = 0.0
        try:
            self.player = Player(self.project.copy(), self.pos)
        except core.ConvertError:
            return
        self.play_start = None
        self.b_play.configure(text='■ 停止')
        self._tick()

    def stop_play(self):
        if self.player:
            self.player.stop()
            self.player = None
            self.b_play.configure(text='▶ 再生')

    def _tick(self):
        pl = self.player
        if pl is None or self.closed:
            return
        if self.play_start is None:        # 音と最初のコマの用意ができるまで待つ
            if pl.audio_ready.is_set() and (not pl.frames.empty() or pl.eof):
                pl.start_sound()
                self.play_start = time.perf_counter()
                self.play_read = 0
        else:
            elapsed = time.perf_counter() - self.play_start
            target = int(elapsed * pl.fps)
            frame = None
            while self.play_read <= target:    # 遅れているときは古いコマを捨てる
                try:
                    frame = pl.frames.get_nowait()
                    self.play_read += 1
                except queue.Empty:
                    break
            if frame is not None:
                self.show(edit.ppm(pl.size, frame))
            self.pos = min(pl.t1, pl.t0 + elapsed)
            self.update_pos()
            if (pl.eof and pl.frames.empty()) or pl.t0 + elapsed >= pl.t1 + 0.3:
                self.stop_play()
                self.pos = pl.t1
                self.update_pos()
                return
        self.win.after(15, self._tick)

    # ---- 編集 ----
    def change(self, func, fail_text):
        """編集の操作を1つ行う (元に戻せるように前の状態を覚える)。"""
        self.stop_play()
        before = self.project.copy()
        if func():
            self.undo_stack.append(before)
            del self.undo_stack[:-50]
            self.refresh()
        else:
            messagebox.showinfo(APP_NAME, fail_text, parent=self.win)

    def do_split(self):
        self.change(lambda: self.project.split(self.pos), '部分の端に近すぎるので、ここでは分けられません。')

    def do_delete(self):
        i = self.project.locate(self.pos)[0]
        start = self.project.bounds()[i][0]

        def f():
            if not self.project.delete(i):
                return False
            self.pos = min(start, self.project.duration)
            return True
        self.change(f, '部分が1つしかないので消せません。\n先に「ここで分ける」で分けてください。')

    def do_trim_head(self):
        pos = self.pos

        def f():
            if pos < edit.MIN_CLIP or not self.project.keep_range(pos, self.project.duration):
                return False
            self.pos = 0.0
            return True
        self.change(f, '消す部分がないか、残りが短すぎます。')

    def do_trim_tail(self):
        pos = self.pos

        def f():
            if self.project.duration - pos < edit.MIN_CLIP:
                return False
            return self.project.keep_range(0.0, pos)
        self.change(f, '消す部分がないか、残りが短すぎます。')

    def do_move(self, d):
        i, off = self.project.locate(self.pos)

        def f():
            if not self.project.move(i, d):
                return False
            self.pos = self.project.bounds()[i + d][0] + off
            return True
        self.change(f, 'これ以上は動かせません。')

    def do_add(self):
        self.stop_play()
        paths = filedialog.askopenfilenames(parent=self.win, title='つなげる動画を選ぶ')
        errors = []
        before = self.project.copy()
        for path in paths:
            try:
                self.project.append(core.probe(path))
            except core.ConvertError as e:
                errors.append(f'{Path(path).name}: {e}')
        if len(self.project.clips) != len(before.clips):
            self.undo_stack.append(before)
            self.refresh()
        if errors:
            messagebox.showwarning(APP_NAME, '次のファイルは追加できませんでした。\n\n' + '\n'.join(errors), parent=self.win)

    def do_undo(self):
        self.stop_play()
        if not self.undo_stack:
            return
        self.project = self.undo_stack.pop()
        self.syncing = True
        self.v_in.set('%g' % self.project.fade_in)
        self.v_out.set('%g' % self.project.fade_out)
        self.syncing = False
        self.refresh()

    def read_fades(self):
        vals = []
        for var in (self.v_in, self.v_out):
            try:
                vals.append(max(0.0, float(var.get() or 0)))
            except ValueError:
                vals.append(0.0)
        return vals

    def on_fade(self):
        if self.syncing:
            return
        self.stop_play()
        self.project.fade_in, self.project.fade_out = self.read_fades()
        self.project.clamp_fades()
        self.draw_line()
        self.request_still()

    # ---- 終了 ----
    def ok(self):
        self.project.fade_in, self.project.fade_out = self.read_fades()
        self.project.clamp_fades()
        project = self.project
        self.close()
        self.on_ok(project)

    def close(self):
        if self.closed:
            return
        self.stop_play()
        self.closed = True
        self.still_event.set()
        self.win.grab_release()
        self.win.destroy()
