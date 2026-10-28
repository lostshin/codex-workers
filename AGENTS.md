# Codex Workers — 貢獻與 agent 規則

給在本專案工作的人與 coding agent。使用說明見 [README.md](README.md)，派工流程見 [SKILL.md](skill/codex-workers/SKILL.md)，少用情境見 [operations.md](skill/codex-workers/references/operations.md)，安裝與帳號見 [setup.md](skill/codex-workers/references/setup.md)。本機私人筆記與封存檔放在 `.private/`（不納入版本控制）。

## 專案範圍

- 目標：單一主 agent 在 Herdr 中指揮多個 Codex worker，每個 worker 使用一個以獨立官方登入隔離的帳號。
- 交付方式是 Skill + CLI；目前沒有 MCP server，不自行擴大範圍。
- `codex_workers.py`：CLI 實作，只用 Python 3.11 標準函式庫；`codex-workers`：shell 入口；`install.py`：建立連結，不覆寫既有檔案。
- `tests/e2e.py` 以 `tests/fake_cli.py` 模擬 Codex 與 Herdr，不需要真實登入或網路。

## 不可退讓的原則

- 帳號別名由使用者自訂。文件、範例、測試與本檔不得放入真實帳號別名、Email、本機路徑、pane ID 或 completion ID；範例用 `<別名>` 或明顯的示意名稱。
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
- `finish --action compact` 後，該輪 `completion_prompt.pending` 變成 `false`，同一輪不能再 `close`（回 `completion_already_handled`）。要關閉就直接選 `close`，或追加一輪小任務完成後再 `close`。

## CLI 設計重點（改程式前先讀）

### 全域鎖

- 所有會寫入紀錄或帳號目錄的操作都用 `Workers.locked()`（資料目錄下的 `.lock`）；`status`、`wait`、`read` 不持鎖。
- 安全模式是「先把不確定的 phase 存檔，再做慢的 Herdr 呼叫」。已存下的 phase 本身就是互斥：其他操作看到 `starting`、`submission_unknown`、`maintenance_unknown` 就會拒絕。
- `start`：名稱保留、登入檢查、`codex --help`、`sync_settings`、`pane split` 都在鎖內，存下 pane ID 後才放鎖，接著不持鎖等 shell、啟動 Codex、送出任務。
- `finish --action compact`：存下 `maintenance_unknown` 後放鎖再送 `/compact`；`keep`、`close` 與 `prompt` 很快，整段持鎖。
- `sync_settings` 必須留在鎖內：同一帳號的兩個 worker 共用同一個 `CODEX_HOME`，並行會互相 `rmtree`／`os.replace`。
- `settled_records`（帳號改名或刪除前的檢查）把 `pane_id` 為空的未結束紀錄視為已結束，所以放鎖前必須先存好 pane ID，否則刪除帳號時會刪到啟動中 worker 的目錄。
- 已知未改：`account add` 在互動登入期間持鎖，期間其他 `start` 會排隊（`prompt`／`finish` 不受影響）。

### 多名稱 `wait`

- `wait a b --timeout N`：任一個結束就返回，輸出 `state`（`settled`／`timeout`）、`settled`、`workers`。
- exit code 取已結束者中最嚴重的一項，所以 0 仍代表「所有已結束的 worker 都完成」。
- 只給一個名稱時，輸出與 exit code 必須與舊版完全相同；既有測試與 SKILL 依賴這點。

## 指令速查

```sh
python3 tests/e2e.py                          # 完整測試（53 項；閒置約 40–50 秒），寫入 evidence/e2e.json（不納入版控）
python3 tests/e2e.py Workflow.test_<name>     # 單一測試
python3 tests/e2e.py -k <關鍵字>              # 依名稱篩選；evidence 的 argv 會記錄篩選條件
./codex-workers --help                        # 本機 CLI（repo 版本）
```

- 沒有 lint 或 build 步驟，不要捏造這類指令。
- 篩選要寫 `Workflow.test_x` 或 `-k`；只寫 `test_x` 會找不到測試。

## 修改與驗證

- 變更前先寫出可能出錯的情境並寫成 `tests/e2e.py` 案例，確認它在舊程式上失敗，再改程式；開發時用 `-k` 跑相關案例，完成時跑完整 `python3 tests/e2e.py`。
- 模擬測試不等於真實派工。改到授權或派工路徑時，另以真實 Herdr 與自己的帳號驗證，並分開回報。
- 文件變更以讀回、連結與行數（或 bytes）檢查驗證。
- 回報須列出改動檔案、實際執行的檢查、結果與未完成事項。

### 並行與時間相關的測試

- 假 Herdr 用 `herdr.lock` 保護狀態檔，可同時跑多個 CLI 程序。延遲注入：`FAKE_SHELL_BUSY`（shell 一直未就緒，直到 `--startup-timeout`）、`FAKE_PROMPT_DELAY`（`agent prompt` 前先等待，且不持狀態鎖）。
- 用 `self.background(...)` 在背景啟動慢操作、`self.until(...)` 等到紀錄進入預期 phase，再執行其他操作；以 `assertIsNone(slow.poll())` 證明其他操作沒有排隊等它。
- 時間相依的測試要留足餘裕（慢操作至少 8 秒），高負載時才不會誤判。
- 測試變慢時先看 `uptime` 的負載，再與 HEAD 比較：`git archive HEAD | tar -x -C <scratchpad>/head`，同一組測試在兩邊交替執行。曾出現 40 秒變 90 秒的情況，結果是負載超過 100，程式本身沒有變慢。

