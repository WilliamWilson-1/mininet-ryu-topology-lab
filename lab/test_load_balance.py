"""Check demand reproducibility and accounting on the supported topologies."""
from collections import Counter
import unittest

from load_balance import _route_under_peak, plan_balance
from topologies import load_topology, topology_catalog


class LoadBalanceTests(unittest.TestCase):
    def test_seed_17_grid_improves_peak_from_18_to_9(self):
        graph = self.make_graph('grid')
        plan = plan_balance(graph, 17)
        self.assertEqual(plan, plan_balance(graph, 17))
        self.assertEqual(plan['baseline_peak_mbps'], 18)
        self.assertEqual(plan['balanced_peak_mbps'], 9)
        self.assertEqual(len(plan['links']), 62)

    def test_accounting_for_all_presets(self):
        for name in topology_catalog():
            graph = self.make_graph(name)
            for seed in (0, 17, 42, 2**32-1):
                with self.subTest(topology=name, seed=seed):
                    plan = plan_balance(graph, seed)
                    demands = plan['demands']
                    self.assertEqual(len(demands), 10)
                    self.assertEqual(len({flow['port'] for flow in demands}), 10)
                    self.assertCountEqual([node for flow in demands
                                           for node in (flow['src'], flow['dst'])], graph.keys())
                    for mode in ('baseline', 'balanced'):
                        load = Counter()
                        for flow in demands:
                            rate, path = flow['rate_mbps'], flow[mode + '_path']
                            self.assertTrue(1 <= rate <= 10)
                            self.assertEqual((path[0], path[-1]), (flow['src'], flow['dst']))
                            self.assertEqual(len(path), len(set(path)))
                            for a, b in zip(path, path[1:]):
                                self.assertIn(b, graph[a])
                                load[a, b] += rate
                        for link in plan['links']:
                            self.assertEqual(link[mode + '_mbps'], load[link['src'], link['dst']])
                        self.assertEqual(plan[mode + '_peak_mbps'], max(load.values()))
                    self.assertLessEqual(plan['balanced_peak_mbps'], plan['baseline_peak_mbps'])

    def test_peak_check_then_shortest_path(self):
        graph = {1: {2: 1, 3: 2}, 2: {4: 1}, 3: {5: 1}, 5: {4: 1}, 4: {}}
        load = {(1, 2): 4, (2, 4): 0, (1, 3): 0, (3, 5): 0, (5, 4): 0}
        self.assertEqual(_route_under_peak(graph, 1, 4, load, 3), [1, 3, 5, 4])
        load[5, 4] = 7
        self.assertEqual(_route_under_peak(graph, 1, 4, load, 3), [1, 2, 4])

    @staticmethod
    def make_graph(name):
        config = load_topology(name)
        graph = {node: {} for node in range(1, config['nodes'] + 1)}
        for a, b in config['edges']:
            graph[a][b] = len(graph[a]) + 2
            graph[b][a] = len(graph[b]) + 2
        return graph
