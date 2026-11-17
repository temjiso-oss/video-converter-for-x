"""切り貼り・フェードの変換とプレビューを確かめる (run_tests.py でテスト動画を作った後に実行)。"""
import subprocess
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from xvideo import core, edit  # noqa: E402

WORK = ROOT / 'tests' / 'work'
failed = 0


def check(name, cond, detail=''):
    global failed
    failed += not cond
    print('OK' if cond else 'NG', name, detail)


def brightness(frame):
    size, data = frame
    rgb = data[len(data) - size[0] * size[1] * 3:]
    return sum(rgb[::97]) / len(rgb[::97])


def main():
    hd = core.probe(WORK / 'hd60.mkv')            # 6秒 1920x1080 60fps
    long = core.probe(WORK / 'long.mp4')          # 300秒 640x360
    port = core.probe(WORK / 'uhd_portrait.webm')  # 3秒 縦長・音声なし
    out = WORK / 'edit_out'

    # 操作
    p = edit.Project([edit.Clip(hd, 0.0, 6.0)])   # mkv の長さは 6.01 秒などになるので、きっちり 6 秒にする
    check('split', p.split(2.0) and p.split(4.0) and len(p.clips) == 3)
    check('split 端は不可', not p.split(0.01) and not p.split(2.0))
    check('delete', p.delete(1) and abs(p.duration - 4.0) < 1e-6)
    check('move', p.move(0, 1) and p.clips[0].start == 4.0 and not p.move(1, 1))
    check('locate', p.locate(2.5) == (1, 0.5), str(p.locate(2.5)))
    q = p.copy()
    check('keep_range', q.keep_range(1.0, 3.0) and abs(q.duration - 2.0) < 1e-6
          and (q.clips[0].start, q.clips[0].end, q.clips[1].start, q.clips[1].end) == (5.0, 6.0, 0.0, 1.0))
    check('edited', p.edited and not edit.Project.from_infos([hd]).edited)

    # 並べ替え + 別の動画をつなぐ + フェード → 変換
    p.append(port)
    p.clips.append(edit.Clip(long, 10.0, 13.0))
    p.fade_in, p.fade_out = 1.0, 2.0
    rs = edit.convert_project(p, core.Options(out_dir=str(out)))
    r = rs[0]
    check('変換 (3本つなぎ)', len(rs) == 1 and not r.problems and abs(r.info.duration - 10.0) < 0.15
          and r.info.display_size == (1920.0, 1080.0) and r.info.has_audio,
          f'{r.info.duration} {r.info.display_size} {r.problems} {r.path.name}')

    # 出力のフェードを明るさで確かめる
    o = edit.Project.from_infos([r.info])
    b = [brightness(edit.preview_frame(o, t)) for t in (0.0, 0.5, 2.0, 9.0, 9.9)]
    check('出力のフェード', b[0] < 5 and b[0] < b[1] < b[2] and b[3] < b[2] * 0.75 and b[4] < b[3] and b[4] < 20,
          str([round(x) for x in b]))

    # プレビューの1コマも同じフェードになる (途中の時刻から作っても時刻がずれない)
    pb = [brightness(edit.preview_frame(p, t)) for t in (0.0, 0.5, 2.0, 9.0, 9.9)]
    check('プレビューのフェード', all(abs(x - y) < 12 for x, y in zip(b, pb)), str([round(x) for x in pb]))

    # プレビュー再生用の映像と音
    cmd, size, fps = edit.preview_video_cmd(p, 3.0, p.duration)
    raw = subprocess.run(cmd, capture_output=True).stdout
    frames = len(raw) / (size[0] * size[1] * 3)
    check('プレビュー映像', abs(frames - 7.0 * fps) <= 2 and size == (640, 360), f'{frames} コマ {size} {fps}fps')
    wav = WORK / 'preview_test.wav'
    subprocess.run(edit.preview_audio_cmd(p, 3.0, p.duration, wav), check=True)
    sec = (wav.stat().st_size - 44) / (22050 * 4)
    check('プレビュー音声', abs(sec - 7.0) < 0.15, f'{sec:.2f} 秒')

    # 長い編集の分割・切り取り
    lp = edit.Project.from_infos([long])
    lp.keep_range(20.0, 220.0)
    lp.fade_out = 3.0
    rs = edit.convert_project(lp, core.Options(out_dir=str(out)))
    check('分割', [round(x.info.duration) for x in rs] == [139, 61] and not any(x.problems for x in rs),
          str([x.info.duration for x in rs]))
    tail = edit.Project.from_infos([rs[1].info])
    check('分割の最後にフェードアウト', brightness(edit.preview_frame(tail, 60.9)) < 20
          and brightness(edit.preview_frame(tail, 50.0)) > 60)
    rs = edit.convert_project(lp, core.Options(out_dir=str(out), long_mode='trim'))
    t = edit.Project.from_infos([rs[0].info])
    check('切り取りの最後にフェードアウト', len(rs) == 1 and round(rs[0].info.duration) == 139
          and brightness(edit.preview_frame(t, 138.9)) < 20)

    # Tk が PPM のバイト列を画像として読めるか
    root = tk.Tk()
    root.withdraw()
    size, data = edit.preview_frame(p, 5.0)
    img = tk.PhotoImage(data=data, format='ppm')
    check('PhotoImage', (img.width(), img.height()) == size, f'{img.width()}x{img.height()}')
    root.destroy()
    print('失敗', failed)
    return failed


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