## 真實派工驗證

- 先確認目前的 shell 有 Herdr 注入的變數（只印出是否設定，不印出 pane ID）。Claude Code 從 Herdr pane 啟動時，Bash 工具會繼承這些變數，可以直接驗證。
- 用 repo 內的 `./codex-workers`，不要用已安裝的連結，以免驗到舊版。
- 測試 worker 用一次性工作目錄（scratchpad 或其他非專案目錄），名稱用 `<別名>-check`。舊紀錄的 phase 是 `closed` 才能同名重建，先查清楚。
- 任務寫具體文字，不用 `<...>` 佔位符：佔位符會被 agent 誤解（實測回覆只剩 `own`）。
- 驗證並行：兩個 `start` 各包在 `( … ) &` 裡，最後 `wait`，各自記錄開始與結束時間；結束時間相近才代表沒有排隊。
- 驗證後以 `status`／`wait` 取得 `completion_id`，再 `finish --action close`。逐一指定參數，不用 shell 迴圈帶整行字串。
- 驗證結果只記錄通過與否和耗時，不記錄帳號別名、pane ID 或 completion ID。

## Skill 文件

- `SKILL.md` 只放每次派工都會用到的流程（目前約 8 KB）；少用情境放 `references/operations.md`，安裝與帳號指令放 `references/setup.md`。新增內容時先判斷屬於哪一份，不要讓主檔再膨脹。
- 改 CLI 行為時，同步更新 SKILL 中對應的指令與輸出說明；README 也有 CLI 說明，若會過時要提出。
- 已安裝的 skill（`~/.codex/skills/codex-workers` 等）可能是其他工具管理的獨立副本，不是連到 repo 的連結；改 repo 不會自動生效。用 `ls -la` 確認連結目標。同步副本屬於 repo 以外的改動，要先問使用者。
- 預設安裝時，skill 目錄會連到 repo，並在每次 `start` 時被複製到 worker 的 `CODEX_HOME`；`skill/` 底下不要留備份檔或暫存檔。

## 已決策事項（不要重新提出，除非使用者要求）

- `start` 預設 `--yolo`：2026-10-10 安全審查標為 HIGH，使用者選擇維持現狀。README 與 SKILL 已有警語。若要收斂，需使用者另行決定（較安全的預設，或明確 opt-in 旗標）。
- 不建立 `CLAUDE.md`：使用者不需要。Claude Code 不會自動讀 `AGENTS.md`；若要自動載入，先問使用者，不要自行建立。
- Repo 已公開於 GitHub，授權 MIT。推送、改動 remote、發布屬對外動作，須先確認。
- 以下評估過、不值得做（2026-10-28）：測試平行化（時間花在程序啟動）、省略每次 `start` 的設定同步（成本可忽略，且全量同步才能傳播刪除）、改用 `herdr agent wait`（`done` 會早到且只能等一個 target）、為整理而重構 `main()` 的分派或分散的 `HERDR_ENV` 檢查。

## 專案狀態（2026-10-28）

- 初始 commit 已推送至公開 GitHub repo（`origin`，分支 `main`）；作者 Email 由使用者指定。
- 2026-10-28 完成最佳化：多名稱 `wait`、縮小全域鎖、SKILL 瘦身（12.8 KB → 8.2 KB）、測試可篩選、殘檔封存。`tests/e2e.py` 53 項通過；真實 Herdr 驗證通過（兩個 `start` 並行、多名稱 `wait`、compact 期間對另一個 worker `prompt` 不排隊），測試 worker 已關閉。
- 以上改動與本檔已 commit 並推送至 `origin/main`。
- 待使用者決定：
  - README 的 `wait` 說明仍只有單一名稱，測試數量也是舊的。
  - 已安裝的 skill 副本尚未同步新版 SKILL。
  - 舊備份在 `.private/bak/`、舊 evidence 在 `.private/evidence-archive/`，是否刪除由使用者決定。
  - 真實驗證時 worker 畫面出現 `Hook failed — plugin contents changed; hook approval required`，與本專案改動無關，尚未調查。

## Git、備份與 shell 陷阱

- 暫存時明確列出檔案，不用 `git add -A`；提交前用 `git status --short` 確認沒有備份檔或 `.private/`。
- commit 作者用 `GIT_AUTHOR_*`／`GIT_COMMITTER_*` 環境變數指定，不改 `git config`。Email 每次由使用者指定，不沿用 `git config` 的預設值。
- 檔案都在 git 中：工作樹乾淨時直接改，不建立 `.bak`。真的需要備份時放到 `.private/bak/`（保留相對路徑），不要放在原檔旁邊。
- 本機 Bash 工具是 zsh：未加引號的變數不會拆字（`set -- $pair` 得到整串）。迴圈傳多個參數時，直接寫明參數或用陣列。
- `du` 被 alias 覆蓋（回 exit 64），要用 `command du`。macOS 是 BSD 工具：沒有 `cat -A`（改用 `cat -e`），`sed -i` 語法也不同；大段文字替換用 Python 並先 `assert` 舊字串只出現一次。
- 暫存檔放 session 的 scratchpad，不放 `/tmp` 或專案目錄。

## 規則維護

- 只收錄重複出現、可歸因、窄改動可解的失敗模式；一次性失誤不入規則。
- 修改前先檢查「已決策事項」，不推翻使用者已確認的方向。
- 本檔是專案規則的單一來源；不要在本檔寫入真實帳號、Email、路徑或 pane ID。
- 本檔維持在 250 行內；專案狀態只保留最新一次，舊進度交給 git 歷史。
