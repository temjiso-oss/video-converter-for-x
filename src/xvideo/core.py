"""動画を X (Twitter) に投稿できる形式 (MP4 / H.264 / AAC) に変換する処理。

GUI (gui.py) とコマンドライン (cli.py) の両方から使う。ffmpeg を呼び出すだけで、ほかの依存はない。
"""
import math
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

# ---- X (Twitter) の投稿条件 (2026-11 時点。変わったらここを直す) ----
LIMIT_SEC = 140            # 通常アカウントの長さの上限 (2分20秒)
SEGMENT_SEC = 139          # 分割・切り取りに使う長さ (上限ぴったりは弾かれることがあるので 1秒余裕)
LIMIT_BYTES = 512 * 1024 * 1024            # 通常アカウントの容量の上限
PREMIUM_LIMIT_SEC = 4 * 3600               # Premium の長さの上限 (約4時間)
PREMIUM_LIMIT_BYTES = 16 * 1024 ** 3       # Premium の容量の上限
BOX_LANDSCAPE = (1920, 1200)               # 横長の最大の大きさ
BOX_PORTRAIT = (1200, 1920)                # 縦長の最大の大きさ
MAX_ASPECT = 3.0                           # 縦横比は 1:3 〜 3:1
MAX_FPS = 60
AUDIO_KBPS = 160

# 画質の設定: (CRF, 映像の最大ビットレート kbps)。X 側で再圧縮されるので、元は高めにしておく
QUALITY = {
    'high': (18, 12000),
    'standard': (21, 8000),
    'small': (25, 4000),
}

NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class ConvertError(Exception):
    pass


class Cancelled(Exception):
    pass


def ffmpeg_exe():
    if getattr(sys, 'frozen', False):
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        for p in (base / 'ffmpeg.exe', Path(sys.executable).parent / 'ffmpeg.exe'):
            if p.exists():
                return str(p)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return 'ffmpeg'


@dataclass
class Info:
    path: Path
    duration: float = 0.0      # 秒 (分からないときは 0)
    width: int = 0             # 保存されている画素数
    height: int = 0
    sar: float = 1.0           # 画素の縦横比
    rotation: int = 0          # 0 / 90 / 180 / 270
    fps: float = 0.0
    has_audio: bool = False
    hdr: bool = False
    size_bytes: int = 0

    @property
    def display_size(self):
        """再生したときの見た目の大きさ (回転・画素の縦横比を反映)。"""
        w, h = self.width * self.sar, float(self.height)
        if self.rotation in (90, 270):
            w, h = h, w
        return w, h


def probe(path):
    """ffmpeg -i の出力から動画の情報を読む。"""
    path = Path(path)
    if not path.is_file():
        raise ConvertError('ファイルが見つかりません')
    r = subprocess.run([ffmpeg_exe(), '-hide_banner', '-i', str(path)],
                       capture_output=True, stdin=subprocess.DEVNULL, creationflags=NOWIN)
    text = r.stderr.decode('utf-8', 'replace')
    info = Info(path=path, size_bytes=path.stat().st_size)
    m = re.search(r'Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)', text)
    if m:
        info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    vline = None
    for line in text.splitlines():
        if re.search(r'Stream #\d+:\d+.*: Video: ', line) and '(attached pic)' not in line:
            vline = line
            break
    if vline is None:
        raise ConvertError('動画として読めませんでした（映像が入っていないか、対応していない形式です）')
    m = re.search(r', (\d{2,5})x(\d{2,5})\b', vline)
    if not m:
        raise ConvertError('動画の大きさが分かりませんでした')
    info.width, info.height = int(m.group(1)), int(m.group(2))
    m = re.search(r'\bSAR (\d+):(\d+)', vline)
    if m and int(m.group(1)) > 0 and int(m.group(2)) > 0:
        info.sar = int(m.group(1)) / int(m.group(2))
    m = re.search(r'([\d.]+) fps', vline) or re.search(r'([\d.]+) tbr', vline)
    if m:
        try:
            info.fps = float(m.group(1))
        except ValueError:
            pass
    m = re.search(r'rotation of (-?[\d.]+) degrees', text)
    if m:
        info.rotation = int(round(-float(m.group(1)) / 90.0)) * 90 % 360
    info.hdr = 'smpte2084' in vline or 'arib-std-b67' in vline
    info.has_audio = bool(re.search(r'Stream #\d+:\d+.*: Audio: ', text))
    return info


