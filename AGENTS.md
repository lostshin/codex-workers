# Codex Workers — 貢獻與 agent 規則

給在本專案工作的人與 coding agent。使用說明見 [README.md](README.md)，派工流程見 [skill/codex-workers/SKILL.md](skill/codex-workers/SKILL.md)，安裝與新增帳號見 [references/setup.md](skill/codex-workers/references/setup.md)。本機私人筆記若存在，放在 `.private/`（不納入版本控制）。

## 專案範圍

- 目標：單一主 agent 在 Herdr 中指揮多個 Codex worker，每個 worker 使用一個以獨立官方登入隔離的帳號。
- 交付方式是 Skill + CLI；目前沒有 MCP server，不自行擴大範圍。
- `codex_workers.py`：CLI 實作，只用 Python 3.11 標準函式庫；`codex-workers`：shell 入口；`install.py`：建立連結，不覆寫既有檔案。
- `tests/e2e.py` 以 `tests/fake_cli.py` 模擬 Codex 與 Herdr，不需要真實登入或網路。

## 不可退讓的原則

- 帳號別名由使用者自訂。文件、範例、測試與本檔不得放入真實帳號別名、Email、本機路徑或 pane ID；範例用 `<別名>` 或明顯的示意名稱。
- 不讀出、列印或複製 token、`auth.json`；不匯入其他工具的憑證。
- 授權失敗時停止，不得回落到主帳號、其他帳號或環境中的 API key。
- 保留主登入、模型、sandbox、核准方式與 caller focus；不重啟共享 daemon，worker 以 `--no-daemon` 啟動。
- pane／agent 操作須有 Herdr 真正注入的 `HERDR_ENV=1` 與 `HERDR_PANE_ID`；不得自行設定變數冒充。
- 送出結果不明時標記 unknown，不自動重送；不自動刪除紀錄來重試。

## Herdr 與 Codex 的已知行為

- `wait`：0＝completed、3＝blocked、4＝unknown／closed、124＝timeout；後三者都不代表完成。
- Herdr 的 `agent read` 成功輸出是純文字，其他指令回傳 JSON；不要假設所有指令都回 JSON。
- Herdr 回報 `done` 可能早於 Codex 畫面完成，CLI 會檢查畫面結尾的 `Working (… esc to interrupt)` 再判定完成。
- pane 消失時 Herdr 對 `pane get` 回 `pane_not_found`、對 `agent get` 回 `agent_not_found`；只有前者能證明 pane 已不存在。
- `status` 不含 cwd，重用 worker 前用 `herdr agent get` 的 `result.agent.cwd` 核對；`prompt` 不會切換目錄。
- `read` 回傳的是終端機畫面，含使用者 prompt 與舊回覆；驗收要辨識本輪的 assistant 回覆，不把 prompt 中的預期答案當成結果。

## 指令速查

```sh
python3 tests/e2e.py                                       # 完整測試（49 項，約 40 秒），寫入 evidence/e2e.json（不納入版控）
cd tests && python3 -m unittest e2e.Workflow.test_<name>   # 單一測試
./codex-workers --help                                     # 本機 CLI
```

- `python3 tests/e2e.py <測試名>` 會忽略參數並跑完整套件，不能用來篩選。
- 沒有 lint 或 build 步驟，不要捏造這類指令。

## 修改與驗證

- 變更前先寫出可能出錯的情境並寫成 `tests/e2e.py` 案例，再改程式；開發時跑相關案例，完成時跑完整 `python3 tests/e2e.py`。
- 模擬測試不等於真實派工。改到授權或派工路徑時，另以真實 Herdr 與自己的帳號驗證，並分開回報。
- 文件變更以讀回、連結與行數檢查驗證。
- 回報須列出改動檔案、實際執行的檢查、結果與未完成事項。

## 真實派工驗證

- 測試 worker 用一次性工作目錄（scratchpad 或其他非專案目錄），名稱用 `<別名>-check`。
- 任務寫具體文字，不用 `<...>` 佔位符：佔位符會被 agent 誤解（實測回覆只剩 `own`）。
- 驗證後以 `status` 取得 `completion_id`，再 `finish --action close`。逐一指定參數，不用 shell 迴圈帶整行字串。
- 驗證結果只記錄通過與否，不記錄帳號別名或 pane ID。

## 已決策事項（不要重新提出，除非使用者要求）

- `start` 預設 `--yolo`：2026-10-10 安全審查標為 HIGH，使用者選擇維持現狀。README 與 SKILL 已有警語。若要收斂，需使用者另行決定（較安全的預設，或明確 opt-in 旗標）。
- 不建立 `CLAUDE.md`：使用者不需要。Claude Code 不會自動讀 `AGENTS.md`；若要自動載入，先問使用者，不要自行建立。
- Repo 已公開於 GitHub，授權 MIT。推送、改動 remote、發布屬對外動作，須先確認。

## 專案狀態（2026-10-10）

- 初始 commit 已推送至公開 GitHub repo（`origin`，分支 `main`）；作者 Email 由使用者指定。
- `tests/e2e.py` 49 項通過；三個真實帳號各自完成測試派工並回覆，測試 worker 已關閉。
- 本次 `AGENTS.md` 更新尚未 commit，等使用者要求再提交。
- 根目錄的 `*.bak*` 與 `__pycache__` 是本機產物，已被 `.gitignore` 排除。

## Git 與 shell 陷阱

- 暫存時明確列出檔案，不用 `git add -A`；提交前用 `git status --short` 確認沒有備份檔或 `.private/`。
- commit 作者用 `GIT_AUTHOR_*`／`GIT_COMMITTER_*` 環境變數指定，不改 `git config`。Email 每次由使用者指定，不沿用 `git config` 的預設值。
- 本機 Bash 工具是 zsh：未加引號的變數不會拆字（`set -- $pair` 得到整串）。迴圈傳多個參數時，直接寫明參數或用陣列。

## 規則維護

- 只收錄重複出現、可歸因、窄改動可解的失敗模式；一次性失誤不入規則。
- 修改前先檢查「已決策事項」，不推翻使用者已確認的方向。
- 本檔是專案規則的單一來源；不要在本檔寫入真實帳號、Email、路徑或 pane ID。
