"""公開用の画面の画像を release/screenshots/ に作る (run_tests.py の後に実行。Pillow が必要)。

写す動画は run_tests.py が ffmpeg で作ったテスト用の映像 (色の帯など) だけ。
保存先は「元の動画と同じフォルダ」にして、このパソコンのフォルダ名が写らないようにする。
"""
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from xvideo import gui  # noqa: E402

WORK = ROOT / 'tests' / 'work'
OUT = ROOT / 'release' / 'screenshots'


def window_box(win):
    """窓の見えている範囲 (タイトルバーを含み、影を含まない)。ほかの窓や背景が写らないように Windows に聞く。"""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(win.wm_frame(), 16)
        rect = wintypes.RECT()
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
            return rect.left, rect.top, rect.right, rect.bottom    # 9 = DWMWA_EXTENDED_FRAME_BOUNDS
    except Exception:
        pass
    x, y = win.winfo_rootx(), win.winfo_rooty()
    return x - 8, y - 32, x + win.winfo_width() + 8, y + win.winfo_height() + 8


def grab(win, path):
    from PIL import ImageGrab
    win.attributes('-topmost', True)
    win.lift()
    for _ in range(40):
        win.update()
        time.sleep(0.01)
    ImageGrab.grab(window_box(win), all_screens=True).save(path)
    print('保存:', path)


def pump(root, sec):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    gui.save_settings = lambda data: None
    gui.load_settings = lambda: {}
    gui.messagebox.askyesno = lambda *a, **k: True     # 2本を選んで編集するときの確認に自動で「はい」
    OUT.mkdir(parents=True, exist_ok=True)

    root = gui.TkinterDnD.Tk() if gui.TkinterDnD else tk.Tk()
    gui.setup_style()
    app = gui.App(root)
    app.set_out('')
    app.add_paths([WORK / 'hd60.mkv', WORK / 'long.mp4', WORK / 'uhd_portrait.webm', WORK / 'anim.gif'])
    pump(root, 0.5)
    grab(root, OUT / 'app.png')

    rows = list(app.items)
    app.tree.selection_set([rows[0], rows[2]])     # 短い2本 (6秒 + 3秒)。部分の色分けが見えるように
    app.open_editor()
    ed = app.editor
    pump(root, 1.5)
    ed.seek(4.0)
    ed.do_split()
    ed.seek(7.0)
    ed.do_split()
    ed.seek(5.0)
    ed.do_delete()
    ed.v_in.set('1')
    ed.v_out.set('2')
    ed.seek(3.0)
    pump(root, 1.5)
    grab(ed.win, OUT / 'editor.png')
    ed.ok()
    pump(root, 0.3)
    root.destroy()


if __name__ == '__main__':
    main()
