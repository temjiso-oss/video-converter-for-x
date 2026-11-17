"""編集の画面を実際に開き、操作 → 再生 → 決定 → 変換までを自動で動かす (run_tests.py の後に実行)。

画面の画像を tests/work/editor.png と main.png に保存する (Pillow があるとき)。
"""
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from xvideo import core, gui  # noqa: E402

WORK = ROOT / 'tests' / 'work'
failed = 0


def check(name, cond, detail=''):
    global failed
    failed += not cond
    print('OK' if cond else 'NG', name, detail, flush=True)


def grab(win, path):
    try:
        from PIL import ImageGrab
    except ImportError:
        return
    win.attributes('-topmost', True)       # ほかの窓が写らないように一番手前に出す
    win.lift()
    for _ in range(30):
        win.update()
        time.sleep(0.01)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    ImageGrab.grab((x - 8, y - 32, x + win.winfo_width() + 8, y + win.winfo_height() + 8)).save(path)


def pump(root, sec):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def main():
    try:                                   # 画面の画像の位置がずれないように (テストのときだけ)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    gui.save_settings = lambda data: None
    gui.load_settings = lambda: {}
    gui.messagebox.askyesno = lambda *a, **k: True
    shown = []
    gui.messagebox.showinfo = lambda *a, **k: shown.append(a[1])
    import xvideo.editor as editor_mod
    editor_mod.messagebox.showinfo = lambda *a, **k: shown.append(a[1])

    root = gui.TkinterDnD.Tk() if gui.TkinterDnD else tk.Tk()
    gui.setup_style()
    app = gui.App(root)
    out = WORK / 'editor_out'
    out.mkdir(exist_ok=True)
    for f in out.iterdir():
        f.unlink()
    app.set_out(str(out))
    app.add_paths([WORK / 'hd60.mkv', WORK / 'long.mp4', WORK / 'uhd_portrait.webm'])
    rows = list(app.items)
    app.tree.selection_set(rows[:2])
    app.open_editor()
    ed = app.editor
    pump(root, 1.5)
    check('最初の1コマが出る', ed.image is not None)
    total0 = ed.project.duration

    ed.seek(2.0)
    ed.do_split()
    ed.seek(4.0)
    ed.do_split()
    check('分ける', len(ed.project.clips) == 4)
    ed.seek(3.0)
    ed.do_delete()
    check('消す', len(ed.project.clips) == 3 and abs(ed.project.duration - (total0 - 2.0)) < 0.01 and abs(ed.pos - 2.0) < 0.01)
    ed.seek(1.0)
    ed.do_move(1)
    check('後ろへ', ed.project.clips[0].start == 4.0 and abs(ed.pos - (ed.project.clips[0].dur + 1.0)) < 0.01,
          f'{ed.pos}')
    ed.do_move(1)
    n = len(shown)
    ed.do_move(1)
    check('端では動かせない', len(shown) == n + 1 and len(ed.project.clips) == 3)
    ed.do_undo()
    ed.do_undo()
    check('元に戻す', ed.project.clips[0].start == 0.0 and ed.project.clips[0].end == 2.0)
    ed.seek(20.0)
    ed.do_trim_tail()
    check('後ろを消す', abs(ed.project.duration - 20.0) < 0.01)
    ed.seek(1.0)
    ed.do_trim_head()
    check('前を消す', abs(ed.project.duration - 19.0) < 0.01 and ed.pos == 0.0)
    ed.v_in.set('1.5')
    ed.v_out.set('2')
    check('フェード', (ed.project.fade_in, ed.project.fade_out) == (1.5, 2.0))
    ed.v_out.set('')            # 入力の途中 (空) でも落ちない
    ed.v_out.set('2')

    ed.seek(0.5)
    pump(root, 1.0)
    grab(ed.win, WORK / 'editor.png')
    ed.toggle_play()
    pump(root, 3.5)
    check('再生', ed.player is not None and ed.pos > 2.0 and ed.play_read > 20,
          f'pos {ed.pos:.2f} コマ {ed.play_read} 音 {ed.player.audio_ok if ed.player else None}')
    grab(ed.win, WORK / 'editor_play.png')
    ed.toggle_play()
    check('停止', ed.player is None)
    ed.seek(18.5)
    ed.toggle_play()
    pump(root, 2.5)
    check('最後で止まる', ed.player is None and abs(ed.pos - 19.0) < 0.01, f'{ed.pos}')

    ed.ok()
    pump(root, 0.3)
    vals = app.tree.item(rows[0], 'values')
    check('一覧にまとまる', len(app.items) == 2 and vals[0].startswith('✂') and 'ほか1本' in vals[0]
          and app.items[rows[0]]['project'] is not None, str(vals))
    grab(root, WORK / 'main.png')

    app.start()
    while app.worker is not None:
        pump(root, 0.2)
    for iid in app.items:
        print(app.tree.item(iid, 'values'), flush=True)
    files = sorted(p.name for p in out.iterdir())
    check('変換', files == ['hd60_edit_x.mp4', 'uhd_portrait_x.mp4'], str(files))
    if (out / 'hd60_edit_x.mp4').exists():
        info = core.probe(out / 'hd60_edit_x.mp4')
        check('編集した動画の長さ', abs(info.duration - 19.0) < 0.15, str(info.duration))
    root.destroy()
    print('失敗', failed)
    return failed


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
