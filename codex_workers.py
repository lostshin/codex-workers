"""Independent, explicitly selected Codex accounts coordinated through Herdr."""
import argparse
import contextlib
import datetime
import fcntl
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

NAME = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
LANGUAGE_INSTRUCTIONS = ('協作語言：派工、追加任務、進度、交接及成果回報一律使用台灣繁體中文與台灣慣用詞彙。'
                         '程式碼、指令、識別字、路徑及必要原文保留原樣；即使任務原文是英文，說明仍使用台灣繁體中文。\n\n任務內容：\n')

def with_language(task):
    # CODEX_WORKERS_LANGUAGE_PROMPT replaces the default note; an empty value sends the task unchanged.
    note = os.environ.get('CODEX_WORKERS_LANGUAGE_PROMPT')
    if note is None:
        return LANGUAGE_INSTRUCTIONS + task
    return note.strip() + '\n\n' + task if note.strip() else task
AUTH_ENV = ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN',
            'OPENAI_ACCESS_TOKEN', 'CODEX_AUTH_JSON')
EXCLUDED = {'auth.json', 'mcp_auth.json', 'history.jsonl', 'sessions',
            'archived_sessions', 'logs', 'log', 'data', '.git', '__pycache__'}

class Failure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

def check_name(name):
    if not NAME.fullmatch(name):
        raise Failure('invalid_name', '名稱須為小寫英文字母開頭，最多 32 字元，可含數字、_、-。')
    return name

def check_worker_name(name, account):
    check_name(name)
    check_name(account)
    if name != account and not (name.startswith(account + '-') and len(name) > len(account) + 1):
        raise Failure('account_name_mismatch', 'worker 名稱須為實際帳號名，或實際帳號名-用途。')

def completion_id(record):
    # Older records have no task ID; their pane and baseline still identify the turn.
    return record.get('task_id') or f"{record['pane_id']}:{record.get('completion_before')}"

def private_dir(path):
    if path.is_symlink():
        raise Failure('unsafe_path', f'拒絕使用連結目錄：{path}')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)

