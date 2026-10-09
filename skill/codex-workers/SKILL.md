---
name: codex-workers
description: 由單一主 agent 指揮不同帳號的 Codex worker，在 Herdr 中派工、收取結果與追加任務；每個帳號以獨立官方登入隔離。適用多帳號 Codex 協作與平行任務；不處理額度查詢、主登入切換或一般單一 Codex 工作。
---

# Codex Workers

透過 `codex-workers` CLI 協調 worker。每個帳號使用獨立 `CODEX_HOME`，在 worker 專用目錄完成 Codex 官方登入；主 Codex 登入與設定保持原樣。

協作語言由 CLI 的 `CODEX_WORKERS_LANGUAGE_PROMPT` 決定：未設定時，每次派工都附上「使用台灣繁體中文回報」的說明；設成其他文字就改用該說明；設成空字串則只送任務原文。派工、追加任務與成果回報依該語言進行，程式碼、指令、識別字、路徑及必要原文保留。若 worker 回覆不符設定語言，完成後請它補交，再驗收整合。

上述語言、命名與完成後選擇由本 skill 與 Codex Workers CLI 管理，不需要修改 Herdr skill。本流程的派工與追加任務，包括 worker 彼此交接，都使用 `codex-workers start`／`prompt`；不要直接用 `herdr agent prompt` 繞過語言設定與狀態核對。Herdr skill 可供查閱底層操作，但其中的一般命名或範例不取代本流程規則。完成提問與 `finish` 由主 agent 收取成果後處理，worker 不自行壓縮或關閉 pane。

## 前置檢查

第一次派工前，以及 CLI 或 Herdr 狀態可能改變時，先用唯讀指令確認必要工具：

```sh
command -v codex-workers >/dev/null && echo "codex-workers: ok" || echo "codex-workers: missing"
python3 -c 'import sys; print("python3:", "ok" if sys.version_info >= (3, 11) else "too old")'
command -v codex >/dev/null && codex --help 2>&1 | grep -q -- '--no-daemon' && echo "codex: ok" || echo "codex: missing or unsupported"
command -v herdr >/dev/null && echo "herdr: ok" || echo "herdr: missing"
[ "$HERDR_ENV" = 1 ] && [ -n "$HERDR_PANE_ID" ] && echo "herdr pane: ok" || echo "herdr pane: not detected"
```

任一項不是 `ok`，就停止派工，告訴使用者缺少什麼，並依 [references/setup.md](references/setup.md) 引導安裝。安裝屬於系統變更：先列出將執行的指令，取得使用者同意後再執行，或請使用者自己執行。不要自行選擇安裝來源以外的套件。

| 缺少項目 | 引導 |
|---|---|
| `codex-workers` | 到 Codex Workers 專案目錄執行 `python3 install.py`（Claude Code 加 `--claude`），再執行 `codex-workers --help`。 |
| `python3` 3.11 以下 | 安裝 Python 3.11 以上版本，並確認 `python3` 指向它。 |
| `codex` 或不支援 `--no-daemon` | 安裝 Codex CLI，見 setup.md 的安裝方式。 |
| `herdr` | 安裝 Herdr，見 setup.md 的安裝方式；安裝後在終端機執行 `herdr`。 |
| `herdr pane` 未偵測到 | 在 Herdr 的 pane 中啟動主 agent。不可手動設定 `HERDR_ENV` 或 `HERDR_PANE_ID`。 |

全部 `ok` 之後，才進入下一節。

## 確認帳號與環境

