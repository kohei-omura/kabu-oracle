# 株オラクル（kabu-oracle）

自分専用の日本株シグナル＆通知ツール。**サーバー不要・GitHub Actions のみ**で動きます。

- 📊 毎朝、ユニバースから「買い候補 / 売り候補」を Top-5 ランキングで通知
- ⏰ 監視銘柄（watchlist）の売買タイミングを場中に検知し、サインが出た時だけ LINE / メール通知
- 🔎 任意の証券コードをその場で分析（エントリー・利確・損切りの目安つき）
- 🧪 バックテストでシグナルの妥当性を検証可能

> ⚠️ これは**自分用の分析補助ツール**です。投資助言ではありません。最終判断は自己責任で行ってください。

---

## 仕組み（スコアリング）

5つのファクターを重み付き合成し、-100〜+100 のスコアを算出します。

| ファクター | 重み | 内容 |
|---|---|---|
| トレンド | 30% | EMA25/EMA75 の配列・傾き |
| モメンタム | 25% | MACD ヒストグラム・RSI |
| 平均回帰 | 15% | ボリンジャー %B（押し目/戻り） |
| 出来高 | 10% | 20日平均比＋騰落方向 |
| 相対力 | 20% | 日経平均（^N225）に対する20日相対パフォーマンス |

**売買サイン**は「スコアが十分」かつ「きっかけ（ゴールデン/デッドクロス、RSIの反転、バンド反発）」が揃った時のみ発火。過熱時は見送る保守設計です。エントリー/損切り/利確は ATR ベースで自動算出します。

---

## セットアップ（5ステップ）

### 1. リポジトリを作って push
```bash
git init && git add . && git commit -m "init"
git remote add origin https://github.com/<あなた>/kabu-oracle.git
git push -u origin main
```

### 2. LINE 通知の準備（Messaging API）
LINE Notify は 2025/3/31 終了済みのため後継の Messaging API を使います。
1. [LINE Developers](https://developers.line.biz/) → 新規プロバイダー＆**Messaging API チャネル**を作成
2. 「チャネルアクセストークン（長期）」を発行 → `LINE_CHANNEL_ACCESS_TOKEN`
3. 作成した公式アカウントを自分のLINEで**友だち追加**
4. 自分の `userId`（U から始まる文字列）を取得 → `LINE_USER_ID`
   （Webhook か、プロフィール取得APIで確認できます）

### 3. メール通知の準備（任意）
Gmail なら「アプリパスワード」を発行して使用。
- `SMTP_HOST=smtp.gmail.com` / `SMTP_PORT=465` / `SMTP_USER=自分のアドレス` / `SMTP_PASS=アプリパスワード` / `MAIL_TO=送信先`

### 4. GitHub Secrets を登録
リポジトリ → Settings → Secrets and variables → Actions → New repository secret

| Secret 名 | 内容 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE チャネルトークン |
| `LINE_USER_ID` | 自分の userId |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` | メール設定（任意） |

### 5. Actions を有効化
リポジトリの **Actions** タブで有効化。`workflow_dispatch` で手動実行して通知が届くか確認。

---

## 設定（config.yaml）
`config.example.yaml` を編集します（GitHub Actions では自動でコピーされます）。
ローカルで使う場合は `cp config.example.yaml config.yaml`。

- `watchlist`: タイミング監視する証券コード
- `universe_file`: ランキング対象（`universe/nikkei_majors.csv` を編集／差し替え）
- `top_n`: ランキング件数
- `thresholds`: RSI 閾値・ATR の損切り/利確倍率

---

## ローカル実行
```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml

python -m src.main analyze 7203     # 単一銘柄を即時分析
python -m src.main rank             # ランキング（通知も実行）
python -m src.main watch            # 監視銘柄チェック（サイン時のみ通知）
python -m src.main watch --status   # 監視銘柄の現況を必ず表示
python -m src.backtest 7203 6758    # バックテスト
```

---

## 自動実行スケジュール
| ワークフロー | タイミング(JST) | 動作 |
|---|---|---|
| `daily-ranking` | 平日 07:30 | 買い/売り Top-5 を通知 |
| `intraday-watch` | 平日 09:00–15:30 の30分毎 | 監視銘柄のサインを検知して通知 |
| `dashboard` | 平日 07:35 ＆ 場中30分毎 | Web ダッシュボードを更新 |

---

## 📱 Web ダッシュボード（GitHub Pages）
スマホ・PCのブラウザで最新ランキングを見られる画面です。`dashboard` ワークフローが
`docs/index.html` を自動生成・コミットし、GitHub Pages が配信します。

**有効化（初回のみ）**
1. リポジトリ → **Settings → Pages**
2. 「Build and deployment」→ Source = **Deploy from a branch**
3. Branch = **main** / フォルダ = **/docs** → Save
4. Actions タブで `dashboard` を一度 **Run workflow**（または `python -m src.main report` をローカル実行して docs/ を push）
5. 数分後、`https://<あなた>.github.io/kabu-oracle/` で表示

> このページは静的HTMLで、データは生成時に埋め込まれます（サーバー不要）。
> このアプリには対話的な「アプリ画面」はなく、確認手段は ①通知 ②このダッシュボード ③Actions のログ の3つです。

---

## ⚠️ 注意・免責
- **株価データは約15〜20分遅延**（yfinance 無料）。スイング向けで、デイトレ用ではありません。
- **GitHub の無料 cron は数分の遅延やスキップがあり得ます。** 「遅延ゼロ」が必須なら VPS（さくら/ConoHa 等）＋常駐スクリプトへ移行を検討してください（コードはそのまま流用可）。
- **リポジトリが60日間無活動だと scheduled workflow は自動停止**します。
- シグナルは確率的な補助であり、**利益を保証しません**。過去のバックテスト成績は将来を保証しません。手数料・スリッページは未考慮です。
- これは投資助言ではなく、自分用の分析補助です。投資判断は自己責任で。
