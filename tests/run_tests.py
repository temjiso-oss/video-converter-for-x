"""テスト用の動画を ffmpeg で作り、変換して結果を確かめる。

    python tests/run_tests.py            (作業フォルダは tests/work。終わっても残す)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from xvideo import core  # noqa: E402

WORK = ROOT / 'tests' / 'work'
FF = core.ffmpeg_exe()


def make(name, args):
    out = WORK / name
    if not out.exists():
        subprocess.run([FF, '-hide_banner', '-loglevel', 'error', '-y'] + args + [str(out)], check=True)
    return out


def src(size, rate, dur, audio=True):
    a = ['-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={rate}:duration={dur}']
    if audio:
        a += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={dur}']
    return a


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    x264 = ['-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p']
    samples = {
        'hd60': make('hd60.mkv', src('1920x1080', 60, 6) + x264 + ['-c:a', 'libopus']),
        'uhd_portrait_noaudio': make('uhd_portrait.webm', src('2160x3840', 30, 3, False) + ['-c:v', 'libvpx-vp9', '-b:v', '4M', '-deadline', 'realtime', '-cpu-used', '8']),
        'odd120': make('odd120.avi', src('853x481', 120, 4) + ['-c:v', 'mpeg4', '-q:v', '4', '-c:a', 'libmp3lame']),
        'wide': make('wide.mp4', src('1600x200', 30, 3) + x264),
        'long': make('long.mp4', src('640x360', 30, 300) + x264 + ['-crf', '35']),
        'hdr': make('hdr.mkv', src('1280x720', 30, 3) + ['-c:v', 'libx265', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p10le',
                                                             '-color_primaries', 'bt2020', '-color_trc', 'smpte2084', '-colorspace', 'bt2020nc']),
        'rotated': make('rotated.mp4', ['-display_rotation', '90', '-i', str(make('rot_src.mp4', src('1280x720', 30, 3) + x264)), '-c', 'copy']),
        'anamorphic': make('anamorphic.mpg', src('720x480', 30, 3) + ['-c:v', 'mpeg2video', '-q:v', '4', '-aspect', '16:9', '-flags', '+ilme+ildct', '-vf', 'setfield=tff']),
        'gif': make('anim.gif', src('320x240', 10, 3, False)),
    }
    out_dir = WORK / 'out'
    failed = 0

    def run(key, expect_count=1, expect_size=None, expect_fps=None, **kw):
        nonlocal failed
        opts = core.Options(out_dir=str(out_dir), **kw)
        info = core.probe(samples[key])
        try:
            results = core.convert_file(info, opts)
        except core.ConvertError as e:
            print(f'NG {key}: {e}')
            failed += 1
            return
        notes = []
        if len(results) != expect_count:
            notes.append(f'個数 {len(results)} (期待 {expect_count})')
        for r in results:
            w, h = r.info.display_size
            # 「そのまま変換」は長さの注意が出るのが正しい
            notes += [p for p in r.problems if not (kw.get('long_mode') == 'keep' and '長さ' in p)]
            if kw.get('long_mode') == 'keep' and not any('長さ' in p for p in r.problems):
                notes.append('長さの注意が出ていない')
            if expect_size and (int(w), int(h)) != expect_size:
                notes.append(f'大きさ {int(w)}x{int(h)} (期待 {expect_size})')
            if expect_fps and abs(r.info.fps - expect_fps) > 0.05:
                notes.append(f'fps {r.info.fps} (期待 {expect_fps})')
            if not r.info.has_audio:
                notes.append('音声なし')
            if not kw.get('premium') and r.info.duration > core.LIMIT_SEC and kw.get('long_mode') != 'keep':
                notes.append(f'長さ {r.info.duration}')
            text = subprocess.run([FF, '-hide_banner', '-i', str(r.path)], capture_output=True).stderr.decode('utf-8', 'replace')
            if 'h264 (High)' not in text or 'yuv420p' not in text or 'aac (LC)' not in text:
                notes.append('形式が違う')
        r0 = results[0]
        w, h = r0.info.display_size
        head = 'NG' if notes else 'OK'
        failed += bool(notes)
        print(f'{head} {key} {kw}: {len(results)}個 {int(w)}x{int(h)} {r0.info.fps:g}fps '
              f'{[round(r.info.duration, 2) for r in results]}秒 {core.fmt_size(sum(r.info.size_bytes for r in results))} {notes}')

    run('hd60', expect_size=(1920, 1080), expect_fps=60)
    run('hd60', expect_size=(1280, 720), expect_fps=30, max_long=1280, max_fps=30, quality='small')
    run('uhd_portrait_noaudio', expect_size=(1080, 1920), expect_fps=30)
    run('odd120', expect_size=(852, 480), expect_fps=60)
    run('wide', expect_size=(1600, 534))
    run('long', expect_count=3, expect_size=(640, 360))
    run('long', expect_count=1, long_mode='trim')
    run('long', expect_count=1, long_mode='keep')
    run('long', expect_count=1, premium=True)
    run('long', expect_count=1, start=10, end=25.5)
    run('long', expect_count=2, start=100, end=300)
    run('hdr', expect_size=(1280, 720))
    run('rotated', expect_size=(720, 1280))
    run('anamorphic', expect_size=(852, 480))
    run('gif', expect_size=(320, 240), expect_fps=10)
    print('失敗', failed)
    return failed


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
