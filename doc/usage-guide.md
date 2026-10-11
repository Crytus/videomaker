# VideoMaker 使い方ガイド

このガイドでは、VideoMakerを使用してYAMLスクリプトから動画を生成する方法を説明します。

## 目次

1. [インストール](#インストール)
2. [設定ファイルの準備](#設定ファイルの準備)
3. [YAMLスクリプトの作成](#yamlスクリプトの作成)
4. [コマンドの使い方](#コマンドの使い方)
5. [詳細な機能説明](#詳細な機能説明)
6. [トラブルシューティング](#トラブルシューティング)

---

## インストール

### 1. 依存関係のインストール

```bash
pip install -e .
```

開発時は追加で以下を実行してください。

```bash
pip install -e ".[dev]"
```

### 2. 外部ツールの準備

- **FFmpeg**: 動画エンコードに必要です。システムにインストールしてください。
- **VOICEVOX**: 音声合成に使用します。`http://127.0.0.1:50021`で起動してください。

---

## 設定ファイルの準備

プロジェクトルートに`config.yaml`を作成します。

### VOICEVOXモード（推奨）

```yaml
voicebox_mode: voicevox
voicebox_url: http://127.0.0.1:50021
voicebox_health_url: http://127.0.0.1:50021/speakers
voicebox_token: null
voicebox_timeout: 30  # Voicebox API呼び出しのタイムアウト（秒）
voicebox_reading_map:  # 音声合成時の読み替え（字幕には影響しない）
  方: かた
voicebox_voice_map:
  narrator_female: "3"
  narrator_male: "1"
ffmpeg_path: null
default_font: assets/fonts/msgothic.ttc
image_dir: assets/images

# 字幕のデフォルト設定
subtitle_font_size: 48
subtitle_color: "#FFFFFF"
subtitle_stroke_color: "#000000"
subtitle_stroke_width: 2
subtitle_line_interval: 0.5  # 複数行字幕の行間時間（秒）

# テロップのデフォルト設定
teletext_font_size: 60
teletext_color: "#FFE066"
teletext_stroke_color: "#222222"
teletext_stroke_width: 3

# 音声のデフォルト設定
voice_volume: 1.0  # ナレーション音量（1.0が100%、0.0～2.0の範囲）
voice_margin_before: 0.5  # 音声の前に追加する無音時間（秒）
voice_margin_after: 0.5  # 音声の後に追加する無音時間（秒）
```

### 汎用モード（カスタムVoicebox API）

```yaml
voicebox_mode: generic
voicebox_url: http://127.0.0.1:9000/api/tts
voicebox_health_url: null
voicebox_token: null
voicebox_voice_map: {}
ffmpeg_path: null
default_font: assets/fonts/msgothic.ttc
image_dir: assets/images

# 字幕のデフォルト設定
subtitle_font_size: 48
subtitle_color: "#FFFFFF"
subtitle_stroke_color: "#000000"
subtitle_stroke_width: 2
subtitle_line_interval: 0.5  # 複数行字幕の行間時間（秒）

# テロップのデフォルト設定
teletext_font_size: 60
teletext_color: "#FFE066"
teletext_stroke_color: "#222222"
teletext_stroke_width: 3

# 音声のデフォルト設定
voice_volume: 1.0  # ナレーション音量（1.0が100%、0.0～2.0の範囲）
voice_margin_before: 0.5  # 音声の前に追加する無音時間（秒）
voice_margin_after: 0.5  # 音声の後に追加する無音時間（秒）
```

### 設定項目の説明

| 項目 | 説明 |
|------|------|
| `voicebox_mode` | `voicevox`または`generic`。VOICEVOXを使う場合は`voicevox`を指定 |
| `voicebox_url` | Voicebox APIのベースURL |
| `voicebox_health_url` | ヘルスチェック用のURL（省略可） |
| `voicebox_token` | 認証トークン（不要な場合は`null`） |
| `voicebox_voice_map` | YAMLスクリプトの音声名と話者IDのマッピング |
| `ffmpeg_path` | FFmpegのパス（システムPATHにある場合は`null`） |
| `default_font` | デフォルトフォントファイルのパス |
| `image_dir` | デフォルト画像ディレクトリ |
| `subtitle_font_size` | 字幕の文字サイズ（デフォルト: 48） |
| `subtitle_color` | 字幕の文字色（デフォルト: "#FFFFFF"） |
| `subtitle_stroke_color` | 字幕の縁取り色（デフォルト: "#000000"） |
| `subtitle_stroke_width` | 字幕の縁取り幅（デフォルト: 2） |
| `subtitle_line_interval` | 複数行字幕を表示する際、行と行の間の待ち時間（秒） |
| `teletext_font_size` | テロップの文字サイズ（デフォルト: 60） |
| `teletext_color` | テロップの文字色（デフォルト: "#FFE066"） |
| `teletext_stroke_color` | テロップの縁取り色（デフォルト: "#222222"） |
| `teletext_stroke_width` | テロップの縁取り幅（デフォルト: 3） |
| `voice_volume` | ナレーション音量（デフォルト: 1.0、0.0～2.0の範囲） |
| `voice_margin_before` | 音声の前の無音時間（秒） |
| `voice_margin_after` | 音声の後の無音時間（秒） |

---

## YAMLスクリプトの作成

動画の仕様とシーン情報を記述したYAMLファイルを作成します。

### 基本構造

```yaml
video:
  width: 1920
  height: 1080
  fps: 30
  bgm: assets/bgm/background.mp3  # BGMファイル（省略可）
  voice: narrator_female           # デフォルトの音声
  output_file: dist/my_video.mp4   # 出力ファイル名（省略可）
  subtitle:
    font: assets/fonts/msgothic.ttc
    position: bottom               # top または bottom
    style:
      fill: "#FFFFFF"              # 文字色
      stroke: "#000000"            # 縁取り色
      font_size: 48                # 文字サイズ（省略可）
      stroke_width: 2              # 縁取り幅（省略可）
      padding: 32                  # パディング（ピクセル）

scenes:
  - id: scene1
    image: assets/images/photo1.jpg
    # または video: assets/videos/movie1.mp4
    duration: 6                    # シーン長（秒）
    voiceover: >
      ここに読み上げるテキストを記述します。
    subtitle: ここに字幕テキストを記述
    teletext:                      # テロップ（省略可）
      text: タイトルテキスト
      position: top_left           # top_left, top_right, bottom_left, bottom_right, center
      style:
        fill: "#FFE066"
        stroke: "#222222"
        font_size: 60              # 文字サイズ（省略可）
        stroke_width: 3            # 縁取り幅（省略可）
    transition: cut                # cut または crossfade
    voice_override:                # シーン固有の音声設定（省略可）
      voice: narrator_male
      speed: 0.95
      pitch: 1.0
      volume: 0.8                  # 音量（1.0が100%）

options:
  voice_cache_dir: .cache/voice  # 音声キャッシュディレクトリ
  subtitle_format: burn          # burn または srt
  keep_temp: false               # 一時ファイルを保持するか
  workers: 1                     # 並列処理のワーカー数
```

### シーン設定の詳細

#### 必須項目

- `id`: シーンの一意な識別子
- `image` または `video`: 画像ファイルまたは動画ファイルのパス
- `duration`: シーンの長さ（秒）。`video`の場合は省略可能（動画の長さに合わせる場合）
- `voiceover`: 読み上げるテキスト

#### 省略可能な項目

- `subtitle`: 画面に表示する字幕テキスト（省略時は`voiceover`を表示、空文字列で非表示）
- `teletext`: テロップ設定
- `transition`: 次のシーンへの遷移効果（`cut`または`crossfade`）
- `voice_override`: シーン固有の音声設定

### 字幕とテロップの違い

| 項目 | 字幕 | テロップ |
|------|------|----------|
| 用途 | 音声の文字起こし | タイトルや補足情報 |
| 位置 | 上部または下部（中央揃え） | 5箇所から選択可能 |
| デフォルト表示 | `subtitle`省略時は`voiceover`を表示 | 設定した場合のみ表示 |
| スタイル | `config.yaml`または`video.subtitle.style`で設定 | `config.yaml`またはシーン毎に個別設定 |

---

## コマンドの使い方

### 1. スクリプトの検証

YAMLスクリプトの構文、ファイルの存在、Voiceboxの疎通を確認します。

```bash
videomaker validate story.yaml
```

オプション：

```bash
videomaker validate story.yaml --config custom_config.yaml --voice-cache .cache/custom
```

### 2. 動画のレンダリング

YAMLスクリプトから動画を生成します。

```bash
videomaker render story.yaml --out dist/output.mp4
```

#### 出力ファイル名の自動決定

`--out`オプションを省略した場合、出力ファイル名は以下の優先順位で決定されます：

1. **スクリプト内の`output_file`指定**（最優先）
2. **スクリプトファイル名から自動生成**（例: `story.yaml` → `dist/story.mp4`）

```yaml
# story.yaml
video:
  output_file: dist/my_video.mp4  # この名前で出力される
```

```bash
# --outオプションなしでレンダリング
videomaker render story.yaml
# → スクリプト内のoutput_file指定がある場合: dist/my_video.mp4
# → 指定がない場合: dist/story.mp4（スクリプト名から自動生成）

# --outオプション指定時は常にそちらが優先
videomaker render story.yaml --out dist/custom.mp4
# → dist/custom.mp4
```

#### 特定のシーンのみをレンダリング

```bash
videomaker render story.yaml --out dist/scene1.mp4 --scene scene1 --scene scene2
```

#### その他のオプション

```bash
videomaker render story.yaml \
  --out dist/output.mp4 \
  --config config.yaml \
  --voice-cache .cache/voice \
  --scene intro --scene ending
```

### 3. プレビュー作成

特定のシーンのみを素早くプレビューします。

```bash
videomaker preview story.yaml --scene intro --out dist/preview.mp4
```

---

## 詳細な機能説明

### 音声合成とキャッシュ

- 音声は`voiceover`フィールドのテキストから自動生成されます
- 生成された音声は`.cache/voice`（デフォルト）にキャッシュされます
- 同じテキストは再利用されるため、2回目以降は高速です

### 話者の設定

#### グローバル設定（全シーンに適用）

```yaml
video:
  voice: narrator_female
```

#### シーン毎の上書き

```yaml
scenes:
  - id: scene1
    voice_override:
      voice: narrator_male
      speed: 0.95   # 読み上げ速度（1.0が標準）
      pitch: 1.0    # ピッチ（1.0が標準）
      volume: 0.8   # 音量（1.0が100%、0.0～2.0の範囲）
```

### ナレーション音量の調整

ナレーションの音量は3つの方法で設定できます（優先順位順）：

1. **シーン個別の設定**（最優先）
2. **config.yamlのデフォルト設定**
3. **ハードコードされた値（1.0）**

```yaml
# config.yaml（プロジェクト全体のデフォルト）
voice_volume: 0.9  # 全体的に少し小さめに

# story.yaml（シーン毎の上書き）
scenes:
  - id: scene1
    voiceover: 通常の音量のナレーション
    # config.yamlの0.9を使用

  - id: scene2
    voiceover: 小さめの音量のナレーション
    voice_override:
      volume: 0.6  # このシーンだけ60%に
```

**音量の目安:**
- `1.0`: 100%（標準）
- `0.8`: 80%（少し小さめ）
- `0.5`: 50%（半分の音量）
- `1.5`: 150%（1.5倍の音量）

### 字幕の表示

各シーンの`subtitle`フィールドに文字列を指定すると、画面に字幕が表示されます。

#### 字幕の自動表示

- `subtitle`を**省略**した場合: `voiceover`の内容が自動的に字幕として表示されます
- `subtitle`に**値を指定**した場合: 指定した内容が字幕として表示されます
- `subtitle: ""`（**空文字列**）の場合: 字幕は表示されません

```yaml
scenes:
  - id: scene1
    voiceover: これは音声テキストです
    # subtitle省略 → voiceoverが字幕として表示される

  - id: scene2
    voiceover: これは音声テキストです
    subtitle: カスタム字幕テキスト  # 指定した内容が表示される

  - id: scene3
    voiceover: これは音声テキストです
    subtitle: ""  # 字幕を表示しない
```

#### 字幕のスタイル設定

字幕のスタイルは3つの方法で設定できます（優先順位順）：

1. **シーン毎の個別設定**（最優先）
2. **config.yamlのデフォルト設定**
3. **ハードコードされた値**

```yaml
# config.yaml（プロジェクト全体のデフォルト）
subtitle_font_size: 48
subtitle_color: "#FFFFFF"
subtitle_stroke_color: "#000000"
subtitle_stroke_width: 2

# story.yaml
video:
  subtitle:
    font: assets/fonts/msgothic.ttc
    position: bottom  # top または bottom
    style:
      fill: "#FFFFFF"       # 文字色
      stroke: "#000000"     # 縁取り色
      font_size: 52         # このシーンだけ大きく
      stroke_width: 3       # 縁取りも太く
      padding: 32           # パディング
```

### テロップの表示

各シーンに`teletext`フィールドを追加すると、画面上の任意の位置にテキストを表示できます。

#### テロップのスタイル設定

テロップのスタイルも3つの方法で設定できます（優先順位順）：

1. **シーン毎の個別設定**（最優先）
2. **config.yamlのデフォルト設定**
3. **ハードコードされた値**

```yaml
# config.yaml（プロジェクト全体のデフォルト）
teletext_font_size: 60
teletext_color: "#FFE066"
teletext_stroke_color: "#222222"
teletext_stroke_width: 3

# story.yaml
scenes:
  - id: scene1
    teletext:
      text: タイトル文字
      position: top_left  # top_left, top_right, bottom_left, bottom_right, center
      style:
        fill: "#FFE066"
        stroke: "#222222"
        font_size: 72        # このシーンだけ大きく
        stroke_width: 4      # 縁取りも太く

### 動画シーンの使用

静止画の代わりに動画ファイルを使用することもできます。

```yaml
scenes:
  - id: movie_scene
    video: assets/videos/clip.mp4
    duration: 10  # 10秒間にトリミング、またはループ（ループは未実装、現在はカットのみ）
    voiceover: 動画のシーンです
```

- `duration`を指定すると、その長さに合わせて動画がカット（または延長）されます。
- `duration`を省略すると、読み上げる音声の長さに自動的に合わせられません（音声の方が長い場合は動画が静止画として延長される動作になる可能性がありますが、現在はシーン長を明示するか、動画の長さを基準にするか注意が必要です）。
    - **補足**: `video`を指定し`duration`を指定した場合、動画が指定時間より長ければカットされ、短ければその長さになります（config.pyの実装に依存）。

### 複数行テキストの扱い

#### 字幕（Subtitle）
字幕テキストに改行が含まれる場合、**1行ずつ順番に**表示されます。
`config.yaml`の`subtitle_line_interval`で行間の待ち時間を指定できます。

```yaml
# config.yaml
subtitle_line_interval: 0.5
```

例：
```
1行目のテキスト
（0.5秒待機）
2行目のテキスト
```
シーン全体の時間から行間時間を引いた残りの時間を、各行に等分して割り当てます。

#### テロップ（Teletext）
テロップテキストに改行が含まれる場合、**全ての行が同時に（スタックして）**表示されます。

```yaml
teletext:
  text: |
    上の行
    下の行
  position: center
```

```

### BGMの追加

```yaml
video:
  bgm: assets/bgm/background.mp3
```

BGMは動画全体の長さに合わせて自動調整され、ボリュームは40%に設定されます。
BGMが動画より短い場合は、動画の終わりまで自動的に繰り返し再生されます。

### Voiceboxのタイムアウト

長い文章の合成でタイムアウトする場合は、`config.yaml`の`voicebox_timeout`（秒、デフォルト30）を大きくしてください。

```yaml
# config.yaml
voicebox_timeout: 120
```

### 読み間違いの訂正（読み替え辞書）

VOICEVOXなどが漢字を誤読する場合、`config.yaml`の`voicebox_reading_map`で音声合成に渡す前の文字列を置き換えられます。
字幕・テロップの表示はそのまま（漢字のまま）です。

```yaml
# config.yaml
voicebox_reading_map:
  方: かた
  方法: ほうほう   # 長い語が優先して置換されるため「方法」は「かた法」になりません
```

- 単純な文字列置換のため、「方」を登録すると「両方」「夕方」なども置換されます。必要に応じて「両方: りょうほう」のように長い語も登録してください。
- 読み替え後のテキストで音声キャッシュが作られるため、辞書を変更すると該当音声は自動的に再生成されます。

### トランジション効果

シーン間の遷移効果を指定できます。

```yaml
scenes:
  - id: scene1
    transition: cut        # カット（デフォルト）
  - id: scene2
    transition: crossfade  # クロスフェード
```

### デフォルトフォントとフォールバック

`config.yaml`で`default_font`を設定しておくと、フォントが見つからない場合に自動的に使用されます。

```yaml
# config.yaml
default_font: assets/fonts/msgothic.ttc
```

**動作:**
1. `story.yaml`の`video.subtitle.font`が存在する場合はそれを使用
2. 見つからない場合は`config.yaml`の`default_font`を使用
3. どちらもない場合はシステムフォントを使用

これにより、フォント設定を一元管理でき、YAMLスクリプトでフォント指定を省略できます。

### 画像ファイルの自動検索

`config.yaml`で`image_dir`を設定しておくと、画像ファイルが見つからない場合に自動的に検索されます。

```yaml
# config.yaml
image_dir: assets/images
```

**動作:**
1. `story.yaml`で指定されたパスが存在する場合はそれを使用
2. 見つからない場合は`image_dir`からファイル名で検索
3. 見つかった場合、自動的にそのパスを使用

```yaml
# story.yaml
scenes:
  - id: intro
    image: DSC00052.JPG  # フルパス不要、ファイル名のみでOK
```

上記の例では、`assets/images/DSC00052.JPG`が自動的に検索されます。

### スタイル設定の優先順位

字幕とテロップのスタイル設定には優先順位があります：

**優先順位（高→低）:**
1. **シーン個別のstyle設定**（`story.yaml`の各シーン）
2. **config.yamlのデフォルト設定**
3. **ハードコードされた値**

**例:**

```yaml
# config.yaml
subtitle_font_size: 48
teletext_font_size: 60

# story.yaml
video:
  subtitle:
    style:
      font_size: 52  # config.yamlの48を上書き

scenes:
  - id: scene1
    subtitle: 通常の字幕  # font_size: 52 を使用

  - id: scene2
    teletext:
      text: 特別なテロップ
      style:
        font_size: 80  # このシーンだけ80
```

---

## トラブルシューティング

### エラー: 素材チェックに失敗しました

**原因**: 画像ファイルやフォントファイルが見つかりません。

**解決策**:
1. YAMLスクリプトのパスが正しいか確認
2. 相対パスはYAMLファイルからの相対位置で記述
3. ファイルが実際に存在するか確認

### エラー: Voiceboxヘルスチェックに失敗しました

**原因**: VOICEVOXサーバーが起動していないか、URLが間違っています。

**解決策**:
1. VOICEVOXを起動（デフォルトは`http://127.0.0.1:50021`）
2. `config.yaml`の`voicebox_url`を確認
3. ブラウザで`http://127.0.0.1:50021/speakers`にアクセスして確認

### エラー: voicevoxモードではvoice(話者ID)が必要です

**原因**: VOICEVOXモードで音声が未設定です。

**解決策**:
1. `config.yaml`に`voicebox_voice_map`を追加
2. または`story.yaml`の`video.voice`に話者IDを設定

```yaml
# config.yaml
voicebox_voice_map:
  narrator_female: "3"
  narrator_male: "1"
```

### エラー: AttributeError: 'ImageClip' object has no attribute 'set_duration'

**原因**: MoviePyのバージョンが2.x系です。

**解決策**: このエラーは修正済みです。最新のコードを使用してください。

### 字幕やテロップが表示されない

**原因**: フォントファイルが見つからないか、TextClipの作成に失敗しています。

**解決策**:
1. フォントファイルのパスを確認
2. `config.yaml`に`default_font`を設定
3. ログに`[yellow]字幕の作成に失敗しました`というメッセージがないか確認
4. ImageMagickがインストールされているか確認（MoviePyのTextClipに必要）

### 画像ファイルが見つからない

**原因**: 画像ファイルのパスが間違っています。

**解決策**:
1. `config.yaml`に`image_dir`を設定
2. 画像ファイル名だけを`story.yaml`に記述
3. `image_dir`に画像ファイルを配置

```yaml
# config.yaml
image_dir: assets/images

# story.yaml
scenes:
  - id: intro
    image: photo.jpg  # assets/images/photo.jpg が自動検索される
```

### 字幕のサイズや色を変更したい

**原因**: デフォルト設定を使用しています。

**解決策**:
1. プロジェクト全体を変更する場合は`config.yaml`を編集
2. 特定のシーンだけ変更する場合は`story.yaml`の`style`を編集

```yaml
# config.yaml（全体）
subtitle_font_size: 52
subtitle_stroke_width: 3

# story.yaml（個別シーン）
video:
  subtitle:
    style:
      font_size: 60  # この動画全体
      stroke_width: 4

scenes:
  - id: special
    subtitle: 特別な字幕
    # このシーンでは video.subtitle.style が適用される
```

### ナレーション音量が大きすぎる/小さすぎる

**原因**: デフォルトの音量（100%）を使用しています。

**解決策**:
1. プロジェクト全体を変更する場合は`config.yaml`を編集
2. 特定のシーンだけ変更する場合は`story.yaml`の`voice_override`を使用

```yaml
# config.yaml（全体）
voice_volume: 0.8  # 全体的に80%に

# story.yaml（個別シーン）
scenes:
  - id: loud_scene
    voiceover: 大きめの音声
    voice_override:
      volume: 1.2  # このシーンだけ120%に
```

---

## サンプルファイル

プロジェクトには以下のサンプルが含まれています：

- `story.yaml`: 実際に動作するサンプルスクリプト
- `samples/story.yaml`: 追加のサンプルスクリプト
- `config.example.yaml`: 設定ファイルのサンプル

---

## 参考情報

### 推奨する話者ID（VOICEVOX）

| 話者名 | ID |
|--------|-----|
| 四国めたん（ノーマル） | 2 |
| ずんだもん（ノーマル） | 3 |
| 春日部つむぎ（ノーマル） | 8 |

話者一覧は`http://127.0.0.1:50021/speakers`で確認できます。

### ファイル構成の推奨

```
project/
├── config.yaml          # 設定ファイル
├── story.yaml           # YAMLスクリプト
├── assets/
│   ├── images/          # 画像ファイル
│   ├── fonts/           # フォントファイル
│   └── bgm/             # BGMファイル
├── dist/                # 出力先
└── .cache/
    └── voice/           # 音声キャッシュ
```

---

## まとめ

VideoMakerを使えば、YAMLスクリプトから簡単に動画を作成できます。

### 基本的な使い方

1. `config.yaml`でVOICEVOXとデフォルト設定を行う
2. `story.yaml`でシーンと字幕・テロップを記述
3. `videomaker render`で動画を生成

### 便利な機能

- **画像ファイル名だけ指定**: `image_dir`設定で自動検索
- **フォント設定の簡略化**: `default_font`設定でフォールバック
- **字幕の自動表示**: `subtitle`省略時は`voiceover`を表示
- **スタイルの柔軟な設定**: プロジェクト全体/動画/シーン単位で設定可能
- **音量の個別調整**: シーン毎にナレーション音量を調整可能

詳しくは[README.md](../README.md)も参照してください。