- 先執行 `codex-workers account list --json`，使用回傳的帳號別名。**別名由使用者自訂**：新增帳號時請使用者決定別名（例如 `work`、`personal`），agent 不代取、不沿用範例名稱，也不另取 alpha／beta 等別名。別名須小寫英文字母開頭、最多 32 字元，可含數字、`_`、`-`。
- 沒有帳號，或使用者要加入新帳號時，依 [references/setup.md](references/setup.md) 由使用者執行 `codex-workers account add <別名>` 完成官方 device login。登入由使用者完成，不讀取或複製主登入憑證。`login_file: "present_unverified"` 只表示登入檔存在，實際啟動或任務成功才證明當次授權可用。
- 使用者可自行管理帳號：`account add <別名>` 新增、`account list --json` 查看、`account rename <舊別名> <新別名>` 改名、`account remove <別名>` 刪除。改名與刪除只在使用者明確要求、且已確認目標別名後執行；刪除前要告知會一併刪除該帳號的登入檔、設定、Codex 對話歷史，以及該帳號已結束的 worker 紀錄，無法復原。該帳號仍有 worker 的 pane 存在或無法確認已消失時，CLI 回 `account_in_use`：先依「完成後選擇」關閉該 worker，不要繞過。授權過期或登錯帳號時，請使用者刪除後以同一別名重新 `add`。
- worker 名稱須為「帳號別名」或「帳號別名-用途」，同樣受 Herdr 小寫英文字母開頭、最多 32 字元的限制。帳號別名要完整：別名為 `<別名>` 時 worker 可叫 `<別名>-review`；只取別名一部分會回 `account_name_mismatch`。pane 標題須與 worker 名稱一致；CLI 在每次派工前核對，必要時修正標題，不任意改綁帳號或改 agent 名稱。
- 派工需要 Herdr 注入的 `HERDR_ENV=1` 與 `HERDR_PANE_ID`。工具執行環境缺少變數時可以列出帳號，但停止 pane／agent 操作；這不等於使用者未在 Herdr 中。先唯讀核對程序鏈與 Codex 的 `shell_environment_policy`，區分未從 Herdr 啟動與環境繼承遭過濾，再提供對應處理方式。不可自行設定這些變數冒充 caller context，也不可未經授權修改 Codex 設定或重啟工作階段。主 agent 工作階段重啟後，`HERDR_PANE_ID` 可能指向已不存在的 pane（`herdr pane get "$HERDR_PANE_ID"` 回 `pane_not_found`），`start` 會在建立 pane 前失敗；請使用者在現有的 Herdr pane 重新開啟主 agent。
- CLI 缺失時讀取 [references/setup.md](references/setup.md)。這些 CLI 指令可在使用者的專案目錄執行，不必切換到 Codex Workers 專案。

## 派工與整合

1. 按使用者指定的帳號分配任務；沒有指定時，從已列出的帳號中提出或選擇明確分工。多個 worker 共用專案時，指明各自負責的檔案、驗收條件，並提醒不可覆蓋其他人的修改。
2. 用 `codex-workers status "$worker_name"` 檢查既有 worker。只有 `worker_not_found` 才代表未建立；其他錯誤要先診斷。重用前再用 `herdr agent get "$worker_name"` 核對 JSON 的 `result.agent.cwd`：`status` 不含目錄，`prompt` 也不會更換目錄。帳號與專案都相符且 `completed` 才用 `prompt` 沿用；不同專案則建立「帳號別名-用途」的新 worker，並明確指定 `--cwd`。`working` 先等待；`blocked`／`unknown` 先讀取畫面。`closed` 表示曾確認關閉，可按需要用 `start` 同名重建。帳號不符時不把任務派給它。
3. 新 worker 使用：

   ```sh
   codex-workers start "$worker_name" --account "$account_alias" --cwd "$project_dir" --task "$task"
   ```

   變數須填入使用者的帳號別名、worker 名稱、專案目錄與任務。省略 `--cwd` 會沿用呼叫端目錄。`start` 預設以 `codex --no-daemon --yolo` 啟動新 worker，略過該 worker 的 sandbox 與核准提示；不需在 `codex-workers start` 另外加參數。就緒後只送一次並返回，接著可啟動其他帳號的工作，讓任務同時進行。連續啟動時逐一檢查每個 `start` 的回傳。啟動失敗（如 `agent_pane_busy`）會留下 `startup_failed` 紀錄：Herdr 確認 pane 已不存在時，CLI 會釋放名稱，可同名重試；pane 仍在或無法確認時回 `duplicate_name`，先檢查該 pane 或改用新名稱。
4. 追蹤與收取結果：

   ```sh
   codex-workers status "$worker_name"
   codex-workers wait "$worker_name" --timeout 30
   codex-workers read "$worker_name" --lines 120
   ```

   `wait` exit code：0＝completed、3＝blocked、4＝unknown／closed、124＝timeout。送出成功、剛啟動的 idle、blocked、unknown 與 timeout 都不代表工作完成。逾時會保留 worker，稍後可繼續等待或讀取。多個 worker 同時工作時，每隔 2–5 秒輪詢各自的 `status`，或使用短時間 `wait` 輪流檢查；不要長時間只等其中一個，延後其他 worker 的完成提示。
5. 完成後追加任務：

   ```sh
   codex-workers prompt "$worker_name" "$followup_task"
   ```

6. 每個 worker 每輪 `completed` 後立即 `read`，辨識本輪成果，再依下一節詢問完成後選擇，不等整批結束。主 agent 檢查實際成果與驗收證據，再整合各 worker 結果。回報帳號、任務、狀態、成果及未完成事項；不要僅憑 worker 宣稱完成就認定驗收通過。

## 完成後選擇

