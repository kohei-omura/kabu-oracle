# 株オラクル — Kabu Oracle 📈

日本株を毎日スクリーニングして、**LINE/メール通知**と**スマホ用ダッシュボード**に出す個人用ツール。
サーバー不要で、**GitHub Actions だけ**で動きます。

📱 **ダッシュボード** → https://kohei-omura.github.io/kabu-oracle/

| できること | 中身 |
|---|---|
| 買い候補ランキング | 全上場銘柄（約3,700）をテクニカル×ファンダで採点し TOP10 を通知・表示 |
| 保有アラート | `holdings.txt` の銘柄を場中20分おきに監視し、利確/損切ライン到達と売りシグナル転換を通知 |
| 長期保有モード | 画面のボタンでON。利確通知を止め、長期の目安株価（1年後/3年後/5年後）を表示 |
| テンバガー候補 | 小型・高成長・高収益の条件への適合度で TOP10 を表示 |
| 銘柄サーチ | 画面でコード/銘柄名を検索。★でウォッチリスト（端末内保存） |

> ⚠️ 自分用の分析補助であり、投資助言ではありません。株価は約15〜20分遅延（yfinance）。判断は自己責任で。

---

## ファイル

| 場所 | 役割 |
|---|---|
| `main.py` | 入口。`rank` / `watch` / `report` / `prices` / `holdings` / `analyze` |
| `config.yaml` | 設定（ユニバース・市場区分・閾値・ファンダ設定） |
| `holdings.txt` | **保有銘柄**（自分で編集。1行 `コード,買値[,利確,損切][,長期]`） |
| `watchlist.txt` | 場中push通知したい銘柄（1行1コード） |
| `kabu/` | ロジック一式（下表） |
| `data/` | 銘柄マスタ（`universe_all.csv`）と通知の重複防止状態 |
| `docs/` | 公開ダッシュボード（**自動生成**。手で触らない） |
| `.github/workflows/` | 定期実行の設定 |

<details>
<summary><code>kabu/</code> の中身</summary>

| ファイル | 役割 |
|---|---|
| `config.py` | 設定・銘柄リスト・保有リストの読込 |
| `data.py` | 株価取得（yfinance） |
| `indicators.py` | テクニカル指標（EMA / RSI / MACD / ボリンジャー / ATR） |
| `signals.py` | スコアリング・売買シグナル・利確損切ライン・勝率試算 |
| `ranking.py` | ユニバース全体の採点と、財務を掛け合わせた複合ランキング |
| `jquants.py` | J-Quants API から財務データ取得 |
| `report.py` | ダッシュボード生成・株価更新・保有アラート |
| `watch.py` | 監視銘柄のタイミング検知 |
| `notify.py` | LINE / メール送信 |
| `backtest.py` | 簡易バックテスト（`python -m kabu.backtest 7203`） |

</details>

---

## 保有銘柄の登録（`holdings.txt`）

```
7803,290              ← 買値だけ。利確/損切はATRから自動計算
7203,2800,3100,2600   ← 利確3100・損切2600を手動指定
3176,1000,長期        ← 長期保有＝利確通知OFF（損切・売りシグナルは通知）
```

到達アラートは**同じ内容なら1日1回**だけ届きます（`data/holdings_state.json` で管理）。

### 長期保有ボタン

ダッシュボードの保有カードにある `☾ 長期保有` を押すと、`holdings.txt` に「長期」が付いて
**利確通知が止まり**、代わりに**長期保有の目安株価**が表示されます。

初回だけ「保有銘柄」見出しの **⚙** からGitHubトークンを登録してください（端末のブラウザにのみ保存）。

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
2. Repository access: **Only select repositories** → このリポジトリだけ
3. Permissions → Repository permissions → **Contents: Read and write**

---

## 判定のしくみ

**スコア（-100〜+100）** … 5ファクターの重み付き合計。
トレンド30% / モメンタム25% / 相対力20% / 平均回帰15% / 出来高10%

**シグナル** … スコア＋25以上で「きっかけ」（ゴールデンクロス・RSI回復・下バンド反発）が
出たら BUY、-25以下で逆が出たら SELL。それ以外は HOLD。

**利確/損切** … ATR(14)基準。利確＝+ATR×3.0、損切＝-ATR×2.0（`config.yaml` で調整可）。
値幅制限を超える指値は自動でクランプ。

**複合スコア** … J-Quants の財務（PER/PBR/ROE/自己資本比率/配当利回り/増益率）を
候補内で順位正規化し、テクニカルと半々で合成。

**理論株価** … 株マップ式（資産価値＋利益価値＋成長価値）・PER基準・ROE基準の3方式。
2方式以上で割安なら「✅購入検討」。

**長期保有の目安** … 年成長率 g＝min(増益率, ROE×(1−配当性向), 15%) として
現値×(1+g)ⁿ を1/3/5年後に表示。理論株価3方式の中央値を長期目標、到達目安年数も算出。

---

## 自動実行

| ワークフロー | JST | 内容 |
|---|---|---|
| `daily-ranking` | 平日 16:30 | 買い候補ランキングを通知（1日1通） |
| `dashboard` | 平日 7:35 / 11:00 / 14:30 / 16:30 | ダッシュボード再生成 |
| `prices` | 平日 9:00〜15:40 の20分毎 | 表示中の株価を更新 |
| `holdings` | 平日 9:00〜15:40 の20分毎 | 保有アラート |
| `intraday-watch` | 平日 9:00〜15:30 の30分毎 | 監視銘柄のタイミング通知 |

Actions タブから手動実行（Run workflow）も可。cron は GitHub 側の混雑で遅延することがあります。

### Secrets（Settings → Secrets and variables → Actions）

| 名前 | 用途 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` | LINE Messaging API のpush通知 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` | メール通知 |
| `JQUANTS_API_KEY` | J-Quants の財務データ（無しならテクニカルのみで動作） |

---

## 手元で動かす

```bash
pip install -r requirements.txt

python main.py analyze 7203     # 1銘柄を即分析
python main.py rank             # ランキングを算出して通知
python main.py report           # docs/ のダッシュボードを生成
python main.py holdings         # 保有アラートの判定
python -m kabu.backtest 7203    # 簡易バックテスト
```
