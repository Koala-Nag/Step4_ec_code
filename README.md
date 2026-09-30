# 開発環境の立ち上げと、設計の検証

## 0. いちばん簡単な立ち上げかた（Windows）

**`ec` フォルダの `start.bat` をダブルクリックする。** これだけ。

```
start.bat   → MySQL を起動 → ダミー決済API（:8010）→ バックエンド（:8000）
              → フロント（:3000）→ ブラウザを開く
stop.bat    → MySQL を止める（データは残る）
seed.bat    → 初期データ 01〜06 を流す（★まっさらな状態に対して）
```

**開くのは `http://localhost:3000/products`。** 商品一覧が出る。

| | |
|---|---|
| **黒い画面が2つ出る** | **消さない。** 片方がバックエンド、片方がフロント。**閉じるとアプリが止まる** |
| **初回は少し待つ** | フロントは最初の1回だけコンパイルする。**12秒待ってからブラウザを開く**ようにしてある |
| **画面が真っ白／エラー** | 黒い画面のほうにエラーが出ている。**そこを見る** |

**★止めるとき**｜黒い画面2つを閉じる → `stop.bat`。**`stop.bat` だけではアプリは止まらない**（MySQL しか止めない）。

### うまくいかないとき

| 出るもの | 直しかた |
|---|---|
| `docker compose failed` | **Docker Desktop が起動していない。** 起動してから、もう一度 `start.bat` |
| `backend\.venv not found` | `python -m venv backend\.venv` → `backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt` |
| `frontend\node_modules not found` | `npm --prefix frontend install` |
| 一覧が全部「品切れ」 | **在庫の初期データが入っていない。** `seed.bat` を流す（`06_demo_stock.sql` が在庫を入れる） |
| 画像が出ない | `.env` の `IMAGE_BASE_URL` を確認（既定は `http://localhost:8000/assets`） |
| `seed` が `ERROR 1062 Duplicate entry` で落ちる | **★これは正しい挙動。** `seed` は「まっさらから作る」道具で、「足す」道具ではない（設計 10.3a）。**入れ直したいときは `docker compose down -v` → `start.bat` → `seed.bat`**（30秒）。★`INSERT IGNORE` にしない——**手元だけにあるデータで試験が通る状態**が作れてしまうため |
| `決済代行を呼べません` | **ダミー決済API（:8010）が動いていない。** `start.bat` は3つのウィンドウを開く。★`mock-gateway` のウィンドウを閉じていないか |

### 手で立ち上げる場合

**3つを別々のウィンドウで動かす。**

```
# ① MySQL（ec フォルダで）
docker compose up -d --wait

# ② バックエンド（ec\backend フォルダで）
.venv\Scripts\python.exe -m uvicorn main:app --port 8000 --reload

# ③ フロント（ec\frontend フォルダで）
npm run dev
```

**②と③は動かしっぱなしにする。** ウィンドウを閉じると止まる。

---

## 1. Docker Desktop を入れる

Windows なら WSL2 が要る。インストーラが誘導してくれる。

## 2. データベースを立ち上げる

このフォルダで、

```
docker compose up -d
```

**初回は1〜2分かかる**（MySQL のイメージを取ってくるため）。
`db/ddl/` の中身は起動時に自動で流れる（**46テーブル**）。

**準備完了かどうかは、テーブル数で判定する。**

```
docker compose exec -T db mysql -uroot -plocalonly -N -B ec   -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ec';"
```

**46 が返れば準備完了。**

> **`docker compose ps` が `healthy` でも、準備完了とはかぎらない。**
> MySQL の初期化は**仮のサーバ**を立てて `db/ddl/` を流し、**流し終えてから仮のサーバを止めて本番のサーバを起動する。**
> 仮のサーバは**ソケットだけ**で待ち受けるので、`mysqladmin ping -h localhost` は**DDL の途中で通ってしまう。**
> 実際に、テーブルが19個の時点で `healthy` になり、そのあと一時的に**接続できなくなる**ことを確認した（2026-09-03）。
>
> **対策として `healthcheck` を TCP 経由（`-h 127.0.0.1`）に変えてある。**
> 仮のサーバは TCP を開かない（ログ上 `port: 0`）ため、**この形なら `healthy` は本番のサーバが上がったことを意味する。**
> 変更後に3回作り直して、3回とも `healthy` の時点で46テーブルがそろっていることを確認した。

## 2a. 既存のDBを新しい設計に追いつかせる（作り直さない場合）

**すでにデータが入っていて消したくないときは、`db/migrations/` を順に流す。**

```
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/migrations/001_catch_up_to_design_v01.sql
```

**`db/ddl/` は「いま何があるか」の正、`db/migrations/` は「前の版からどう動かすか」。**
どちらの経路を通っても同じ形になる（`mysqldump --no-data` の差分がゼロであることを確認済み）。

## 3. 初期データを入れる

```
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/seed/01_prefecture.sql
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/seed/02_master.sql
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/seed/03_demo.sql
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/seed/04_product.sql
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/seed/05_product_image.sql
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/seed/06_demo_stock.sql
```

