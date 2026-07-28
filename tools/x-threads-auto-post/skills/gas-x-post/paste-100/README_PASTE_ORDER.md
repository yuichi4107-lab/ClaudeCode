# Apps Script 100行制限向け 貼り付け順

Apps Scriptで「＋」→「スクリプト」を追加し、以下の8ファイルを1つずつ作って貼り付けてください。
各ファイルは100行未満です。

1. `01_Config_Main.gs`
2. `02_XPost.gs`
3. `03_ThreadsPost.gs`
4. `04_Helpers.gs`
5. `05_OAuth_Error.gs`
6. `06_Setup_Run.gs`
7. `11_Note_Config_Setup.gs`
8. `12_Note_Helpers.gs`

Apps Script側のファイル名は、拡張子なしでもOKです。
例: `01_Config_Main`

貼り終えたら保存し、次の順で実行します。

1. `setupSpreadsheet`
2. `setupNoteRssBridge`
3. `dryRunNoteRssBridge`
