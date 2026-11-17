# テスト

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