def atomic_text(path, text):
    fd, temporary = tempfile.mkstemp(prefix='.workers-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def atom(value):
    """Serialize TOML values as inline tables, retaining decoded semantics."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return 'nan'
        return str(value)
    if isinstance(value, list):
        return '[' + ', '.join(atom(x) for x in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(atom(k) + ' = ' + atom(v) for k, v in value.items()) + '}'
    raise Failure('invalid_config', '設定含無法處理的 TOML 值。')

def credential_key(key):
    return bool(re.search(r'(^|[_-])(token|secret|password|credential|api[_-]?key)($|[_-])', key, re.I))

def credential_url(value):
    if not isinstance(value, str) or '://' not in value:
        return False
    url = urlsplit(value)
    return bool(url.username or url.password or any(credential_key(k) for k, _ in parse_qsl(url.query)))

def clean_config(value, warnings, prefix=''):
    """Do not import inline secrets or shared remote/account connections."""
    if isinstance(value, list):
        return [clean_config(x, warnings, prefix) for x in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        field = prefix + key
        # Public top-level token budgets are settings, not credentials.
        token_setting = (key in {'model_auto_compact_token_limit', 'model_auto_compact_token_limit_scope',
                                 'tool_output_token_limit'} and (not prefix or prefix.endswith(':')))
        if key in {'cli_auth_credentials_store', 'mcp_oauth_credentials_store'}:
            result[key] = 'file'
        elif (key in {'CODEX_HOME', 'http_headers', 'bearer_token', 'experimental_bearer_token',
                      'remote', 'remote_auth', 'chatgpt_auth_tokens', 'account', 'accounts'}
              or (credential_key(key) and not token_setting) or credential_url(child)):
            warnings.append(field)
        else:
            result[key] = clean_config(child, warnings, field + '.')
    return result

def excluded(name):
    return (name in EXCLUDED or name.endswith(('.sqlite', '.sqlite-wal', '.sqlite-shm', '.db'))
            or name.startswith(('history.', 'auth.', '.credentials')))

def copy_resources(source, target, source_home, ancestors=()):
    resolved = source.resolve(strict=True)
    if resolved in ancestors:
        raise Failure('resource_cycle', '規則或 skills 包含循環連結。')
    relative = resolved.relative_to(source_home) if resolved.is_relative_to(source_home) else None
    if excluded(resolved.name) or (relative and any(excluded(part) for part in relative.parts)):
        raise Failure('unsafe_resource', '規則或 skills 連結指向帳號或歷史資料。')
    if resolved.is_dir():
        target.mkdir(mode=0o700)
        for entry in sorted(source.iterdir()):
            if not excluded(entry.name):
                copy_resources(entry, target / entry.name, source_home, ancestors + (resolved,))
    elif resolved.is_file():
        shutil.copyfile(resolved, target)
        target.chmod(resolved.stat().st_mode & 0o700)

def sync_settings(source, home):
    if not (source / 'config.toml').is_file():
        raise Failure('missing_config', f'找不到主設定：{source / "config.toml"}')
    warnings, managed = [], []
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=home) as temporary:
        stage = Path(temporary)
        for config in [source / 'config.toml', *sorted(source.glob('*.config.toml'))]:
            values = clean_config(tomllib.loads(config.read_text()), warnings, config.name + ':')
            values['cli_auth_credentials_store'] = 'file'
            values['mcp_oauth_credentials_store'] = 'file'
            text = '\n'.join(atom(k) + ' = ' + atom(v) for k, v in values.items()) + '\n'
            if tomllib.loads(text) != values:
                raise Failure('config_roundtrip', '設定語意驗證失敗，未啟動代理。')
            (stage / config.name).write_text(text)
            managed.append(config.name)
        for name in ('AGENTS.md', 'rules', 'skills'):
            if (source / name).exists():
                copy_resources(source / name, stage / name, source)
                managed.append(name)
        # Plugin data and app-server connections are deliberately not shared.
        if (source / 'plugins' / 'cache').is_dir():
            (stage / 'plugins').mkdir(mode=0o700)
            (stage / 'plugins' / 'cache').symlink_to(source / 'plugins' / 'cache', target_is_directory=True)
            managed.append('plugins')
        manifest = home / '.workers-sync.json'
        previous = json.loads(manifest.read_text()) if manifest.is_file() else []
        allowed = {'config.toml', 'AGENTS.md', 'rules', 'skills', 'plugins'}
        for name in set(previous) | set(managed):
            if name not in allowed and not re.fullmatch(r'[\w.-]+\.config\.toml', name):
                raise Failure('invalid_manifest', '同步清單含非法路徑。')
            destination = home / name
            if destination.is_symlink() or destination.is_file():
                destination.unlink()
            elif destination.is_dir():
                shutil.rmtree(destination)
            if name in managed:
                os.replace(stage / name, destination)
        atomic_text(manifest, json.dumps(managed))
    return {'withheld_fields': sorted(set(warnings)),
            'tool_authorization': '外部工具可能需在此帳號另行授權；未複製連線與 OAuth 資料。'}

def isolated_env(home):
    env = dict(os.environ, CODEX_HOME=str(home))
    for name in AUTH_ENV:
        env.pop(name, None)
    return env

def auth_status(home):
    auth = home / 'auth.json'
    if auth.is_symlink():
        return 'linked_file_rejected'
    if not auth.exists():
        return 'missing'
    if not auth.is_file() or auth.stat().st_size == 0:
        return 'invalid_file'
    return 'present_unverified'

class Workers:
    def __init__(self):
        self.root = Path(os.environ.get('CODEX_WORKERS_HOME',
                                       str(Path.home() / '.local/share/codex-workers'))).expanduser().absolute()
        self.source = Path(os.environ.get('CODEX_WORKERS_SOURCE', str(Path.home() / '.codex'))).expanduser().resolve()
        resolved = self.root.resolve()
        if resolved.is_relative_to(self.source) or self.source.is_relative_to(resolved):
            raise Failure('unsafe_root', '工具資料目錄不得與主 Codex 設定目錄重疊。')

    @contextlib.contextmanager
    def locked(self):
        private_dir(self.root)
        lock = self.root / '.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def home(self, alias):
        check_name(alias)
        accounts = self.root / 'accounts'
        if accounts.is_symlink() or (accounts / alias).is_symlink():
            raise Failure('unsafe_account', '拒絕使用連結帳號目錄。')
        return accounts / alias

    def record_path(self, name):
        check_name(name)
        records = self.root / 'workers'
        private_dir(records)
        return records / (name + '.json')

    def save(self, record):
        atomic_text(self.record_path(record['name']), json.dumps(record, ensure_ascii=False) + '\n')

    def load(self, name):
        path = self.record_path(name)
        if not path.is_file() or path.is_symlink():
            raise Failure('worker_not_found', '找不到本工具建立的代理。')
        return json.loads(path.read_text())

    def herdr(self, *args, timeout=15):
        if os.environ.get('HERDR_ENV') != '1':
            raise Failure('not_in_herdr', '請在 Herdr pane 內執行（HERDR_ENV=1）；未控制任何 session。')
        try:
            p = subprocess.run(['herdr', *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Failure('herdr_timeout', 'Herdr 回應逾時；未重送或終止代理。') from None
        if p.returncode == 0 and args[:2] == ('agent', 'read'):
            return {'read': {'text': p.stdout}}
        try:
            reply = json.loads(p.stdout if p.returncode == 0 else p.stderr)
        except json.JSONDecodeError:
            raise Failure('herdr_invalid_response', 'Herdr 回應無法解析；請檢查原 pane，勿盲目重送。') from None
        if p.returncode or 'error' in reply:
            code = reply.get('error', {}).get('code', 'herdr_failure')
            raise Failure(code, 'Herdr 操作未確認成功；請檢查 pane，工具不會重送。')
        return reply['result']

    def add(self, alias):
        with self.locked():
            home = self.home(alias)
            if auth_status(home) != 'missing':
                raise Failure('account_exists', '帳號已有登入；不覆寫。')
            private_dir(home.parent)
            private_dir(home)
            report = sync_settings(self.source, home)
            # Keep official interactive/device login on the caller's terminal.
            result = subprocess.run(['codex', '--no-daemon', '-c', 'cli_auth_credentials_store="file"',
                                     'login', '--device-auth'], env=isolated_env(home))
            if result.returncode or auth_status(home) != 'present_unverified':
                raise Failure('login_failed', '官方登入未完成；可用相同 alias 重試，不會借用其他帳號。')
            (home / 'auth.json').chmod(0o600)
            return {'account': alias, 'login_file': auth_status(home), **report}

    def list_accounts(self):
        directory = self.root / 'accounts'
        if directory.is_symlink():
            raise Failure('unsafe_account', '拒絕使用連結帳號目錄。')
        accounts = []
        if directory.is_dir():
            for home in sorted(directory.iterdir()):
                if NAME.fullmatch(home.name) and home.is_dir():
                    state = 'linked_directory_rejected' if home.is_symlink() else auth_status(home)
                    accounts.append({'alias': home.name, 'login_file': state})
        return {'accounts': accounts, 'note': '登入檔存在不代表 token 仍有效。'}

    def existing_home(self, alias):
        home = self.home(alias)
        if not home.is_dir():
            raise Failure('account_not_found', '找不到這個帳號別名。')
        return home

    def settled_records(self, alias):
        # Every unfinished worker must be confirmed gone by Herdr before its account changes.
        records = self.root / 'workers'
        found = []
        for path in sorted(records.glob('*.json')) if records.is_dir() else []:
            record = json.loads(path.read_text())
            if record.get('account') != alias:
                continue
            if record['phase'] != 'closed' and not self.pane_missing(record.get('pane_id')):
                raise Failure('account_in_use', f'{record["name"]} 的 pane 仍存在或無法確認已消失；請先關閉該 worker。')
            found.append((path, record))
        return found

    def remove(self, alias):
        with self.locked():
            home = self.existing_home(alias)
            found = self.settled_records(alias)
            shutil.rmtree(home)
            for path, _ in found:
                path.unlink()
            return {'account': alias, 'removed_workers': [record['name'] for _, record in found],
                    'note': '已刪除該帳號的登入檔、設定與對話歷史。'}

    def rename(self, alias, new_alias):
        with self.locked():
            home = self.existing_home(alias)
            target = self.home(new_alias)
            if target.exists() or target.is_symlink():
                raise Failure('account_exists', '新別名已存在；不覆寫。')
            found = self.settled_records(alias)
            os.rename(home, target)
            for path, record in found:
                record['account'] = new_alias
                atomic_text(path, json.dumps(record, ensure_ascii=False) + '\n')
            return {'account': new_alias, 'previous': alias,
                    'updated_workers': [record['name'] for _, record in found]}

    def identity(self, record):
        agent = self.herdr('agent', 'get', record['pane_id'])['agent']
        if agent.get('name') != record['name'] or agent.get('pane_id') != record['pane_id'] or agent.get('agent') != 'codex':
            raise Failure('worker_replaced', 'pane 中的代理已更換，拒絕派工。')
        if not agent.get('cwd') or Path(agent['cwd']).resolve() != Path(record['cwd']).resolve():
            raise Failure('worker_cwd_mismatch', '代理工作目錄與紀錄不符，拒絕派工或完成後操作。')
        return agent

    def align_pane_name(self, record):
        check_worker_name(record['name'], record['account'])
        pane = self.herdr('pane', 'get', record['pane_id'])['pane']
        if pane.get('label') != record['name']:
            self.herdr('pane', 'rename', record['pane_id'], record['name'])
            pane = self.herdr('pane', 'get', record['pane_id'])['pane']
        if pane.get('pane_id') != record['pane_id'] or pane.get('label') != record['name']:
            raise Failure('pane_name_unconfirmed', 'pane 命名未確認成功；未送出任務。')

    def pane_missing(self, pane_id):
        # Only Herdr's explicit answer proves the pane is gone; any other failure keeps the record as is.
        if not pane_id:
            return True
        try:
            self.herdr('pane', 'get', pane_id)
        except Failure as error:
            return error.code == 'pane_not_found'
        return False

    def screen_working(self, record):
        # Herdr can report done while Codex still renders its live "Working (… esc to interrupt)" line.
        text = self.herdr('agent', 'read', record['pane_id'], '--source', 'recent-unwrapped', '--lines', '20')['read']['text']
        return re.search(r'Working \(.*esc to interrupt', text) is not None

    def wait_for_shell(self, pane_id, timeout):
        deadline = time.monotonic() + timeout
        while True:
            pane = self.herdr('pane', 'get', pane_id)['pane']
            if pane.get('agent'):
                raise Failure('agent_pane_busy', '新 pane 已有代理，未啟動或派工。')
            info = self.herdr('pane', 'process-info', '--pane', pane_id)['process_info']
            shell = info.get('shell_pid')
            if (shell and info.get('foreground_process_group_id') == shell
                    and [p.get('pid') for p in info.get('foreground_processes', [])] == [shell]):
                return
            if time.monotonic() >= deadline:
                raise Failure('shell_not_ready', '新 pane 的 shell 尚未就緒，未啟動或派工；保留紀錄供檢查。')
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))

    def submit(self, record, task, agent):
        self.align_pane_name(record)
        record.update(phase='submission_unknown', completion_before=agent.get('completion_seq'),
                      task_id=uuid.uuid4().hex)
        record.pop('finish_action', None)
        # Persist uncertainty before writing terminal input. A failure is never retried.
        self.save(record)
        self.herdr('agent', 'prompt', record['pane_id'], with_language(task))
        record['phase'] = 'submitted'
        self.save(record)
        return {'name': record['name'], 'account': record['account'], 'pane_id': record['pane_id'],
                'state': 'submitted'}

    def start(self, name, alias, cwd, task, direction, startup_timeout):
        check_worker_name(name, alias)
        if not task.strip():
            raise Failure('empty_task', '任務不可空白。')
        cwd = Path(cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise Failure('invalid_cwd', '工作目錄不存在或不是目錄。')
        if os.environ.get('HERDR_ENV') != '1' or not os.environ.get('HERDR_PANE_ID'):
            raise Failure('not_in_herdr', '請在 Herdr pane 內執行；未建立 pane。')
        with self.locked():
            path = self.record_path(name)
            if path.exists():
                previous = self.load(name)
                # A failed start whose pane Herdr no longer has cannot still hold the name.
                if previous['phase'] != 'closed' and not (
                        previous['phase'] == 'startup_failed' and self.pane_missing(previous.get('pane_id'))):
                    raise Failure('duplicate_name', '名稱已保留；請使用新名稱，或先檢查既有代理。')
            home = self.home(alias)
            if auth_status(home) != 'present_unverified':
                raise Failure('login_missing', f'請先執行 codex-workers account add {alias}。')
            if any(a.get('name') == name for a in self.herdr('agent', 'list')['agents']):
                raise Failure('duplicate_name', 'Herdr 中已有同名代理。')
            help_result = subprocess.run(['codex', '--help'], capture_output=True, text=True,
                                         env=isolated_env(home), timeout=10)
            if help_result.returncode or '--no-daemon' not in help_result.stdout:
                raise Failure('unsupported_codex', '本機 Codex 必須支援 --no-daemon。')
            report = sync_settings(self.source, home)
            if direction is None:
                layout = self.herdr('pane', 'layout', '--current')['layout']
                caller = next(p for p in layout['panes'] if p['pane_id'] == os.environ['HERDR_PANE_ID'])
                rect = caller['rect']
                direction = 'right' if rect['width'] >= 120 and rect['width'] >= rect['height'] * 2 else 'down'
            record = {'name': name, 'account': alias, 'cwd': str(cwd), 'phase': 'starting',
                      'pane_id': None, 'caller_pane_id': os.environ['HERDR_PANE_ID']}
            self.save(record)
            try:
                args = ['pane', 'split', '--current', '--direction', direction, '--cwd', str(cwd),
                        '--env', 'CODEX_HOME=' + str(home), '--no-focus']
                # Empty overrides prevent inherited API credentials selecting another account.
                for key in AUTH_ENV:
                    args += ['--env', key + '=']
                record['pane_id'] = self.herdr(*args)['pane']['pane_id']
                self.save(record)
                self.wait_for_shell(record['pane_id'], startup_timeout)
                self.herdr('agent', 'start', name, '--kind', 'codex', '--pane', record['pane_id'],
                           '--timeout', str(int(startup_timeout * 1000)), '--', '--no-daemon', '--yolo',
                           '-c', 'cli_auth_credentials_store="file"',
                           '-c', 'mcp_oauth_credentials_store="file"', '-C', str(cwd),
                           timeout=startup_timeout + 5)
                agent = self.identity(record)
                if not agent.get('interactive_ready') or agent['agent_status'] not in ('idle', 'done'):
                    raise Failure('agent_not_ready', '代理尚未就緒；未送出任務，請檢查 pane。')
                return {**self.submit(record, task, agent), **report}
            except (Failure, OSError, subprocess.TimeoutExpired, KeyError, StopIteration):
                if record['phase'] == 'starting':
                    record['phase'] = 'startup_failed'
                    self.save(record)
                raise

    def status(self, name):
        record = self.load(name)
        result = {k: record[k] for k in ('name', 'account', 'pane_id')}
        if record['phase'] == 'closed':
            return {**result, 'state': 'closed'}
        if record['phase'] != 'submitted':
            return {**result, 'state': 'unknown', 'reason': record['phase']}
        try:
            agent = self.identity(record)
        except Failure as error:
            if error.code == 'agent_not_found' and self.pane_missing(record['pane_id']):
                # Nothing is left to keep or compact; finish can only record the close.
                return {**result, 'state': 'unknown', 'reason': 'pane_missing', 'completion_id': completion_id(record)}
            return {**result, 'state': 'unknown', 'reason': error.code}
        state = agent.get('agent_status', 'unknown')
        completion = agent.get('completion_seq')
        baseline = record.get('completion_before')
        if state in ('done', 'idle'):
            # Idle at startup or immediately after paste is not completed work.
            acknowledged = record.get('finish_action', {}).get('completion_id') == completion_id(record)
            if acknowledged:
                state = 'completed'
            elif completion is None or (baseline is not None and completion <= baseline):
                state = 'working'
            else:
                try:
                    state = 'working' if self.screen_working(record) else 'completed'
                except Failure:
                    return {**result, 'state': 'unknown', 'reason': 'screen_unreadable',
                            'herdr_state': agent.get('agent_status')}
        if state not in ('completed', 'working', 'blocked', 'unknown'):
            state = 'unknown'
        result.update(state=state, herdr_state=agent.get('agent_status'))
        if state == 'completed':
            turn = completion_id(record)
            result.update(completion_id=turn, completion_prompt={
                'pending': record.get('finish_action', {}).get('completion_id') != turn,
                'message': f"{name} 這輪任務已完成。要保留、執行 /compact，還是關閉 pane？",
                'choices': ['keep', 'compact', 'close']})
        return result

    def finish(self, name, turn, action):
        if os.environ.get('HERDR_ENV') != '1' or not os.environ.get('HERDR_PANE_ID'):
            raise Failure('not_in_herdr', '請在 Herdr pane 內選擇完成後操作；未控制任何 session。')
        with self.locked():
            record = self.load(name)
            current = self.status(name)
            if current.get('reason') == 'pane_missing':
                if current['completion_id'] != turn:
                    raise Failure('stale_completion', '這是舊任務的選擇；請讀取目前狀態後重新選擇。')
                if action != 'close':
                    raise Failure('pane_missing', 'pane 已不在 Herdr；只能記錄為關閉。')
                record.update(phase='closed', finish_action={'completion_id': turn, 'action': action})
                self.save(record)
                return {'name': name, 'account': record['account'], 'pane_id': record['pane_id'],
                        'completion_id': turn, 'action': action, 'state': 'closed',
                        'note': 'pane 已不在 Herdr；只更新紀錄，未操作任何 pane。'}
            if current['state'] != 'completed':
                raise Failure('worker_not_settled', '代理尚未確認完成；不壓縮或關閉。')
            if current['completion_id'] != turn:
                raise Failure('stale_completion', '這是舊任務的選擇；請讀取目前成果後重新選擇。')
            if not current['completion_prompt']['pending']:
                raise Failure('completion_already_handled', '這輪已處理完成後選擇；不重複執行。')
            if record['pane_id'] in (os.environ['HERDR_PANE_ID'], record['caller_pane_id']):
                raise Failure('caller_pane_protected', '拒絕對主 agent 的 pane 執行完成後操作。')
            agent = self.identity(record)
            if not agent.get('interactive_ready') or agent.get('agent_status') not in ('idle', 'done'):
                raise Failure('worker_not_settled', '代理尚未就緒；不壓縮或關閉。')
            record['finish_action'] = {'completion_id': turn, 'action': action}
            if action == 'keep':
                self.save(record)
                return {**current, 'action': action, 'completion_prompt': {**current['completion_prompt'], 'pending': False}}
            # Persist uncertainty before any terminal input or pane close.
            record['phase'] = 'maintenance_unknown'
            self.save(record)
            if action == 'compact':
                self.herdr('agent', 'prompt', record['pane_id'], '/compact', '--wait', '--timeout', '30000', timeout=35)
                settled = self.identity(record)
                if not settled.get('interactive_ready') or settled.get('agent_status') not in ('idle', 'done'):
                    raise Failure('compact_not_settled', '已送出 /compact，但尚未確認就緒；請讀取畫面，勿重送。')
                record['phase'] = 'submitted'
                state = 'compact_submitted'
            else:
                self.herdr('pane', 'close', record['pane_id'])
                record['phase'] = 'closed'
                state = 'closed'
            self.save(record)
            return {'name': name, 'account': record['account'], 'pane_id': record['pane_id'],
                    'completion_id': turn, 'action': action, 'state': state,
                    **({'note': '已送出 /compact 並等待代理就緒；請 read 確認實際壓縮結果。'} if action == 'compact' else {})}

    def prompt(self, name, task):
        if not task.strip():
            raise Failure('empty_task', '任務不可空白。')
        with self.locked():
            record = self.load(name)
            if record['phase'] != 'submitted' or self.status(name)['state'] != 'completed':
                raise Failure('worker_not_settled', '請先 wait/read 確認上一輪完成；忙碌、blocked 或未知狀態不追加任務。')
            agent = self.identity(record)
            if not agent.get('interactive_ready') or agent.get('agent_status') not in ('idle', 'done'):
                raise Failure('agent_not_ready', '代理尚未就緒；未送出追加任務，請檢查 pane。')
            return self.submit(record, task, agent)

    def read(self, name, lines):
        record = self.load(name)
        if record['phase'] == 'closed' or not record.get('pane_id'):
            raise Failure('no_pane', '尚無可讀取的 pane。')
        self.identity(record)
        result = self.herdr('agent', 'read', record['pane_id'], '--source', 'recent-unwrapped', '--lines', str(lines))
        return {'name': name, 'text': result['read']['text'],
                'note': '畫面擷取可能不含完整長回答；必要時完成後追加任務請代理另存結果檔。'}

def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('必須為正數秒數。')
    return number

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description='在 Herdr 中以隔離 Codex 帳號派工（Python 3.11+）。')
    commands = parser.add_subparsers(dest='command', required=True)
    account = commands.add_parser('account', help='官方登入與本機登入檔狀態')
    accounts = account.add_subparsers(dest='action', required=True)
    accounts.add_parser('add', help='以獨立 CODEX_HOME 完成官方 device login').add_argument('alias')
    accounts.add_parser('list', help='唯讀列出帳號與登入檔狀態').add_argument('--json', action='store_true')
    rename = accounts.add_parser('rename', help='更改帳號別名；仍有 worker 在跑時拒絕')
    rename.add_argument('alias'); rename.add_argument('new_alias')
    accounts.add_parser('remove', help='刪除帳號的登入檔、設定與對話歷史；仍有 worker 在跑時拒絕').add_argument('alias')
    start = commands.add_parser('start', help='建立 sibling pane，就緒後派工並立即返回')
    start.add_argument('name'); start.add_argument('--account', required=True)
    start.add_argument('--cwd', default=os.getcwd()); start.add_argument('--task', required=True)
    start.add_argument('--direction', choices=('right', 'down'))
    start.add_argument('--startup-timeout', type=positive, default=30)
    prompt = commands.add_parser('prompt', help='上一輪完成後追加任務')
    prompt.add_argument('name'); prompt.add_argument('text')
    finish = commands.add_parser('finish', help='依使用者選擇保留、壓縮或關閉已完成的 worker')
    finish.add_argument('name'); finish.add_argument('--completion-id', required=True)
    finish.add_argument('--action', choices=('keep', 'compact', 'close'), required=True)
    commands.add_parser('status', help='不把 idle 或 unknown 當完成').add_argument('name')
    wait = commands.add_parser('wait', help='等待完成／blocked／unknown；逾時不終止代理')
    wait.add_argument('name'); wait.add_argument('--timeout', type=positive, default=120)
    read = commands.add_parser('read', help='讀取近期結果，保留主 pane 焦點')
    read.add_argument('name'); read.add_argument('--lines', type=int, default=120)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        workers = Workers()
        code = 0
        if args.command == 'account':
            if args.action == 'add':
                result = workers.add(args.alias)
            elif args.action == 'rename':
                result = workers.rename(args.alias, args.new_alias)
            elif args.action == 'remove':
                result = workers.remove(args.alias)
            else:
                result = workers.list_accounts()
        elif args.command == 'start':
            result = workers.start(args.name, args.account, args.cwd, args.task, args.direction, args.startup_timeout)
        elif args.command == 'prompt':
            result = workers.prompt(args.name, args.text)
        elif args.command == 'finish':
            result = workers.finish(args.name, args.completion_id, args.action)
        elif args.command == 'status':
            if os.environ.get('HERDR_ENV') != '1':
                raise Failure('not_in_herdr', '請在 Herdr 內查詢代理。')
            result = workers.status(args.name)
        elif args.command == 'read':
            if args.lines <= 0:
                raise Failure('invalid_lines', '--lines 必須為正整數。')
            result = workers.read(args.name, args.lines)
        else:
            if os.environ.get('HERDR_ENV') != '1':
                raise Failure('not_in_herdr', '請在 Herdr 內等待代理。')
            deadline = time.monotonic() + args.timeout
            while True:
                result = workers.status(args.name)
                if result['state'] in ('completed', 'blocked', 'unknown', 'closed'):
                    code = {'completed': 0, 'blocked': 3, 'unknown': 4, 'closed': 4}[result['state']]
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    result = {**result, 'last_state': result['state'], 'state': 'timeout'}
                    code = 124
                    break
                time.sleep(min(0.2, remaining))
        print(json.dumps(result, ensure_ascii=False))
        return code
    except Failure as error:
        print(json.dumps({'error': {'code': error.code, 'message': error.message}}, ensure_ascii=False))
        return 1
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as error:
        print(json.dumps({'error': {'code': 'local_failure',
                                   'message': f'本機操作失敗（{type(error).__name__}）；請檢查路徑、設定及 CLI，勿盲目重送。'}}, ensure_ascii=False))
        return 1