- `status`／`wait` 在 `completed` 時回傳 `completion_id` 與 `completion_prompt`。當 `pending: true`，透過可用的提問工具向使用者詢問「保留、執行 /compact、關閉 pane」，附帳號、worker 名稱與本輪成果摘要。同一個 `completion_id` 已詢問且尚未回答時不重問；其他 worker 繼續工作。
- 未回答時保留 pane，不自行選擇。使用者選定後執行：

  ```sh
  codex-workers finish "$worker_name" --completion-id "$completion_id" --action keep
  ```

  保留用 `keep`、壓縮用 `compact`、關閉用 `close`。選擇只適用該輪；後續追加任務完成會取得新的 ID，再詢問一次。執行前 CLI 會重新核對身分、目錄、完成狀態與 ID；主 pane、過期選擇及已處理選擇會被拒絕。
- `compact_submitted` 只代表原樣 `/compact` 已送出並等待代理就緒；再 `read` 核對實際壓縮結果，不能直接宣稱壓縮成功。不要用一般 `prompt` 傳 slash command，避免語言說明改變指令。壓縮本身不算新任務，不再觸發完成提問。
- `closed` 表示指定 worker pane 已關閉；帳號授權與 session 歷史保留。操作失敗的 `maintenance_unknown` 不代表成功；先 `read` 與核對實際狀態，不重送，不自行刪除紀錄重試。
- `status` 回 `reason: "pane_missing"` 表示 Herdr 確認 pane 已不存在，並附 `completion_id`。只接受 `finish --action close`：CLI 只把紀錄標為 `closed`，不操作任何 pane；keep／compact 回 `pane_missing`。若是 `agent_not_found`（pane 還在）或查詢失敗，不會記為關閉，請使用者檢查該 pane；不刪除紀錄。

## 讀取與失敗處理

- 主 skill 更新不代表既有帳號的 skill 副本或已載入的指引已更新。使用者授權修正既有 workers 的 skills 時，只同步指定 skill，不整包同步設定。取得有效 Herdr context 並確認 worker 已完成後，用 `codex-workers prompt` 請它重新讀取 `$CODEX_HOME/skills/codex-workers/SKILL.md`；該輪仍須收取成果並詢問完成後選擇，不以檔案同步當作真實派工驗收。
- `read` 的 JSON `text` 是終端機畫面，可能含使用者 prompt 與舊回覆。驗收時辨識本輪的 assistant 回覆，不把 prompt 中的預期答案當成成果。Herdr 可能先偵測到完成、畫面稍後才更新；可以短暫再讀取，不重送任務。Herdr 回報 `done` 可能早於回覆完成數分鐘，所以 CLI 判定 `completed` 前會檢查畫面結尾是否仍有 Codex 的 `Working (… esc to interrupt)`：仍在執行回 `working`，讀不到畫面回 `unknown`（`screen_unreadable`）。收取成果時仍從 text 結尾確認完整回覆與 `Worked for`；text 開頭可能殘留舊畫面（如用量儀表板），不要從開頭擷取。等待一律用 `wait --timeout`，不另寫 sleep 迴圈。
- 長回答可能截斷。增加 `--lines` 仍不足時，在該輪完成後以 `prompt` 請 worker 將完整結果存成檔案，再讀取該檔。
- 預檢失敗可能尚未建立 worker 紀錄；建立 pane 或送出階段的失敗則會保留名稱及已取得的 pane ID。先判讀錯誤與 `status`，有 pane ID 才 `read`；不把無紀錄與送出結果不明混為一談，不盲目重送或任意刪除紀錄來重試。
- 登入失敗或授權失效時停止派工，請使用者重新登入該帳號；不得回落到主帳號、另一個帳號或環境中的 API key。

## 授權與隔離

- 不讀出 token，也不複製主 `auth.json`。每個帳號的 refresh token 由該帳號的 Codex 自行管理。
- 新 worker 預設使用 `--no-daemon --yolo`，只影響新 worker 的執行權限；不修改主帳號設定、不重啟共享 daemon，也不切換主登入。不要替使用者新增 worktree、覆寫模型，或重啟既有 worker，除非該操作已在任務範圍內獲授權。`prompt` 沿用既有 worker 的啟動權限。
- 每次新啟動同步設定、profiles、規則與 skills，只共用 plugin cache；不複製主 session、歷史資料或 plugin OAuth。`withheld_fields` 表示略過的內嵌憑證／連線欄位。
- 外部工具可能需要工作帳號另行授權。未授權時明確回報，不借用主帳號的連線或放寬權限。
- 只用使用者自己的帳號；不分享帳號，也不用多帳號規避服務的用量限制。
