# VideoMaker

YAMLで書いたシナリオから、静止画・動画素材にナレーション音声（VOICEVOX など）・字幕・テロップ・BGMを合成した動画を自動生成する Python ツールです。

## 特長

- YAMLスクリプトで動画仕様・シーン情報を宣言的に管理
- VOICEVOX（または汎用 Voicebox 互換 API）で音声合成し、結果をキャッシュして再利用
- 漢字の読み間違いを設定ファイルの読み替え表で訂正（字幕の表示には影響しない）
- ナレーションの長さに合わせてシーンの長さを自動決定
- 複数行ナレーションを1行ずつ合成し、字幕も1行ずつ順番に表示
- テロップ（シーンの見出し）の表示、動画素材シーンの挿入
- BGM の合成（動画より短い BGM は自動でループ）
- 低解像度・低fpsで素早く内容を確認できるプレビューモード
- 音声を合成せず字幕・テロップだけで作る音声なしモード（アフレコ用）
- NVIDIA GPU（NVENC）によるハードウェアエンコード

---

## 目次

1. [実行環境の構築](#実行環境の構築)
2. [クイックスタート](#クイックスタート)
3. [コマンド](#コマンド)
4. [設定ファイル config.yaml](#設定ファイル-configyaml)
5. [シナリオファイル（YAMLスクリプト）](#シナリオファイルyamlスクリプト)
6. [動作の詳細](#動作の詳細)
7. [高速化とプレビュー](#高速化とプレビュー)
8. [トラブルシューティング](#トラブルシューティング)
9. [既知の制限・未実装の項目](#既知の制限未実装の項目)
10. [修正履歴](#修正履歴)

---

## 実行環境の構築

Windows 11 で動作確認しています（Python 3.10.5 / MoviePy 2.1.2 / VOICEVOX ENGINE 0.25.1 / GeForce RTX 3060）。

### 必要なもの

| ソフトウェア | 必須 | 用途 |
|---|---|---|
| Python 3.10 以上 | 必須 | 本体の実行 |
| VOICEVOX（エンジン） | 必須（※） | ナレーション音声の合成 |
| 日本語フォント（.ttf / .ttc / .otf） | 必須 | 字幕・テロップの描画 |
| NVIDIA GPU とドライバ | 任意 | GPU エンコード（NVENC）による高速化 |

※ 汎用の Voicebox 互換 API サーバーを使うこともできます（[音声合成サーバー](#音声合成サーバーの設定)参照）。

FFmpeg を別途インストールする必要はありません。MoviePy の依存パッケージ `imageio-ffmpeg` に同梱された FFmpeg（NVENC 対応ビルド）が自動的に使われます。

### 1. Python のインストール

[python.org](https://www.python.org/downloads/) から Python 3.10 以上をインストールします（インストール時に「Add python.exe to PATH」にチェック）。

```powershell
python --version   # Python 3.10.x 以上であることを確認
```

### 2. VideoMaker のインストール

仮想環境を作ってからインストールすることを推奨します。

```powershell
cd E:\work\videomaker
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # PowerShell の場合（cmd.exe なら .venv\Scripts\activate.bat）
pip install -e .
```

`Activate.ps1` の実行がブロックされる場合は、一度だけ次を実行してください。

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

開発用ツール（pytest, ruff, mypy）も入れる場合:

```powershell
pip install -e ".[dev]"
pytest
```

インストールすると `videomaker` コマンドが使えるようになります（`python -m videomaker.cli` でも同じです）。

### 3. VOICEVOX の準備

1. [VOICEVOX 公式サイト](https://voicevox.hiroshiba.jp/) から VOICEVOX をダウンロードしてインストールします。
2. VOICEVOX を起動します（アプリを起動するとエンジンが `http://127.0.0.1:50021` で待ち受けます。エンジン単体版の `run.exe` でも構いません）。
3. 疎通と話者IDを確認します。

```powershell
curl http://127.0.0.1:50021/version
curl http://127.0.0.1:50021/speakers   # 各キャラクターの styles[].id が話者IDです
```

確認した話者IDを `config.yaml` の `voicebox_voice_map` に設定します。VOICEVOX で作成した音声を動画に使う場合は、各キャラクターの利用規約に従ってクレジットを表記してください。

### 4. フォントの準備

字幕・テロップは日本語フォントで描画します。フォントが見つからないと日本語が表示されません。

- Windows に標準で入っている MS ゴシックを使う場合: `C:\Windows\Fonts\msgothic.ttc` を `assets/fonts/` にコピー
- 他のフォント（例: Noto Sans JP）を使う場合も `assets/fonts/` に置くのが簡単です

`config.yaml` の `default_font` にパスを設定します。

### 5. 設定ファイルの作成

`config.example.yaml` をコピーして `config.yaml` を作り、環境に合わせて編集します。

```powershell
Copy-Item config.example.yaml config.yaml
```

`config.yaml` はカレントディレクトリから読み込まれます。VideoMaker はプロジェクトのルートディレクトリで実行してください。

### 6. GPU エンコード（任意）

NVIDIA GPU と最新のドライバがあれば、追加のインストールなしで NVENC が使えます。既定（`video_encoder: auto`）では起動時に NVENC が動くか確認し、使えなければ CPU（libx264）でエンコードします。

### ディレクトリ構成

```
videomaker/
├─ config.yaml            … 実行環境の設定（カレントディレクトリから読み込み）
├─ config.example.yaml    … 設定ファイルのひな形
├─ samples/story.yaml     … シナリオのひな形
├─ assets/
│   ├─ fonts/             … フォント（ファイル名だけで指定したときの検索先）
│   ├─ images/            … 画像（同上）
│   ├─ videos/            … 動画素材（同上）
│   └─ sounds/            … BGM（同上）
├─ .cache/voice/          … 音声合成のキャッシュ
├─ dist/                  … 出力先（既定）
└─ src/videomaker/        … ソースコード
```

---

## クイックスタート

```powershell
# 1. VOICEVOX を起動しておく
# 2. シナリオを検証（素材ファイルの有無、VOICEVOX との疎通）
videomaker validate pylori1.yaml

# 3. まずプレビューで内容を確認（960x540 / 10fps で高速に出力）
videomaker preview pylori1.yaml          # -> dist/pylori1_preview.mp4

# 4. 問題なければ本番の書き出し
videomaker render pylori1.yaml           # -> dist/pylori1.mp4
```

---

## コマンド

### `videomaker validate SCRIPT`

シナリオの構文、素材ファイル（画像・動画・BGM・フォント）の存在、音声合成サーバーとの疎通を確認します。サーバーに接続できない場合は警告だけを表示します。`--no-voice` を付けると（またはシナリオで `options.no_voice: true` のとき）疎通確認を省略します。

### 共通オプション

| オプション | 説明 |
|---|---|
| `--debug` | エラー発生時にトレースバック（詳細情報）も表示する。コマンド名の前に指定する（例: `videomaker --debug render story.yaml`） |

通常、ファイルの不足・YAMLの書式ミス・タイムアウトなどのエラーは、原因と対処のヒントだけを表示して終了します（終了コード 1）。

### `videomaker render SCRIPT`

音声合成 → シーン合成 → 動画の書き出しを行います。

| オプション | 説明 |
|---|---|
| `--out PATH` | 出力先。省略時はシナリオの `video.output_file`、それもなければ `dist/<スクリプト名>.mp4` |
| `--scene ID` | 指定したシーンだけを書き出す（複数回指定可） |
| `--preview`, `-p` | プレビューモードで書き出す（`preview` コマンドと同じ。出力名の既定は `<名前>_preview.mp4`） |
| `--encoder auto\|cpu\|nvenc` | 映像エンコーダ。省略時は config の `video_encoder` |
| `--fps N` | 出力フレームレートを上書き |
| `--scale X` | 出力解像度の倍率を上書き（0.1〜1.0。例: 0.5 で 1920x1080 → 960x540） |
| `--config PATH` | 設定ファイルを指定（省略時はカレントディレクトリの `config.yaml`） |
| `--voice-cache DIR` | 音声キャッシュのディレクトリを指定 |
| `--no-voice` | 音声なしモード。音声を合成せず、字幕・テロップのみで書き出す（[音声なしモード](#音声なしモードアフレコ用)参照。出力名の既定は `<名前>_novoice.mp4`） |

### `videomaker preview SCRIPT`

内容確認用に、低解像度・低fps・高速なエンコード設定で書き出します（既定は 0.5倍・10fps）。

| オプション | 説明 |
|---|---|
| `--scene ID`, `-s ID` | 対象シーン（複数回指定可。省略時は全シーン） |
| `--out PATH` | 出力先。省略時は `dist/<スクリプト名>_preview.mp4` |
| `--fps N` | フレームレート（既定: config の `preview_fps`） |
| `--scale X` | 解像度の倍率（既定: config の `preview_scale`） |
| `--encoder`, `--config`, `--voice-cache`, `--no-voice` | `render` と同じ |

例:

```powershell
videomaker preview pylori1.yaml -s 1-2 -s 1-3          # 2シーンだけ確認
videomaker preview pylori1.yaml --scale 0.25 --fps 5   # さらに軽く
videomaker render  pylori1.yaml --encoder cpu          # GPU を使わずに書き出す
```

### `videomaker clear [SCRIPT]`

音声キャッシュ（キャッシュディレクトリ直下の `*.wav`）をすべて削除します。削除前に確認を求めます。

| オプション | 説明 |
|---|---|
| `SCRIPT` | 指定するとそのシナリオの `options.voice_cache_dir` を対象にする（省略時は `.cache/voice`） |
| `--voice-cache DIR` | 対象のキャッシュディレクトリを指定（最優先） |
| `--yes`, `-y` | 確認せずに削除する |

```powershell
videomaker clear              # .cache/voice を削除
videomaker clear pylori1.yaml -y
```

---

## 設定ファイル config.yaml

実行環境に関する設定です。すべての項目は省略でき、省略時は既定値が使われます。

### 音声合成サーバーの設定

| キー | 既定値 | 説明 |
|---|---|---|
| `voicebox_mode` | `generic` | `voicevox`（VOICEVOX エンジン）または `generic`（汎用 Voicebox 互換 API） |
| `voicebox_url` | `http://127.0.0.1:9000/api/tts` | サーバーの URL。`voicevox` モードではルート（例: `http://127.0.0.1:50021`）を指定 |
| `voicebox_health_url` | `null` | 疎通確認用 URL。`null` の場合、`voicevox` モードでは `<url>/speakers`、`generic` モードでは URL の `/tts` を `/health` に置き換えたものを使用（置き換えられなければ確認しない） |
| `voicebox_token` | `null` | `generic` モードで `Authorization: Bearer <token>` ヘッダーとして送るトークン |
| `voicebox_timeout` | `30` | API 呼び出しのタイムアウト（秒）。長いナレーションで失敗する場合は大きくする |
| `voicebox_voice_map` | `{}` | シナリオで使う声の名前 → 話者ID の対応表 |
| `voicebox_reading_map` | `{}` | 音声合成前に置き換える読みの表（下記） |

**声の名前と話者ID**: シナリオの `video.voice` や `voice_override.voice` には、`narrator_male` のような分かりやすい名前を書き、`voicebox_voice_map` で VOICEVOX の話者ID に変換します。話者ID（数字）をシナリオに直接書くこともできます。`voicevox` モードでは、最終的に数字の話者IDになっている必要があります。

```yaml
voicebox_voice_map:
  narrator_female: "3"
  narrator_male: "10"
```

**読み替え（漢字の読み間違いの訂正）**: `voicebox_reading_map` に書いた語は、音声合成に送る直前に置き換えられます。字幕・テロップの表示は元の文字のままです。長い語から優先して置換されるので、「行方: ゆくえ」と「方: かた」を両方書いても「行方」は正しく「ゆくえ」になります。

```yaml
voicebox_reading_map:
  方: かた
  行方: ゆくえ
  十二指腸: じゅうにしちょう
```

`generic` モードでは、`voicebox_url` に `{"text": ..., "voice": ..., "speed": ..., "pitch": ...}` を JSON で POST し、応答の本文を音声ファイル（wav）として保存します。

### 素材・フォントの設定

| キー | 既定値 | 説明 |
|---|---|---|
| `default_font` | `null` | 字幕・テロップのフォント。シナリオの `video.subtitle.font` が見つからない場合や未指定の場合に使用 |
| `image_dir` | `null` | 画像の検索先ディレクトリ。シナリオに書いた画像が見つからない場合、同じファイル名をこのディレクトリから探す（例: ComfyUI の出力フォルダ） |
| `ffmpeg_path` | `null` | 未使用（同梱の FFmpeg が使われます） |

### 字幕・テロップの既定値

| キー | 既定値 | 説明 |
|---|---|---|
| `subtitle_font_size` | `48` | 字幕の文字サイズ（シナリオの `style.font_size` が優先） |
| `subtitle_stroke_width` | `2` | 字幕の縁取り幅（シナリオの `style.stroke_width` が優先） |
| `subtitle_line_interval` | `0.0` | 複数行ナレーションの行と行の間に入れる無音・字幕非表示の時間（秒）。0 より大きいと1行ずつ音声合成します（[動作の詳細](#複数行のナレーションと字幕)参照） |
| `max_line_chars` | `30` | ナレーション・字幕の1行の最大文字数の目安。超える行は句読点を優先して自動分割します（[長いナレーションの自動分割](#長いナレーションの自動分割)参照）。`0` で分割しない |
| `teletext_font_size` | `60` | テロップの文字サイズ（シナリオの `style.font_size` が優先） |
| `teletext_stroke_width` | `3` | テロップの縁取り幅（シナリオの `style.stroke_width` が優先） |
| `subtitle_color`, `subtitle_stroke_color`, `teletext_color`, `teletext_stroke_color` | | 現在は使われていません。文字色・縁取り色はシナリオの `style.fill` / `style.stroke` で指定してください |

### 音声の既定値

| キー | 既定値 | 説明 |
|---|---|---|
| `voice_volume` | `1.0` | ナレーションの音量（0.0〜2.0、1.0 が 100%）。シーンの `voice_override.volume` が優先 |
| `voice_margin_before` | `0.0` | ナレーションの前に入れる無音（秒） |
| `voice_margin_after` | `0.0` | ナレーションの後に入れる無音（秒） |
| `no_voice_chars_per_second` | `6.0` | 音声なしモードでシーンの長さを見積もるときの読み上げ速度（1秒あたりの文字数） |
| `no_voice_min_duration` | `2.0` | 音声なしモードで見積もるシーンの長さの最小値（秒） |

### エンコード・プレビューの設定

| キー | 既定値 | 説明 |
|---|---|---|
| `video_encoder` | `auto` | `auto`（NVENC が使えれば GPU、使えなければ CPU）/ `cpu`（libx264）/ `nvenc`（h264_nvenc）/ FFmpeg のコーデック名 |
| `video_preset` | `null` | エンコーダのプリセット。未指定時は libx264: `medium`（プレビュー時 `ultrafast`）、NVENC: `p5`（プレビュー時 `p1`） |
| `video_quality` | `null` | 画質。libx264 は CRF、NVENC は CQ の値で、小さいほど高画質・大きいファイル。未指定時は 23（プレビュー時は libx264: 30、NVENC: 32） |
| `preview_scale` | `0.5` | プレビュー時の解像度の倍率 |
| `preview_fps` | `10` | プレビュー時のフレームレート |

### 設定例

```yaml
voicebox_mode: voicevox
voicebox_url: http://127.0.0.1:50021
voicebox_health_url: http://127.0.0.1:50021/speakers
voicebox_timeout: 30
voicebox_voice_map:
  narrator_female: "10"
  narrator_male: "10"
voicebox_reading_map:
  方: かた

default_font: assets/fonts/msgothic.ttc
image_dir: E:/ComfyUI/ComfyUI/output

subtitle_font_size: 54
subtitle_stroke_width: 3
subtitle_line_interval: 0.2
teletext_font_size: 60
teletext_stroke_width: 3

voice_volume: 1.0
voice_margin_before: 1.0
voice_margin_after: 0.5

video_encoder: auto
preview_scale: 0.5
preview_fps: 10
```

---

## シナリオファイル（YAMLスクリプト）

1本の動画の内容を記述するファイルです。`video`（動画全体の設定）、`scenes`（シーンの配列）、`options` の3つのセクションからなります。

### 全体の例

```yaml
video:
  width: 1920
  height: 1080
  fps: 30
  voice: narrator_male
  bgm: assets/sounds/BGM2-1.wav
  output_file: dist/pylori.mp4
  subtitle:
    font: assets/fonts/msgothic.ttc
    position: bottom
    style:
      fill: "#FFFFFF"
      stroke: "#000000"
      font_size: 54
      padding: 32

scenes:
  - id: 1-1
    image: output/scene_1-1.png
    teletext:
      text: "オープニング"
      position: top_left
      style:
        fill: "#FFE066"
        stroke: "#222222"
    voiceover: |
      日本では、胃の中に住み着く細菌「ヘリコバクター・ピロリ」―
      通称「ピロリ菌」が、少なくとも3,000万人以上の人々に
      感染していると考えられています。

  - id: 1-2
    image: output/scene_1-2.png
    voiceover: |
      ピロリ菌の正式名称は
      「ヘリコバクター・ピロリ（Helicobacter pylori）」です。
    voice_override:
      voice: narrator_female
      speed: 1.1
      volume: 1.2

  - id: demo
    video: assets/videos/demo.mp4
    duration: 8
    voiceover: 実際の様子を動画でご覧ください。
    subtitle: ""          # 字幕を表示しない

options:
  voice_cache_dir: .cache/voice
```

### `video`（動画全体の設定）

| キー | 既定値 | 説明 |
|---|---|---|
| `width` | `1920` | 出力の幅（px） |
| `height` | `1080` | 出力の高さ（px） |
| `fps` | `30` | フレームレート |
| `voice` | `null` | ナレーションの声（`voicebox_voice_map` の名前、または話者ID） |
| `bgm` | `null` | BGM ファイル（mp3 / wav など）。動画より短い場合はループ、長い場合は動画の長さでカット。音量は 40% |
| `output_file` | `null` | 出力ファイル名。`--out` を省略したときに使用 |
| `transition` | `cut` | シーン切り替えのトランジションの既定値（`cut` / `fade` / `crossfade`。[トランジション](#シーン切り替えのトランジション)参照） |
| `transition_duration` | `0.5` | トランジションの長さ（秒）の既定値 |
| `subtitle` | | 字幕の設定（下記） |

#### `video.subtitle`

| キー | 既定値 | 説明 |
|---|---|---|
| `font` | `null` | 字幕とテロップのフォント。見つからなければ `assets/fonts/<ファイル名>`、次に config の `default_font` を使用 |
| `position` | `bottom` | `bottom`（画面下）または `top`（画面上） |
| `style` | | 字幕のスタイル（下記の `style` 参照） |

#### `style`（字幕・テロップ共通）

| キー | 既定値 | 説明 |
|---|---|---|
| `fill` | `"#FFFFFF"` | 文字色 |
| `stroke` | `"#000000"` | 縁取り色。`null` で縁取りなし |
| `stroke_width` | `null` | 縁取り幅（px）。`null` なら config の値 |
| `font_size` | `null` | 文字サイズ。`null` なら config の値 |
| `padding` | `24` | 字幕の画面端からの余白（px）。字幕のみ有効 |
| `background` | `null` | 未実装 |

### `scenes`（シーンの配列）

| キー | 必須 | 既定値 | 説明 |
|---|---|---|---|
| `id` | ○ | | シーンID（重複不可）。`--scene` での指定に使う |
| `image` | △ | | 背景の静止画。`image` と `video` のどちらか一方を指定 |
| `video` | △ | | 背景の動画素材 |
| `voiceover` | ○ | | ナレーション本文。複数行で書ける |
| `duration` | | `null` | シーンの長さ（秒）。省略時はナレーション音声の長さ＋前後の無音 |
| `subtitle` | | `null` | 字幕の文章。省略時は `voiceover` を字幕にする。`""`（空文字）で字幕なし |
| `teletext` | | `null` | テロップ（下記） |
| `voice_override` | | `null` | このシーンだけ声・速度などを変える（下記） |
| `transition` | | `null` | 前のシーンからこのシーンへ切り替わるときのトランジション（`cut` / `fade` / `crossfade`）。省略時は `video.transition`。最初のシーンでは無視 |
| `transition_duration` | | `null` | このシーンへのトランジションの長さ（秒）。省略時は `video.transition_duration` |
| `kenburns` | | `false` | 未実装 |

#### `teletext`（テロップ）

シーンの最初から最後まで表示される見出しです。

| キー | 既定値 | 説明 |
|---|---|---|
| `text` | （必須） | テロップの文字。複数行で書くと縦に並べて表示 |
| `position` | `top_left` | `top_left` / `top_right` / `bottom_left` / `bottom_right` / `center` |
| `style` | | `style` 参照。`fill` の既定値は白なので、色を付けたい場合は指定する（例: `"#FFE066"`） |

#### `voice_override`（シーンごとの声の上書き）

| キー | 説明 |
|---|---|
| `voice` | 声の名前または話者ID |
| `speed` | 話速（VOICEVOX の `speedScale`。1.0 が標準） |
| `pitch` | 音高（VOICEVOX の `pitchScale`。0.0 が標準で、±0.15 程度の範囲） |
| `volume` | ナレーション音量（0.0〜2.0）。config の `voice_volume` より優先 |

### `options`

| キー | 既定値 | 説明 |
|---|---|---|
| `voice_cache_dir` | `.cache/voice` | 音声キャッシュの保存先（`--voice-cache` が優先） |
| `no_voice` | `false` | `true` で音声なしモード（アフレコ用）。`--no-voice` と同じ |
| `subtitle_format` | `burn` | 未実装（字幕は常に映像に焼き込み） |
| `keep_temp` | `false` | 未実装 |
| `workers` | `1` | 未実装 |

### ファイルパスの解決

- シナリオ内の相対パス（`image`, `video`, `bgm`, `subtitle.font`, `voice_cache_dir`）は、**シナリオファイルのあるディレクトリ**を基準に解決されます。
- 見つからない場合は、ファイル名だけで次の場所を探します。
  - 画像: `assets/images/` → config の `image_dir`
  - 動画: `assets/videos/`
  - BGM: `assets/sounds/`
  - フォント: `assets/fonts/` → config の `default_font`

---

## 動作の詳細

### シーンの長さ

- `duration` を省略すると、`voice_margin_before` ＋ ナレーション音声の長さ ＋ `voice_margin_after` になります。
- `duration` を指定した場合はその長さになります。ナレーション（前後の無音を含む）より短いと音声が途中で切れます。
- 静止画は `width` × `height` に合わせて拡大・縮小されます（縦横比は維持されません。画像は出力と同じ縦横比で用意してください）。
- 動画素材は、長さの差が 5% 以内ならそのまま、長ければ `duration` でカット、短ければ `duration` まで延長します。

### 複数行のナレーションと字幕

`voiceover` を `|` を使って複数行で書くと、次のように処理されます。

- **字幕**: 1行ずつ順番に表示されます（`subtitle` を指定した場合は `subtitle` の行が対象）。各行の表示時間は、シーンの長さから行間の時間を引き、各行の文字数（空白を除く）に比例して割り振ります。1行の字幕はシーン全体で表示されます。
- **音声**: config の `subtitle_line_interval` が 0 より大きい場合、1行ずつ音声合成し、行と行の間に `subtitle_line_interval` 秒の無音を入れて結合します。0 の場合はナレーション全体をまとめて合成します。
- 字幕は横幅（`width` − 200px）を超えると折り返されます。

### 長いナレーションの自動分割

1行が config の `max_line_chars`（既定 30文字）を超える場合は、自動で複数の行に分割し、上の「複数行」と同じように処理します（1行ずつ音声合成・字幕を順番に表示）。`voiceover: >` で長い文章をまとめて書いても、自分で改行を入れる必要はありません。

```yaml
    voiceover: >
      山道からはずっと八ヶ岳が望めます。
      春先の八ヶ岳はまだ山頂付近に雪が残っていて、
      青空とのコントラストがとても美しく、
      登山道を歩く人たちの目を楽しませてくれます。
```

上の例は、`>` によって1行の文章（82文字）になり、次の4行に分割されます。

```
山道からはずっと八ヶ岳が望めます。
春先の八ヶ岳はまだ山頂付近に雪が残っていて、
青空とのコントラストがとても美しく、
登山道を歩く人たちの目を楽しませてくれます。
```

- **分割位置の優先順位**: ① 句点（`。！？`） ② 読点など（`、，；：`。`3,000` のような数字の区切りは除く） ③ 空白 ④ 括弧の前後 ⑤ ひらがなから漢字・カタカナに変わる位置（文節の切れ目になりやすい）。同じ優先度なら、行の長さがなるべく均等になる位置を選びます。
- 1行に収まる短い文は、句点があってもつなげたままにします（例: `本当ですか！？　はい、そうです。`）。
- 句読点・閉じ括弧・小さい「っ」「ゃ」・長音「ー」などで行が始まらないようにします。`。」` のように句点の後の閉じ括弧は前の行に含めます。
- `|` で自分で改行した行も、`max_line_chars` を超えていれば分割されます。分割したくない場合は `max_line_chars: 0` にしてください。
- `>` は改行を半角空白に置き換えるため、日本語の文字に挟まれた半角空白は取り除きます（英単語の間の空白は残ります）。
- 音声なしモードの長さの見積もり（行間の数）にも、分割後の行数が使われます。

### シーン切り替えのトランジション

`video.transition` で全シーン共通の切り替え方を、`scenes[].transition` でシーンごとの切り替え方を指定します（シーン側が優先）。シーンの `transition` は「前のシーンからそのシーンに入るとき」の切り替え方です。

| 種類 | 見え方 | 動画の長さ |
|---|---|---|
| `cut` | 瞬間的に切り替え（既定） | 変わらない |
| `fade` | 前のシーンが暗くなり、黒を経由して次のシーンが明るくなる。`transition_duration` の前半で暗転、後半で明転 | 変わらない |
| `crossfade` | 前のシーンの終わりに次のシーンを重ね、溶け込ませる | 重なった分（`transition_duration`）だけ短くなる |

```yaml
video:
  transition: fade            # 全シーン共通
  transition_duration: 0.5
scenes:
  - id: s1
    ...
  - id: s2
    transition: crossfade     # s1 → s2 だけクロスフェード
    transition_duration: 1.0
  - id: s3
    transition: cut           # s2 → s3 は瞬間切り替え
```

- **ナレーションの重なり防止**: `crossfade` では前後のシーンが重なるため、前のシーン末尾の無音＋次のシーン先頭の無音（`voice_margin_before` / `voice_margin_after` や `duration` の余り）を超える長さを指定すると、声が重ならない長さに自動で短縮されます（警告を表示）。無音がほとんど無い場合は `cut` になります。`crossfade` を長めに使う場合は `voice_margin_before` / `voice_margin_after` を大きくしてください。
- **長さの上限**: トランジションの長さは、前後どちらのシーンの長さの半分も超えないよう自動で短縮されます。
- **字幕**: `crossfade` で前後のシーンが重なっている間は字幕を表示しません。字幕はシーンの残りの区間で表示されます（複数行の場合も、その区間を行数で分けて順番に表示）。テロップは映像と一緒に溶け込みます。`fade` では字幕も映像と一緒に暗転します。
- **処理時間**: 混ぜる処理を行うのはトランジションの区間だけなので、書き出し時間はほとんど増えません（1080p/30fps・約10秒の動画で 8.2秒 → 10.0秒）。

### 音声なしモード（アフレコ用）

ナレーションを後から自分で録音（アフレコ）する場合に、音声合成をせず字幕・テロップだけの動画を作ります。`render` / `preview` / `validate` に `--no-voice` を付けるか、シナリオに `options.no_voice: true` を書くと有効になります。

```powershell
videomaker render story.yaml --no-voice       # -> dist/story_novoice.mp4
videomaker preview story.yaml --no-voice      # -> dist/story_novoice_preview.mp4
```

- VOICEVOX は不要です（接続しません）。音声キャッシュも作りません。
- `voiceover` は字幕として表示されます（`subtitle` を指定した場合はそちら）。複数行の場合は音声ありと同様に1行ずつ表示されます。
- `duration` を省略したシーンは、ナレーションの文字数から長さを見積もります。
  - 長さ ＝ max(文字数 ÷ `no_voice_chars_per_second`, `no_voice_min_duration`) ＋ 行間（(行数−1) × `subtitle_line_interval`） ＋ `voice_margin_before` ＋ `voice_margin_after`
  - 文字数には空白を含みません。読む速さに合わせて `no_voice_chars_per_second` を調整するか、シーンごとに `duration` を指定してください。
- BGM は通常どおり合成されます。
- 書き出し後に、アフレコ用のタイムテーブル（各シーンの開始・終了時刻、切り替え方、ナレーション）が表示されます。`crossfade` で重なるシーンは、重なった時刻のまま表示されます（例: 前のシーンが 0:03.50 に終わり、次のシーンが 0:02.50 に始まる）。

### 音声キャッシュ

- 音声合成の結果は、文章・声・速度・音高から決まる名前で `.cache/voice/<hash>.wav` に保存され、同じ内容は再利用されます。ナレーションを修正したシーン・行だけが再合成されます。
- 複数行ナレーションを結合した音声も `.cache/voice/combined_<hash>.wav` にキャッシュされます。
- 読み替え表を変更すると、該当する行は自動的に再合成されます。キャッシュを消したい場合は `videomaker clear` を実行してください。

---

## 高速化とプレビュー

### 仕組み

- 静止画シーンの画面は、字幕・テロップが切り替わるときにしか変化しません。そこで、切り替わり区間ごとに1回だけ画面を合成し、そのフレームを使い回しています（出力される映像は従来と同じです）。
- プレビューモードでは、元の解像度で合成したフレームを区間ごとに1回だけ縮小し、低fps・高速なエンコード設定で書き出します。字幕の位置や大きさの比率は本番と同じです。
- NVIDIA GPU があれば、映像のエンコードを GPU（NVENC）で行います。

### 処理時間の目安

約88秒・2シーン・1920x1080/30fps のシナリオ（pylori1.yaml）での実測値です（CPU 16スレッド / GeForce RTX 3060）。

| モード | 処理時間 |
|---|---|
| 修正前 | 約 8分24秒 |
| 通常の書き出し（CPU / libx264） | 約 67秒 |
| 通常の書き出し（GPU / NVENC） | 約 53秒 |
| プレビュー（960x540 / 10fps） | 約 9秒 |

動画素材（`video:`）のシーンは毎フレームの合成が必要なため、プレビューで fps と解像度を下げた分だけ速くなります。

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `Voiceboxヘルスチェックに失敗しました` | VOICEVOX が起動しているか、`voicebox_url` / `voicebox_health_url` が正しいか確認 |
| `voicevoxモードでは数値の話者IDが必要です` | `voicebox_voice_map` に声の名前が登録されているか確認 |
| 長いナレーションで音声合成がタイムアウトする | `voicebox_timeout` を大きくする（例: 120） |
| 漢字の読みが間違っている | `voicebox_reading_map` に正しい読みを登録 |
| 字幕が表示されない・文字化けする | 日本語フォントを `default_font` または `video.subtitle.font` に設定 |
| `素材ファイルが見つかりません` | 表示されたファイルのパスを確認（[ファイルパスの解決](#ファイルパスの解決)参照） |
| `YAML形式が不正です` | 表示された行・列付近のインデントや `キー: 値` の書き方を確認 |
| `予期しないエラーが発生しました` | `videomaker --debug render ...` で詳細を表示して原因を確認 |
| VOICEVOX を使わずに字幕だけの動画を作りたい | `--no-voice`（[音声なしモード](#音声なしモードアフレコ用)参照） |
| GPU を使わずに書き出したい | `--encoder cpu` または config で `video_encoder: cpu` |
| 書き出しが遅い | まず `videomaker preview` で内容を確認し、最後に `render` する |

---

## 既知の制限・未実装の項目

- `kenburns`、`style.background`、`options` の `subtitle_format` / `keep_temp` / `workers` は、設定は受け付けますが動作には反映されません。
- テロップの `position` が `top_right` / `bottom_left` / `bottom_right` の場合、文字の左上が画面の右端・下端付近に置かれるため、テロップが画面外にはみ出します。現状は `top_left` または `center` を使ってください。
- config の `subtitle_color` などの色設定は使われていません（シナリオの `style` で指定）。
- 複数行字幕の各行の表示時間は等分のため、行ごとの音声の長さとは厳密には一致しません。

---

## 修正履歴

### 2026-10

- **長いナレーションの自動分割**: `max_line_chars`（既定 30文字）を超える行を、句点 → 読点 → 空白 → 括弧 → 文節らしい境目の優先順で自動分割し、1行ずつ音声合成・字幕表示するようにした。`voiceover: >` で書いた文章の日本語間の余分な空白も取り除く。複数行字幕の表示時間を、行数で等分する方式から文字数に比例する方式に変更。
- **シーン切り替えのトランジションを追加**: `video.transition` / `scenes[].transition` で `cut` / `fade` / `crossfade` を指定できるようにした。クロスフェードはナレーションが重ならない長さに自動で短縮し、重なる区間は字幕を表示しない。トランジション区間だけフレームを混ぜる方式で、書き出し速度をほぼ維持。シーンより長い音声が次のシーンに食い込まないよう切り詰めるようにした。
- **音声なしモードを追加（アフレコ用）**: `--no-voice` または `options.no_voice: true` で、音声合成をせず字幕・テロップのみの動画を作る。シーンの長さは文字数から見積もり（`no_voice_chars_per_second` / `no_voice_min_duration`）、書き出し後にアフレコ用タイムテーブルを表示する。
- **エラーメッセージの改善**: ファイルの不足、YAML・設定値の誤り、VOICEVOX の接続失敗・タイムアウト、素材の読み込みや書き出しの失敗を、トレースバックではなく原因と対処のヒントで表示するようにした。`--debug` で詳細を表示できる。
- **プレビューモードを追加**: `videomaker preview`（全シーン/複数シーン対応）と `render --preview`。低解像度・低fps・高速エンコード設定で内容を素早く確認できる。`--fps` / `--scale` で調整可能。
- **書き出しの高速化**: 静止画シーンを字幕の切り替わり区間ごとに1回だけ合成するように変更し、シーンの連結方法も見直した（1080p/30fps で約 8分24秒 → 約 1分）。
- **GPU エンコード（NVENC）に対応**: `video_encoder`（`auto` / `cpu` / `nvenc`）、`video_preset`、`video_quality` を追加。`auto` では NVENC が使えるか自動判定する。
- **複数行ナレーションの結合音声をキャッシュ**: 毎回の再エンコードをやめ、一時 mp3 ファイルが溜まり続ける問題も解消。
- **VOICEVOX 呼び出しのタイムアウトを設定可能に**: `voicebox_timeout`。
- **BGM のループ**: 動画より短い BGM を使うとエラーになっていた問題を修正し、自動で繰り返すようにした。
- **読み替え表を追加**: `voicebox_reading_map` で漢字の読み間違いを訂正できるようにした（字幕には影響しない）。
- **複数行ナレーションの順次処理**: 1行ずつ音声合成し、字幕も1行ずつ順番に表示するようにした。
- 依存パッケージの MoviePy を 2.x 以上に変更（コードが 2.x の API を使っているため）。

### それ以前

- VOICEVOX モード（`voicebox_mode: voicevox`、`voicebox_voice_map`）とヘルスチェック URL の設定に対応
- 字幕・テロップのスタイルの既定値、音量、前後の無音を config で設定できるようにした
- ナレーションの長さからシーンの長さを自動決定
- 動画素材シーンの挿入、`image_dir` による画像の自動検索

---

## ライセンス

社内利用前提（必要に応じて追記してください）。
