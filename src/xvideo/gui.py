"""Video Converter for X の画面 (tkinter)。"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__, core, edit
from .editor import Editor

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:          # ドラッグ＆ドロップのライブラリがなくても動くように
    TkinterDnD = None

VIDEO_EXT = {'.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi', '.wmv', '.flv', '.ts', '.m2ts', '.mts',
             '.mpg', '.mpeg', '.vob', '.3gp', '.ogv', '.asf', '.gif', '.f4v', '.mxf', '.divx'}

ACCOUNT = [('normal', '通常（2分20秒・512MBまで）'), ('premium', 'Premium（長い動画も投稿できる）')]
LONG = [('split', '2分20秒以内に分割する（複数のファイルになる）'),
        ('trim', '最初の2分20秒だけにする'),
        ('keep', '切らずにそのまま変換する')]
QUALITY = [('high', '高画質（ファイル大きめ）'), ('standard', '標準'), ('small', '軽い（ファイル小さめ）')]
SIZE = [(1920, '1080p（フルHD）まで'), (1280, '720p（HD）まで')]
FPS = [(60, '60fps まで'), (30, '30fps まで')]


def settings_path():
    base = Path(os.environ.get('APPDATA') or Path.home()) / 'VideoConverterForX'
    return base / 'settings.json'


def load_settings():
    p = settings_path()
    if not p.exists():   # 改名前 (TwitterVideoConverter) の設定があれば引き継ぐ
        p = p.parent.parent / 'TwitterVideoConverter' / 'settings.json'
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_settings(data):
    try:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    except Exception:
        pass


class Choice:
    """「内部の値 ⇔ 表示の文字」を持つ読み取り専用のコンボボックス。"""

    def __init__(self, parent, items, value, width=40, command=None):
        self.items = items
        self.var = tk.StringVar()
        self.box = ttk.Combobox(parent, textvariable=self.var, state='readonly', width=width,
                                values=[label for _, label in items])
        self.set(value)
        if command:
            self.box.bind('<<ComboboxSelected>>', lambda e: command())

    def set(self, value):
        for v, label in self.items:
            if v == value:
                self.var.set(label)
                return
        self.var.set(self.items[0][1])

    def get(self):
        for v, label in self.items:
            if label == self.var.get():
                return v
        return self.items[0][0]


class App:
    def __init__(self, root):
        self.root = root
        self.items = {}            # tree の id → {'info': Info, 'state': 'wait'|'done'|'error'}
        self.msgs = queue.Queue()
        self.worker = None
        self.cancel = threading.Event()
        self.last_out_dir = None
        s = load_settings()

        root.title(f'{APP_NAME} {__version__}')
        root.minsize(760, 560)
        pad = dict(padx=8, pady=4)

        top = ttk.Frame(root)
        top.pack(fill='x', **pad)
        hint = 'この窓に動画をドラッグ＆ドロップするか、「動画を追加」を押してください。' if TkinterDnD \
            else '「動画を追加」を押して動画を選んでください。'
        ttk.Label(top, text=hint).pack(side='left')
        ttk.Button(top, text='このアプリについて', command=self.about).pack(side='right')

        mid = ttk.Frame(root)
        mid.pack(fill='both', expand=True, **pad)
        cols = ('name', 'length', 'size', 'state')
        self.tree = ttk.Treeview(mid, columns=cols, show='headings', height=8, selectmode='extended')
        try:                       # 文字が大きい環境でも「長さ」「元の大きさ」が欠けないように、文字の幅から決める
            from tkinter import font
            f = font.nametofont('TkDefaultFont')
            w_len = max(60, f.measure('00:00:00') + 16)
            w_size = max(150, f.measure('元の大きさ'), f.measure('3840x2160 120fps') + 16)
        except tk.TclError:
            w_len, w_size = 60, 150
        for c, text, w, anchor in (('name', 'ファイル', 300, 'w'), ('length', '長さ', w_len, 'e'),
                                   ('size', '元の大きさ', w_size, 'w'), ('state', '状態', 260, 'w')):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor, stretch=c in ('name', 'state'))
        sb = ttk.Scrollbar(mid, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='left', fill='y')
        self.tree.bind('<Delete>', lambda e: self.remove_selected())
        self.tree.bind('<Double-1>', lambda e: self.open_editor())

        btns = ttk.Frame(root)
        btns.pack(fill='x', **pad)
        self.b_add = ttk.Button(btns, text='動画を追加…', command=self.pick_files)
        self.b_add.pack(side='left')
        self.b_edit = ttk.Button(btns, text='編集（プレビュー・切り貼り・フェード）…', command=self.open_editor)
        self.b_edit.pack(side='left', padx=(6, 0))
        self.b_remove = ttk.Button(btns, text='選んだものを外す', command=self.remove_selected)
        self.b_remove.pack(side='left', padx=6)
        self.b_clear = ttk.Button(btns, text='一覧を空にする', command=self.clear)
        self.b_clear.pack(side='left')

        box = ttk.LabelFrame(root, text='設定')
        box.pack(fill='x', **pad)
        box.columnconfigure(1, weight=1)
        self.c_account = Choice(box, ACCOUNT, 'premium' if s.get('premium') else 'normal', command=self.on_account)
        self.c_long = Choice(box, LONG, s.get('long_mode', 'split'))
        self.c_quality = Choice(box, QUALITY, s.get('quality', 'standard'))
        self.c_size = Choice(box, SIZE, s.get('max_long', 1920))
        self.c_fps = Choice(box, FPS, s.get('max_fps', 60))
        rows = (('アカウントの種類', self.c_account.box), ('長い動画の扱い', self.c_long.box),
                ('画質', self.c_quality.box), ('大きさ', self.c_size.box), ('なめらかさ', self.c_fps.box))
        for r, (label, w) in enumerate(rows):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky='w', padx=8, pady=3)
            w.grid(row=r, column=1, sticky='w', padx=8, pady=3)

        r = len(rows)
        ttk.Label(box, text='使う範囲（空なら全部）').grid(row=r, column=0, sticky='w', padx=8, pady=3)
        rng = ttk.Frame(box)
        rng.grid(row=r, column=1, sticky='w', padx=8, pady=3)
        self.v_start = tk.StringVar()
        self.v_end = tk.StringVar()
        ttk.Entry(rng, textvariable=self.v_start, width=9).pack(side='left')
        ttk.Label(rng, text=' から ').pack(side='left')
        ttk.Entry(rng, textvariable=self.v_end, width=9).pack(side='left')
        ttk.Label(rng, text=' まで　（例 0:15 から 1:30。編集していない全部の動画に使われます）').pack(side='left')

        r += 1
        ttk.Label(box, text='保存先').grid(row=r, column=0, sticky='w', padx=8, pady=3)
        outf = ttk.Frame(box)
        outf.grid(row=r, column=1, sticky='we', padx=8, pady=3)
        self.v_out = tk.StringVar(value=s.get('out_dir', ''))
        self.l_out = ttk.Label(outf, text='')
        self.l_out.pack(side='left')
        ttk.Button(outf, text='フォルダを選ぶ…', command=self.pick_out).pack(side='left', padx=6)
        ttk.Button(outf, text='元の動画と同じ場所にする', command=lambda: self.set_out('')).pack(side='left')
        self.set_out(self.v_out.get())

        bottom = ttk.Frame(root)
        bottom.pack(fill='x', **pad)
        self.bar = ttk.Progressbar(bottom, maximum=1000)
        self.bar.pack(fill='x')
        self.v_status = tk.StringVar(value='動画を追加して「変換を始める」を押してください。')
        ttk.Label(bottom, textvariable=self.v_status).pack(anchor='w', pady=(4, 0))

        act = ttk.Frame(root)
        act.pack(fill='x', padx=8, pady=(2, 10))
        self.b_start = ttk.Button(act, text='変換を始める', command=self.start)
        self.b_start.pack(side='left')
        self.b_stop = ttk.Button(act, text='中止', command=self.stop, state='disabled')
        self.b_stop.pack(side='left', padx=6)
        self.b_open = ttk.Button(act, text='保存先を開く', command=self.open_out, state='disabled')
        self.b_open.pack(side='left')

        self.on_account()
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.after(100, self.poll)

    # ---- 一覧 ----
    def add_paths(self, paths):
        files = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                files += sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT)
            elif p.is_file():
                files.append(p)
        known = {str(it['info'].path).lower() for it in self.items.values()}
        errors = []
        for f in files:
            if str(f).lower() in known:
                continue
            try:
                info = core.probe(f)
            except core.ConvertError as e:
                errors.append(f'{f.name}: {e}')
                continue
            w, h = info.display_size
            desc = f'{int(round(w))}x{int(round(h))} {info.fps:g}fps' + (' HDR' if info.hdr else '')
            iid = self.tree.insert('', 'end', values=(
                f.name, core.fmt_time(info.duration) if info.duration else '?', desc, '待機中'))
            self.items[iid] = {'info': info, 'project': None, 'state': 'wait'}
            known.add(str(f).lower())
        if errors:
            messagebox.showwarning(APP_NAME, '次のファイルは追加できませんでした。\n\n' + '\n'.join(errors[:10]))
        self.v_status.set(f'{len(self.items)} 本の動画が一覧にあります。')

    def pick_files(self):
        paths = filedialog.askopenfilenames(title='変換する動画を選ぶ', filetypes=[
            ('動画', ' '.join('*' + e for e in sorted(VIDEO_EXT))), ('すべてのファイル', '*.*')])
        if paths:
            self.add_paths(paths)

    def remove_selected(self):
        if self.worker:
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.items.pop(iid, None)

    def clear(self):
        if self.worker:
            return
        for iid in list(self.items):
            self.tree.delete(iid)
        self.items.clear()

    # ---- 編集 ----
    def open_editor(self):
        if self.worker:
            return
        sel = [i for i in self.tree.selection() if i in self.items]
        if not sel and len(self.items) == 1:
            sel = list(self.items)
        if not sel:
            messagebox.showinfo(APP_NAME, '編集する動画を一覧から選んでください。\n'
                                          '複数選ぶと、つなげて1本の動画にできます。')
            return
        if len(sel) > 1 and not messagebox.askyesno(
                APP_NAME, f'選んだ {len(sel)} 本を、一覧の順につなげて1本の動画として編集しますか？\n'
                          '（「決定」を押すと、一覧では1行にまとまります）'):
            return
        try:
            project = edit.Project()
            for iid in sel:
                it = self.items[iid]
                if it['project']:
                    project.clips += it['project'].copy().clips
                else:
                    project.append(it['info'])
            first = self.items[sel[0]]['project']
            if first:
                project.fade_in, project.fade_out = first.fade_in, first.fade_out
        except core.ConvertError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.editor = Editor(self.root, project, lambda p: self.apply_edit(sel, p))

    def apply_edit(self, sel, project):
        iid = sel[0]
        for other in sel[1:]:              # つなげた分は1行にまとめる
            self.tree.delete(other)
            self.items.pop(other, None)
        it = self.items[iid]
        it['project'] = project if project.edited else None
        it['info'] = project.clips[0].info
        it['state'] = 'wait'
        name = it['info'].path.name
        if it['project']:
            files = len({str(c.info.path).lower() for c in project.clips})
            name = '✂ ' + name + (f' ほか{files - 1}本' if files > 1 else '')
        self.tree.set(iid, 'name', name)
        self.tree.set(iid, 'length', core.fmt_time(project.duration))
        self.tree.set(iid, 'state', '待機中（編集あり）' if it['project'] else '待機中')
        self.v_status.set('編集を覚えました。「変換を始める」で変換します。' if it['project']
                          else '編集なしに戻しました。')

    # ---- 設定 ----
    def on_account(self):
        self.c_long.box.configure(state='disabled' if self.c_account.get() == 'premium' else 'readonly')

    def set_out(self, folder):
        self.v_out.set(folder)
        self.l_out.configure(text=folder if folder else '元の動画と同じフォルダ')

    def pick_out(self):
        d = filedialog.askdirectory(title='保存先のフォルダを選ぶ', initialdir=self.v_out.get() or None)
        if d:
            self.set_out(str(Path(d)))

    def options(self):
        return core.Options(
            premium=self.c_account.get() == 'premium', long_mode=self.c_long.get(),
            quality=self.c_quality.get(), max_long=self.c_size.get(), max_fps=self.c_fps.get(),
            start=core.parse_time(self.v_start.get()), end=core.parse_time(self.v_end.get()),
            out_dir=self.v_out.get())

    def remember(self):
        save_settings({'premium': self.c_account.get() == 'premium', 'long_mode': self.c_long.get(),
                       'quality': self.c_quality.get(), 'max_long': self.c_size.get(),
                       'max_fps': self.c_fps.get(), 'out_dir': self.v_out.get()})

    # ---- 変換 ----
    def start(self):
        if self.worker:
            return
        if not self.items:
            messagebox.showinfo(APP_NAME, '先に動画を追加してください。')
            return
        try:
            opts = self.options()
            if opts.end and opts.end <= opts.start:
                raise core.ConvertError('使う範囲の「まで」は「から」より後にしてください')
        except core.ConvertError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        if opts.out_dir and not Path(opts.out_dir).is_dir():
            messagebox.showerror(APP_NAME, '保存先のフォルダが見つかりません。選び直してください。')
            return
        jobs = [(iid, it['info'], it['project']) for iid, it in self.items.items() if it['state'] != 'done']
        if not jobs:                       # 全部終わっている → もう一度やり直す
            jobs = [(iid, it['info'], it['project']) for iid, it in self.items.items()]
        for iid, _, _ in jobs:
            self.items[iid]['state'] = 'wait'
            self.tree.set(iid, 'state', '待機中')
        self.remember()
        self.cancel.clear()
        self.set_busy(True)
        self.worker = threading.Thread(target=self.run_jobs, args=(jobs, opts), daemon=True)
        self.worker.start()

    def run_jobs(self, jobs, opts):
        ok = bad = 0
        for n, (iid, info, project) in enumerate(jobs):
            if self.cancel.is_set():
                break

            def progress(f, i, parts, iid=iid, n=n):
                self.msgs.put(('progress', iid, f, i, parts, n, len(jobs)))
            try:
                if project:
                    results = edit.convert_project(project, opts, progress, self.cancel)
                else:
                    results = core.convert_file(info, opts, progress, self.cancel)
                self.msgs.put(('done', iid, results))
                ok += 1
            except core.Cancelled:
                self.msgs.put(('state', iid, 'wait', '中止しました'))
                break
            except core.ConvertError as e:
                self.msgs.put(('state', iid, 'error', f'失敗: {e}'))
                bad += 1
            except Exception as e:          # 思わぬエラーでも次の動画へ進む
                self.msgs.put(('state', iid, 'error', f'失敗: {e!r}'))
                bad += 1
        self.msgs.put(('finished', ok, bad, self.cancel.is_set()))

    def poll(self):
        try:
            while True:
                m = self.msgs.get_nowait()
                kind = m[0]
                if kind == 'progress':
                    _, iid, f, i, parts, n, total = m
                    self.bar['value'] = f * 1000
                    part = f'（{i}/{parts} 個目）' if parts > 1 else ''
                    if self.tree.exists(iid):
                        self.tree.set(iid, 'state', f'変換中 {int(f * 100)}%{part}')
                    self.v_status.set(f'{n + 1}/{total} 本目を変換中… {int(f * 100)}%{part}')
                elif kind == 'done':
                    _, iid, results = m
                    self.items[iid]['state'] = 'done'
                    self.last_out_dir = results[0].path.parent
                    self.b_open.configure(state='normal')
                    size = sum(r.info.size_bytes for r in results)
                    w, h = results[0].info.display_size
                    text = f'完了 {int(w)}x{int(h)} {core.fmt_size(size)}'
                    if len(results) > 1:
                        text = f'完了 {len(results)} 個に分割 合計 {core.fmt_size(size)}'
                    problems = sorted({p for r in results for p in r.problems})
                    if problems:
                        text += ' ／注意: ' + '・'.join(problems)
                    self.tree.set(iid, 'state', text)
                elif kind == 'state':
                    _, iid, state, text = m
                    self.items[iid]['state'] = state
                    self.tree.set(iid, 'state', text)
                elif kind == 'finished':
                    _, ok, bad, cancelled = m
                    self.worker = None
                    self.set_busy(False)
                    self.bar['value'] = 0 if cancelled else 1000
                    if cancelled:
                        self.v_status.set('中止しました。')
                    elif bad:
                        self.v_status.set(f'終わりました。成功 {ok} 本、失敗 {bad} 本（「状態」の列に理由があります）。')
                    else:
                        self.v_status.set(f'{ok} 本の変換が終わりました。「保存先を開く」でファイルを確認できます。')
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_busy(self, busy):
        for b in (self.b_start, self.b_add, self.b_edit, self.b_remove, self.b_clear):
            b.configure(state='disabled' if busy else 'normal')
        self.b_stop.configure(state='normal' if busy else 'disabled')

    def stop(self):
        if self.worker:
            self.cancel.set()
            self.v_status.set('中止しています…')

    def open_out(self):
        if self.last_out_dir and Path(self.last_out_dir).is_dir():
            os.startfile(str(self.last_out_dir))

    def about(self):
        messagebox.showinfo(APP_NAME, (
            f'{APP_NAME} {__version__}\n\n'
            '動画を X（旧 Twitter）の投稿条件に合わせた形式（MP4・H.264・AAC）に変換します。\n\n'
            '・大きさは 1920x1200（縦長は 1200x1920）以内、60fps 以内に収めます。\n'
            '・通常アカウントは 2分20秒・512MB までなので、長い動画は分割または切り取りできます。\n'
            '・HDR の動画は普通の色（SDR）に直します。音のない動画には無音を入れます。\n'
            '・「編集」で、プレビューを見ながら切り貼り・つなぎ・フェードができます。\n\n'
            '変換には同梱の FFmpeg（GNU GPL v3）を使っています。\n'
            'X の投稿条件は変わることがあります。権利を持っている動画だけを変換・投稿してください。\n'
            '非公式のツールで、X Corp. とは関係ありません。「X」「Twitter」は X Corp. の商標です。\n\n'
            'Copyright (c) 2026 BW — MIT ライセンス'))

    def on_close(self):
        if self.worker and not messagebox.askyesno(APP_NAME, '変換の途中です。中止して閉じますか？'):
            return
        self.cancel.set()
        self.remember()
        if self.worker:
            self.worker.join(3)
        self.root.destroy()


def setup_style():
    """画面の見た目の設定 (テストやスクリーンショット作りでも同じ見た目にするため関数に分けている)。"""
    try:
        ttk.Style().theme_use('vista')
    except tk.TclError:
        pass
    try:                           # 文字が大きい環境でも一覧の行が欠けないように
        from tkinter import font
        ttk.Style().configure('Treeview', rowheight=font.nametofont('TkDefaultFont').metrics('linespace') + 6)
    except tk.TclError:
        pass


def main():
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    setup_style()
    app = App(root)
    if TkinterDnD:
        def on_drop(event):
            if not app.worker:
                app.add_paths(root.tk.splitlist(event.data))
        root.drop_target_register(DND_FILES)
        root.dnd_bind('<<Drop>>', on_drop)
    if len(sys.argv) > 1:          # exe のアイコンに動画をドラッグ＆ドロップしたとき
        root.after(200, lambda: app.add_paths(sys.argv[1:]))
    root.mainloop()


if __name__ == '__main__':
    main()