@dataclass
class Options:
    premium: bool = False          # Premium (長い動画を投稿できる) アカウント向け
    long_mode: str = 'split'       # 通常アカウントで 2分20秒を超えるとき: split / trim / keep
    quality: str = 'standard'      # high / standard / small
    max_long: int = 1920           # 長い辺の上限 (1920 または 1280)
    max_fps: int = 60              # 60 または 30
    start: float = 0.0             # 使う範囲の始まり (秒)
    end: float = 0.0               # 使う範囲の終わり (秒。0 = 最後まで)
    out_dir: str = ''              # 保存先 (空 = 元の動画と同じフォルダ)


def _even(x):
    return max(2, int(x) // 2 * 2)


def plan_size(info, max_long=1920):
    """出力の大きさを決める。返り値: (拡大縮小後の幅, 高さ, 余白込みの幅, 高さ)"""
    w, h = info.display_size
    bw, bh = BOX_LANDSCAPE if w >= h else BOX_PORTRAIT
    k = min(max_long, 1920) / 1920.0
    bw, bh = bw * k, bh * k
    s = min(1.0, bw / w, bh / h)
    sw, sh = _even(round(w * s)), _even(round(h * s))
    pw, ph = sw, sh
    if sw > sh * MAX_ASPECT:               # 横に細長すぎる → 上下に黒い余白
        ph = _even(math.ceil(sw / MAX_ASPECT) + 1)
    elif sh > sw * MAX_ASPECT:             # 縦に細長すぎる → 左右に黒い余白
        pw = _even(math.ceil(sh / MAX_ASPECT) + 1)
    return sw, sh, pw, ph


def plan_fps(info, max_fps=60):
    """出力のコマ数。返り値: (ffmpeg に渡す文字列, 数値)"""
    src = info.fps if 1.0 <= info.fps <= 1000.0 else 30.0
    f = min(src, float(min(max_fps, MAX_FPS)))
    for val, expr in ((23.976, '24000/1001'), (29.97, '30000/1001'), (59.94, '60000/1001')):
        if abs(f - val) < 0.011:
            return expr, val
    return ('%.3f' % f).rstrip('0').rstrip('.'), f


def plan_segments(info, opts):
    """変換する区間のリスト [(開始秒, 長さ秒 または None)] を作る。"""
    total = info.duration
    start = max(0.0, opts.start)
    end = opts.end if opts.end > 0 else total
    if total > 0:
        end = min(end, total) if end > 0 else total
        if start >= end:
            raise ConvertError('使う範囲の指定が動画の長さを超えています')
    span = (end - start) if end > 0 else 0.0       # 0 = 長さ不明
    explicit = opts.start > 0 or opts.end > 0
    if opts.premium or opts.long_mode == 'keep' or span <= LIMIT_SEC:
        if span <= 0:
            return [(start, None)]
        return [(start, span if explicit else None)]
    if opts.long_mode == 'trim':
        return [(start, float(SEGMENT_SEC))]
    segs = []
    t = start
    while end - t > 0.5:
        segs.append((t, min(float(SEGMENT_SEC), end - t)))
        t += SEGMENT_SEC
    return segs


def output_paths(info, opts, count, suffix=''):
    folder = Path(opts.out_dir) if opts.out_dir else info.path.parent
    stem = info.path.stem + suffix
    if count == 1:
        return [folder / f'{stem}_x.mp4']
    digits = max(2, len(str(count)))
    return [folder / f'{stem}_x_{i + 1:0{digits}d}.mp4' for i in range(count)]


def build_filters(info, opts):
    sw, sh, pw, ph = plan_size(info, opts.max_long)
    fps_expr, fps_val = plan_fps(info, opts.max_fps)
    vf = ['yadif=deint=interlaced']        # インターレースの印が付いたコマだけ解除
    if info.hdr:                           # HDR → SDR (そのままだと X で色が薄くなる)
        vf += ['zscale=t=linear:npl=100', 'format=gbrpf32le', 'zscale=p=bt709',
               'tonemap=tonemap=hable:desat=0', 'zscale=t=bt709:m=bt709:r=tv']
    vf += [f'scale={sw}:{sh}:flags=lanczos', 'setsar=1']
    if (pw, ph) != (sw, sh):
        vf.append(f'pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:black')
    vf += [f'fps={fps_expr}', 'format=yuv420p']
    return ','.join(vf), fps_val, (pw, ph)


def build_command(info, opts, out, start, dur, maxrate_k):
    crf, _ = QUALITY.get(opts.quality, QUALITY['standard'])
    vf, fps_val, _ = build_filters(info, opts)
    cmd = [ffmpeg_exe(), '-hide_banner', '-y', '-loglevel', 'error', '-nostdin']
    if start > 0:
        cmd += ['-ss', '%.3f' % start]
    cmd += ['-i', str(info.path)]
    if not info.has_audio:                 # 音がない動画には無音を入れる
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
    if dur:
        cmd += ['-t', '%.3f' % dur]
    cmd += ['-map', '0:V:0', '-map', '0:a:0' if info.has_audio else '1:a:0']
    if not info.has_audio:
        cmd += ['-shortest']
    cmd += ['-vf', vf] + encode_args(opts, fps_val, maxrate_k, info.hdr, out)
    return cmd


def encode_args(opts, fps_val, maxrate_k, hdr, out):
    """ffmpeg の出力側の引数 (映像・音声のエンコード設定から出力ファイルまで)。"""
    crf, _ = QUALITY.get(opts.quality, QUALITY['standard'])
    args = ['-c:v', 'libx264', '-preset', 'medium', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-crf', str(crf), '-maxrate', f'{maxrate_k}k', '-bufsize', f'{maxrate_k * 2}k',
            '-g', str(max(2, int(round(fps_val * 2)))), '-bf', '2']
    if hdr:
        args += ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709']
    args += ['-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k', '-ar', '48000', '-ac', '2',
             '-sn', '-dn', '-map_metadata', '-1', '-map_chapters', '-1',
             '-movflags', '+faststart', '-f', 'mp4',
             '-progress', 'pipe:1', '-nostats', str(out)]
    return args


def _run(cmd, total, progress, cancel):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, creationflags=NOWIN)
    err = []
    t = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    t.start()
    cancelled = False
    for raw in proc.stdout:
        if cancel is not None and cancel.is_set():
            cancelled = True
            proc.kill()
            break
        line = raw.decode('ascii', 'replace').strip()
        if line.startswith('out_time_us=') and total and progress:
            try:
                progress(max(0.0, min(1.0, int(line[12:]) / 1e6 / total)))
            except ValueError:
                pass
    proc.wait()
    t.join(5)
    if cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        msg = (err[0].decode('utf-8', 'replace') if err else '').strip().splitlines()
        raise ConvertError('変換に失敗しました: ' + (' / '.join(msg[-3:]) if msg else f'コード {proc.returncode}'))


