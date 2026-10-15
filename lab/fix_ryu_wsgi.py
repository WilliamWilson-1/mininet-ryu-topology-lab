#!/usr/bin/env python3
"""Patch Ryu 4.34's removed Eventlet sentinel inside the active venv only."""
import importlib.metadata
import importlib.util
import re
import sys
from pathlib import Path

MARKER = '# mininet-ryu-topology-lab: eventlet WSGI compatibility'
REPLACEMENT = '''class _AlreadyHandledResponse(Response):
    # mininet-ryu-topology-lab: eventlet WSGI compatibility
    def __call__(self, environ, start_response):
        from eventlet import wsgi as eventlet_wsgi

        if hasattr(eventlet_wsgi, "ALREADY_HANDLED"):
            return eventlet_wsgi.ALREADY_HANDLED

        eventlet_wsgi.WSGI_LOCAL.already_handled = True
        return []


'''


def patched_source(source):
    if MARKER in source:
        return source, False
    updated, count = re.subn(
        r'^class _AlreadyHandledResponse\(Response\):.*?(?=^def websocket\()',
        REPLACEMENT, source, flags=re.M | re.S,
    )
    if count != 1:
        raise ValueError('Ryu WSGI source differs from the expected structure; no file changed')
    compile(updated, 'ryu/app/wsgi.py', 'exec')
    return updated, True


def main():
    if sys.prefix == sys.base_prefix:
        raise SystemExit('Activate the Ryu .venv first; system packages will not be modified')
    if importlib.metadata.version('ryu') != '4.34':
        raise SystemExit('This compatibility patch targets Ryu 4.34 only')
    spec = importlib.util.find_spec('ryu')
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit('Ryu is not installed in this environment')
    target = (Path(next(iter(spec.submodule_search_locations))) / 'app' / 'wsgi.py').resolve()
    if Path(sys.prefix).resolve() not in target.parents:
        raise SystemExit('Ryu package is outside the active venv; no file changed')
    source = target.read_text(encoding='utf-8')
    updated, changed = patched_source(source)
    if not changed:
        print('Already patched:', target)
        return
    backup = target.with_suffix('.py.bak')
    if not backup.exists():
        backup.write_bytes(target.read_bytes())
    temporary = target.with_name(target.name + '.sdn-lab.tmp')
    temporary.write_text(updated, encoding='utf-8')
    temporary.replace(target)
    print('Patched:', target)
    print('Original backup:', backup)


if __name__ == '__main__':
    main()
