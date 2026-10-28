---
name: codex-workers
description: 由單一主 agent 指揮不同帳號的 Codex worker，在 Herdr 中派工、收取結果與追加任務；每個帳號以獨立官方登入隔離。適用多帳號 Codex 協作與平行任務；不處理額度查詢、主登入切換或一般單一 Codex 工作。
---

# Codex Workers

透過 `codex-workers` CLI 協調 worker。每個帳號使用獨立 `CODEX_HOME` 與 Codex 官方登入；主 Codex 登入與設定保持原樣。

- 派工與追加任務（包括 worker 彼此交接）一律用 `codex-workers start`／`prompt`，不要用 `herdr agent prompt` 繞過語言設定與狀態核對。Herdr skill 只供查閱底層操作，其命名或範例不取代本流程；本流程不需要修改 Herdr skill。
- 協作語言由 `CODEX_WORKERS_LANGUAGE_PROMPT` 決定：未設定時每次派工附上「使用台灣繁體中文回報」；設成其他文字就改用該說明；空字串只送任務原文。worker 回覆不符設定語言時，完成後請它補交再驗收。
- 完成提問與 `finish` 由主 agent 處理，worker 不自行壓縮或關閉 pane。
- 少用情境見 [references/operations.md](references/operations.md)：Herdr 環境診斷、帳號改名與刪除、罕見狀態與失敗、更新既有 worker 的 skill、授權與隔離。

## 前置檢查

第一次派工前，以及 CLI 或 Herdr 狀態可能改變時，先執行：

```sh
command -v codex-workers >/dev/null && echo "codex-workers: ok" || echo "codex-workers: missing"
python3 -c 'import sys; print("python3:", "ok" if sys.version_info >= (3, 11) else "too old")'
command -v codex >/dev/null && codex --help 2>&1 | grep -q -- '--no-daemon' && echo "codex: ok" || echo "codex: missing or unsupported"
command -v herdr >/dev/null && echo "herdr: ok" || echo "herdr: missing"
[ "$HERDR_ENV" = 1 ] && [ -n "$HERDR_PANE_ID" ] && echo "herdr pane: ok" || echo "herdr pane: not detected"
```

任一項不是 `ok` 就停止派工，告訴使用者缺少什麼，並依 [references/setup.md](references/setup.md) 列出安裝指令。安裝屬於系統變更：取得同意後再執行，或請使用者自己執行；不自選其他安裝來源。`herdr pane` 未偵測到時，請使用者在 Herdr 的 pane 中啟動主 agent；不可手動設定 `HERDR_ENV` 或 `HERDR_PANE_ID`。

## 帳號與命名

- 先執行 `codex-workers account list --json`，使用回傳的別名。**別名由使用者自訂**（小寫英文字母開頭、最多 32 字元，可含數字、`_`、`-`）：agent 不代取、不沿用範例名稱，也不另取 alpha／beta 等別名。
- 沒有帳號或要加入新帳號時，依 setup.md 由使用者執行 `codex-workers account add <別名>` 完成官方 device login。`login_file: "present_unverified"` 只表示登入檔存在，實際派工成功才證明授權可用。改名、刪除或回 `account_in_use` 時見 operations.md。
- worker 名稱須為「帳號別名」或「帳號別名-用途」（例如 `<別名>-review`），同樣限 32 字元；別名要完整，否則回 `account_name_mismatch`。CLI 每次派工前核對並修正 pane 標題，不任意改綁帳號或改 agent 名稱。
- CLI 可在使用者的專案目錄執行。

## 派工與整合

1. 按使用者指定的帳號分配任務；未指定時提出明確分工。多個 worker 共用專案時，指明各自負責的檔案與驗收條件，並提醒不可覆蓋他人修改。
2. 重用既有 worker 前先 `codex-workers status "$worker_name"`：只有 `worker_not_found` 代表未建立，其他錯誤先診斷。`status` 不含目錄且 `prompt` 不換目錄，所以再用 `herdr agent get "$worker_name"` 核對 `result.agent.cwd`。帳號與專案都相符且 `completed` 才用 `prompt` 沿用；不同專案就建立新的「帳號別名-用途」worker 並指定 `--cwd`。`working` 先等待，`blocked`／`unknown` 先讀取畫面，`closed` 可同名 `start` 重建。帳號不符時不派工。
3. 新 worker：

   ```sh
   codex-workers start "$worker_name" --account "$account_alias" --cwd "$project_dir" --task "$task"
   ```

   省略 `--cwd` 會沿用呼叫端目錄。`start` 預設以 `codex --no-daemon --yolo` 啟動，略過該 worker 的 sandbox 與核准提示，不需另加參數。就緒後只送一次並返回。多個 `start` 可同時執行，等待就緒期間不會擋住其他 worker 的派工、追加或完成後操作；逐一檢查每個回傳。啟動失敗會留下 `startup_failed`：Herdr 確認 pane 已不存在時釋放名稱、可同名重試；否則回 `duplicate_name`，先檢查該 pane 或改用新名稱。
