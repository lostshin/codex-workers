#!/usr/bin/env python3
"""Run the public CLI against isolated fake executables; never use real login."""
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CLI = PROJECT / 'codex-workers'

class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'main'
        self.data = self.root / 'workers'
        self.source.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('codex', 'herdr'):
            target = self.bin / name
            target.write_bytes((PROJECT / 'tests' / 'fake_cli.py').read_bytes())
            target.chmod(0o755)
        (self.source / 'config.toml').write_text('''model = "fixture-model"
approval_policy = "on-request"
sandbox_mode = "read-only"
cli_auth_credentials_store = "keyring"
[profiles.deep]
model_reasoning_effort = "high"
[mcp_servers.private]
url = "https://example.invalid/mcp"
http_headers = { Authorization = "fixture-secret" }
[shell_environment_policy.set]
OPENAI_API_KEY = "fixture-secret"
CODEX_HOME = "/must-not-use-main-home"
SAFE_VALUE = "yes"
''')
        (self.source / 'deep.config.toml').write_text('model = "fixture-deep"\nsandbox_mode = "workspace-write"\n')
        (self.source / 'AGENTS.md').write_text('Anonymous rules')
        for name in ('rules', 'skills', 'plugins/cache', 'plugins/data'):
            (self.source / name).mkdir(parents=True, exist_ok=True)
        (self.source / 'rules' / 'safe.rules').write_text('fixture')
        (self.source / 'skills' / 'one').mkdir()
        (self.source / 'skills' / 'one' / 'SKILL.md').write_text('fixture skill')
        (self.source / 'plugins' / 'cache' / 'asset.txt').write_text('fixture asset')
        (self.source / 'plugins' / 'data' / 'connection.json').write_text('fixture-secret')
        for name in ('auth.json', 'history.jsonl', 'state.sqlite', 'mcp_auth.json'):
            (self.source / name).write_text('fixture-secret')
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        CODEX_WORKERS_HOME=str(self.data), CODEX_WORKERS_SOURCE=str(self.source),
                        FAKE_ROOT=str(self.root), HERDR_ENV='1', HERDR_PANE_ID='fixture:p0',
                        OPENAI_API_KEY='fixture-secret')
        self.snapshot = {str(p.relative_to(self.source)): p.read_bytes()
                         for p in self.source.rglob('*') if p.is_file()}
    def tearDown(self):
        self.assertEqual(self.snapshot, {str(p.relative_to(self.source)): p.read_bytes()
                                        for p in self.source.rglob('*') if p.is_file()})
        self.tmp.cleanup()
    def run_cli(self, *args, code=0, extra=None):
        result = subprocess.run([sys.executable, str(CLI), *args], env=self.env | (extra or {}),
                                cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout)
    def calls(self):
        p = self.root / 'calls.jsonl'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []









    def add(self, alias='alpha'):
        return self.run_cli('account', 'add', alias)
    def start(self, name='alpha', alias='alpha', **kw):
        return self.run_cli('start', name, '--account', alias, '--task', 'Anonymous task', **kw)
    def finish(self, status='done', completion=2):
        p = self.root / 'herdr.json'
        s = json.loads(p.read_text())
        a = s['agents']['alpha']
        a.update(agent_status=status, completion_seq=completion, state_change_seq=2)
        p.write_text(json.dumps(s))
    def test_two_accounts_sync_dispatch_continue_and_read(self):
        self.add(); self.add('beta')
        homes = [self.data / 'accounts' / x for x in ('alpha', 'beta')]
        self.assertNotEqual(homes[0], homes[1])
        for home in homes:
            c = tomllib.loads((home / 'config.toml').read_text())
            self.assertEqual(c['model'], 'fixture-model')
            self.assertEqual(c['sandbox_mode'], 'read-only')
            self.assertEqual(c['approval_policy'], 'on-request')
            self.assertEqual(c['cli_auth_credentials_store'], 'file')
            self.assertEqual(c['profiles']['deep']['model_reasoning_effort'], 'high')
            self.assertNotIn('http_headers', c['mcp_servers']['private'])
            self.assertNotIn('OPENAI_API_KEY', c['shell_environment_policy']['set'])
            self.assertNotIn('CODEX_HOME', c['shell_environment_policy']['set'])
            self.assertEqual((home / 'skills/one/SKILL.md').read_text(), 'fixture skill')
            self.assertEqual((home / 'AGENTS.md').read_text(), 'Anonymous rules')
            self.assertTrue((home / 'plugins/cache').is_symlink())
            self.assertFalse((home / 'plugins/data').exists())
            for name in ('history.jsonl', 'state.sqlite', 'mcp_auth.json'):
                self.assertFalse((home / name).exists())
            self.assertNotIn('fixture-secret', (home / 'auth.json').read_text())
            self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        self.assertEqual(len(self.run_cli('account', 'list', '--json')['accounts']), 2)
        (self.source / 'rules' / 'safe.rules').write_text('updated')
        self.snapshot['rules/safe.rules'] = b'updated'
        self.start(); self.start('beta', 'beta')
        self.assertEqual((homes[0] / 'rules/safe.rules').read_text(), 'updated')
        splits = [c['args'] for c in self.calls() if c['args'][:2] == ['pane', 'split']]
        self.assertEqual(len(splits), 2)
        for split, home in zip(splits, homes):
            self.assertIn('CODEX_HOME=' + str(home), split)
            self.assertIn('--no-focus', split)
            self.assertEqual(Path(split[split.index('--cwd') + 1]).resolve(), self.root.resolve())
        starts = [c['args'] for c in self.calls() if c['args'][:2] == ['agent', 'start']]
        self.assertTrue(all('--no-daemon' in x for x in starts))
        self.assertTrue(all('--yolo' in x[x.index('--') + 1:] for x in starts))
        self.assertTrue(all('cli_auth_credentials_store="file"' in x for x in starts))
        self.assertTrue(all(c['api_key'] is None for c in self.calls() if c['cli'] == 'codex'))
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'working')
        self.finish()
        self.assertEqual(self.run_cli('wait', 'alpha', '--timeout', '1')['state'], 'completed')
        self.assertIn('Anonymous fixture result', self.run_cli('read', 'alpha')['text'])
        self.run_cli('prompt', 'alpha', 'Follow up')
        self.assertEqual(sum(c['args'][:2] == ['agent', 'prompt'] for c in self.calls()), 3)
    def test_no_herdr_context_never_controls_session(self):
        self.add()
        self.start(code=1, extra={'HERDR_ENV': ''})
        self.assertFalse(any(c['cli'] == 'herdr' for c in self.calls()))

    def test_public_token_limits_sync_without_importing_nested_credentials(self):
        limits = {'model_context_window': 1000000, 'model_auto_compact_token_limit': 900000,
                  'model_auto_compact_token_limit_scope': 'total', 'tool_output_token_limit': 12000}
        config = self.source / 'config.toml'
        config.write_text(''.join(f'{key} = {json.dumps(value)}\n' for key, value in limits.items())
                          + config.read_text() + 'model_auto_compact_token_limit = "fixture-secret"\n')
        self.snapshot['config.toml'] = config.read_bytes()
        self.add(); self.start()
        worker = tomllib.loads((self.data / 'accounts/alpha/config.toml').read_text())
        for key, value in limits.items():
            self.assertEqual(worker.get(key), value)
        self.assertNotIn('http_headers', worker['mcp_servers']['private'])
        self.assertNotIn('OPENAI_API_KEY', worker['shell_environment_policy']['set'])
        self.assertNotIn('model_auto_compact_token_limit', worker['shell_environment_policy']['set'])
        self.assertNotIn('fixture-secret', (self.data / 'accounts/alpha/config.toml').read_text())

    def test_duplicate_login_missing_and_invalid_cwd_before_split(self):
        self.add(); self.start()
        self.start(code=1)
        self.start('missing', 'missing', code=1)
        self.run_cli('start', 'alpha-badcwd', '--account', 'alpha', '--cwd', str(self.root/'missing'),
                     '--task', 'fixture', code=1)
        self.assertEqual(sum(c['args'][:2] == ['pane', 'split'] for c in self.calls()), 1)
    def test_login_failure_can_retry_without_other_account_credentials(self):
        self.run_cli('account','add','alpha',code=1,extra={'FAKE_LOGIN_FAIL':'1'})
        self.add()
        self.run_cli('account','add','alpha',code=1)
        self.assertEqual(sum(c['cli']=='codex' and 'login' in c['args'] for c in self.calls()),2)
    def test_start_failure_never_prompts_or_retries(self):
        self.add(); self.start(code=1,extra={'FAKE_START_FAIL':'1'})
        self.start(code=1)
        self.assertFalse(any(c['args'][:2] == ['agent','prompt'] for c in self.calls()))
    def test_prompt_failure_is_uncertain_and_never_resent(self):
        self.add(); self.start(code=1,extra={'FAKE_PROMPT_FAIL':'1'})
        self.run_cli('prompt','alpha','retry',code=1)
        self.assertEqual(sum(c['args'][:2]==['agent','prompt'] for c in self.calls()),1)
        self.assertEqual(self.run_cli('status','alpha')['state'],'unknown')
    def test_timeout_keeps_worker_alive(self):
        self.add(); self.start()
        result=self.run_cli('wait','alpha','--timeout','0.05',code=124)
        self.assertEqual(result['state'],'timeout')
        self.assertEqual(self.run_cli('status','alpha')['state'],'working')
        self.assertFalse(any(c['args'][:2]==['pane','close'] for c in self.calls()))
    def test_blocked_unknown_and_idle_are_not_false_completion(self):
        self.add(); self.start()
        self.finish('blocked',None)
        self.assertEqual(self.run_cli('wait','alpha',code=3)['state'],'blocked')
        self.finish('unknown',None)
        self.assertEqual(self.run_cli('wait','alpha',code=4)['state'],'unknown')
        self.finish('idle',None)
        self.assertEqual(self.run_cli('wait','alpha','--timeout','0.05',code=124)['state'],'timeout')
    def test_busy_followup_is_rejected(self):
        self.add(); self.start()
        self.run_cli('prompt','alpha','Follow up',code=1)
        self.assertEqual(sum(c['args'][:2]==['agent','prompt'] for c in self.calls()),1)
    def test_path_traversal_and_empty_task_rejected(self):
        self.run_cli('account','add','../escape',code=1)
        self.add()
        self.run_cli('start','alpha','--account','alpha','--task',' ',code=1)
        self.assertFalse(any(c['args'][:2]==['pane','split'] for c in self.calls()))
    def test_unready_agent_never_receives_task(self):
        self.add(); self.start(code=1,extra={'FAKE_NOT_READY':'1'})
        self.assertFalse(any(c['args'][:2]==['agent','prompt'] for c in self.calls()))
    def test_closed_or_replaced_pane_is_unknown_and_not_prompted(self):
        self.add(); self.start(); self.finish()
        p=self.root/'herdr.json'; s=json.loads(p.read_text()); s['agents']['alpha']['name']='replacement'
        p.write_text(json.dumps(s))
        self.assertEqual(self.run_cli('status','alpha')['state'],'unknown')
        self.run_cli('prompt','alpha','Follow up',code=1)
    def test_removed_settings_disappear_without_removing_login(self):
        self.add()
        (self.source/'deep.config.toml').unlink()
        self.snapshot.pop('deep.config.toml')
        (self.source/'skills/one/SKILL.md').unlink()
        (self.source/'skills/one').rmdir()
        self.snapshot.pop('skills/one/SKILL.md')
        self.start()
        home=self.data/'accounts/alpha'
        self.assertFalse((home/'deep.config.toml').exists())
        self.assertFalse((home/'skills/one').exists())
        self.assertEqual(json.loads((home/'auth.json').read_text()),{'fixture':True})
    def test_credential_resource_symlink_rejected_before_pane(self):
        (self.source/'skills/leak').symlink_to(self.source/'auth.json')
        self.snapshot['skills/leak'] = b'fixture-secret'
        self.run_cli('account','add','alpha',code=1)
        self.assertFalse(any(c['args'][:2]==['pane','split'] for c in self.calls()))
    def test_followup_requires_a_new_completion_sequence(self):
        self.add(); self.start(); self.finish()
        self.run_cli('prompt','alpha','Follow up')
        self.finish('idle',2)
        self.assertEqual(self.run_cli('wait','alpha','--timeout','0.05',code=124)['state'],'timeout')
        self.finish('idle',4)
        self.assertEqual(self.run_cli('wait','alpha','--timeout','1')['state'],'completed')
    def test_same_source_and_data_root_never_changes_main(self):
        self.run_cli('account','add','alpha',code=1,extra={'CODEX_WORKERS_HOME':str(self.source)})
    def test_alias_symlink_does_not_use_main_login(self):
        (self.data/'accounts').mkdir(parents=True)
        (self.data/'accounts/alpha').symlink_to(self.source,target_is_directory=True)
        self.run_cli('account','add','alpha',code=1)
    def test_inline_auth_urls_and_auth_environment_not_shared(self):
        p=self.source/'config.toml'
        p.write_text(p.read_text()+'''\n[mcp_servers.inline]\nurl="https://example.invalid/mcp?api_key=fixture-secret"\n[model_providers.private]\nbase_url="https://user:fixture-secret@example.invalid"\n''')
        self.snapshot['config.toml']=p.read_bytes()
        self.add()
        self.assertNotIn('fixture-secret',(self.data/'accounts/alpha/config.toml').read_text())











    def choice(self, action, completion_id=None, **kw):
        if completion_id is None:
            completion_id = self.run_cli('status', 'alpha')['completion_id']
        return self.run_cli('finish', 'alpha', '--completion-id', completion_id,
                            '--action', action, **kw)

    def test_language_contract_preserves_first_and_followup_tasks(self):
        self.add()
        task = 'Review code: `print("hello")`\nKeep API identifiers.'
        self.run_cli('start', 'alpha', '--account', 'alpha', '--task', task)
        self.finish()
        self.run_cli('prompt', 'alpha', 'Follow up: `foo_bar`')
        prompts = [c['args'][3] for c in self.calls() if c['args'][:2] == ['agent', 'prompt']]
        self.assertEqual(len(prompts), 2)
        for text, original in zip(prompts, (task, 'Follow up: `foo_bar`')):
            self.assertIn('台灣繁體中文', text)
            self.assertIn('派工', text)
            self.assertTrue(text.endswith(original))

    def test_language_prompt_can_be_replaced_or_disabled(self):
        self.add(); self.add('beta')
        self.start(extra={'CODEX_WORKERS_LANGUAGE_PROMPT': 'Reply in English.'})
        self.start('beta', 'beta', extra={'CODEX_WORKERS_LANGUAGE_PROMPT': ''})
        prompts = [c['args'][3] for c in self.calls() if c['args'][:2] == ['agent', 'prompt']]
        self.assertEqual(prompts[0], 'Reply in English.\n\nAnonymous task')
        self.assertEqual(prompts[1], 'Anonymous task')
        self.finish()
        self.run_cli('prompt', 'alpha', 'Follow up', extra={'CODEX_WORKERS_LANGUAGE_PROMPT': 'Reply in English.'})
        followup = [c['args'][3] for c in self.calls() if c['args'][:2] == ['agent', 'prompt']][-1]
        self.assertEqual(followup, 'Reply in English.\n\nFollow up')

    def test_worker_name_must_identify_account_before_any_pane(self):
        self.add()
        for name in ('reviewer', 'alphabeta', 'alpha-'):
            self.assertEqual(self.start(name, code=1)['error']['code'], 'account_name_mismatch')
        self.assertFalse(any(c['cli'] == 'herdr' for c in self.calls()))
        self.start('alpha-review')
        pane = self.run_cli('status', 'alpha-review')['pane_id']
        state = json.loads((self.root / 'herdr.json').read_text())
        self.assertEqual(state['panes'][pane]['label'], 'alpha-review')

    def test_rename_failure_and_unconfirmed_label_never_submit(self):
        for mode in ('FAKE_RENAME_FAIL', 'FAKE_RENAME_NOOP'):
            with self.subTest(mode=mode):
                self.add(mode.lower())
                self.start(mode.lower(), mode.lower(), code=1, extra={mode: '1'})
        self.assertFalse(any(c['args'][:2] == ['agent', 'prompt'] for c in self.calls()))

    def test_new_shell_is_ready_before_agent_start(self):
        self.add();self.start(extra={'FAKE_SHELL_STARTING':'1'})
        self.assertEqual(self.run_cli('status','alpha')['state'],'working')
        self.assertEqual(sum(c['args'][:2]==['agent','start'] for c in self.calls()),1)

    def test_busy_shell_timeout_never_starts_or_prompts_agent(self):
        self.add()
        result=self.run_cli('start','alpha','--account','alpha','--task','Task','--startup-timeout','0.2',
                            code=1,extra={'FAKE_SHELL_BUSY':'1'})
        self.assertEqual(result['error']['code'],'shell_not_ready')
        self.assertFalse(any(c['args'][:2] in (['agent','start'],['agent','prompt']) for c in self.calls()))

    def test_followup_repairs_label_only_after_validating_cwd(self):
        self.add(); self.start(); self.finish()
        p = self.root / 'herdr.json'
        state = json.loads(p.read_text())
        pane = state['agents']['alpha']['pane_id']
        state['panes'][pane]['label'] = 'old title'
        state['agents']['alpha']['cwd'] = str(self.root / 'other')
        p.write_text(json.dumps(state))
        before = len(self.calls())
        self.run_cli('prompt', 'alpha', 'Follow up', code=1)
        self.assertFalse(any(c['args'][:2] in (['pane', 'rename'], ['agent', 'prompt'])
                             for c in self.calls()[before:]))
        state['agents']['alpha']['cwd'] = str(self.root)
        p.write_text(json.dumps(state))
        self.run_cli('prompt', 'alpha', 'Follow up')
        self.assertEqual(json.loads(p.read_text())['panes'][pane]['label'], 'alpha')

    def test_completion_choice_is_stable_acknowledged_and_renewed(self):
        self.add(); self.start()
        self.assertNotIn('completion_id', self.run_cli('status', 'alpha'))
        self.finish()
        first = self.run_cli('wait', 'alpha', '--timeout', '1')
        again = self.run_cli('status', 'alpha')
        self.assertEqual(first['completion_id'], again['completion_id'])
        self.assertTrue(again['completion_prompt']['pending'])
        self.assertEqual(again['completion_prompt']['choices'], ['keep', 'compact', 'close'])
        before = len(self.calls())
        self.choice('keep', first['completion_id'])
        self.assertFalse(any(c['args'][:2] in (['agent', 'prompt'], ['pane', 'close'])
                             for c in self.calls()[before:]))
        self.assertFalse(self.run_cli('status', 'alpha')['completion_prompt']['pending'])
        self.choice('close', first['completion_id'], code=1)
        self.run_cli('prompt', 'alpha', 'Next task')
        self.finish(completion=4)
        second = self.run_cli('status', 'alpha')
        self.assertNotEqual(first['completion_id'], second['completion_id'])
        self.assertTrue(second['completion_prompt']['pending'])
        self.choice('close', first['completion_id'], code=1)

    def test_compact_is_raw_once_and_does_not_create_a_new_task_prompt(self):
        self.add(); self.start(); self.finish()
        completed = self.run_cli('status', 'alpha')
        result = self.choice('compact')
        self.assertEqual(result['state'], 'compact_submitted')
        prompts = [c['args'] for c in self.calls() if c['args'][:2] == ['agent', 'prompt']]
        self.assertEqual(prompts[-1][3], '/compact')
        self.assertIn('--wait', prompts[-1])
        after = self.run_cli('status', 'alpha')
        self.assertEqual(after['completion_id'], completed['completion_id'])
        self.assertFalse(after['completion_prompt']['pending'])
        self.choice('compact', completed['completion_id'], code=1)
        self.run_cli('prompt', 'alpha', 'Next task')
        self.finish(completion=6)
        self.assertTrue(self.run_cli('status', 'alpha')['completion_prompt']['pending'])

    def test_close_only_worker_and_allow_same_name_with_new_completion_id(self):
        self.add(); self.add('beta'); self.start(); self.start('beta', 'beta'); self.finish()
        before = self.run_cli('status', 'alpha')
        auth = (self.data / 'accounts/alpha/auth.json').read_bytes()
        self.choice('close')
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'closed')
        self.assertEqual(self.run_cli('wait', 'alpha', code=4)['state'], 'closed')
        self.assertEqual(self.run_cli('status', 'beta')['state'], 'working')
        self.assertEqual((self.data / 'accounts/alpha/auth.json').read_bytes(), auth)
        self.run_cli('read', 'alpha', code=1)
        self.start(); self.finish()
        after = self.run_cli('status', 'alpha')
        self.assertNotEqual(before['pane_id'], after['pane_id'])
        self.assertNotEqual(before['completion_id'], after['completion_id'])
        self.choice('close', before['completion_id'], code=1)

    def test_finish_rejects_busy_blocked_unknown_replaced_and_caller(self):
        self.add(); self.start(); self.finish()
        completion_id = self.run_cli('status', 'alpha')['completion_id']
        for status in ('working', 'blocked', 'unknown'):
            self.finish(status)
            for action in ('keep', 'compact', 'close'):
                self.choice(action, completion_id, code=1)
        self.finish()
        p = self.root / 'herdr.json'
        state = json.loads(p.read_text())
        state['agents']['alpha']['name'] = 'replacement'
        p.write_text(json.dumps(state))
        self.choice('close', completion_id, code=1)
        state['agents']['alpha']['name'] = 'alpha'
        p.write_text(json.dumps(state))
        pane = state['agents']['alpha']['pane_id']
        self.choice('close', completion_id, code=1, extra={'HERDR_PANE_ID': pane})
        self.assertFalse(any(c['args'][:2] == ['pane', 'close'] for c in self.calls()))
        self.assertEqual(sum(c['args'][:2] == ['agent', 'prompt'] for c in self.calls()), 1)

    def test_finish_requires_genuine_caller_context(self):
        self.add(); self.start(); self.finish()
        completion_id = self.run_cli('status', 'alpha')['completion_id']
        before = len(self.calls())
        for overrides in ({'HERDR_ENV': ''}, {'HERDR_PANE_ID': ''}):
            self.choice('close', completion_id, code=1, extra=overrides)
        self.assertEqual(before, len(self.calls()))

    def test_failed_maintenance_is_unknown_and_never_repeated(self):
        self.add(); self.start(); self.finish()
        completion_id = self.run_cli('status', 'alpha')['completion_id']
        self.choice('compact', completion_id, code=1, extra={'FAKE_PROMPT_FAIL': '1'})
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'unknown')
        self.choice('compact', completion_id, code=1)
        self.run_cli('prompt', 'alpha', 'New task', code=1)
        self.assertEqual(sum(c['args'][:2] == ['agent', 'prompt'] for c in self.calls()), 2)

    def test_close_failure_keeps_record_unknown_and_never_retries(self):
        self.add(); self.start(); self.finish()
        completion_id = self.run_cli('status', 'alpha')['completion_id']
        self.choice('close', completion_id, code=1, extra={'FAKE_CLOSE_FAIL': '1'})
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'unknown')
        self.choice('close', completion_id, code=1)
        self.assertEqual(sum(c['args'][:2] == ['pane', 'close'] for c in self.calls()), 1)

    def test_compact_blocked_is_not_reported_as_success(self):
        self.add(); self.start(); self.finish()
        self.choice('compact', code=1, extra={'FAKE_COMPACT_BLOCKED': '1'})
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'unknown')

    def test_compact_without_turn_completion_event_can_still_continue(self):
        self.add(); self.start(); self.finish()
        self.choice('compact', extra={'FAKE_COMPACT_NOSEQ': '1'})
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'completed')
        self.assertFalse(self.run_cli('status', 'alpha')['completion_prompt']['pending'])
        self.run_cli('prompt', 'alpha', 'Next task')
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'working')

    def test_followup_unready_never_receives_task(self):
        self.add(); self.start(); self.finish()
        self.run_cli('prompt', 'alpha', 'Next task', code=1, extra={'FAKE_NOT_READY': '1'})
        self.assertEqual(sum(c['args'][:2] == ['agent', 'prompt'] for c in self.calls()), 1)

    def test_legacy_record_supports_completion_and_first_followup(self):
        self.add(); self.start(); self.finish()
        p = self.data / 'workers/alpha.json'
        record = json.loads(p.read_text())
        record.pop('task_id', None)
        p.write_text(json.dumps(record))
        first = self.run_cli('status', 'alpha')['completion_id']
        self.assertEqual(first, self.run_cli('status', 'alpha')['completion_id'])
        self.choice('keep', first)
        self.run_cli('prompt', 'alpha', 'New task')
        self.finish(completion=4)
        self.assertNotEqual(first, self.run_cli('status', 'alpha')['completion_id'])

    def herdr_state(self, change):
        p = self.root / 'herdr.json'
        state = json.loads(p.read_text())
        change(state)
        p.write_text(json.dumps(state))

    def screen(self, text):
        self.herdr_state(lambda s: s.update(screen=text))

    def vanish(self, name='alpha', keep_pane=False):
        pane = json.loads((self.data / 'workers' / f'{name}.json').read_text())['pane_id']
        def change(state):
            if not keep_pane:
                state['panes'].pop(pane, None)
            state['agents'] = {k: a for k, a in state['agents'].items() if a['pane_id'] != pane}
        self.herdr_state(change)

    def test_herdr_done_while_screen_still_working_is_not_completion(self):
        self.add(); self.start(); self.finish()
        self.screen('partial reply\n• Working (1m 56s • esc to interrupt)\n\n\n'
                    '› Ask Codex to do anything\n\n  model footer')
        status = self.run_cli('status', 'alpha')
        self.assertEqual(status['state'], 'working')
        self.assertNotIn('completion_id', status)
        self.assertEqual(self.run_cli('wait', 'alpha', '--timeout', '0.3', code=124)['last_state'], 'working')
        self.run_cli('prompt', 'alpha', 'Too early', code=1)
        self.assertEqual(sum(c['args'][:2] == ['agent', 'prompt'] for c in self.calls()), 1)
        self.screen('• Ran search\n' + '\n'.join(f'reply line {i}' for i in range(30))
                    + '\n\n  Worked for 2m 3s • 12:21 AM\n\n\n› Ask Codex to do anything\n\n  model footer')
        done = self.run_cli('wait', 'alpha', '--timeout', '1')
        self.assertEqual(done['state'], 'completed')
        self.choice('keep', done['completion_id'])

    def test_unreadable_screen_is_never_reported_as_completion(self):
        self.add(); self.start(); self.finish()
        result = self.run_cli('status', 'alpha', extra={'FAKE_READ_FAIL': '1'})
        self.assertEqual((result['state'], result['reason']), ('unknown', 'screen_unreadable'))
        self.assertNotIn('completion_id', result)
        self.choice('close', 'any', code=1, extra={'FAKE_READ_FAIL': '1'})
        self.assertFalse(any(c['args'][:2] == ['pane', 'close'] for c in self.calls()))

    def test_failed_start_releases_name_only_when_herdr_confirms_pane_is_gone(self):
        self.add()
        self.start(code=1, extra={'FAKE_START_FAIL': '1'})
        self.assertEqual(self.start(code=1)['error']['code'], 'duplicate_name')
        self.vanish(keep_pane=True)
        self.assertEqual(self.start(code=1)['error']['code'], 'duplicate_name')
        self.vanish()
        self.assertEqual(self.start(code=1, extra={'FAKE_PANE_GET_FAIL': '1'})['error']['code'], 'duplicate_name')
        self.start()
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'working')
        self.assertEqual(sum(c['args'][:2] == ['pane', 'split'] for c in self.calls()), 2)

    def test_failed_split_without_pane_releases_name(self):
        self.add()
        self.start(code=1, extra={'FAKE_SPLIT_FAIL': '1'})
        self.start()
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'working')

    def test_uncertain_submission_keeps_name_even_when_pane_is_gone(self):
        self.add(); self.start(code=1, extra={'FAKE_PROMPT_FAIL': '1'})
        self.vanish()
        self.assertEqual(self.start(code=1)['error']['code'], 'duplicate_name')
        status = self.run_cli('status', 'alpha')
        self.assertEqual(status['reason'], 'submission_unknown')
        self.assertNotIn('completion_id', status)

    def test_missing_pane_can_only_be_recorded_closed(self):
        self.add(); self.start(); self.finish()
        completion_id = self.run_cli('status', 'alpha')['completion_id']
        self.vanish()
        status = self.run_cli('status', 'alpha')
        self.assertEqual((status['state'], status['reason']), ('unknown', 'pane_missing'))
        self.assertEqual(status['completion_id'], completion_id)
        for action in ('keep', 'compact'):
            self.assertEqual(self.choice(action, completion_id, code=1)['error']['code'], 'pane_missing')
        self.assertEqual(self.choice('close', 'stale-turn', code=1)['error']['code'], 'stale_completion')
        self.choice('close', completion_id, code=1, extra={'HERDR_PANE_ID': ''})
        result = self.choice('close', completion_id)
        self.assertEqual(result['state'], 'closed')
        self.assertFalse(any(c['args'][:2] == ['pane', 'close'] for c in self.calls()))
        self.assertEqual(sum(c['args'][:2] == ['agent', 'prompt'] for c in self.calls()), 1)
        self.assertEqual(self.run_cli('status', 'alpha')['state'], 'closed')
        self.start()

    def test_agent_gone_or_unconfirmed_pane_is_never_recorded_closed(self):
        self.add(); self.start(); self.finish()
        completion_id = self.run_cli('status', 'alpha')['completion_id']
        self.vanish(keep_pane=True)
        status = self.run_cli('status', 'alpha')
        self.assertEqual(status['reason'], 'agent_not_found')
        self.assertNotIn('completion_id', status)
        self.assertEqual(self.choice('close', completion_id, code=1)['error']['code'], 'worker_not_settled')
        self.vanish()
        self.choice('close', completion_id, code=1, extra={'FAKE_PANE_GET_FAIL': '1'})
        self.assertNotEqual(self.run_cli('status', 'alpha', extra={'FAKE_PANE_GET_FAIL': '1'})['state'], 'closed')
        self.assertFalse(any(c['args'][:2] == ['pane', 'close'] for c in self.calls()))

    def aliases(self):
        return [a['alias'] for a in self.run_cli('account', 'list', '--json')['accounts']]

    def record(self, name):
        return json.loads((self.data / 'workers' / f'{name}.json').read_text())

    def test_remove_refuses_while_a_worker_pane_may_still_exist(self):
        self.add(); self.start('alpha-live')
        for extra in ({}, {'HERDR_ENV': ''}, {'FAKE_PANE_GET_FAIL': '1'}):
            with self.subTest(extra=extra):
                result = self.run_cli('account', 'remove', 'alpha', code=1, extra=extra)
                self.assertEqual(result['error']['code'], 'account_in_use')
                self.assertTrue((self.data / 'accounts/alpha/auth.json').is_file())
                self.assertTrue((self.data / 'workers/alpha-live.json').is_file())

    def test_remove_deletes_only_that_account_and_its_finished_records(self):
        self.add(); self.add('beta')
        self.start(); self.finish(); self.choice('close')
        self.start('alpha-gone')
        self.vanish('alpha-gone')
        self.start('beta', 'beta')
        beta_auth = (self.data / 'accounts/beta/auth.json').read_bytes()
        before = len(self.calls())
        result = self.run_cli('account', 'remove', 'alpha')
        self.assertEqual(result['account'], 'alpha')
        self.assertEqual(sorted(result['removed_workers']), ['alpha', 'alpha-gone'])
        self.assertFalse((self.data / 'accounts/alpha').exists())
        self.assertFalse((self.data / 'workers/alpha.json').exists())
        self.assertFalse((self.data / 'workers/alpha-gone.json').exists())
        self.assertEqual(self.aliases(), ['beta'])
        self.assertEqual((self.data / 'accounts/beta/auth.json').read_bytes(), beta_auth)
        self.assertEqual(self.run_cli('status', 'beta')['state'], 'working')
        self.assertFalse(any(c['args'][:2] == ['pane', 'close'] for c in self.calls()[before:]))
        self.add()
        self.assertIn('alpha', self.aliases())

    def test_remove_rejects_unknown_invalid_and_linked_accounts(self):
        self.assertEqual(self.run_cli('account', 'remove', 'ghost', code=1)['error']['code'], 'account_not_found')
        self.assertEqual(self.run_cli('account', 'remove', '../escape', code=1)['error']['code'], 'invalid_name')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('fixture')
        (self.data / 'accounts').mkdir(parents=True)
        (self.data / 'accounts/linked').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_cli('account', 'remove', 'linked', code=1)['error']['code'], 'unsafe_account')
        self.assertTrue((outside / 'keep.txt').is_file())

    def test_rename_moves_login_and_updates_records(self):
        self.add(); self.add('beta')
        self.start(); self.finish(); self.choice('close')
        auth = (self.data / 'accounts/alpha/auth.json').read_bytes()
        result = self.run_cli('account', 'rename', 'alpha', 'gamma')
        self.assertEqual((result['account'], result['previous']), ('gamma', 'alpha'))
        self.assertEqual(self.aliases(), ['beta', 'gamma'])
        self.assertEqual((self.data / 'accounts/gamma/auth.json').read_bytes(), auth)
        self.assertEqual(self.record('alpha')['account'], 'gamma')
        self.assertEqual(self.start('alpha', 'alpha', code=1)['error']['code'], 'login_missing')
        self.start('gamma-review', 'gamma')
        self.assertIn('CODEX_HOME=' + str(self.data / 'accounts/gamma'),
                      [c['args'] for c in self.calls() if c['args'][:2] == ['pane', 'split']][-1])
        self.run_cli('account', 'remove', 'gamma', code=1)
        self.vanish('gamma-review')
        self.run_cli('account', 'remove', 'gamma')
        self.assertFalse((self.data / 'workers/alpha.json').exists())

    def test_rename_rejects_conflicts_live_workers_and_bad_names(self):
        self.add(); self.add('beta')
        self.assertEqual(self.run_cli('account', 'rename', 'alpha', 'beta', code=1)['error']['code'], 'account_exists')
        self.assertEqual(self.run_cli('account', 'rename', 'ghost', 'gamma', code=1)['error']['code'], 'account_not_found')
        self.assertEqual(self.run_cli('account', 'rename', 'alpha', 'Bad Name', code=1)['error']['code'], 'invalid_name')
        self.start()
        self.assertEqual(self.run_cli('account', 'rename', 'alpha', 'gamma', code=1)['error']['code'], 'account_in_use')
        self.assertEqual(self.aliases(), ['alpha', 'beta'])
        self.assertEqual(self.record('alpha')['account'], 'alpha')

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Workflow)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    artifact = {'fixture': 'anonymous fake CLI only', 'tests': result.testsRun,
                'failures': len(result.failures), 'errors': len(result.errors),
                'passed': result.wasSuccessful(), 'rerun': 'python3 tests/e2e.py'}
    (PROJECT/'evidence').mkdir(exist_ok=True)
    (PROJECT/'evidence'/'e2e.json').write_text(json.dumps(artifact,indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
