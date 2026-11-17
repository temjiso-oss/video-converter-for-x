"""配布用の exe を作る。

    python build_exe.py

出力: dist/VideoConverterForX/VideoConverterForX.exe (ffmpeg.exe を同梱)
      files/VideoConverterForX-<版>.zip
      (README・LICENSE・THIRD_PARTY_NOTICES・licenses/・screenshots/ も同梱)
依存: pip install -r requirements.txt
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'
NAME = 'VideoConverterForX'


def main():
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    work = ROOT / 'build'
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
           '--name', NAME, '--distpath', str(ROOT / 'dist'), '--workpath', str(work),
           '--specpath', str(work), '--paths', str(SRC),
           '--collect-all', 'tkinterdnd2',
           '--add-binary', f'{ff};.',
           '--exclude-module', 'imageio_ffmpeg', '--exclude-module', 'numpy', '--exclude-module', 'PIL',
           '--exclude-module', 'matplotlib',
           str(SRC / 'app.py')]
    subprocess.run(cmd, check=True)
    dist = ROOT / 'dist' / NAME
    internal = dist / '_internal'
    base = internal if internal.exists() else dist
    src_ff = base / Path(ff).name
    if src_ff.exists():
        src_ff.rename(base / 'ffmpeg.exe')
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy(ROOT / name, dist / name)
    if (dist / 'licenses').exists():
        shutil.rmtree(dist / 'licenses')
    shutil.copytree(ROOT / 'licenses', dist / 'licenses')
    # README の画像 (tests/make_screenshots.py で release/screenshots に作ったもの)
    shots = ROOT / 'release' / 'screenshots'
    if (dist / 'screenshots').exists():
        shutil.rmtree(dist / 'screenshots')
    if shots.exists():
        shutil.copytree(shots, dist / 'screenshots', ignore=shutil.ignore_patterns('*.mp4'))
    sys.path.insert(0, str(SRC))
    from xvideo import __version__
    (ROOT / 'files').mkdir(exist_ok=True)
    out = ROOT / 'files' / f'{NAME}-{__version__}'
    shutil.make_archive(str(out), 'zip', dist.parent, dist.name)
    print('OK:', dist / f'{NAME}.exe')
    print('ZIP:', str(out) + '.zip')


if __name__ == '__main__':
    main()
