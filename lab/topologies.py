"""Shared topology selection for Mininet, Ryu, and the static demo catalog."""
import argparse
import json
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
SELECTION = ROOT / '.active-topology'


def topology_catalog():
    catalog = json.loads((ROOT / 'topologies.json').read_text())
    catalog['grid'].update(json.loads((ROOT / 'topology.json').read_text()))
    return catalog


def load_topology(name=None):
    if name is None:
        name = SELECTION.read_text().strip() if SELECTION.exists() else 'grid'
    catalog = topology_catalog()
    if name not in catalog:
        raise ValueError('未知拓扑 %r，可选 %s' % (name, ', '.join(catalog)))
    config = dict(catalog[name], name=name)
    if config['nodes'] != 20:
        raise ValueError('实验拓扑必须包含 20 台交换机')
    graph = {node: set() for node in range(1, 21)}
    for a, b in config['edges']:
        if type(a) is not int or type(b) is not int or a not in graph or b not in graph or a == b:
            raise ValueError('链路端点必须是 1 到 20 中两个不同的整数')
        if b in graph[a]:
            raise ValueError('拓扑包含重复链路')
        graph[a].add(b)
        graph[b].add(a)
    reached, pending = {1}, [1]
    while pending:
        node = pending.pop()
        for neighbor in graph[node] - reached:
            reached.add(neighbor)
            pending.append(neighbor)
    if len(reached) != 20:
        raise ValueError('拓扑必须连通')
    return config


def main():
    parser = argparse.ArgumentParser(description='列出或选择下次启动使用的实验拓扑')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--list', action='store_true')
    actions.add_argument('--select', metavar='NAME')
    args = parser.parse_args()
    try:
        if args.list:
            for name in topology_catalog():
                config = load_topology(name)
                print('%-12s 20 交换机 / %2d 链路  %s' %
                      (name, len(config['edges']), config['title']))
            return
        config = load_topology(args.select)
        if args.select:
            # Atomic replacement prevents readers from seeing an empty name.
            temporary = ROOT / ('.active-topology.%d.tmp' % os.getpid())
            try:
                temporary.write_text(config['name'] + '\n')
                temporary.replace(SELECTION)
            finally:
                temporary.unlink(missing_ok=True)
            print('已选择 %s (%s)；请重新启动 Ryu 和 Mininet。' %
                  (config['title'], config['name']))
            return
        print(json.dumps(config, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
