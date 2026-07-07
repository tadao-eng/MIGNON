# OPOYO Learning — 開発引き継ぎドキュメント (HANDOFF)

> このファイルは、開発を別のAIエージェント(Antigravity等)や開発者に引き継ぐための完全な資料です。
> これ1枚を読めば、経緯・設計思想・データ構造・今後のロードマップまで把握できることを目的としています。
> 最終更新: 2026-07-06 (Claude Code セッションにて作成)

---

## 1. プロジェクトの目的とユーザー像

- **ユーザー**: 日本人・30代後半。東京で小さなカフェ(MIGNON)を経営。
- **目標**: **90日間(3ヶ月)で英語とインドネシア語を日常会話レベルに**。1日1時間を学習に充てる。ハードワーク志向。
- **利用形態**: スマホ(PWAとしてホーム画面に追加)で毎日使用。
- アプリ名は 2026-07-06 に MIGNON LINGO から OPOYO Learning へ変更(ユーザーのAI秘書「OPOYO」に付随するアプリのため)。
  ただし localStorage キーは `mignon-lingo-v2` のまま(変更すると既存進捗が消えるため。内部キーは変えないこと)。
- 元々は1年計画だったが、ユーザーの要望で「3ヶ月・1日1時間・複数方面から潰す」集中プログラムに変更した経緯がある。

## 2. リポジトリ構成

```
MIGNON/  (GitHub: tadao-eng/MIGNON)
├── index.html            ← 既存の売上入力アプリ「MIGNON SALES ENTRY」。★絶対に触らない
└── learn/                ← 語学学習アプリ(このプロジェクト)
    ├── index.html        ← アプリ本体。単一ファイル(HTML+CSS+JS+全教材データ)
    ├── sw.js             ← Service Worker(オフライン対応)
    ├── manifest.json     ← PWAマニフェスト
    ├── icon-192.png / icon-512.png / apple-touch-icon.png  ← アプリアイコン(紺地に「ML LINGO」)
    ├── words.json        ← 単語データの書き出し(LINEボット等の外部ツール用)
    ├── curriculum.json   ← 90日分の日別配信カリキュラム(LINEボット用。毎日10語+文法1課)
    ├── line-bot-guide.md ← LINE AI秘書の設定ガイド(配信フロー・貼り付け用プロンプト)
    ├── export-words.mjs  ← index.html → words.json / curriculum.json 生成スクリプト
    ├── README.md         ← ユーザー向け説明
    └── HANDOFF.md        ← このファイル
```

- **デプロイ**: GitHub Pages(`main` ブランチ / root)。公開URL: `https://tadao-eng.github.io/MIGNON/learn/`
- **開発ブランチ**: `claude/language-learning-app-ognsbt` で開発 → PRで `main` にスカッシュマージする運用。
  - 注意: スカッシュマージ後はブランチとmainの履歴がズレて次のPRがコンフリクトするので、**新作業の前に `git merge origin/main` でブランチを同期すること**(コンフリクト時はブランチ側=最新版を採用: `-X ours`)。
- サーバー・ビルドツール・フレームワークは**一切なし**。純粋な静的ファイルのみ。

## 3. デザイン原則(重要・変更しないこと)

ユーザーの強い希望で、コスメブランド **SHIRO (shiro-shiro.jp) のような極めてミニマルなUI** に統一している。
既存の `index.html`(売上アプリ)と同じデザイン言語。

- 配色: 白背景 `#FFFFFF` × ネイビー `#000033` × 薄グレー罫線 `#E5E5E5`。この3色+グレー文字のみ
- タイポグラフィ: Inter + Noto Sans JP、細めのウェイト(300/400)、見出しは小さな大文字+広い字間(`letter-spacing: 0.25em` 前後)
- **禁止**: 絵文字の多用・グラデーション・角丸・影・カラフルなボタン・紙吹雪などの派手な演出
  (絵文字はストリークの🔥とLINE報告文など最小限のみ)
- 罫線は1pxのヘアライン。進捗バーも1〜3pxの細い線
- ナビは下部固定のテキストのみ3タブ: HOME / WORDS / RECORD

## 4. アプリ仕様

### 4.1 1日のプログラム(ホーム画面のタスクボード)

4タスクすべて完了でその日クリア→ストリーク(連続日数)が1増える。`checkGoalAndStreak()` が判定。

