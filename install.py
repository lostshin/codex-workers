#!/usr/bin/env python3
"""Install links without overwriting another command or skill."""
import os
import sys
from pathlib import Path

project = Path(__file__).resolve().parent
targets = {
    Path.home() / '.local/bin/codex-workers': project / 'codex-workers',
    Path.home() / '.codex/skills/codex-workers': project / 'skill/codex-workers',
}
if '--claude' in sys.argv[1:]:
    # Claude Code discovers skills from its own directory.
    targets[Path.home() / '.claude/skills/codex-workers'] = project / 'skill/codex-workers'
for destination, source in targets.items():
    if (destination.exists() or destination.is_symlink()) and not (
            destination.is_symlink() and destination.resolve() == source.resolve()):
        raise SystemExit(f'Refusing to overwrite {destination}')
os.chmod(project / 'codex-workers', 0o755)
for destination, source in targets.items():
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_symlink():
        destination.symlink_to(source, target_is_directory=source.is_dir())
    print(f'{destination} -> {source}')
