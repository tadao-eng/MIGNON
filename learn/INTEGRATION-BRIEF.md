# OPOYO Learning ⇄ LINE AI秘書 統合ブリーフ（引き継ぎ用）

> **この文書の使い方**
> デスクトップの Claude Code（またはターミナルCLI）で、あなたのLINE AI秘書のコードが入ったフォルダ
> （例: `cloudcode/AI秘書最新`）を開き、この文書を一緒に読ませて次のように指示してください:
>
> 「`INTEGRATION-BRIEF.md` を読んで、この秘書に OPOYO Learning の学習配信機能を組み込んで」
>
> この1枚だけで、OPOYO Learning 側の仕様・データ・組み込み方針がすべて分かるように書いています。
> OPOYO Learning 側のリポジトリを直接見たい場合は GitHub: `tadao-eng/MIGNON`（`learn/` 配下）。
> 最終更新: 2026-07-07

---

## 0. 全体像（30秒サマリ）

- **OPOYO Learning** = 英語×インドネシア語の学習アプリ（PWA）。ユーザーはこれで毎日1時間学ぶ。
  公開URL: `https://tadao-eng.github.io/MIGNON/learn/`
- **LINE AI秘書（＝この秘書）** の役割 = 学習の「配信・コーチ・催促・会話相手」。
  アプリが「教材と記録」、秘書が「毎日声をかけてくる鬼コーチ兼会話練習相手」という分担。
- **繋ぎ方** = 秘書がOPOYO側の公開JSON（`curriculum.json` / `words.json`）を読み、
  毎日の教材を配信する。ユーザーがアプリから送る「日次報告」を秘書が受けて記録・称賛・催促する。

---

## 1. OPOYO Learning 側で既にあるもの（秘書が使える材料）

| ファイル / URL | 中身 |
|---|---|
| `https://tadao-eng.github.io/MIGNON/learn/curriculum.json` | **日別カリキュラム**（308日分）。毎日: 英5語+イ5語+文法1課。各日に `extra`（翌日分の先取り）付き |
| `https://tadao-eng.github.io/MIGNON/learn/words.json` | 全単語（英1513/イ1431・順次拡張中）+ 12週テーマ |
| GitHub raw | `https://raw.githubusercontent.com/tadao-eng/MIGNON/main/learn/curriculum.json`（Pages無効でも取得可） |

いずれも認証不要のGETで読める静的JSON。**秘書側はこれをfetchするだけでよい**（教材データを秘書内に複製する必要はない）。

---

## 2. データ構造

### 2.1 curriculum.json

```jsonc
{
  "app": "OPOYO Learning",
  "updated": "2026-07-07",
  "per_day": { "words": 10, "grammar": 1, "with_extra": { "words": 20, "grammar": 2 } },
  "days": [
    {
      "day": 1,
      "week": 1,
      "theme": "あいさつ・自己紹介",
      "words": {
        "en": { "review": false, "list": [ { "word": "Good morning", "meaning": "おはようございます", "category": "あいさつ・基本" }, ... 5語 ] },
        "id": { "review": false, "list": [ { "word": "Selamat pagi", "meaning": "おはようございます", "category": "あいさつ・基本" }, ... 5語 ] }
      },
      "grammar": {
        "lang": "en", "no": 1, "review": false,
        "title": "be動詞（am / is / are）",
        "point": "「AはBです」は be動詞で表します。…",
        "examples": [ { "text": "I am busy.", "jp": "私は忙しい" }, ... ]
      },
      "extra": { /* words と grammar を持つ。翌日分の先取り＝倍ペース用 */ }
    }
    // ... day 2 ... 308
  ]
}
```

- **今日が Day 何日目か** は、秘書側が **学習開始日（start_date）を1つ保持**して `経過日数 + 1` で計算する。
  `days[day-1]` がその日の配信内容。
- `review: true` = その教材が一巡して復習に回った印（配信文言を「今日は復習」に変えると良い）。
- `extra` = ユーザーが「もっと」「今日は倍」と言ったときに追加配信する分（翌日先取り）。
  先取りした翌日は同じ内容が通常枠で流れるが、それはそのまま復習になるので問題ない。

### 2.2 words.json

