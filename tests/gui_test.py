"""画面を実際に開き、動画の追加 → 変換開始 → 完了までを自動で動かす (run_tests.py の後に実行)。"""
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from xvideo import gui  # noqa: E402

WORK = ROOT / 'tests' / 'work'


def main():
    gui.save_settings = lambda data: None          # テストでユーザーの設定を書き換えない
    gui.load_settings = lambda: {}
    gui.messagebox.showwarning = lambda *a, **k: print('warning:', a[1])
    root = gui.TkinterDnD.Tk() if gui.TkinterDnD else tk.Tk()
    gui.setup_style()
    app = gui.App(root)
    out = WORK / 'gui_out'
    out.mkdir(exist_ok=True)
    app.set_out(str(out))
    app.add_paths([WORK / 'hd60.mkv', WORK / 'long.mp4', ROOT / 'README.md'])
    app.v_start.set('0:10')
    app.v_end.set('2:40')
    app.start()
    states = []

    def check():
        if app.worker is None:
            for iid in app.items:
                states.append(app.tree.item(iid, 'values'))
            root.destroy()
        else:
            root.after(200, check)
    root.after(500, check)
    root.mainloop()
    for s in states:
        print(s)
    print(app.v_status.get())
    print(sorted(p.name for p in out.iterdir()))


if __name__ == '__main__':
    main()
