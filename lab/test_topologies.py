"""Verify topology selection, all host pairs, and broadcast forwarding plans."""
from collections import deque
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import topologies
from broadcast import broadcast_plan
from paths import dial_shortest_path


class TopologyTests(unittest.TestCase):
    def test_demo_catalog_matches_controller_and_selection_is_explicit(self):
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(json.loads((root / 'docs/topologies.json').read_text()),
                         topologies.topology_catalog())
        with tempfile.TemporaryDirectory() as directory:
            selection = Path(directory) / 'selection'
            with patch.object(topologies, 'SELECTION', selection):
                self.assertEqual(topologies.load_topology()['name'], 'grid')
                selection.write_text('dual-ring\n')
                self.assertEqual(topologies.load_topology()['name'], 'dual-ring')
                self.assertEqual(topologies.load_topology('campus')['name'], 'campus')
                with self.assertRaises(ValueError):
                    topologies.load_topology('missing')

    def test_selection_command(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ('topologies.py', 'topologies.json', 'topology.json'):
                (target / name).write_bytes((root / name).read_bytes())
            subprocess.run([sys.executable, str(target / 'topologies.py'), '--select', 'campus'],
                           check=True, capture_output=True)
            self.assertEqual((target / '.active-topology').read_text(), 'campus\n')
            failed = subprocess.run(
                [sys.executable, str(target / 'topologies.py'), '--select', 'missing'],
                capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual((target / '.active-topology').read_text(), 'campus\n')

    def test_every_host_pair_and_every_broadcast_source(self):
        for name in topologies.topology_catalog():
            config = topologies.load_topology(name)
            graph = {n: {} for n in range(1, 21)}
            for a, b in config['edges']:
                graph[a][b] = len(graph[a]) + 2
                graph[b][a] = len(graph[b]) + 2
            hosts = {n: dict(name=f'h{n}', port=1) for n in graph}
            peers = {(a, port): (b, graph[b][a]) for a, ports in graph.items()
                     for b, port in ports.items()}
            for source in graph:
                distances, queue = {source: 0}, deque([source])
                while queue:
                    node = queue.popleft()
                    for neighbor in graph[node]:
                        if neighbor not in distances:
                            distances[neighbor] = distances[node] + 1
                            queue.append(neighbor)
                for target in graph:
                    if source == target:
                        continue
                    with self.subTest(topology=name, source=source, target=target):
                        result = dial_shortest_path({n: dict.fromkeys(ports, 1) for n, ports in graph.items()}, source, target)
                        self.assertEqual(result['shortest_hops'], distances[target])
                        self.assertEqual(result['distance'], distances[target])
                        for route in (result['shortest'],):
                            self.assertEqual(route[0], source)
                            self.assertEqual(route[-1], target)
                            self.assertEqual(len(route), len(set(route)))
                            self.assertTrue(all(b in graph[a] for a, b in zip(route, route[1:])))
                plan = broadcast_plan(graph, hosts, source)
                rules = {(r['switch'], r['in_port']): r['out_ports'] for r in plan['rules']}
                pending, reached, deliveries = [(source, 1)], set(), []
                while pending:
                    node, incoming = pending.pop()
                    self.assertNotIn(node, reached)
                    reached.add(node)
                    for port in rules[node, incoming]:
                        if port == 1:
                            deliveries.append(node)
                        else:
                            pending.append(peers[node, port])
                self.assertEqual(reached, set(graph))
                self.assertCountEqual(deliveries, set(graph) - {source})
                self.assertEqual(len(plan['links']), 19)


if __name__ == '__main__':
    unittest.main()
