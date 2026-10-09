#!/usr/bin/env python3
"""Anonymous Codex/Herdr processes used by the CLI integration tests."""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
root = Path(os.environ['FAKE_ROOT'])
log = root / 'calls.jsonl'
with log.open('a') as stream:
    stream.write(json.dumps({'cli': Path(sys.argv[0]).name, 'args': args,
                             'home': os.environ.get('CODEX_HOME'),
                             'api_key': os.environ.get('OPENAI_API_KEY')}) + '\n')

def reply(result):
    print(json.dumps({'id': 'fixture', 'result': result}))

def fail(code):
    print(json.dumps({'error': {'code': code, 'message': 'anonymous failure'}}), file=sys.stderr)
    sys.exit(1)

if Path(sys.argv[0]).name == 'codex':
    if '--help' in args:
        print('--no-daemon')
    elif 'login' in args:
        if os.environ.get('FAKE_LOGIN_FAIL'):
            sys.exit(1)
        (Path(os.environ['CODEX_HOME']) / 'auth.json').write_text('{"fixture": true}')
    else:
        fail('unexpected_codex_command')
    sys.exit(0)

state_path = root / 'herdr.json'
state = json.loads(state_path.read_text()) if state_path.exists() else {'agents': {}, 'panes': {}, 'next': 1}
command = args[:2]
if command == ['agent', 'list']:
    reply({'agents': list(state['agents'].values())})
elif command == ['pane', 'layout']:
    reply({'layout': {'panes': [{'pane_id': 'fixture:p0', 'rect': {'width': 160, 'height': 40}}]}})
elif command == ['pane', 'split']:
    if os.environ.get('FAKE_SPLIT_FAIL'):
        fail('split_failed')
    pane = 'fixture:p' + str(state['next'])
    state['next'] += 1
    state['panes'][pane] = {'pane_id': pane, 'label': None, 'cwd': args[args.index('--cwd') + 1]}
    reply({'pane': {'pane_id': pane}})
elif command == ['pane', 'get']:
    if os.environ.get('FAKE_PANE_GET_FAIL'):
        fail('herdr_failure')
    if args[2] not in state['panes']:
        fail('pane_not_found')
    reply({'pane': state['panes'][args[2]]})
elif command == ['pane', 'process-info']:
    pane = args[args.index('--pane') + 1]
    info = state['panes'][pane]
    info['shell_checks'] = info.get('shell_checks', 0) + 1
    ready = not os.environ.get('FAKE_SHELL_BUSY') and (not os.environ.get('FAKE_SHELL_STARTING') or info['shell_checks'] > 2)
    reply({'process_info': {'shell_pid': 100, 'foreground_process_group_id': 100,
                           'foreground_processes': [{'pid': 100}] if ready else [{'pid': 100}, {'pid': 999}],
                           'pane_id': pane}})
elif command == ['pane', 'rename']:
    if os.environ.get('FAKE_RENAME_FAIL'):
        fail('rename_failed')
    pane = state['panes'][args[2]]
    if not os.environ.get('FAKE_RENAME_NOOP'):
        pane['label'] = args[3]
    reply({'pane': pane})
elif command == ['pane', 'close']:
    if os.environ.get('FAKE_CLOSE_FAIL'):
        fail('close_failed')
    state['panes'].pop(args[2])
    state['agents'] = {k: a for k, a in state['agents'].items() if a['pane_id'] != args[2]}
    reply({'closed': True})
elif command == ['agent', 'start']:

    if os.environ.get('FAKE_SHELL_STARTING') and not state['panes'][args[args.index('--pane') + 1]].get('shell_checks', 0) > 2:
        fail('agent_pane_busy')
    if os.environ.get('FAKE_START_FAIL'):
        fail('agent_start_timeout')
    name = args[2]
    pane = args[args.index('--pane') + 1]
    agent = {'name': name, 'pane_id': pane, 'agent': 'codex', 'agent_status': 'idle',
             'cwd': state['panes'][pane]['cwd'], 'interactive_ready': True, 'state_change_seq': 0, 'completion_seq': None}
    state['agents'][name] = agent
    reply({'agent': agent})
elif command == ['agent', 'get']:
    agent = next((a for a in state['agents'].values() if a['pane_id'] == args[2]), None)
    if not agent:
        fail('agent_not_found')
    if os.environ.get('FAKE_NOT_READY'):
        agent['interactive_ready'] = False
    reply({'agent': agent})
elif command == ['agent', 'prompt']:
    agent = next(a for a in state['agents'].values() if a['pane_id'] == args[2])
    agent['agent_status'] = 'working'
    agent['state_change_seq'] += 1
    if os.environ.get('FAKE_PROMPT_FAIL'):
        state_path.write_text(json.dumps(state))
        fail('agent_prompt_stalled')
    if args[3] == '/compact':
        agent['agent_status'] = 'blocked' if os.environ.get('FAKE_COMPACT_BLOCKED') else 'done'
        agent['completion_seq'] = None if os.environ.get('FAKE_COMPACT_NOSEQ') else (agent['completion_seq'] or 0) + 1
    reply({'agent': agent})
elif command == ['agent', 'read']:
    if os.environ.get('FAKE_READ_FAIL'):
        fail('read_failed')
    lines = state.get('screen', 'Anonymous fixture result').split('\n')
    if '--lines' in args:
        lines = lines[-int(args[args.index('--lines') + 1]):]
    print('\n'.join(lines))
else:
    fail('unexpected_herdr_command')
state_path.write_text(json.dumps(state))