```jsonc
{
  "roadmap": [ { "week": 1, "theme": "あいさつ・自己紹介", "goal": "出会いの表現を反射で言えるように" }, ... 12週 ],
  "en": [ { "word": "eat", "meaning": "食べる", "category": "日常動詞", "forms": "変化: eat – ate – eaten" }, ... ],
  "id": [ { "word": "membeli", "meaning": "買う", "category": "日常動詞", "forms": "語根: beli（口語では beli だけでもOK）" }, ... ]
}
```
`forms` は任意（不規則動詞の変化形やインドネシア語の語根メモ）。全単語からのランダム出題やレベル別テストに使える。

---

## 3. アプリからの「日次報告」フォーマット（秘書がパースする対象）

ユーザーがOPOYOアプリのホームで「LINEに今日の報告を送る」を押すと、以下のテキストがLINEに共有される:

```
📚 OPOYO Learning Day 12/90
タスク 4/4（単語42枚 文法✅ 読解✅ 音読✅）
🔥 12日連続
苦手: postpone / berapa / lurus
```

実力テストの報告はこちら:
```
📝 OPOYO Learning 実力テスト
Day 12/90 — 18/20問正解（90%）
🔥 12日連続
```

- 1行目「Day N/90」から進捗、2行目からタスク達成状況、3行目からストリークを取得できる。
- 「苦手:」の単語は**翌日のミニテストに必ず混ぜる**と定着に効く。

---

## 4. 統合のゴール（3段階・合意済み）

### 段階1: 報告と催促のループ（最優先・効果大）
- ユーザーの日次報告を受けたら **記録して短く具体的に褒める**。「苦手:」語は翌日テストに回す。
- **毎日22時までに報告が来なければ催促**する（例:「今日の報告がまだです。ストリークが切れます🔥」）。
- （任意）報告をスプレッドシート等に蓄積すれば学習グラフも作れる。

### 段階2: スキマ時間のミニ教材
- 朝: **今日の10語**（`curriculum.json` の `days[day-1]` の en5+id5）を意味・変化形つきで配信。
- 昼: **今日の文法1課**（`grammar.title` + `point` + `examples`）。
- 夕: **ミニテスト5問**（今日の10語から4択。1問ごとに正誤+短い解説、最後にスコア）。
- 「もっと/倍」と言われたら `extra` を配信。週テーマ（`roadmap`）に沿った「今日の一言」も可。

### 段階3: 会話の実戦相手（日常会話目標の本命）
- 夜、5往復だけ英語/インドネシア語で雑談やロールプレイ（「今日はカフェ注文。私が店員ね」）。
- 間違いはさりげなく訂正し、**間違えた表現を翌朝のテストに回す**。
- 週末に「今週の実戦テスト」（その週のテーマをぶっつけ本番で会話）。

**まず段階1から実装するのが吉。** ハードワークを支える「報告先＝人（っぽい相手）」がいることが継続に一番効く。

---

## 5. 実装方針（秘書のプラットフォーム別）

> デスクトップの新セッションでは、まず秘書のコードを読んで**実行基盤とLLM利用の有無**を特定すること。

### A. Google Apps Script + LINE Messaging API（自作でよくある構成）
- `UrlFetchApp.fetch('https://tadao-eng.github.io/MIGNON/learn/curriculum.json')` でJSON取得 → `JSON.parse`。
- **時間主導トリガー**（`ScriptApp.newTrigger`）で朝/昼/夕/夜の配信関数を定時実行。
- `start_date` は `PropertiesService.getScriptProperties()` に保存し、経過日数から `day` を算出。
- LINE配信は Messaging API の push（`https://api.line.me/v2/bot/message/push`）を `UrlFetchApp` で叩く。
- 日次報告のパースは、Webhook（doPost）で受けたテキストを正規表現で解析（例: `/Day (\d+)\/90/`, `/苦手: (.+)/`）。

### B. Dify / Coze / n8n などノーコード
- 「HTTPリクエスト」ノードで curriculum.json を取得 → 変数に格納 → メッセージ整形ノードで配信。
- スケジュール/Cronノードで定時トリガー。ナレッジに words.json を登録して質問応答にも使う。