def encode_segment(info, opts, out, start, dur, progress=None, cancel=None):
    """1区間を変換する。容量の上限を超えたらビットレートを下げてやり直す。"""
    seg_len = dur or max(0.0, info.duration - start)
    return encode_limited(lambda part, maxrate: build_command(info, opts, part, start, dur, maxrate),
                          out, seg_len, opts, [info.path], progress, cancel)


def encode_limited(make_cmd, out, seg_len, opts, sources, progress=None, cancel=None):
    """make_cmd(一時ファイル, 最大ビットレート) で作ったコマンドを実行し、容量の上限に収める。"""
    out = Path(out)
    if any(out.resolve() == Path(s).resolve() for s in sources):
        raise ConvertError('保存先が元の動画と同じファイルになっています')
    out.parent.mkdir(parents=True, exist_ok=True)
    limit = PREMIUM_LIMIT_BYTES if opts.premium else LIMIT_BYTES
    _, maxrate = QUALITY.get(opts.quality, QUALITY['standard'])
    if seg_len > 0:
        fit = int(limit * 8 * 0.95 / seg_len / 1000) - AUDIO_KBPS - 10
        if fit < 150:
            raise ConvertError('長すぎて容量の上限（%dMB）に収まりません。分割するか範囲を短くしてください'
                               % (limit // 1024 ** 2))
        maxrate = min(maxrate, fit)
    part = out.with_name(out.stem + '.part.mp4')
    try:
        for attempt in range(3):
            _run(make_cmd(part, maxrate), seg_len, progress, cancel)
            size = part.stat().st_size
            if size <= limit:
                break
            maxrate = max(150, int(maxrate * limit / size * 0.9))
        else:
            raise ConvertError('容量の上限に収まりませんでした')
        os.replace(part, out)
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass
    return out


@dataclass
class Result:
    path: Path
    info: Info
    problems: list = field(default_factory=list)


def check_output(path, opts):
    """出来上がったファイルが X の条件に合っているか確かめる。"""
    info = probe(path)
    problems = []
    w, h = info.display_size
    bw, bh = BOX_LANDSCAPE if w >= h else BOX_PORTRAIT
    if w > bw or h > bh:
        problems.append('大きさが上限を超えています')
    if max(w, h) > min(w, h) * MAX_ASPECT + 2:
        problems.append('縦横比が範囲外です')
    if info.fps > MAX_FPS + 0.01:
        problems.append('コマ数が60fpsを超えています')
    limit_b = PREMIUM_LIMIT_BYTES if opts.premium else LIMIT_BYTES
    limit_s = PREMIUM_LIMIT_SEC if opts.premium else LIMIT_SEC
    if info.size_bytes > limit_b:
        problems.append('容量が上限を超えています')
    if info.duration > limit_s + 0.05:
        problems.append('長さが上限（%s）を超えています' % fmt_time(limit_s))
    return Result(Path(path), info, problems)


def convert_file(info, opts, progress=None, cancel=None):
    """1本の動画を変換する。progress(全体の進み 0〜1, 何本目, 全部で何本)。返り値: Result のリスト"""
    segs = plan_segments(info, opts)
    outs = output_paths(info, opts, len(segs))
    results = []
    for i, ((start, dur), out) in enumerate(zip(segs, outs)):
        def cb(f, i=i):
            if progress:
                progress((i + f) / len(segs), i + 1, len(segs))
        cb(0.0)
        encode_segment(info, opts, out, start, dur, cb, cancel)
        results.append(check_output(out, opts))
    if progress:
        progress(1.0, len(segs), len(segs))
    return results


def fmt_time(sec):
    sec = int(round(sec))
    if sec >= 3600:
        return '%d:%02d:%02d' % (sec // 3600, sec // 60 % 60, sec % 60)
    return '%d:%02d' % (sec // 60, sec % 60)


def fmt_size(n):
    if n >= 1024 ** 3:
        return '%.2f GB' % (n / 1024 ** 3)
    return '%.1f MB' % (n / 1024 ** 2)


def parse_time(text):
    """「90」「1:30」「1:02:03」を秒にする。空なら 0。"""
    text = (text or '').strip().replace('：', ':')
    if not text:
        return 0.0
    try:
        parts = [float(p) for p in text.split(':')]
    except ValueError:
        raise ConvertError(f'時間の書き方が正しくありません: {text}（例 1:30）')
    if len(parts) > 3 or any(p < 0 for p in parts):
        raise ConvertError(f'時間の書き方が正しくありません: {text}（例 1:30）')
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec
