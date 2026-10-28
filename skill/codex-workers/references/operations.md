# 操作細節

主流程見 [SKILL.md](../SKILL.md)。以下內容只在對應情況發生時讀取。

## Herdr 環境診斷

派工需要 Herdr 注入的 `HERDR_ENV=1` 與 `HERDR_PANE_ID`。工具執行環境缺少變數時可以列出帳號，但停止 pane／agent 操作；這不等於使用者未在 Herdr 中。

1. 先唯讀核對程序鏈與 Codex 的 `shell_environment_policy`，區分「主 agent 未從 Herdr 啟動」與「環境繼承遭過濾」，再提供對應處理方式。
2. 不可自行設定這些變數冒充 caller context，也不可未經授權修改 Codex 設定或重啟工作階段。
3. 主 agent 工作階段重啟後，`HERDR_PANE_ID` 可能指向已不存在的 pane（`herdr pane get "$HERDR_PANE_ID"` 回 `pane_not_found`），`start` 會在建立 pane 前失敗；請使用者在現有的 Herdr pane 重新開啟主 agent。

## 帳號改名與刪除

- `account rename <舊別名> <新別名>` 與 `account remove <別名>` 只在使用者明確要求、且已確認目標別名後執行。指令行為見 [setup.md](setup.md#改名與刪除)。
- 刪除前要告知使用者：會一併刪除該帳號的登入檔、設定、Codex 對話歷史，以及該帳號已結束的 worker 紀錄，無法復原。
- 該帳號仍有 worker 的 pane 存在或無法確認已消失時，CLI 回 `account_in_use`：先依 SKILL.md「完成後選擇」關閉該 worker，不要繞過。
- 授權過期或登錯帳號時，請使用者刪除後以同一別名重新 `add`。

## 罕見狀態與失敗

- `status` 回 `reason: "pane_missing"` 表示 Herdr 確認 pane 已不存在，並附 `completion_id`。只接受 `finish --action close`：CLI 只把紀錄標為 `closed`，不操作任何 pane；keep／compact 回 `pane_missing`。若是 `agent_not_found`（pane 還在）或查詢失敗，不會記為關閉，請使用者檢查該 pane；不刪除紀錄。
- 預檢失敗可能尚未建立 worker 紀錄；建立 pane 或送出階段的失敗則會保留名稱及已取得的 pane ID。先判讀錯誤與 `status`，有 pane ID 才 `read`；不把無紀錄與送出結果不明混為一談，不盲目重送或任意刪除紀錄來重試。

## 更新既有 worker 的 skill

主 skill 更新不代表既有帳號的 skill 副本或已載入的指引已更新。使用者授權修正既有 workers 的 skills 時，只同步指定 skill，不整包同步設定。取得有效 Herdr context 並確認 worker 已完成後，用 `codex-workers prompt` 請它重新讀取 `$CODEX_HOME/skills/codex-workers/SKILL.md`；該輪仍須收取成果並詢問完成後選擇，不以檔案同步當作真實派工驗收。

## 授權與隔離

- 不讀出 token，也不複製主 `auth.json`。每個帳號的 refresh token 由該帳號的 Codex 自行管理。
- 新 worker 預設使用 `--no-daemon --yolo`，只影響新 worker 的執行權限；不修改主帳號設定、不重啟共享 daemon，也不切換主登入。不要替使用者新增 worktree、覆寫模型，或重啟既有 worker，除非該操作已在任務範圍內獲授權。`prompt` 沿用既有 worker 的啟動權限。
- 每次新啟動同步設定、profiles、規則與 skills，只共用 plugin cache；不複製主 session、歷史資料或 plugin OAuth。`withheld_fields` 表示略過的內嵌憑證／連線欄位。
- 外部工具可能需要工作帳號另行授權。未授權時明確回報，不借用主帳號的連線或放寬權限。
