# 同梱しているソフトウェアとライセンス / Third-party notices

Video Converter for X の本体（`src/` のプログラムとビルド用スクリプト）は MIT ライセンスです（`LICENSE`）。
Windows 版の配布物には、次のソフトウェアが含まれています。各ライセンスの全文は `licenses/` フォルダにあります。

| ソフトウェア | 用途 | ライセンス | 全文 |
|---|---|---|---|
| FFmpeg 9.0.2（gyan.dev "essentials" ビルド、imageio-ffmpeg 0.8.1 経由で入手） | 動画・音声の変換 | **GNU GPL v3**（`--enable-gpl --enable-version3` でビルドされたもの） | `licenses/GPL-3.0.txt` |
| Python 3.12 | 実行環境 | PSF License | `licenses/Python-LICENSE.txt` |
| Tcl/Tk 8.6 (tkinter) | 画面 | Tcl/Tk License (BSD 系) | `licenses/Tcl-Tk-license.terms` |
| tkinterdnd2 0.7 / tkdnd | ドラッグ＆ドロップ | MIT（tkinterdnd2）/ BSD 系（tkdnd） | `licenses/tkinterdnd2-LICENSE.txt` |
| imageio-ffmpeg 0.8 | FFmpeg の入手 | BSD-2-Clause | `licenses/imageio-ffmpeg-LICENSE.txt` |
| PyInstaller 6.22（ブートローダー） | exe 化 | GPL v2 以降 + 配布を認める例外条項 | `licenses/PyInstaller-COPYING.txt` |

## FFmpeg について（GPL v3）

- `_internal/ffmpeg.exe` は FFmpeg プロジェクト（https://ffmpeg.org/ ）の成果物で、改変していません。
  このアプリは ffmpeg.exe を別のプログラムとして起動して使っています。
- ビルド: FFmpeg 9.0.2 "essentials_build"（https://www.gyan.dev/ffmpeg/builds/ ）。
- ソースコードの入手先:
  - FFmpeg 9.0.2 のソース（`ffmpeg-9.0.2.tar.xz`）は、このアプリの GitHub の Releases（各版の添付ファイル）にも置いています。
    FFmpeg の公式の配布場所は https://ffmpeg.org/releases/ です。
  - ビルドに使われた外部ライブラリとビルド設定は、上記 gyan.dev のページで公開されています。
  - `ffmpeg.exe -version` を実行すると、ビルドの設定（`--enable-gpl --enable-version3` など）を確認できます。
  - 入手できない場合は、配布ページ（GitHub の Issues など）でお知らせください。
- FFmpeg は GPL v3 の条件で、どなたでも再配布・改変できます。条件の全文は `licenses/GPL-3.0.txt` です。
- このアプリ本体（MIT ライセンス）は、FFmpeg を組み込まず、別のプログラムとして起動して使っています。アプリ本体のソースコードも GitHub で公開しています。

## 商標について

「X」「Twitter」は X Corp. の商標です。このアプリは非公式のもので、X Corp. とは関係がなく、X Corp. の承認・提携を受けたものではありません。