| タスク | 内容 | 目安 | 完了条件(log のキー) |
|---|---|---|---|
| 単語トレーニング | SRS復習+新規。フラッシュカード/意味4択/リスニング4択が混ざる | 約25分 | `cards >= settings.cardsGoal`(既定40枚) |
| 文法レッスン | 解説+例文(TTS付き)+4択クイズ3問。英/イを日替わり交互 | 約15分 | `g === true` |
| リーディング | 短文+設問2問+全訳。文法と逆の言語 | 約10分 | `r === true` |
| 音読・スピーキング | フレーズ10本(EN5+ID5)をTTSに続けて発声 | 約10分 | `s === true` |

- 言語の日替わり: `grammarLangToday()` = 奇数日en/偶数日id、`readingLangToday()` はその逆(毎日両言語に触れる設計)
- Extra(追加学習): **実力テスト20問**(下記)、会話ダイアログ練習(英/イ)、苦手単語特訓(lapses≥2の単語15枚)、言語別単語セッション、文法/読解のおかわり
- **実力テスト**: 学習済み単語(12語未満なら全単語)から20問をランダム出題。単語→意味40% / 意味→単語40% / リスニング20%。**SRSやタスク進捗に影響せず何度でも反復可**。結果画面にスコア・間違い一覧・「LINEに結果を報告」ボタン(`startTest()` / `tsession`)

### 4.2 SRS(間隔反復)仕様

- Leitner方式。`INTERVALS = [0,1,3,7,14,30,60,120]`(box番号→次回までの日数)
- 評価: 「もう一度」= box1にリセット+lapses++、セッション内3枚後に再出題 / 「あいまい」= 明日 / 「覚えた」= box+1して間隔を空ける
- box≥3 で「マスター」扱い(単語帳の●表示、統計のマスター数)
- 2回目以降のカードは出題形式がランダム: 意味4択35% / リスニング4択30% / フラッシュカード35%

### 4.3 localStorage スキーマ(キー: `mignon-lingo-v2`)

```js
{
  startDate: "YYYY-MM-DD",     // Day計算の起点
  xp: 0, streak: 0, bestStreak: 0,
  lastGoalDate: null,           // 最後に全タスク達成した日
  srs: { "<cardId>": { box, due:"YYYY-MM-DD", reps, lapses } },
  log: { "YYYY-MM-DD": { cards, newEn, newId, g, r, s } },
  gram: { en: { next }, id: { next } },   // 次の文法レッスンindex(全課修了後はランダム復習)
  read: { en: 0, id: 0 },                 // 読んだ本数(indexは % 本数 で循環)
  dlg:  { en: 0, id: 0 },                 // 会話ダイアログの進行
  custom: [ ["c1","en","word","意味"] ],  // ユーザー追加単語
  customSeq: 0,
  settings: { newPerDay: 8, cardsGoal: 40, vocabLang: "mix", rate: 0.95 }
}
```

- カードID: 内蔵英語 `e0..`、内蔵インドネシア語 `i0..`、カスタム `c1..`(配列indexがIDなので**既存単語の途中挿入・削除はNG、末尾追加のみ**)
- 旧v1(`mignon-lingo-v1`)からの移行コードが `load()` にある
- **設定画面にバックアップ(JSONコピー)/復元(貼り付け)機能あり**。データはユーザーの端末にしかないことに注意

### 4.4 教材データ構造(すべて index.html 内にインライン)

```js
EN_WORDS / ID_WORDS: [word, 意味, カテゴリ, 変化形?]   // 変化形は任意の第4要素(文字列)
  // 例: ["eat","食べる","日常動詞","変化: eat – ate – eaten"]
  // 例: ["membeli","買う","日常動詞","語根: beli（口語では beli だけでもOK）"]
GRAMMAR.{en,id}: [{ t:題, e:解説, ex:[[例文,訳]], q:[[問題,[選択肢4つ],正解idx]] }]
READINGS.{en,id}: [{ t:題, text:本文, jp:全訳, q:[[問い,[選択肢],正解idx]] }]
DIALOGUES.{en,id}: [{ t:場面, lines:[["A"|"B", セリフ, 訳]] }]   // Bがユーザー役
ROADMAP: [[週テーマ, 説明]] ×12週
BADGES: [[名前, 条件関数]] ×12
```

