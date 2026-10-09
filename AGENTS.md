# Codex Workers — 貢獻與 agent 規則

給在本專案工作的人與 coding agent。使用說明見 [README.md](README.md)，派工流程見 [skill/codex-workers/SKILL.md](skill/codex-workers/SKILL.md)。本機私人筆記若存在，放在 `.private/`（不納入版本控制）。

## 專案範圍

- 目標：單一主 agent 在 Herdr 中指揮多個 Codex worker，每個 worker 使用一個以獨立官方登入隔離的帳號。
- 交付方式是 Skill + CLI；目前沒有 MCP server，不自行擴大範圍。
- `codex_workers.py`：CLI 實作，只用 Python 3.11 標準函式庫；`codex-workers`：啟動入口；`install.py`：安裝連結。
- `skill/codex-workers/SKILL.md`：派工流程；`references/setup.md`：安裝與新增帳號。
- `tests/e2e.py` 以 `tests/fake_cli.py` 模擬 Codex 與 Herdr，不需要真實登入或網路。

## 不可退讓的原則

- 帳號別名由使用者自訂。文件、範例與測試不得放入任何真實帳號名稱、Email、路徑或 pane ID；範例用 `<別名>` 或明顯的示意名稱。
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

## 修改與驗證

- 變更前先寫出可能出錯的情境並寫成 `tests/e2e.py` 案例，再改程式；開發時跑相關案例，完成時跑完整 `python3 tests/e2e.py`。
- 模擬測試不等於真實派工。改到授權或派工路徑時，另以真實 Herdr 與自己的帳號驗證，並分開回報。
- 文件變更以讀回、連結與行數檢查驗證。
- 回報須列出改動檔案、實際執行的檢查、結果與未完成事項。
