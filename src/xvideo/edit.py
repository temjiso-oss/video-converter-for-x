"""切り貼り・フェードの編集 (クリップを並べたもの) と、その変換・プレビュー。

Project = クリップ (元の動画のどこからどこまで) を順に並べたもの + 全体のフェードイン/アウト。
変換もプレビューも同じ ffmpeg のフィルターグラフ (build_graph) から作るので、見た目が一致する。
"""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import core

MIN_CLIP = 0.1             # これより短いクリップは作らない (秒)
MAX_FADE = 10.0
HDR_CHAIN = ['zscale=t=linear:npl=100', 'format=gbrpf32le', 'zscale=p=bt709',
             'tonemap=tonemap=hable:desat=0', 'zscale=t=bt709:m=bt709:r=tv']


@dataclass
class Clip:
    info: core.Info
    start: float           # 元の動画での始まり (秒)
    end: float             # 元の動画での終わり (秒)

    @property
    def dur(self):
        return self.end - self.start


@dataclass
class Project:
    clips: list = field(default_factory=list)
    fade_in: float = 0.0   # 全体の最初のフェードイン (秒。映像と音)
    fade_out: float = 0.0  # 全体の最後のフェードアウト (秒)

    @classmethod
    def from_infos(cls, infos):
        p = cls()
        for info in infos:
            p.append(info)
        return p

    def append(self, info):
        if info.duration <= MIN_CLIP:
            raise core.ConvertError(f'{info.path.name}: 長さが分からないため編集できません')
        self.clips.append(Clip(info, 0.0, info.duration))

    def copy(self):
        return Project([Clip(c.info, c.start, c.end) for c in self.clips], self.fade_in, self.fade_out)

    @property
    def duration(self):
        return sum(c.dur for c in self.clips)

    @property
    def edited(self):
        """元の動画1本そのままから何か変えてあるか。"""
        if self.fade_in > 0 or self.fade_out > 0 or len(self.clips) != 1:
            return True
        c = self.clips[0]
        return c.start > 0.001 or c.end < c.info.duration - 0.001

    def bounds(self):
        """各クリップの全体での (始まり, 終わり)。"""
        out, pos = [], 0.0
        for c in self.clips:
            out.append((pos, pos + c.dur))
            pos += c.dur
        return out

    def locate(self, t):
        """全体での時刻 t があるクリップの番号と、そのクリップ内での経過秒。"""
        b = self.bounds()
        for i, (a, e) in enumerate(b):
            if t < e or i == len(b) - 1:
                return i, max(0.0, min(t - a, e - a))
        return 0, 0.0

    def clamp_fades(self):
        half = max(0.0, self.duration / 2)
        self.fade_in = max(0.0, min(self.fade_in, MAX_FADE, half))
        self.fade_out = max(0.0, min(self.fade_out, MAX_FADE, half))

    # ---- 編集の操作 (できなかったら False) ----
    def split(self, t):
        i, off = self.locate(t)
        c = self.clips[i]
        if off < MIN_CLIP or c.dur - off < MIN_CLIP:
            return False
        self.clips[i:i + 1] = [Clip(c.info, c.start, c.start + off), Clip(c.info, c.start + off, c.end)]
        return True

    def delete(self, i):
        if len(self.clips) <= 1 or not 0 <= i < len(self.clips):
            return False
        del self.clips[i]
        self.clamp_fades()
        return True

    def move(self, i, d):
        j = i + d
        if not (0 <= i < len(self.clips) and 0 <= j < len(self.clips)):
            return False
        self.clips[i], self.clips[j] = self.clips[j], self.clips[i]
        return True

    def keep_range(self, t0, t1):
        """全体の t0〜t1 だけを残す。"""
        if t1 - t0 < MIN_CLIP:
            return False
        new = []
        for c, (a, e) in zip(self.clips, self.bounds()):
            s, f = max(t0, a), min(t1, e)
            if f - s >= 0.001:
                new.append(Clip(c.info, c.start + (s - a), c.start + (f - a)))
        if not new:
            return False
        self.clips = new
        self.clamp_fades()
        return True