**入る量**｜商品52件・SKU 887件・商品画像208行・**在庫（42商品ぶん）**。★`P0051`（2,500円）と `P0052`（2,499円）は**送料無料の境目（5,000円／4,999円）をクーポン無しで作るための商品**（要件定義書 6.4・R-26）。倉庫 W001 に20点ずつ、店舗 T003 に3点ずつ必ず置く（再引当を画面で確かめるため）。

**★`06_demo_stock.sql` は画面のためのもの**（2026-09-05）。`04`・`05` は在庫を入れないので、**そのままだと一覧が全部「品切れ」になり、2値も3値も片側しか見られない。** 倉庫（W001）のバックヤードにだけ置き、**`P0001`・`P0002` には触っていない**ので、引当の検証（検証1〜13）に回帰はない。

**`04` と `05` は `INSERT IGNORE`。** `03_demo.sql` が入れる P0001・P0002 とその4SKUに重ねて流せる。

## 3a. 商品画像

**画像の実体は `assets/products/` にある**（まずはプレースホルダ200枚）。

```
python tools/make_placeholder.py        # 200枚を作る。既にあるものは触らない
python tools/import_images.py           # incoming/ の実物を規約名で products/ へ上書き
```

**`product_image.url` は相対パス**（`products/P0001_BK_1.jpg`）。**表示するときに `IMAGE_BASE_URL` を頭に付ける**（`.env.example` 参照）。
**ファイル名が規約で固定されているので、実物への差し替えでDBは1行も変わらない**（商品画像の仕様 8.1）。

## 4. 設計の検証を流す

```
docker compose exec -T db mysql -uroot -plocalonly ec_koala < db/verify.sql
```

**確認すること**

| 検証 | 期待する結果 |
|---|---|
| 1 | 在庫数2・引当済数7 の行ができる（これが通常運用で残る状態） |
| 2 | コメントを外して1回流すと **ERROR 1690** が出る。**出るのが正しい** |
| 3 | 引き算をしない読み方なら **0** が返る |
| 4 | **T003 → T004 → W001 → T001** の順に並ぶ。T002 は出ない |
| 5 | **W001 のみ**（T003 は除外テーブルにあるので出ない） |
| 6 | 引当1 → 解放1 → もう一度解放0。**3手目が0件で、かつエラーにならない**（3.2.4） |

## 5. 同時実行の検証

```
bash db/verify_concurrent.sh
```

**期待**：片方の更新件数が 1、もう片方が 0。`reserved_qty` は 1 で止まる。

Windows で bash が無ければ、Git Bash か WSL から実行する。

## 6. 止める・消す

```
docker compose down        # 止めるだけ。データは残る
docker compose down -v     # データごと消す。作り直したいとき
```

---

## この検証で何を確かめているか

**設計仕様書 3.2.2 ①** で決めた「SQLで引き算をしない」が、本当に必要だったかを確かめる。

MySQL は `INT UNSIGNED` 同士の引き算が負になると、0を返さず **エラーで止まる**。
`WHERE 在庫数 - 引当済数 >= n` と書くと、**「更新件数0で失敗」ではなく例外**になり、
9.4 の先勝ち判定そのものが成立しない。

**検証2でエラーが出れば、この判断が正しかったことの証拠になる。**

## ファイルの位置づけ

| ファイル | 何か |
|---|---|
| `db/ddl/*.sql` | **テーブル定義の正（47テーブル）。** 設計仕様書はここを指している |
| `db/migrations/*.sql` | **前の版からどう動かすか。** 既存のDBを消さずに追いつかせる |
| `db/seed/*.sql` | 初期データ（N-16）。`01`〜`06` を順に流す |
| `start.bat` / `stop.bat` / `seed.bat` | **Windows 用の立ち上げ・停止・初期データ**（0章） |
| `backend/` | FastAPI。`api/`（AP-xx）・`domain/`（判断）・`repository/`（DB）。設計 2.2 |
| `frontend/` | Next.js。`app/products/`（SCR-02・03）・`lib/api/`（**OpenAPI から生成した型**） |
| `db/verify.sql` | 引当まわりの設計が成立するかの確認（検証1〜6） |
| `db/verify_concurrent.sh` | 9.4 の先勝ちの確認（検証7） |
| `db/verify_split_alloc.sh` | 6.2 の割り付け（BR-06・BR-07）の確認（検証8〜13） |
| `db/check_ledger.sh` | 移行の台帳と `migrations/` の照合。**まっさらな新品にだけ流す** |
| `db/check_sql_header.sh` | 全 `.sql` が `SET NAMES utf8mb4;` / `USE ec_koala;` で始まるかの検査。**DB不要** |
| `db/perf/` | 性能測定（R-08）。量データの生成と、単発・並列・キャッシュ非搭載の測定 |
| `tools/make_placeholder.py` | 商品画像のプレースホルダを200枚生成 |
| `tools/import_images.py` | `assets/incoming/` の実物を規約名で `assets/products/` へ上書き |
| `assets/SOURCES.md` | 画像の出どころと状態（プレースホルダ／差し替え済み） |
| `docs/screenshots/` | **画面の見本。`20〜43` が最新**（R-28 の1周。未ログイン `2x`・ログイン中 `3x`・再決済 `4x`）。`10〜13` は運営の画面（R-22） |
| `docs/error-codes.md` | **設計仕様書 8.2 の写し。** CI の7段目がこれと `backend/core/errors.py` を突き合わせる。**直すときは 8.2 が先** |
