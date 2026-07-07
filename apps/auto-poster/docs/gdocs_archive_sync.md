# 投稿済みアーカイブ → Googleドキュメント自動転記（初回セットアップ手順）

目的: Gem / NotebookLM に「投稿済みネタ＋投稿予定ストック」を常に最新の状態で参照させ、
類似投稿の再生成を防ぐ。**初回10分のセットアップ後は、あなたの作業はゼロになる。**

## データの流れ（全自動）

```
毎朝7:30  run_daily_menu.cmd
            └ export_posts_for_notebooklm.py
                ├ data/analytics/raw/*.csv（投稿済み・全期間）
                ├ stock_posts_draft.csv（投稿予定ストック）
                └ → G:\マイドライブ\90_X_KeitaCPA\keita_posted_archive.txt に出力
                     （Google Drive for Desktop が即時クラウド同期）
毎朝4:00頃 Apps Script（下記・時間トリガー）
            └ txt を Googleドキュメント「KeitaCPA_投稿済みアーカイブ」に全文転記
随時       Gem のナレッジ／NotebookLM のソースがこのドキュメントを参照
```

- Gemのナレッジ: Driveから追加したGoogleドキュメントは参照時に最新内容が使われる
- NotebookLM: ソース一覧でこのドキュメントの「同期」を押した時点の内容に更新される
  （記事を書く前に1クリック。それ以外の管理作業なし）

## 初回セットアップ（1回だけ）

### 1. Apps Script プロジェクト作成
1. https://script.google.com → 「新しいプロジェクト」
2. プロジェクト名: `KeitaCPA_ArchiveSync`
3. 以下のコードを貼り付けて保存（コード部分のみ。囲い記号 ``` は貼らないこと）

```javascript
const FOLDER_NAME = '90_X_KeitaCPA';
const TXT_FILE_NAME = 'keita_posted_archive.txt';
const DOC_NAME = 'KeitaCPA_投稿済みアーカイブ';

function syncArchiveToDoc() {
  const folders = DriveApp.getFoldersByName(FOLDER_NAME);
  if (!folders.hasNext()) throw new Error('フォルダが見つかりません: ' + FOLDER_NAME);
  const folder = folders.next();

  const files = folder.getFilesByName(TXT_FILE_NAME);
  if (!files.hasNext()) throw new Error('txtが見つかりません: ' + TXT_FILE_NAME);
  const text = files.next().getBlob().getDataAsString('UTF-8');

  // ドキュメントを取得（なければ作成）
  let docId;
  const docs = folder.getFilesByName(DOC_NAME);
  if (docs.hasNext()) {
    docId = docs.next().getId();
  } else {
    const doc = DocumentApp.create(DOC_NAME);
    doc.saveAndClose();
    DriveApp.getFileById(doc.getId()).moveTo(folder);
    docId = doc.getId();
  }

  // 大きなテキストでも安定する Drive API 直接更新（text/plain を Docs に変換取り込み）
  // 注: DocumentApp.setText() は数十万文字で "Service Documents failed" になるため使わない
  const url = 'https://www.googleapis.com/upload/drive/v3/files/' + docId
            + '?uploadType=media&supportsAllDrives=true';
  const res = UrlFetchApp.fetch(url, {
    method: 'patch',
    contentType: 'text/plain; charset=utf-8',
    payload: text,
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('Drive API更新失敗: ' + res.getResponseCode() + ' ' + res.getContentText().slice(0, 300));
  }
  Logger.log('OK: ' + text.length + ' 文字を転記しました');
}
```

### 2. 動作確認
エディタ上部で関数 `syncArchiveToDoc` を選び「実行」→ 初回は権限承認
（DriveアクセスとGoogle API接続の2種類。コード変更後に再承認を求められることもある）
→ 実行ログに「OK: 〇〇文字を転記しました」と出て、
`G:\マイドライブ\90_X_KeitaCPA\` の「KeitaCPA_投稿済みアーカイブ」に中身が入っていればOK。

### 3. 毎日トリガーの設定
左メニューの時計アイコン（トリガー）→「トリガーを追加」
- 実行する関数: `syncArchiveToDoc`
- イベントのソース: 時間主導型 → 日付ベースのタイマー → **午前4時〜5時**

### 4. Gem / NotebookLM への接続
- **Gem**（投稿生成・記事生成の両方）: Gemの編集画面 → ナレッジ → Googleドライブから
  「KeitaCPA_投稿済みアーカイブ」を追加。カスタム指示に以下を追記（未追記の場合）:
  > ナレッジ「KeitaCPA_投稿済みアーカイブ」にあるネタ・切り口・具体例は使用済みである。
  > 同じ税務トピックを扱う場合も、必ず別の切り口・別の場面設定で書くこと。
- **NotebookLM**: ソース追加 → Googleドキュメント → 同ドキュメントを選択。以後は「同期」ボタンのみ。

## 制約・メンテナンス

- Googleドキュメントの上限は約100万文字。現在約30万文字なので当面問題ないが、
  超えそうになったら export 側で「直近2年分のみ」に絞る改修を行う
- アーカイブの鮮度 = analytics CSVの最終ダウンロード日。月次分析のCSV取得が実質の更新タイミング
  （投稿予定ストック部分は毎朝更新される）
