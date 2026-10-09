# Codex Workers

Codex Workers 讓你在 Claude Code 或 Codex 中，把任務派給多個 Codex worker 同時執行。每個 worker 使用你自己的一個獨立登入帳號，並有獨立的 `CODEX_HOME`，所以登入、設定與對話紀錄不會在 worker 之間共用。

它由兩部分組成：

- **skill**（`codex-workers`）：讓主 agent（Claude Code 或 Codex）知道派工流程。你在主 agent 中呼叫它派工、追蹤與收取結果。
- **CLI**（`codex-workers` 命令）：skill 透過它操作 [Herdr](https://github.com/herdrdev/herdr) 的 pane 與 worker。skill 無法獨立運作，所以兩者都要安裝。

CLI 只使用 Python 3.11 標準函式庫。

> **English summary:** A CLI + agent skill that lets one main agent (Claude Code or Codex) dispatch tasks to multiple Codex CLI workers inside Herdr panes, each running under its own separately logged-in account and `CODEX_HOME`. macOS only (tested). Docs are in Traditional Chinese; the worker language prompt is configurable via `CODEX_WORKERS_LANGUAGE_PROMPT`.

## 介紹影片

![介紹影片：一個主 agent 指揮多個隔離帳號的 Codex worker](docs/intro.gif)

完整影片（畫質較好）：[docs/intro.mp4](docs/intro.mp4)。

## 基本概念

| 名詞 | 意思 |
|---|---|
| 主 agent | 你正在使用的 Claude Code 或 Codex。它呼叫 skill，負責派工、等待結果與收取成果。 |
| skill | 安裝在 `~/.codex/skills/` 或 `~/.claude/skills/` 的派工流程說明。主 agent 依它操作 CLI。 |
| worker | 由工具在 Herdr pane 中啟動的 Codex，負責執行一個任務。 |
| 帳號別名 | 你為登入帳號取的名字，例如 `work`。由你自己決定。 |
| worker 名稱 | 派工時使用的名字，必須是「帳號別名」或「帳號別名-用途」，例如 `work-review`。 |
| pane | Herdr 中的終端機區塊。每個 worker 佔用一個 pane。 |
| `completion_id` | 某一輪任務完成時的識別碼。完成後的選擇（保留、壓縮或關閉）必須帶上它。 |

適合的情境：同一個專案的幾項獨立工作（例如程式審查與文件整理）要同時進行，或要把個人與工作帳號分開使用。

## 使用前請先讀

- **worker 預設以 `--yolo` 執行。** 新 worker 會略過 Codex 的 sandbox 與核准提示，可以直接修改 `--cwd` 目錄中的檔案並執行指令。只有在你信任任務內容，且專案有版本控制時才使用。
- **只使用你自己的帳號。** [OpenAI 使用條款](https://openai.com/policies/terms-of-use/) 規定不得分享帳號（"You may not share your account credentials or make your account available to anyone else"），也不得規避用量限制（"circumvent any rate limits or restrictions"）。本工具用來隔離你自己的不同帳號（例如個人與工作帳號），不是用多個帳號繞過額度。是否符合條款由你自行判斷並負責。

## 需求

| 項目 | 需求 |
|---|---|
| 作業系統 | macOS（唯一實測過的環境；Linux 未測試） |
| Python | 3.11 以上 |
| Codex CLI | 支援 `--no-daemon` 與 `codex login --device-auth`（實測 v0.162.0） |
| Herdr | 支援 `pane split --env`（實測 0.9.3） |
| 主 agent | 必須在 Herdr 的 pane 中啟動。CLI 需要 Herdr 注入的 `HERDR_ENV` 與 `HERDR_PANE_ID`。若主 agent 重新啟動後原 pane 已不存在，請在現有的 pane 中重新開啟主 agent。 |
| 帳號 | 每個 worker 帳號都必須是你自己的 ChatGPT 帳號，且方案包含 Codex。每個帳號都要登入一次。 |
| PATH | `~/.local/bin` 在 PATH 中 |

### 安裝必要工具

依序安裝，每一項擇一即可：

```sh
brew install --cask codex          # Codex CLI，或 npm install -g @openai/codex
brew install herdr                 # Herdr，或 curl -fsSL https://herdr.dev/install.sh | sh
```

安裝 Herdr 後，在終端機執行 `herdr` 啟動，再在其中的 pane 啟動 Claude Code 或 Codex 作為主 agent。

skill 在派工前會自動檢查上述工具。缺少時，它會列出缺少的項目與對應的安裝指令，不會自行安裝。完整的安裝方式見 [skill/codex-workers/references/setup.md](skill/codex-workers/references/setup.md)。

## 安裝

安裝會同時安裝 CLI 與 skill：

```sh
git clone https://github.com/lostshin/codex-workers
cd codex-workers
python3 install.py            # 使用 Codex
python3 install.py --claude   # 使用 Claude Code（同時也安裝 Codex 的 skill）
codex-workers --help          # 確認 CLI 可以執行
```

安裝程式建立以下連結，都指向本專案：

| 連結位置 | 內容 |
|---|---|
| `~/.local/bin/codex-workers` | CLI 命令 |
| `~/.codex/skills/codex-workers` | Codex 的 skill |
| `~/.claude/skills/codex-workers` | Claude Code 的 skill，只有加上 `--claude` 才會建立 |

注意事項：

- 安裝程式不覆寫既有檔案。若目標位置已有其他工具管理的 skill，安裝會停止並列出路徑。
- 移動專案後，需要重新執行安裝。
- 安裝或更新 skill 後，請開新的 session，確保主 agent 讀到最新的 skill 內容。

## 在 Claude Code 或 Codex 中使用

### 1. 準備

1. 在 Herdr pane 中啟動主 agent（Claude Code 或 Codex）。主 agent 必須在 Herdr 內執行，否則 CLI 無法控制 pane。
2. 新增要使用的帳號。每個帳號只需要做一次。別名由你自己取，格式為小寫英文字母開頭、最多 32 字元，可含數字、`_`、`-`。
   - **Claude Code：** 在輸入框輸入 `! codex-workers account add <別名>`。`!` 會在目前的 session 中執行這個命令，畫面的網址與代碼會直接顯示在對話中。
   - **Codex 或一般終端機：** 執行 `codex-workers account add <別名>`。
   - 在瀏覽器開啟畫面上的網址、輸入一次性代碼，並登入要加入的帳號。建議使用無痕視窗，以免誤用其他已登入的帳號。
3. 確認帳號：

   ```sh
   codex-workers account list --json
   ```

   `login_file` 為 `present_unverified` 只代表登入檔存在，不代表授權仍有效。實際派工成功，才能證明授權可用。其他值的意思見[疑難排解](#疑難排解)。

### 2. 派工

在主 agent 中呼叫 skill，後面接上你的任務與帳號。Claude Code 的寫法如下：

```text
/codex-workers 用 work 帳號檢查這個專案的 README，列出不清楚的段落。不要修改任何檔案。
```

在 Codex 中呼叫 skill 的方式，依你使用的 Codex 版本而定，請參考該版本的 skill 說明。

skill 會依照下列流程操作：

1. 檢查帳號與既有的 worker。
2. 建立 worker、送出任務。多個 worker 可以同時進行。
3. 追蹤進度，worker 完成後讀取本輪成果。
4. 詢問你完成後要怎麼處理（見下方〈完成後選擇〉）。
5. 依你的選擇執行，並檢查實際成果後，再整合各 worker 的結果。

skill 不會自動關閉 pane。完成後要保留、壓縮或關閉，由你決定。

### 完成後選擇

每個 worker 完成一輪任務後，skill 會詢問你要怎麼處理：

| 選擇 | 結果 |
|---|---|
| `keep` | 保留 pane，之後可以繼續追加任務或再次讀取。 |
| `compact` | 送出 `/compact` 並保留 pane。這不算新任務。工具只確認指令已送出，請用 `read` 查看實際結果。 |
| `close` | 關閉 pane。帳號的登入與對話歷史會保留。 |

選擇只適用該輪任務。下一輪完成後，會取得新的 `completion_id`，需要重新選擇。

### 注意事項

- 同名 worker 在上一輪完成後可以追加任務。要在不同專案工作，請使用新的 worker 名稱，並指定 `--cwd`。
- 多個 worker 寫入同一個目錄時，請在任務中明確分配各自負責的檔案。
- 主 agent 重新啟動後，若原 pane 已不存在，派工會在建立 pane 前失敗。請在現有的 pane 中重新開啟主 agent。

## 直接使用 CLI

當你要除錯、手動操作，或沒有使用 skill 時，可以直接執行 CLI：

```sh
codex-workers start work-review --account work --task 'Review this project and list potential bugs. Do not change files.'
codex-workers wait work-review --timeout 120
codex-workers read work-review
codex-workers status work-review
codex-workers finish work-review --completion-id <completion_id> --action close
```

範例中的 `work` 與 `work-review` 是示意名稱，請換成你自己的。`<completion_id>` 請填入 `status` 在 worker 完成時回傳的值。

| 指令 | 用途 |
|---|---|
| `account add <別名>` | 建立帳號目錄，並執行官方 device login。登入憑證固定以檔案保存。 |
| `account list --json` | 列出帳號別名與登入檔狀態，不讀取檔案內容。 |
| `account rename <舊別名> <新別名>` | 更改帳號別名。worker 仍在執行時會拒絕。 |
| `account remove <別名>` | 刪除帳號的登入檔、設定、對話歷史與已結束的 worker 紀錄。worker 仍在執行時會拒絕。 |
| `start <名稱> --account <別名> --task <文字>` | 建立 pane、同步設定、送出任務，然後立即返回。 |
| `prompt <名稱> <文字>` | 上一輪完成後追加任務。 |
| `status <名稱>` | 回傳 JSON 狀態：`working`、`completed`、`blocked`、`unknown` 或 `closed`。 |
| `wait <名稱> --timeout <秒>` | 等待 worker 完成。預設 120 秒。逾時不會終止 worker。 |
| `read <名稱> --lines <n>` | 讀取近期畫面。預設 120 行。 |
| `finish <名稱> --completion-id <id> --action keep\|compact\|close` | 依你的選擇處理已完成的 worker。 |

`start` 的選用參數：

- `--cwd <目錄>`：worker 的工作目錄。預設為執行指令時的目錄。
- `--direction right|down`：切分 pane 的方向。未指定時由工具決定。
- `--startup-timeout <秒>`：等待新 pane 就緒的時間。預設 30 秒。

所有指令都以 JSON 輸出結果。`wait` 的結束代碼如下：

| 代碼 | 意思 |
|---|---|
| 0 | completed |
| 3 | blocked |
| 4 | unknown 或 closed |
| 124 | timeout |
| 1 | 其他失敗 |
| 2 | 參數錯誤 |

代碼 3、4 與 124 都不代表任務已完成。

## 帳號管理

**別名由你自己取。** 你可以隨時改名或刪除帳號：

| 操作 | 指令 |
|---|---|
| 新增 | `codex-workers account add <別名>` |
| 查看 | `codex-workers account list --json` |
| 改名 | `codex-workers account rename <舊別名> <新別名>` |
| 刪除 | `codex-workers account remove <別名>` |

> **警告：** `account remove` 會刪除該帳號的登入檔、設定、Codex 對話歷史與已結束的 worker 紀錄。這些資料**無法復原**。

- 如果該帳號的 worker pane 仍存在，或工具無法向 Herdr 確認 pane 已消失，改名與刪除都會回傳 `account_in_use`，且不做任何變更。請先關閉該 worker。
- 授權過期或登錯帳號時，先執行 `remove`，再以同一別名執行 `add` 重新登入。

## 語言設定

每次派工時，工具預設會在任務前附上「使用台灣繁體中文回報」的說明。你可以用環境變數改變這段說明：

```sh
export CODEX_WORKERS_LANGUAGE_PROMPT='Reply in English.'   # 改用自訂說明
export CODEX_WORKERS_LANGUAGE_PROMPT=''                    # 不附加說明，只送任務原文
```

## 設定與隔離

- 每次啟動 worker 時，工具會把來源目錄（預設為 `~/.codex`，可用 `CODEX_WORKERS_SOURCE` 改變）中的 `config.toml`、`*.config.toml`、`AGENTS.md`、`rules/` 與 `skills/` 複製到該 worker 的 `CODEX_HOME`。模型、profiles、sandbox 與核准設定都會保留。
- plugin 只共用 `plugins/cache`。不共用 `plugins/data`、OAuth、帳號連線、auth、history、sessions 或資料庫。
- 內嵌的憑證、認證 headers 與帶有憑證的 URL 不會被複製。回應中的 `withheld_fields` 會列出被略過的欄位名稱。
- 外部工具可能需要在 worker 帳號中另行授權。
- 既有的 worker 不會因為設定更新而自動重啟。

| 環境變數 | 預設值 | 用途 |
|---|---|---|
| `CODEX_WORKERS_HOME` | `~/.local/share/codex-workers` | 帳號登入與 worker 紀錄 |
| `CODEX_WORKERS_SOURCE` | `~/.codex` | 唯讀的設定來源 |
| `CODEX_WORKERS_LANGUAGE_PROMPT` | 繁體中文說明 | 派工時附加的語言說明 |

`CODEX_WORKERS_HOME` 與 `CODEX_WORKERS_SOURCE` 指向的路徑不得互相重疊。

## 資料位置與移除

- 帳號登入：`~/.local/share/codex-workers/accounts/<別名>/`（權限 0700，內含該帳號的 `auth.json`）
- worker 紀錄：`~/.local/share/codex-workers/workers/`

若要完整移除，請刪除 `install.py` 建立的連結（`~/.local/bin/codex-workers`、`~/.codex/skills/codex-workers`、`~/.claude/skills/codex-workers`），再刪除 `~/.local/share/codex-workers/`。後者會刪除所有 worker 帳號的登入檔。

## 疑難排解

| 症狀或代碼 | 原因與處理 |
|---|---|
| `login_file: missing` | 沒有登入檔。執行 `codex-workers account add <別名>`。 |
| `login_file: invalid_file` | 登入檔是空的或不是一般檔案。刪除該帳號後以同一別名重新 `add`。 |
| `login_file: linked_file_rejected` | 登入檔是符號連結，工具拒絕使用。刪除後以同一別名重新 `add`。 |
| `duplicate_name` | 名稱已被保留。請改用新名稱，或先用 `status` 檢查既有的 worker。 |
| `login_missing` | 該帳號沒有登入檔。執行 `codex-workers account add <別名>`。 |
| `not_in_herdr` | 指令不是在 Herdr pane 中執行。請在 Herdr pane 中執行。不要自行設定 `HERDR_ENV` 或 `HERDR_PANE_ID`。 |
| `account_name_mismatch` | worker 名稱必須是帳號別名，或「帳號別名-用途」。 |
| `account_in_use` | 該帳號的 worker pane 仍存在，或無法確認已消失。請先關閉該 worker。 |
| `worker_not_found` | 找不到這個名稱的 worker 紀錄。 |
| `wait` 結束代碼 4 | worker 狀態為 unknown 或 closed。先用 `status` 與 `read` 查看，工具不會自動重送。 |
| `wait` 結束代碼 124 | 等待逾時，worker 仍在執行。之後可以再次 `wait` 或 `read`。 |
| 送出結果不明（狀態 unknown） | 工具不會自動重送任務。請先用 `read` 或查看 pane。 |
| 登入失敗 | 若沒有登入檔，可用相同別名重試。已有登入檔的別名不會被覆寫。 |
| `read` 只顯示部分內容 | 畫面可能截斷長回答。請在任務完成後，要求 worker 把完整結果存成檔案，再讀取該檔。 |
| 主 agent 重新啟動後無法派工 | 原 pane 可能已不存在。請在現有的 pane 中重新開啟主 agent。 |

## 測試

```sh
python3 tests/e2e.py
```

測試會以匿名的假 Codex 與 Herdr 執行，不使用真實登入或網路。結果寫入 `evidence/e2e.json`（不納入版本控制）。模擬測試不等於真實派工。真實行為請以你自己的帳號在 Herdr 中驗證。

## 更多文件

- [skill/codex-workers/SKILL.md](skill/codex-workers/SKILL.md)：主 agent 使用的完整派工流程。
- [skill/codex-workers/references/setup.md](skill/codex-workers/references/setup.md)：安裝與新增帳號的詳細步驟。

## 授權

[MIT](LICENSE)
