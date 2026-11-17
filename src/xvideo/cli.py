"""コマンドライン版。

    python -m xvideo.cli 入力.mp4 [入力2.mkv ...] [-o 保存先フォルダ] [--premium]
                         [--long split|trim|keep] [--quality high|standard|small]
                         [--max-long 1920|1280] [--max-fps 60|30] [--start 0:10] [--end 1:30]
"""
import argparse
import sys

from . import core


def main(argv=None):
    ap = argparse.ArgumentParser(description='動画を X (Twitter) に投稿できる MP4 に変換する')
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--out-dir', default='')
    ap.add_argument('--premium', action='store_true')
    ap.add_argument('--long', dest='long_mode', choices=['split', 'trim', 'keep'], default='split')
    ap.add_argument('--quality', choices=list(core.QUALITY), default='standard')
    ap.add_argument('--max-long', type=int, choices=[1920, 1280], default=1920)
    ap.add_argument('--max-fps', type=int, choices=[60, 30], default=60)
    ap.add_argument('--start', default='')
    ap.add_argument('--end', default='')
    a = ap.parse_args(argv)
    opts = core.Options(premium=a.premium, long_mode=a.long_mode, quality=a.quality,
                        max_long=a.max_long, max_fps=a.max_fps, out_dir=a.out_dir,
                        start=core.parse_time(a.start), end=core.parse_time(a.end))
    failed = 0
    for path in a.inputs:
        try:
            info = core.probe(path)
            last = [-1]

            def progress(f, i, n):
                pct = int(f * 100)
                if pct != last[0] and pct % 10 == 0:
                    last[0] = pct
                    print(f'  {pct}% ({i}/{n})', flush=True)
            print(f'{path}: {info.width}x{info.height} {info.fps:g}fps {core.fmt_time(info.duration)}', flush=True)
            for r in core.convert_file(info, opts, progress):
                w, h = r.info.display_size
                state = 'OK' if not r.problems else '注意: ' + '・'.join(r.problems)
                print(f'  -> {r.path}  {int(w)}x{int(h)} {r.info.fps:g}fps '
                      f'{core.fmt_time(r.info.duration)} {core.fmt_size(r.info.size_bytes)}  {state}', flush=True)
        except core.ConvertError as e:
            failed += 1
            print(f'{path}: 失敗: {e}', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