def canvas_size(project, max_long=1920):
    """出力の大きさ。最初のクリップで決め、ほかのクリップは余白を付けて合わせる。"""
    _, _, pw, ph = core.plan_size(project.clips[0].info, max_long)
    return pw, ph


def fit_box(size, box_w, box_h):
    w, h = size
    k = min(box_w / w, box_h / h)
    return core._even(round(w * k)), core._even(round(h * k))


def build_graph(project, t0, t1, canvas, fps_expr, video=True, audio=True, fast=False):
    """全体の t0〜t1 を作る ffmpeg の入力の引数とフィルターグラフ。出力のラベルは [v] と [a]。

    fast=True はプレビュー用 (粗い拡大縮小、インターレース解除なし)。
    """
    cw, ch = canvas
    inputs, parts, n = [], [], 0
    for c, (a, e) in zip(project.clips, project.bounds()):
        s, f = max(t0, a), min(t1, e)
        if f - s < 0.001:
            continue
        inputs += ['-ss', '%.3f' % (c.start + (s - a)), '-t', '%.3f' % (f - s), '-i', str(c.info.path)]
        if video:
            sw, sh = fit_box(c.info.display_size, cw, ch)
            sw, sh = min(sw, cw), min(sh, ch)
            scale = [f'scale={sw}:{sh}:flags={"fast_bilinear" if fast else "lanczos"}', 'setsar=1']
            hdr = HDR_CHAIN if c.info.hdr else []
            chain = scale + hdr if fast else ['yadif=deint=interlaced'] + hdr + scale
            if (sw, sh) != (cw, ch):
                chain.append(f'pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:black')
            chain += [f'fps={fps_expr}', 'format=yuv420p', 'setpts=PTS-STARTPTS']
            parts.append(f'[{n}:V:0]{",".join(chain)}[v{n}]')
        if audio:
            if c.info.has_audio:
                parts.append(f'[{n}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                             f'asetpts=PTS-STARTPTS[a{n}]')
            else:
                parts.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={f - s:.3f}[a{n}]')
        n += 1
    if n == 0:
        raise core.ConvertError('変換する部分がありません')
    labels = ''.join((f'[v{i}]' if video else '') + (f'[a{i}]' if audio else '') for i in range(n))
    parts.append(f'{labels}concat=n={n}:v={int(video)}:a={int(audio)}'
                 + ('[vc]' if video else '') + ('[ac]' if audio else ''))
    total = project.duration
    fades = []
    if project.fade_in > 0 and t0 < project.fade_in:
        fades.append(f'fade=t=in:st=0:d={project.fade_in:.3f}')
    if project.fade_out > 0 and t1 > total - project.fade_out:
        fades.append(f'fade=t=out:st={total - project.fade_out:.3f}:d={project.fade_out:.3f}')
    for on, pre, src, dst in ((video, '', '[vc]', '[v]'), (audio, 'a', '[ac]', '[a]')):
        if not on:
            continue
        chain = [pre + f for f in fades]
        if chain and t0 > 0:           # フェードの時刻は全体での時刻なので、いったん時刻をずらす
            chain = [f'{pre}setpts=PTS+{t0:.3f}/TB'] + chain + [f'{pre}setpts=PTS-STARTPTS']
        parts.append(src + (','.join(chain) or f'{pre}null') + dst)
    return inputs, ';'.join(parts)


def plan_spans(total, opts):
    """全体をどの区間に分けて出力するか [(開始, 終わり)]。"""
    if opts.premium or opts.long_mode == 'keep' or total <= core.LIMIT_SEC:
        return [(0.0, total)]
    spans, t = [], 0.0
    while total - t > 0.5:
        spans.append((t, min(t + core.SEGMENT_SEC, total)))
        t += core.SEGMENT_SEC
    return spans


def output_paths(project, opts, count):
    return core.output_paths(project.clips[0].info, opts, count, '_edit')


def convert_project(project, opts, progress=None, cancel=None):
    """編集した内容を変換する。返り値: core.Result のリスト"""
    project = project.copy()
    if not opts.premium and opts.long_mode == 'trim' and project.duration > core.LIMIT_SEC:
        project.keep_range(0.0, float(core.SEGMENT_SEC))     # 最初だけ残す。フェードアウトはその終わりに付く
    project.clamp_fades()
    first = project.clips[0].info
    canvas = canvas_size(project, opts.max_long)
    fps_expr, fps_val = core.plan_fps(first, opts.max_fps)
    hdr = any(c.info.hdr for c in project.clips)
    sources = [c.info.path for c in project.clips]
    spans = plan_spans(project.duration, opts)
    outs = output_paths(project, opts, len(spans))
    results = []
    for i, ((t0, t1), out) in enumerate(zip(spans, outs)):
        def cb(f, i=i):
            if progress:
                progress((i + f) / len(spans), i + 1, len(spans))
        cb(0.0)
        inputs, graph = build_graph(project, t0, t1, canvas, fps_expr)

        def make_cmd(part, maxrate, inputs=inputs, graph=graph, t0=t0, t1=t1):
            return ([core.ffmpeg_exe(), '-hide_banner', '-y', '-loglevel', 'error', '-nostdin'] + inputs
                    + ['-filter_complex', graph, '-map', '[v]', '-map', '[a]', '-t', '%.3f' % (t1 - t0)]
                    + core.encode_args(opts, fps_val, maxrate, hdr, part))
        core.encode_limited(make_cmd, out, t1 - t0, opts, sources, cb, cancel)
        results.append(core.check_output(out, opts))
    if progress:
        progress(1.0, len(spans), len(spans))
    return results


# ---- プレビュー ----
PREVIEW_BOX = (640, 360)
PREVIEW_FPS = 15
PREVIEW_MAX_SEC = 300      # 1回の再生で用意する長さの上限


def preview_size(project):
    return fit_box(canvas_size(project), *PREVIEW_BOX)


def preview_fps(project):
    f = project.clips[0].info.fps
    return int(min(PREVIEW_FPS, f)) if 1.0 <= f < PREVIEW_FPS else PREVIEW_FPS


def ppm(size, rgb):
    return b'P6\n%d %d\n255\n' % size + rgb


def preview_frame(project, t):
    """全体の時刻 t の1コマ (フェード込み)。返り値: (大きさ, PPM のバイト列)。取れなければ None。"""
    total = project.duration
    size = preview_size(project)
    t = max(0.0, min(t, total - 0.05))
    inputs, graph = build_graph(project, t, min(total, t + 0.5), size, '30', audio=False, fast=True)
    cmd = ([core.ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-nostdin'] + inputs
           + ['-filter_complex', graph, '-map', '[v]', '-frames:v', '1',
              '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, creationflags=core.NOWIN)
    need = size[0] * size[1] * 3
    if len(r.stdout) < need:
        return None
    return size, ppm(size, r.stdout[:need])


def preview_video_cmd(project, t0, t1):
    """t0〜t1 を小さい生の映像 (rgb24) として標準出力に流すコマンド。返り値: (コマンド, 大きさ, fps)"""
    size, fps = preview_size(project), preview_fps(project)
    inputs, graph = build_graph(project, t0, t1, size, str(fps), audio=False, fast=True)
    cmd = ([core.ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-nostdin'] + inputs
           + ['-filter_complex', graph, '-map', '[v]', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    return cmd, size, fps


def preview_audio_cmd(project, t0, t1, wav_path):
    """t0〜t1 の音を WAV に書き出すコマンド。"""
    inputs, graph = build_graph(project, t0, t1, (2, 2), '1', video=False)
    return ([core.ffmpeg_exe(), '-hide_banner', '-y', '-loglevel', 'error', '-nostdin'] + inputs
            + ['-filter_complex', graph, '-map', '[a]', '-ar', '22050', '-ac', '2',
               '-c:a', 'pcm_s16le', '-f', 'wav', str(Path(wav_path))])