現在の収録量: 単語 **EN1088/ID1011**、文法 **各60課**、読解 各12本、会話 各6場面。
文法後半(46-60課)は「日常会話・口語の実戦パターン」に特化(英: would like/used to/伝聞/get変化/あいづち/電話 等、
イ: 語気助詞 dong-sih-kok-deh/-in/lagi/kan/kayak/口語疑問詞/値切り/WA表現 等)。話し言葉の聞き取り対策を重視。
curriculum.json は全単語が一巡する日数(現在196日)+各日 `extra`(先取り分)を自動生成し、
倍ペース=20語+文法2課/日に対応。

### 語彙3000語への増量ラダー(ユーザー目標・進行中)

**最終目標: 各言語3000語、文法は各60課程度。** 品質維持のため1バッチ+500語前後で段階的に追加する。

| バッチ | 目標 | 状態 |
|---|---|---|
| 1 | 各500語 / 文法35課 | ✅ 完了 |
| 2 | EN963 / ID882 / 文法45課 | ✅ 完了 |
| 2.5 | 文法 各60課(会話・口語特化) | ✅ 完了 |
| 3 | EN1088 / ID1011(ビジネス/IT/社会/句動詞/イディオム/ことわざ) | ✅ 完了(このバッチ) |
| 4 | 各1500語 | 未着手 |
| 5 | 各2000語 | 未着手 |
| 6-7 | 各3000語 | 未着手 |

**バッチ追加の手順(必ず守ること):**
1. `EN_WORDS` / `ID_WORDS` の**末尾にのみ**追加(既存行の挿入・削除・並べ替えはID破壊になるため厳禁)
2. カテゴリ候補: EN=ニュース・社会/ビジネス応用/イディオム/句動詞2/形容詞3/学術基礎…
   ID=ビジネス/ニュース語彙/スラング・SNS/ジャワ語借用の日常語/中級動詞の続き…
3. 追加後に `node learn/export-words.mjs` を実行 → 出力の重複チェック(下記スクリプト)で dups: none を確認
   `node -e "const j=require('./learn/words.json'); ['en','id'].forEach(l=>{const s={};j[l].forEach(w=>s[w.word.toLowerCase()]=(s[w.word.toLowerCase()]||0)+1);console.log(l,Object.entries(s).filter(([k,v])=>v>1).map(([k])=>k).join(',')||'no dups')})"`
4. 同語で意味が違う場合は語形を変えて回避(例: fall→autumn、watch→wristwatch)
5. Playwrightでアプリ起動確認 → コミット → PR → main へマージ

### 4.5 音声(TTS)

- Web Speech API (`speechSynthesis`)。**過去に「音声が変」というバグがあった**: 端末に対象言語の音声がないと日本語音声で英語を読んでいた。
- 修正済みの実装: `pickVoice(lang)` が `getVoices()` から en-US/en-GB/en、id-ID/id/ms を優先順で探し、`localService` を優先して明示的に `utterance.voice` に設定する。**この仕組みを壊さないこと**
- インドネシア語音声がない端末では初回のみトースト通知
- 速度は設定で変更可(`settings.rate`)。iOSでは自動再生がジェスチャ必須で失敗することがある(ボタン再生は動く)

### 4.6 テスト方法

Playwright(Chromium)でファイルを直接開いてE2E確認するのが定石:

```js
const { chromium } = require('playwright');
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }); // 環境による
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
page.on('pageerror', e => console.log(e.message));   // JSエラー検出
await page.goto('file:///.../learn/index.html');
// state を evaluate で直接操作して「2日目以降」等の状態を再現できる:
await page.evaluate(() => { state.srs['e0']={box:1,due:todayStr(),reps:1,lapses:3}; save(); renderHome(); });
```

Google Fonts の読み込みエラー(ERR_CONNECTION系)はオフライン環境由来なので無視してよい。

## 5. 外部連携

### 5.1 words.json / curriculum.json(実装済み)

- LINEボット等が読むためのファイル。公開URL:
  `https://tadao-eng.github.io/MIGNON/learn/words.json`
  `https://tadao-eng.github.io/MIGNON/learn/curriculum.json`
- **curriculum.json が本命**: 90日分の日別割り当て(毎日 英5語+イ5語+文法1課、要点・例文入り)。
  ボット側は開始日を保持して経過日数で `days[]` を引くだけ。一巡後は `review: true` で復習に回る。
  詳細な構造・配信フロー・LLM用プロンプトは **line-bot-guide.md** を参照
- **正本は index.html 内の配列**。教材を変更したら `node learn/export-words.mjs` で両ファイルを再生成してコミットすること

