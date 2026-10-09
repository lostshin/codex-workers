# Codex Workers

在 [Herdr](https://github.com/herdrdev/herdr) 中，由一個主 agent（Claude Code 或 Codex）指揮多個 Codex worker。每個 worker 使用一個獨立登入的帳號與獨立的 `CODEX_HOME`，互不共用登入、歷史或連線。CLI 只用 Python 3.11 標準函式庫。

> **English summary:** A CLI + agent skill that lets one main agent dispatch tasks to multiple Codex CLI workers inside Herdr panes, each running under its own separately logged-in account and `CODEX_HOME`. macOS only (tested). Docs are in Traditional Chinese; the worker language prompt is configurable via `CODEX_WORKERS_LANGUAGE_PROMPT`.

## ⚠️ 使用前請先讀

- **worker 預設以 `--yolo` 執行**：新 worker 會略過 Codex 的 sandbox 與核准提示，可以直接修改 `--cwd` 目錄中的檔案並執行指令。只在你信任任務內容、且專案有版本控制的情況下使用。
- **遵守 OpenAI 使用條款**：只使用你自己的帳號。[OpenAI Terms of Use](https://openai.com/policies/terms-of-use/) 規定不得分享帳號（"You may not share your account credentials or make your account available to anyone else"），也不得規避用量限制（"circumvent any rate limits or restrictions"）。本工具的用途是隔離不同帳號（例如個人與工作帳號）各自執行任務，不是用多個帳號繞過額度。是否符合條款由使用者自行判斷與負責。

## 運作前提

| 項目 | 需求 |
|---|---|
| 作業系統 | macOS（唯一實測過的環境；Linux 未測試） |
| Python | 3.11 以上 |
| Codex CLI | 支援 `--no-daemon` 與 `codex login --device-auth`（實測 v0.162.0） |
| Herdr | 支援 `pane split --env`（實測 0.9.3） |
| 主 agent | **必須在 Herdr 的 pane 裡啟動**，CLI 才拿得到 `HERDR_ENV`、`HERDR_PANE_ID`。主 agent 重啟後若原 pane 已不存在，要回到現有 pane 重新開啟 |
| 帳號 | 每個 worker 帳號都是你自己的 ChatGPT 帳號，且方案包含 Codex；每個帳號登入一次 |
| PATH | `~/.local/bin` 在 PATH 中 |

## 安裝

```sh
git clone <本 repo 網址> codex-workers
cd codex-workers
python3 install.py            # Codex 使用者
python3 install.py --claude   # Claude Code 使用者（另外安裝到 ~/.claude/skills）
codex-workers --help
```

安裝程式建立指向本專案的連結，不覆寫既有檔案；移動專案後需重新安裝。

## 新增帳號

**別名由你自己取**（小寫英文字母開頭、最多 32 字元，可含數字、`_`、`-`），例如工作帳號叫 `work`、個人帳號叫 `personal`。每個帳號執行一次，依畫面網址與一次性代碼在瀏覽器登入對應的帳號：

```sh
codex-workers account add <別名>
codex-workers account list --json
```

登入前請確認瀏覽器登入的是要加入的帳號（可用無痕視窗）。工具不讀取或複製主 Codex 的登入檔。`present_unverified` 只表示登入檔存在，實際派工成功才證明授權有效。登入失敗且沒有登入檔時可用相同別名重試；已有登入的別名不會被覆寫。

### 管理帳號

| 操作 | 指令 |
|---|---|
| 新增 | `codex-workers account add <別名>` |
| 查看 | `codex-workers account list --json` |
| 改名 | `codex-workers account rename <舊別名> <新別名>` |
| 刪除 | `codex-workers account remove <別名>` |

- `remove` 會刪除該帳號的登入檔、設定、Codex 對話歷史與已結束的 worker 紀錄，**無法復原**。
- 該帳號仍有 worker 的 pane 存在，或無法向 Herdr 確認 pane 已消失時，改名與刪除都會回 `account_in_use` 且不做任何變更；請先關閉該 worker。
- 授權過期或登錯帳號時，先 `remove` 再以同一別名 `add` 重新登入。

## 派工與追加任務

在 Herdr pane 內執行。worker 名稱須為「帳號別名」或「帳號別名-用途」。以下用示意別名 `work`、`personal`，請換成你自己的：

```sh
codex-workers start work-review --account work --task 'Review this project and list potential bugs. Do not change files.'
codex-workers start personal-docs --account personal --task 'Summarize the project structure. Do not change files.'
codex-workers wait work-review --timeout 120
codex-workers read work-review
codex-workers prompt work-review 'Expand the first finding with evidence.'
codex-workers finish work-review --completion-id <status 回傳的 completion_id> --action close
```

要指定其他工作目錄，加上 `--cwd /path/to/project`。工具建立 sibling pane 並保留主 pane 焦點，不建立 worktree。多個 worker 寫入同一目錄時，請明確分配檔案責任。

安裝 skill 後，也可以直接請主 agent 用 `/codex-workers` 派工，它會依 [SKILL.md](skill/codex-workers/SKILL.md) 的流程操作並在每輪完成時詢問你要保留、壓縮或關閉 worker。

| 指令 | 行為 |
|---|---|
| `account add <別名>` | 建立獨立目錄並執行官方 device login，credential store 固定為 file |
| `account list --json` | 列出別名與登入檔狀態，不讀取檔案內容 |
| `account rename <舊> <新>` | 更改別名；有 worker 仍在執行時拒絕 |
| `account remove <別名>` | 刪除帳號與其對話歷史；有 worker 仍在執行時拒絕 |
| `start <名稱> --account <別名> --task <文字>` | 建立 pane、同步設定，就緒後派工並立即返回 |
| `prompt <名稱> <文字>` | 上一輪完成後追加任務 |
| `status <名稱>` | JSON 狀態：working／completed／blocked／unknown／closed |
| `wait <名稱> --timeout <秒>` | 預設 120 秒，逾時不終止 worker |
| `read <名稱> --lines <n>` | 讀取近期畫面，預設 120 行 |
| `finish <名稱> --completion-id <id> --action keep\|compact\|close` | 依你的選擇處理已完成的 worker |

`start` 可用 `--direction right|down` 指定切分方向，`--startup-timeout` 預設 30 秒。所有結果以 JSON 輸出。`wait` exit code：0＝completed、3＝blocked、4＝unknown／closed、124＝timeout；其他失敗為 1，參數錯誤為 2。

## 語言設定

每次派工預設會在任務前加上「使用台灣繁體中文回報」的說明。可用環境變數改變：

```sh
export CODEX_WORKERS_LANGUAGE_PROMPT='Reply in English.'   # 改用自訂說明
export CODEX_WORKERS_LANGUAGE_PROMPT=''                    # 不加任何說明，只送任務原文
```

## 設定與隔離

- 每次新啟動從 `~/.codex` 讀取 `config.toml`、`*.config.toml`、`AGENTS.md`、`rules/`、`skills/` 同步到 worker；保留模型、profiles、sandbox 與核准方式。
- plugin 只連結 `plugins/cache`；不共用 `plugins/data`、OAuth、帳號連線、auth、history、sessions 或資料庫。內嵌憑證、認證 headers 與帶憑證的 URL 會略過，回應中的 `withheld_fields` 列出欄位名稱。外部工具可能需要在 worker 帳號另行授權。
- 既有 worker 不會自動重啟。

| 環境變數 | 預設 | 用途 |
|---|---|---|
| `CODEX_WORKERS_HOME` | `~/.local/share/codex-workers` | 帳號登入與 worker 紀錄 |
| `CODEX_WORKERS_SOURCE` | `~/.codex` | 唯讀的設定來源 |
| `CODEX_WORKERS_LANGUAGE_PROMPT` | 繁中說明 | 派工時附加的語言說明 |

前兩個路徑不得互相重疊。

## 資料位置與移除

- 帳號登入：`~/.local/share/codex-workers/accounts/<別名>/`（權限 0700，含該帳號的 `auth.json`）
- worker 紀錄：`~/.local/share/codex-workers/workers/`

移除方式：刪除 `install.py` 建立的連結（`~/.local/bin/codex-workers`、`~/.codex/skills/codex-workers`、`~/.claude/skills/codex-workers`），再刪除 `~/.local/share/codex-workers/`。後者會刪除所有 worker 帳號的登入檔。

## 失敗處理

- 重複名稱、缺少登入、無效目錄會在建立 pane 前拒絕。
- 啟動失敗會保留名稱；Herdr 確認 pane 已不存在時才釋放，可同名重試。
- 送出結果不明標記為 unknown，工具不自動重送；先 `read` 或查看 pane。
- 等待逾時保留 worker，可稍後再 `status`／`wait`／`read`。
- pane 被關閉或 agent 被替換時為 unknown，拒絕送任務給替代的 agent。pane 已不存在時，`finish --action close` 只把紀錄標為關閉。
- `read` 是終端機畫面，長回答可能截斷；可在完成後請 worker 把完整結果存檔。

## 測試

```sh
python3 tests/e2e.py
```

以匿名的假 Codex／Herdr 執行，不使用真實登入或網路；結果寫入 `evidence/e2e.json`（不納入版本控制）。模擬測試不等於真實派工，真實行為請以自己的帳號在 Herdr 中驗證。

## 授權

[MIT](LICENSE)
