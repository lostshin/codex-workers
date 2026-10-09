# 安裝與帳號登入

僅在 CLI 缺失或需要新增帳號時讀取本檔。

## CLI 與 skill

需要 Python 3.11+、支援 `--no-daemon` 的 Codex，以及支援 `pane split --env` 的 Herdr。在 Codex Workers 專案執行 `python3 install.py`（Claude Code 使用者加 `--claude`），再用 `codex-workers --help` 驗證；`~/.local/bin` 須在 PATH 中。安裝程式不覆寫其他工具的既有檔案。

`install.py` 建立指向專案的連結：`~/.local/bin/codex-workers`、`~/.codex/skills/codex-workers`，加 `--claude` 時另有 `~/.claude/skills/codex-workers`。保留專案位置；移動專案需要重新安裝連結。若 skill 目錄已被其他工具管理（不是指向本專案的連結），安裝程式會拒絕覆寫；此時修改專案的 `skill/codex-workers/` 後，要自行把改動同步到該工具管理的副本。新 session 才能保證使用更新後的 skill 描述；既有 session 可直接讀取安裝路徑的 `SKILL.md`。

## 新增帳號

別名由使用者自訂，agent 不代取。一次只登入一個帳號：

1. 請使用者決定別名，並先用無痕視窗或登出其他帳號，確保瀏覽器登入的是要加入的帳號。
2. 由使用者執行 `codex-workers account add <別名>`（Claude Code 在輸入框加 `!` 前綴），依畫面網址與一次性代碼完成登入。這一步要使用者在瀏覽器確認，agent 不代為操作，也不讀取或複製主登入憑證。
3. 指令可能超過工具的執行時限而轉到背景。讀取其輸出或 `codex-workers account list --json` 確認結果，不要再執行一次；重跑會回 `account_exists`，不影響第一次的登入。
4. 登入失敗且沒有登入檔時，可用相同別名重試。別名已有登入檔時 `account add` 不會覆寫；要換帳號請使用者另取別名。

帳號資料存於 `~/.local/share/codex-workers/accounts/<別名>/`（可用 `CODEX_WORKERS_HOME` 改位置）。`login_file: "present_unverified"` 只表示登入檔存在，實際派工成功才證明授權可用。

## 改名與刪除

- `codex-workers account rename <舊別名> <新別名>`：搬移帳號目錄並更新該帳號 worker 紀錄中的帳號名稱；新別名已存在時拒絕。改名後請用新別名建立 worker，舊 worker 名稱不會自動改變。
- `codex-workers account remove <別名>`：刪除該帳號的登入檔、設定與 Codex 對話歷史，並清除該帳號已結束的 worker 紀錄；無法復原。目錄中指向主 Codex `plugins/cache` 的連結只會移除連結本身，主設定不受影響。
- 兩者在該帳號仍有 worker 的 pane 存在、或無法向 Herdr 確認 pane 已消失（包括不在 Herdr 內執行）時，回 `account_in_use` 並不做任何變更。先關閉該 worker 再重試。
- 授權過期或登錯帳號：先 `remove`，再以同一別名 `add` 重新登入。