4. 追蹤與收取結果：

   ```sh
   codex-workers wait "$worker_a" "$worker_b" --timeout 30
   codex-workers status "$worker_name"
   codex-workers read "$worker_name" --lines 120
   ```

   `wait` exit code：0＝completed、3＝blocked、4＝unknown／closed、124＝timeout。送出成功、剛啟動的 idle、blocked、unknown 與 timeout 都不代表完成；逾時會保留 worker。只給一個名稱時，輸出就是該 worker 的狀態。

   多個 worker 同時工作時，把所有尚未處理的 worker 交給同一個 `wait`，不要長時間只等其中一個。任一個結束（completed、blocked、unknown 或 closed）就返回：`settled` 列出已結束的名稱，`workers` 列出每個 worker 的狀態，`state` 為 `settled` 或 `timeout`。exit code 取已結束者中最嚴重的一項，有 blocked 或 unknown 就不是 0。處理完 `settled` 中的 worker 後，把它們移出名單再繼續 `wait`，否則會立即返回。
5. 完成後追加任務：`codex-workers prompt "$worker_name" "$followup_task"`。
6. 每個 worker 每輪 `completed` 後立即 `read` 辨識本輪成果，再詢問完成後選擇，不等整批結束。檢查實際成果與驗收證據後再整合；回報帳號、任務、狀態、成果及未完成事項，不憑 worker 宣稱完成就認定通過。

## 完成後選擇

- `status`／`wait` 在 `completed` 時回傳 `completion_id` 與 `completion_prompt`。`pending: true` 時，用提問工具詢問使用者「保留、執行 /compact、關閉 pane」，附帳號、worker 名稱與本輪成果摘要。同一個 `completion_id` 已問未答時不重問；其他 worker 繼續工作。
- 未回答時保留 pane，不自行選擇。使用者選定後執行（`keep`／`compact`／`close`）：

  ```sh
  codex-workers finish "$worker_name" --completion-id "$completion_id" --action keep
  ```

  選擇只適用該輪；追加任務完成後會有新 ID，再問一次。CLI 會重新核對身分、目錄、完成狀態與 ID，拒絕主 pane、過期與已處理的選擇。
- `compact_submitted` 只代表原樣 `/compact` 已送出且代理就緒；再 `read` 核對實際結果。不要用 `prompt` 傳 slash command，語言說明會改變指令。壓縮不算新任務，不觸發完成提問。
- `closed` 表示 pane 已關閉，帳號授權與 session 歷史保留。`maintenance_unknown` 不代表成功：先 `read` 核對，不重送，不刪除紀錄重試。
- `status` 回 `reason: "pane_missing"` 時，只能 `finish --action close` 記錄關閉，見 operations.md「罕見狀態與失敗」。

## 讀取與驗收

- `read` 的 `text` 是終端機畫面，可能含使用者 prompt 與舊回覆；辨識本輪的 assistant 回覆，不把 prompt 中的預期答案當成果。從 text 結尾確認完整回覆與 `Worked for`，開頭可能殘留舊畫面。
- Herdr 回報 `done` 可能早於畫面完成，CLI 會檢查畫面結尾的 `Working (… esc to interrupt)`：仍在執行回 `working`，讀不到畫面回 `unknown`（`screen_unreadable`）。畫面稍後才更新時可短暫再讀，不重送任務。等待一律用 `wait --timeout`，不另寫 sleep 迴圈。
- 長回答可能截斷；加大 `--lines` 仍不足時，該輪完成後用 `prompt` 請 worker 存成檔案再讀取。
- 登入失敗或授權失效時停止派工，請使用者重新登入該帳號；不得回落到主帳號、另一個帳號或環境中的 API key。不讀出 token，不複製主 `auth.json`。只用使用者自己的帳號，不分享帳號，也不用多帳號規避用量限制。