### 5.2 LINE報告ボタン(実装済み)

- ホームの「LINEに今日の報告を送る」→ `buildReportText()` が以下を生成し、Web Share API(なければ `https://line.me/R/share?text=`)で共有:
  Day数 / タスク4つの達成状況 / ストリーク / 苦手単語トップ3
- ユーザーはこれをLINEのAI秘書チャットに送る想定

### 5.3 LINE AI秘書との連携ロードマップ(未実装・合意済みの計画)

ユーザーは自作の「LINE AI秘書」を持っている(実装方式は未確認。GAS+Messaging API か外部サービスの可能性)。
**ボット側の実装方式を確認してから着手すること。** 3段階の計画で合意済み:

1. **報告と催促のループ**(アプリ側は完了)
   - ボット側: 報告を受けて記録・称賛、報告がない日の22時に催促プッシュ
2. **スキマ時間のミニ教材**
   - ボットが words.json を読み、朝に3問クイズ配信、週テーマ(`roadmap`)に沿った「今日の一言」
   - Day数はボット側で `startDate` からの経過日数を計算(またはユーザー報告から把握)
3. **会話の実戦相手**(3ヶ月目標の本命)
   - 夜に5往復のロールプレイ(週テーマの場面)。間違いを翌朝のクイズに回す。週末に実戦テスト

## 6. 既知の制約・注意点

- **進捗データは端末のlocalStorageのみ**。消えると戻らない → バックアップ機能をユーザーに定期的に使わせること。サーバー同期(GAS+スプレッドシート等)は将来課題
- iOS PWA はプッシュ通知が不安定なため、リマインダーはLINEボットかGoogleカレンダーで行う方針
  (Googleカレンダーへの「毎日21時・90回繰り返し」登録はMCP接続エラーで未完。イベント内容は決定済み: 21:00-22:00 JST、タイトル「MIGNON LINGO — 語学1時間」)
- `index.html`(リポジトリ直下)は別アプリ。**learn/ 以外は変更禁止**
- コミットメッセージやPRは日本語/英語どちらでも良いが、PRを作ったらマージまで行う運用だった

## 7. 今後のバックログ(優先順)

1. **LINE連携 段階1のボット側**(§5.3) — ボットの実装方式の確認が必要
2. **コンテンツ増量の継続** — 目標: 単語を各言語500語程度へ(現在EN325/ID298)。文法・読解・会話も随時追加。
   追加時は既存配列の**末尾に追加**(ID安定性のため)し、words.json を再生成
3. **進捗のサーバー同期** — GAS + スプレッドシート(売上アプリと同じ構成)で state を同期すれば、機種変更耐性とボットからの進捗参照が両立できる
4. リスニング強化(文章の聞き取り)、発音チェック(SpeechRecognition、iOS制約あり)、週次レビュー画面 などのアイデアあり

## 8. これまでの経緯(PR履歴)

| PR | 内容 |
|---|---|
| #1 | 初版(365日計画・カラフルUI)+ PWA対応 + GitHub Pages公開 |
| #2 | 90日集中プログラム化(4タスク制)、文法30課・読解24本追加、TTS音声選択バグ修正、SHIRO風ミニマルUIへ全面刷新 |
| #3 | バックアップ/復元、リスニング出題、90日ヒートマップ、会話ダイアログ12本、苦手特訓、オフライン対応(sw.js)、単語の変化形表示、文法50課へ・単語増量 |
| #4 | LINE報告ボタン、words.json + 生成スクリプト、この引き継ぎ資料 |
| #5 | 実力テスト(20問・反復可)、curriculum.json(90日配信カリキュラム)、line-bot-guide.md |
| #6 | 単語を各言語500語超に増量(EN510/ID500)、文法を各35課に、curriculum 180日+extra(倍ペース対応)、アプリのペース設定拡張(新規24語・目標120枚まで) |

## 9. 方針メモ(2026-07-06 ユーザー決定)

- **新出の単語・文法の摂取はLINE配信を主軸にする**(1日最低10語+文法1課)。アプリは反復テスト・SRS・読解・音読の「定着の場」
- **90日に縛られない**。90日は最初のマイルストーンで、カリキュラムは180日分。やる気のある日は倍ペース(20語+文法2課)で進められること
- LINEボットの実装方式は未確認のまま。確認できたら line-bot-guide.md の最終節に具体実装を追記すること