### C. LLMベースの秘書（システムプロンプトを設定できる場合）
- §6のプロンプトをシステムプロンプトに追記。ボットがURLをfetchできるなら curriculum.json を都度参照。
  fetchできない場合は、配信サーバ側（A/B）でJSONを読み、その日の教材をLLMに渡す形にする。

---

## 6. LLM秘書用システムプロンプト（貼り付け用）

```
# 語学コーチの役割（OPOYO Learning 連携）
あなたはユーザーの語学コーチも兼ねる。ユーザーは英語とインドネシア語の日常会話習得を目指し、
OPOYO Learning アプリ（https://tadao-eng.github.io/MIGNON/learn/）で毎日学ぶ。
1日最低10単語+文法1課。90日は最初のマイルストーンで、学習は継続する。

- カリキュラム: https://tadao-eng.github.io/MIGNON/learn/curriculum.json
  開始日は {START_DATE}。今日が Day 何日目かを計算し、その日（days[day-1]）の教材を使う。
- 「今日の単語」→ その日の英語5語+インドネシア語5語を、意味・変化形(forms)付きで見やすく出す。
- 「もっと」「倍」→ その日の extra（追加10語+文法1課）を出す。やる気を必ず褒める。
- 「テスト」→ 直近3日分の単語から4択クイズを1問ずつ計10問。1問ごとに正誤+短い解説、最後にスコアと誤答まとめ。
- ユーザーから「📚 OPOYO Learning Day…」の報告が来たら: 内容を記録し、短く具体的に褒める。
  「苦手:」の単語があれば翌日のテストに必ず含める。
- 22時までに報告がない日は「今日の報告がまだです。ストリークが切れます🔥」と催促する。
- 英語・インドネシア語の質問には例文つきで答え、新出語は
  「アプリの単語帳に追加しておくといいですよ: <単語> / <意味>」と添える。
- 口調: 簡潔・前向き・ただし甘やかさない。ハードワークを支えるコーチであること。
```
`{START_DATE}` はユーザーがOPOYOを使い始めた日（アプリのDay表示から逆算可）に置き換える。

---

## 7. データ同期の運用（重要）

- **教材の正本は OPOYO Learning の `learn/index.html`（tadao-eng/MIGNON）内の配列**。
  単語・文法を増やしたら OPOYO側で `node learn/export-words.mjs` を実行して JSON を再生成しコミットする。
- 秘書は **GitHub Pages / raw のURLを都度fetchするだけ**でよい（常に最新が読める）。
  秘書内にJSONを複製すると同期漏れの元になるので避ける。
- どうしてもローカルに置きたい場合は、デスクトップの秘書フォルダに `curriculum.json` を
  コピーし、更新のたびに公開URLから取り直すスクリプトを用意する。

---

## 8. 現状と未完タスク（2026-07-07 時点）

**OPOYO Learning 側（ほぼ完成・稼働中）**
- アプリ本体、SRS、4タスク制、実力テスト、90日ヒートマップ、バックアップ/復元、オフライン対応、
  LINE報告ボタン、単語 英1513/イ1431（→各3000語へ拡張継続中）、文法 各60課、curriculum/words.json。

**秘書側（これから＝この統合作業）**
1. 段階1（報告受信→記録・称賛・催促）の実装 ← まずここ
2. 段階2（朝昼夕の定時配信＋ミニテスト）
3. 段階3（会話ロールプレイ）
4. `start_date` の保存と Day 計算
5. curriculum.json のfetch＋整形

**補足**: OPOYOアプリの「LINEに報告」ボタンは Web Share / LINE共有URL で秘書トークにテキストを送る作り。
秘書のWebhookでそのテキストを受けてパースすれば段階1が回り始める。

---

## 9. 連絡事項（OPOYO側の担当＝別セッションへ戻すとき）

秘書側の実装が固まって、OPOYO側に必要な変更（報告フォーマットの調整、専用エンドポイントの追加など）が出たら、
`tadao-eng/MIGNON` の `learn/` を扱っているセッションに以下を伝える:
- 変えてほしい報告テキストの形式
- 秘書が読みやすいデータ構造の要望（例: day単位ではなく週単位でまとめた別JSONが欲しい 等）

OPOYO側は `learn/HANDOFF.md` に全仕様、`learn/line-bot-guide.md` に配信ガイドを保持している。
