import json
import unittest
from pathlib import Path

from broadcast import broadcast_plan, kruskal_tree


class BroadcastTests(unittest.TestCase):
    def test_weighted_mst_skips_cycle_and_takes_cheapest_connector(self):
        edges = [(5, 1, 4), (2, 1, 3), (1, 2, 1), (1, 3, 2), (3, 3, 4)]
        self.assertEqual(kruskal_tree(range(1, 5), edges),
                         [(1, 1, 2), (1, 2, 3), (3, 3, 4)])
        with self.assertRaises(ValueError):
            kruskal_tree(range(1, 6), edges)

    def test_all_roots_forward_exactly_one_copy_per_receiver(self):
        config = json.loads(Path(__file__).with_name('topology.json').read_text())
        graph = {n: {} for n in range(1, config['nodes'] + 1)}
        for a, b in config['edges']:
            graph[a][b] = len(graph[a]) + 2
            graph[b][a] = len(graph[b]) + 2
        hosts = {n: dict(name=f'h{n}', port=1) for n in graph}
        peer = {(a, port): (b, graph[b][a]) for a, ports in graph.items()
                for b, port in ports.items()}
        original_edges = None
        for root in graph:
            with self.subTest(root=root):
                plan = broadcast_plan(graph, hosts, root)
                edges = {tuple(sorted((e['src'], e['dst']))) for e in plan['links']}
                if original_edges is None:
                    original_edges = edges
                self.assertEqual(edges, original_edges)
                self.assertEqual(len(edges), 19)
                self.assertEqual(plan['total_weight'], 19)
                rules = {(r['switch'], r['in_port']): r['out_ports'] for r in plan['rules']}
                pending, visited, delivered = [(root, 1)], set(), []
                while pending:
                    node, incoming = pending.pop()
                    self.assertNotIn(node, visited)
                    visited.add(node)
                    for port in rules[node, incoming]:
                        if port == 1:
                            delivered.append(node)
                        else:
                            pending.append(peer[node, port])
                self.assertEqual(visited, set(graph))
                self.assertCountEqual(delivered, set(graph) - {root})


if __name__ == '__main__':
    unittest.main()
