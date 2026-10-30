# VideoMaker

YAMLで書いたシナリオから、静止画・動画素材にナレーション音声（VOICEVOX など）・字幕・テロップ・BGMを合成した動画を自動生成する Python ツールです。

## 特長

- YAMLスクリプトで動画仕様・シーン情報を宣言的に管理
- VOICEVOX（または汎用 Voicebox 互換 API）で音声合成し、結果をキャッシュして再利用
- 漢字の読み間違いを設定ファイルの読み替え表で訂正（字幕の表示には影響しない）
- ナレーションの長さに合わせてシーンの長さを自動決定
- 複数行ナレーションを1行ずつ合成し、字幕も1行ずつ順番に表示
- テロップ（シーンの見出し）の表示、動画素材シーンの挿入
- BGM の合成（動画より短い BGM は自動でループ。音量・再生開始位置・フェードも指定可能）
- シーンの開始時刻を指定して曲に合わせて切り替える、ミュージックビデオ向けの機能
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
| Git | 任意 | GitHub からのソース取得・更新（ZIP ダウンロードなら不要） |

※ 汎用の Voicebox 互換 API サーバーを使うこともできます（[音声合成サーバー](#音声合成サーバーの設定)参照）。

FFmpeg を別途インストールする必要はありません。MoviePy の依存パッケージ `imageio-ffmpeg` に同梱された FFmpeg（NVENC 対応ビルド）が自動的に使われます。

### 1. Python のインストール

[python.org](https://www.python.org/downloads/) から Python 3.10 以上をインストールします（インストール時に「Add python.exe to PATH」にチェック）。

```powershell
python --version   # Python 3.10.x 以上であることを確認
```

### 2. VideoMaker のインストール

#### ソースの取得（GitHub から）

ソースコードは GitHub の [Crytus/videomaker](https://github.com/Crytus/videomaker) で公開しています。

**Git を使う場合**（[Git for Windows](https://gitforwindows.org/) などをインストールしておく）:

```powershell
cd E:\work                       # 置きたい場所に移動
git clone https://github.com/Crytus/videomaker.git
cd videomaker
```

**Git を使わない場合**: リポジトリのページで「Code」→「Download ZIP」を選んでダウンロードし、好きな場所に展開して、展開したフォルダ（`pyproject.toml` があるフォルダ）に移動します。

`config.yaml` とフォント（`assets/fonts/`）はリポジトリに含まれていません。後述の手順 4・5 で各自用意してください。

#### インストール

仮想環境を作ってからインストールすることを推奨します。取得したフォルダ（`pyproject.toml` があるフォルダ）で次を実行します。

```powershell
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

#### 最新版への更新

Git で取得した場合は、取得したフォルダで次を実行します（`-e` でインストールしているので、通常は再インストール不要です。依存パッケージが変わったときだけ `pip install -e .` を再実行してください）。

```powershell
git pull
pip install -e .                 # 依存パッケージが変わったときのみ
```

ZIP で取得した場合は、新しい ZIP をダウンロードして展開し直し、`config.yaml`・`assets/fonts/` の中身・自分で作ったシナリオなどを新しいフォルダにコピーしてから、仮想環境を作り直してインストールしてください。

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
| `--log-dir DIR` | 実行ログの出力先（既定: `logs`）。環境変数 `VIDEOMAKER_LOG_DIR` でも指定できる。コマンド名の前に指定する |

通常、ファイルの不足・YAMLの書式ミス・タイムアウトなどのエラーは、原因と対処のヒントだけを表示して終了します（終了コード 1）。

### 実行ログ

`validate` / `render` / `preview` を実行すると、画面に表示した内容が `logs/日時_コマンド名_シナリオ名.log`（例: `logs/20261029_103000_render_story.log`）にも保存されます。ログファイルは新しいものから 30 個まで残し、それより古いものは自動で削除します。

- 処理を止めるほどではない問題（BGM が短い、動画素材が指定時間より短い、など）は「警告」としてログに記録されます。実行の終わりに警告があった場合は、`警告が N 件ありました。内容をログファイルで確認してください: ...` と表示されます。
- moviepy などのライブラリが出す警告（`UserWarning` など）は、進捗表示を崩さないよう画面には出さず、ログファイルにだけ記録します。数字だけが違う同じ種類の警告（フレーム番号違いなど）は 1 件にまとめます。
- エラーで終了した場合は、`--debug` を付けなくてもトレースバックがログファイルに残ります。

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
| `subtitle_background` | `null` | 字幕の背景色の既定値（シナリオの `style.background` が優先）。例: `"#00000080"` |
| `teletext_background` | `null` | テロップの背景色の既定値（シナリオの `style.background` が優先） |
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
| `bgm` | `null` | BGM ファイル（mp3 / wav など）。動画より短い場合はループ、長い場合は動画の長さでカット |
| `bgm_volume` | `0.4` | BGM の音量（0.0〜2.0。1.0 が元の音量） |
| `bgm_start` | `0` | BGM ファイルのどの位置から再生するか（秒、または `"分:秒"`。例: `"0:30"`） |
| `bgm_fade_in` | `0` | BGM のフェードインの長さ（秒） |
| `bgm_fade_out` | `0` | BGM のフェードアウトの長さ（秒）。動画の終わり（BGM が先に終わる場合は BGM の終わり）にかける |
| `bgm_loop` | `true` | BGM が動画より短いときに繰り返すか。`false` なら BGM が終わった後は無音 |
| `output_file` | `null` | 出力ファイル名。`--out` を省略したときに使用 |
| `transition` | `cut` | シーン切り替えのトランジションの既定値（`cut` / `fade` / `crossfade`。[トランジション](#シーン切り替えのトランジション)参照） |
| `transition_duration` | `0.5` | トランジションの長さ（秒）の既定値 |
| `scene_interval` | `0` | シーン切り替えの間の既定値（秒）。ナレーションが終わってから次のシーンに切り替わるまでの時間（[シーン切り替えの間](#シーン切り替えの間)参照） |
| `subtitle` | | 字幕の設定（下記） |
| `teletext` | | テロップの共通設定（下記） |
| `max_line_chars` | `null` | ナレーション・字幕の1行の最大文字数。指定すると config の `max_line_chars` より優先（`0` で分割しない）。縦動画など画面幅が狭いシナリオで小さめにする |
| `teletext_max_line_chars` | `null` | テロップの1行の最大文字数。超える行は自動で折り返す（`null`・`0` なら折り返さない）。シーンの `teletext.max_line_chars` が優先 |

#### `video.subtitle`

| キー | 既定値 | 説明 |
|---|---|---|
| `font` | `null` | 字幕とテロップのフォント。見つからなければ `assets/fonts/<ファイル名>`、次に config の `default_font` を使用 |
| `position` | `bottom` | `bottom`（画面下）、`top`（画面上）、`none`（字幕を出力しない） |
| `style` | | 字幕のスタイル（下記の `style` 参照） |

#### `video.teletext`

| キー | 既定値 | 説明 |
|---|---|---|
| `position` | `top_left` | シーンの `teletext.position` を省略したときの配置。値はシーンの `position` と同じ。`none` にすると、`position` を指定したシーンのテロップだけが表示される |
| `style` | | テロップのスタイルの既定値（`style` 参照）。シーンの `teletext.style` に書いた項目だけがシーンごとに上書きされ、書いていない項目はここの値になる |
| `max_line_chars` | `null` | テロップの1行の最大文字数の既定値。`video.teletext_max_line_chars` より優先、シーンの `teletext.max_line_chars` がさらに優先 |

全シーンで同じ色・背景のテロップを使う場合は、ここにまとめて書けます。

```yaml
video:
  teletext:
    position: none          # position を書かないシーンはテロップを出さない
    style:
      fill: "#FFE066"
      stroke: "#222222"
      background: "#00000080"
scenes:
  - id: intro
    teletext:
      text: イントロ
      position: center      # このシーンだけ表示
      style:
        fill: "#FF0000"     # 文字色だけ変える（縁取り・背景は video.teletext.style のまま）
```

#### `style`（字幕・テロップ共通）

| キー | 既定値 | 説明 |
|---|---|---|
| `fill` | `"#FFFFFF"` | 文字色 |
| `stroke` | `"#000000"` | 縁取り色。`null` で縁取りなし |
| `stroke_width` | `null` | 縁取り幅（px）。`null` なら config の値 |
| `font_size` | `null` | 文字サイズ。`null` なら config の値 |
| `padding` | `24` | 字幕の画面端からの余白（px）。字幕のみ有効 |
| `background` | `null` | 文字の背景色。`"#RRGGBB"`、半透明は `"#RRGGBBAA"`（例: `"#00000080"` で50%の黒）、`red` などの色名も可。`null` なら config の `subtitle_background` / `teletext_background` |
| `background_opacity` | `null` | 背景の不透明度（0.0＝透明〜1.0＝不透明）。`background` のアルファ値に掛け合わせる |
| `background_padding` | `16` | 文字の周りに広げる背景の余白（px） |

#### 文字の背景（読みにくいときに）

画像によって字幕やテロップが読みにくい場合は、`style.background` で文字の後ろに色付きの矩形を敷けます。矩形は文字が実際に描かれている範囲より `background_padding` だけ大きくなります。

```yaml
video:
  subtitle:
    style:
      background: "#00000080"        # 字幕: 半透明の黒
scenes:
  - id: intro
    teletext:
      text: 飯盛山登山道からの八ヶ岳
      style:
        fill: "#FFE066"
        background: "#1E3A5F"        # テロップ: 紺色を
        background_opacity: 0.6      # 60%の不透明度で
        background_padding: 20       # 文字の周りに20pxの余白
```

- 半透明は `"#RRGGBBAA"` の末尾2桁（`00`＝透明〜`FF`＝不透明。`80` で約50%）か、`background_opacity` で指定します。両方指定すると掛け合わせます。
- 複数行のテロップは、全行をまとめて1枚の矩形で囲みます。複数行の字幕は、表示中の行ごとに文字の長さに合わせた矩形になります。
- 全シーン共通にしたい場合は、config の `subtitle_background` / `teletext_background` に指定します（シナリオの `style.background` が優先）。

### `scenes`（シーンの配列）

| キー | 必須 | 既定値 | 説明 |
|---|---|---|---|
| `id` | ○ | | シーンID（重複不可）。`--scene` での指定に使う |
| `image` | △ | | 背景の静止画。`image` と `video` のどちらか一方を指定 |
| `video` | △ | | 背景の動画素材 |
| `voiceover` | | `""` | ナレーション本文。複数行で書ける。省略するとナレーションなしのシーン。`{無音 0.5}` で途中に無音を入れられる（[ナレーションに無音を入れる](#ナレーションに無音を入れる)参照） |
| `start` | | `null` | シーンの開始時刻（動画の先頭からの秒数、または `"分:秒"`・`"時:分:秒"`）。指定すると、直前のシーンの長さがこの時刻に合わせて決まる（[シーンの長さ](#シーンの長さ)参照） |
| `duration` | | `null` | シーンの長さ（秒）。省略時はナレーション音声の長さ＋前後の無音。ナレーションより短い値を指定した場合は、ナレーションが収まる長さに自動で延長 |
| `subtitle` | | `null` | 字幕の文章。省略時は `voiceover` を字幕にする。`""`（空文字）で字幕なし |
| `teletext` | | `null` | テロップ（下記） |
| `voice_override` | | `null` | このシーンだけ声・速度などを変える（下記） |
| `transition` | | `null` | 前のシーンからこのシーンへ切り替わるときのトランジション（`cut` / `fade` / `crossfade`）。省略時は `video.transition`。最初のシーンでは無視 |
| `transition_duration` | | `null` | このシーンへのトランジションの長さ（秒）。省略時は `video.transition_duration` |
| `interval` | | `null` | このシーンのナレーションが終わってから次のシーンに切り替わるまでの間（秒）。省略時は `video.scene_interval` |
| `kenburns` | | `false` | 未実装 |

#### `teletext`（テロップ）

シーンの最初から最後まで表示される見出しです。

| キー | 既定値 | 説明 |
|---|---|---|
| `text` | （必須） | テロップの文字。複数行で書くと縦に並べて表示 |
| `position` | `null` | `top_left` / `top_right` / `bottom_left` / `bottom_right` / `center` / `none`（テロップを出力しない）。省略時は `video.teletext.position`（既定は `top_left`） |
| `style` | | `style` 参照。書いた項目だけが `video.teletext.style` を上書きする。どちらにも書かない場合の `fill` は白なので、色を付けたい場合は指定する（例: `"#FFE066"`） |
| `max_line_chars` | `null` | 1行の最大文字数。超える行は自動で折り返す。`null` なら `video.teletext.max_line_chars`、次に `video.teletext_max_line_chars`、`0` なら折り返さない |

#### `voice_override`（シーンごとの声の上書き）

指定したキーだけが上書きされます。たとえば `speed` だけを書いた場合、声は `video.voice` のまま速度だけが変わります。

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

シーンの長さは、次の優先順で決まります。

1. **次のシーンに `start` がある場合**: 次のシーンの開始時刻までの長さ（`duration` やナレーションより優先）
2. **`duration` を指定した場合**: その長さ。ただし、ナレーション（前後の無音を含む）より短い場合は、ナレーションが途中で切れないよう、その長さまで自動で延長します（警告を表示）。ナレーションを長くしたときに `duration` を直し忘れても大丈夫です。音声なしモードでは、指定した `duration` がそのまま使われます。
3. **ナレーションがある場合**: `voice_margin_before` ＋ ナレーション音声の長さ ＋ `voice_margin_after` ＋ 切り替えの間（`interval` / `video.scene_interval`。最後のシーンには加えない）
4. **動画素材のシーン**: 動画ファイルの長さ
5. **最後のシーンで BGM がある場合**: BGM の終わりまで

どれにも当てはまらない場合（ナレーションも `duration` も無く、次のシーンにも `start` が無い）はエラーになります。

- 静止画は `width` × `height` に合わせて拡大・縮小されます（縦横比は維持されません。画像は出力と同じ縦横比で用意してください）。
- 動画素材は、長さの差が 5% 以内ならそのまま、長ければ `duration` でカット、短ければ `duration` まで延長します。

### シーン切り替えの間

ナレーションが終わってすぐに次のシーンに切り替わると慌ただしく感じる場合は、切り替えの前に間（ま）をあけられます。冒頭の `video.scene_interval` で全シーン共通の間を、シーンごとの `interval` で個別の間を指定します（シーンの指定が優先）。間のあいだは画像（テロップ・最後の行の字幕）を表示したままで、BGM も流れ続けます。

```yaml
video:
  scene_interval: 1.0     # 基本の間: ナレーションの後、1秒おいて次のシーンへ
scenes:
  - id: intro
    image: a.jpg
    voiceover: 春の山道には小鳥の声が響きます。
  - id: river1
    image: b.jpg
    interval: 0.3         # このシーンの後だけ短く
    voiceover: 谷を抜ける風が、澄んだ川面を揺らします。
  - id: river2
    image: c.jpg
    interval: 3           # このシーンの後は長めに
    voiceover: とても気持ちの良い登山道です。
  - id: ending
    image: d.jpg
    duration: 8
```

- 間は、シーンの長さがナレーションから決まる場合に、ナレーション（config の `voice_margin_after` を含む）の後に加えます。`duration` を指定したシーン、次のシーンに `start` があるシーン、ナレーションの無いシーンには加えません。
- 最後のシーンは次のシーンへの切り替えが無いので加えません。
- `crossfade` のトランジションは、間の時間も使って重ねます（間が長いほど、ナレーションに重ならずに長いクロスフェードにできます）。
- config の `voice_margin_before` / `voice_margin_after` は全シナリオ共通の余白、`scene_interval` はシナリオごとの設定です。

### ナレーションに無音を入れる

ナレーションの途中に `{無音 秒数}` と書くと、その位置に指定した秒数の無音が入ります。字幕には表示されません。BGM は無音の間もそのまま流れます。

```yaml
    voiceover: |
      春の山道には{無音 0.5}小鳥の声が響きます。
      {無音 1.5}
      飯盛山は八ヶ岳を望むのに最良の山です。
```

- 行の途中に書いた場合は、字幕はつながった1行（`春の山道には小鳥の声が響きます。`）のまま、無音の間も表示し続けます。
- 無音だけの行は、前の行との間の無音になります（字幕はその間表示されません）。
- `{無音 0.5秒}` のように「秒」を付けても、括弧・空白が全角（`｛無音　0.5｝`）でも構いません。`voiceover: >` で書いた場合も使えます。
- `無音` の代わりに `mute` も使えます（`{mute 0.5}`、`{mute 0.5s}`。大文字小文字は問いません）。
- 無音の前後のテキストは別々に音声合成して、間に無音を挟んでつなぎます（このため1行ずつの合成と同じく、字幕は各行の音声に合わせて表示されます）。
- `{無音}` のように秒数が無いなど書式が誤っている場合は、エラーになります。
- 音声なしモードでは、見積もったシーンの長さに無音の秒数を加えます。

### ミュージックビデオ（開始時刻の指定）

曲（BGM）に合わせて画面を切り替えたいときは、各シーンに `start`（動画の先頭からの開始時刻）を指定します。曲を再生ソフトや Audacity で聞きながら、切り替えたい時刻をそのまま書けます。サンプルは `musicvideo.yaml` です。

```yaml
video:
  bgm: assets/sounds/song.mp3
  bgm_volume: 1.0          # 曲が主役なので元の音量で
  bgm_fade_out: 3.0
  bgm_loop: false
  transition: crossfade
scenes:
  - id: intro
    image: assets/images/intro.jpg
    teletext:
      text: 曲名
  - id: verse1
    image: assets/images/a.jpg
    start: "0:12.5"        # 「分:秒」または秒数（12.5）
    subtitle: |
      一番の歌詞の1行目
      一番の歌詞の2行目
  - id: chorus
    image: assets/images/b.jpg
    start: "0:45"
    subtitle: サビの歌詞   # 最後のシーンは duration を省略すると曲の終わりまで
```

- `start` を指定したシーンは、必ずその時刻に始まります。直前のシーンの長さは自動で決まり、`duration` を書いても `start` が優先されます（異なる場合は警告を表示）。ナレーションが収まらない場合は途中で切れます（警告を表示）。
- `start` は書いたシーンだけに指定すれば十分です。`start` の無いシーンは前のシーンに続けて始まり、次に `start` のあるシーンの直前のシーンで長さを調整します。
- `start` は後ろのシーンほど大きい値にしてください。最初のシーンの `start` は省略するか 0 にします（曲の途中から動画を始めたい場合は `video.bgm_start` を使います。`start` は `bgm_start` からの時刻になります）。
- `crossfade` を使っても開始時刻はずれません。次のシーンが `start` の時刻からフェードインし始めるよう、前のシーンを重なる分だけ延ばします。
- `voiceover` を省略すると、ナレーションの無いシーンになります。すべてのシーンでナレーションが無い場合は VOICEVOX に接続しません。歌詞は `subtitle` に書きます（複数行の場合は文字数に比例して1行ずつ表示されます）。
- `--scene` で途中のシーンだけを書き出すと、BGM はそのシーンの開始時刻の位置から再生されます（サビだけ確認する場合などに便利です）。

### 複数行のナレーションと字幕

`voiceover` を `|` を使って複数行で書くと、次のように処理されます。

- **字幕**: 1行ずつ順番に表示されます（`subtitle` を指定した場合は `subtitle` の行が対象）。1行ずつ音声合成した場合（下記）は、各行の音声が鳴り始めたときにその行の字幕を表示し、音声が終わると消します（最後の行はシーンの終わりまで表示）。それ以外の場合は、シーンの長さから行間の時間を引き、各行の文字数（空白を除く）に比例して割り振ります。1行の字幕はシーン全体で表示されます。
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
- シナリオの `video.max_line_chars` を指定すると、config より優先されます。同じナレーションで横動画と縦動画を作るときは、縦動画のシナリオだけ小さい値にしてください（字幕の文字サイズ 48 で幅 1080px なら 18〜20文字程度が目安）。
- テロップは既定では自動で折り返しません。`video.teletext_max_line_chars`（全シーン共通）またはシーンの `teletext.max_line_chars` を指定すると、同じ規則で折り返して複数行で表示します。

### シーン切り替えのトランジション

`video.transition` で全シーン共通の切り替え方を、`scenes[].transition` でシーンごとの切り替え方を指定します（シーン側が優先）。シーンの `transition` は「前のシーンからそのシーンに入るとき」の切り替え方です。

| 種類 | 見え方 | 動画の長さ |
|---|---|---|
| `cut` | 瞬間的に切り替え（既定） | 変わらない |
| `fade` | 前のシーンが暗くなり、黒を経由して次のシーンが明るくなる。`transition_duration` の前半で暗転、後半で明転 | 変わらない |
| `crossfade` | 前のシーンの終わりに次のシーンを重ね、溶け込ませる | 重なった分（`transition_duration`）だけ短くなる（`start` を指定したシーンの開始時刻は変わらない） |

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
| `予期しないエラーが発生しました` | `videomaker --debug render ...` で詳細を表示するか、ログファイルのトレースバックで原因を確認 |
| `警告が N 件ありました` | 表示されたログファイルで「警告」の行を確認（[実行ログ](#実行ログ)参照） |
| ログに `bytes wanted but 0 bytes read ... Using the last valid frame instead.` | 動画素材の最後のフレームより後ろを読もうとしたときの moviepy の警告。動画が指定時間より短く、最後のフレームを止めて表示している場合などに出る。frame index が総フレーム数と同じか、それより後ろなら問題なし。かなり手前のフレームで出ている場合は、動画ファイルが壊れている可能性がある |
| VOICEVOX を使わずに字幕だけの動画を作りたい | `--no-voice`（[音声なしモード](#音声なしモードアフレコ用)参照） |
| GPU を使わずに書き出したい | `--encoder cpu` または config で `video_encoder: cpu` |
| 書き出しが遅い | まず `videomaker preview` で内容を確認し、最後に `render` する |

---

## 既知の制限・未実装の項目

- `kenburns`、`options` の `subtitle_format` / `keep_temp` / `workers` は、設定は受け付けますが動作には反映されません。
- テロップの `position` が `top_right` / `bottom_left` / `bottom_right` の場合、文字の左上が画面の右端・下端付近に置かれるため、テロップが画面外にはみ出します。現状は `top_left` または `center` を使ってください。
- config の `subtitle_color` などの色設定は使われていません（シナリオの `style` で指定）。
- `subtitle_line_interval` が 0 の場合や `subtitle` を別に指定した場合、複数行字幕の表示時間は文字数による割り振りのため、音声とは厳密には一致しません。
- ミュージックビデオの歌詞は、現状はシーンの `subtitle` で表示します。1行ごとの表示時刻の指定（LRC 形式の読み込みなど）は今後対応予定です。

---

## 修正履歴

### 2026-10

- **実行ログ**: 実行時の表示内容を `logs/` のログファイルにも保存するようにした。処理を止めない問題（警告）やライブラリの警告はログに記録し、実行の終わりに警告があればログファイルの確認を促すメッセージを表示する（[実行ログ](#実行ログ)参照）。
- **シーン切り替えの間**: `video.scene_interval`（基本の間）とシーンごとの `interval` で、ナレーションが終わってから次のシーンに切り替わるまでの間を指定できるようにした。
- **ナレーションに無音を挿入**: `voiceover` の中に `{無音 0.5}` と書くと、その位置に無音を入れるようにした（字幕には表示しない。BGM はそのまま流れる）。`{mute 0.5}` とも書ける。
- **画面幅に合わせた1行の文字数**: シナリオの `video.max_line_chars` でナレーション・字幕の1行の最大文字数を（config より優先して）指定できるようにした。テロップも `video.teletext_max_line_chars` / `teletext.max_line_chars` で自動で折り返せるようにした。
- **画像・動画のアスペクト比を維持**: 素材と出力のアスペクト比が違う場合に引き伸ばさず、中央部分を切り取ってから出力サイズに合わせるようにした（横長の画像を縦動画に使うと左右が切れる）。
- **ミュージックビデオ向けの機能を追加**: シーンの開始時刻を `start`（秒、または `"分:秒"`）で指定できるようにした。直前のシーンの長さは自動で決まり、クロスフェードでも開始時刻はずれない。`voiceover` を省略可能にし、最後のシーンは長さを省略すると BGM の終わりまで表示する。BGM の音量（`bgm_volume`）・再生開始位置（`bgm_start`）・フェードイン/アウト（`bgm_fade_in` / `bgm_fade_out`）・ループの有無（`bgm_loop`）を指定できるようにした。`--scene` で途中のシーンだけを書き出したときは、BGM をそのシーンの開始時刻の位置から再生する。動画素材のシーンは、`duration` を省略すると動画ファイルの長さになる。
- **字幕・テロップの背景色**: `style.background`（半透明は `#RRGGBBAA`）、`background_opacity`、`background_padding` で、文字より少し大きい色付きの矩形を文字の後ろに敷けるようにした。config の `subtitle_background` / `teletext_background` で既定値も指定可能。あわせて、テロップの `top_right` / `bottom_*` 配置で文字が画面外にはみ出していた問題を修正。
- **ナレーションとシーン・字幕のタイミングを修正**: `duration` がナレーションより短い場合に、画面が切り替わり音声が途中で切れていた問題を修正し、ナレーションが収まる長さまで自動で延長するようにした。1行ずつ音声合成した場合は、字幕を各行の音声に合わせて切り替えるようにした。
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

MITライセンス

```
The MIT License (MIT)

Copyright (c) 2026 Crytus

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```
