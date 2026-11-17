"""公開用のソース一式を release/ にそろえる (GitHub にそのまま置ける形)。

    python tests/run_tests.py          # テスト用の動画 (tests/work) を作る
    python tests/make_screenshots.py   # README の画像 (release/screenshots/)
    python build_exe.py                # 配布用 zip (files/VideoConverterForX-<版>.zip)
    python make_release.py             # release/ (ソース・ライセンス・README・技術資料)

個人的な作業メモ (docs/HANDOFF.md など)、テスト用の動画・変換結果 (tests/work)、exe・zip は入れない。
"""
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REL = ROOT / 'release'

KEEP_IN_RELEASE = {'screenshots'}          # 消さずに残すもの (make_screenshots.py が作る)

# 技術資料 (docs/SPEC.md) の作業メモの言い回しを公開向けに直す。直す前の文が見つからなければ止める
SPEC_FIXES = [
    (r'\nユーザーの依頼（2026-11-10）:「[^」]*」。\n', '\n'),
    (r'（1\.1\.0 で追加。ユーザーの依頼 2026-11-11:[^）]*）', '（1.1.0 で追加）'),
    (r'※ この表は作成した AI の知識によるもので、今回は公式ページでの再確認はしていない。',
     '※ この表は作成時点（2026-11）の作者の理解によるもので、公式ページでの再確認はしていない。'),
]

GITIGNORE = '''__pycache__/
*.pyc
build/
dist/
files/
tests/work/
*.spec
*.part.mp4
# 変換した動画・テスト用の動画を誤って入れないように
*.mp4
*.mkv
*.webm
*.avi
*.mov
*.mpg
*.gif
*.wav
'''

TESTS_README = '''# テスト

`run_tests.py` を最初に実行してください。ffmpeg でテスト用の動画（色の帯の映像と 440Hz の音）を `tests/work/` に作り、
変換結果（形式・大きさ・fps・長さ・容量）を確かめます。ほかのテストはその動画を使います。

| ファイル | 内容 |
|---|---|
| `run_tests.py` | 変換の確認（15通り。数分かかります） |
| `gui_test.py` | 画面を自動で操作して変換まで |
| `edit_test.py` | 切り貼り・フェードの変換とプレビュー |
| `editor_test.py` | 編集の窓を自動で操作（数秒音が鳴ります。Pillow があれば画面の画像を保存） |
| `make_screenshots.py` | README 用の画面の画像を `release/screenshots/` に作る（Pillow が必要） |

`tests/work/` は消してかまいません（次に `run_tests.py` を実行すると作り直します）。
'''


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def check_private():
    """個人情報が紛れ込んでいないか (このパソコンのユーザー名・ホームフォルダのパス・メールアドレス・作業用のフォルダ名)。"""
    words = {os.environ.get('USERNAME', ''), Path.home().name}
    words = [re.escape(w) for w in words if len(w) >= 3]
    bad = re.compile('|'.join(words + [r'\\Users\\', r'/Users/', r'01_AI-Projects', r'[A-Za-z]:\\\\?01_',
                                       r'[\w.+-]+@(gmail|yahoo|outlook|hotmail|icloud)\.']), re.IGNORECASE)
    names = re.compile(r'\b(JISO|Muse|Strata|Codex)\b')          # チーム内の呼び名
    for p in REL.rglob('*'):
        if not p.is_file() or p.parent.name == 'licenses' or p.name == 'make_release.py':
            continue
        if p.suffix in ('.py', '.md', '.txt', '') or p.name in ('.gitignore', 'LICENSE'):
            text = p.read_text(encoding='utf-8', errors='ignore')
            m = bad.search(text) or names.search(text)
            if m:
                raise SystemExit(f'個人情報らしき文字列があります: {p} ({m.group(0)!r})')


def main():
    # 前回作った分 (画像以外) を消す
    for p in REL.iterdir() if REL.exists() else []:
        if p.name in KEEP_IN_RELEASE:
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    REL.mkdir(exist_ok=True)
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'requirements.txt', 'build_exe.py', 'make_release.py'):
        copy(ROOT / name, REL / name)
    shutil.copytree(ROOT / 'licenses', REL / 'licenses')
    copy(ROOT / 'src' / 'app.py', REL / 'src' / 'app.py')
    for p in (ROOT / 'src' / 'xvideo').glob('*.py'):
        copy(p, REL / 'src' / 'xvideo' / p.name)
    for p in (ROOT / 'tests').glob('*.py'):
        copy(p, REL / 'tests' / p.name)
    (REL / 'tests' / 'README.md').write_text(TESTS_README, encoding='utf-8')
    spec = (ROOT / 'docs' / 'SPEC.md').read_text(encoding='utf-8')
    for pat, rep in SPEC_FIXES:
        spec, n = re.subn(pat, rep, spec)
        if n == 0:
            raise SystemExit(f'docs/SPEC.md に直す文が見つかりません（SPEC を変えたら SPEC_FIXES も直す）: {pat}')
    spec = spec.replace('# 仕様書: Video Converter for X', '# 技術資料: Video Converter for X', 1)
    (REL / 'docs').mkdir(exist_ok=True)
    (REL / 'docs' / 'TECHNICAL.md').write_text(spec, encoding='utf-8')
    (REL / '.gitignore').write_text(GITIGNORE, encoding='utf-8')
    for need in ('screenshots/app.png', 'screenshots/editor.png'):
        if not (REL / need).exists():
            print(f'注意: release/{need} がありません（python tests/make_screenshots.py で作る）')
    check_private()
    n = sum(1 for p in REL.rglob('*') if p.is_file())
    print(f'release/ に {n} ファイル')


if __name__ == '__main__':
    main()
