"""Compare Dial with independent shortest-path oracles, including zero costs."""
import json
import random
import unittest
from pathlib import Path

from paths import dial_shortest_path


class PathTests(unittest.TestCase):
    def test_weighted_graphs_against_floyd_warshall(self):
        rng = random.Random(17)
        for _ in range(50):
            graph = {n: {} for n in range(7)}
            distances = [[float('inf')] * 7 for _ in graph]
            for a in graph:
                distances[a][a] = 0
                for b in graph:
                    if a != b and rng.random() < .4:
                        graph[a][b] = distances[a][b] = rng.randrange(6)
            for k in graph:
                for a in graph:
                    for b in graph:
                        distances[a][b] = min(distances[a][b],
                                              distances[a][k] + distances[k][b])
            for a in graph:
                for b in graph:
                    if distances[a][b] == float('inf'):
                        with self.assertRaises(ValueError):
                            dial_shortest_path(graph, a, b)
                    else:
                        result = dial_shortest_path(graph, a, b)
                        path = result['shortest']
                        self.assertEqual(result['distance'], distances[a][b])
                        self.assertEqual(path[0], a)
                        self.assertEqual(path[-1], b)
                        self.assertEqual(len(path), len(set(path)))
                        self.assertEqual(sum(graph[x][y] for x, y in zip(path, path[1:])),
                                         distances[a][b])

    def test_decrease_key_and_bucket_wraparound(self):
        graph = {1: {2: 5, 3: 1}, 2: {4: 4}, 3: {2: 1}, 4: {5: 5}, 5: {}}
        result = dial_shortest_path(graph, 1, 5)
        self.assertEqual(result['shortest'], [1, 3, 2, 4, 5])
        self.assertEqual(result['distance'], 11)
        self.assertEqual(result['bucket_count'], 6)

    def test_zero_cost_cycle_and_invalid_costs(self):
        result = dial_shortest_path({1: {2: 0}, 2: {1: 0, 3: 0}, 3: {}}, 1, 3)
        self.assertEqual(result['distance'], 0)
        self.assertEqual(result['bucket_count'], 1)
        for cost in (-1, .5, True):
            with self.assertRaises(ValueError):
                dial_shortest_path({1: {2: cost}, 2: {}}, 1, 2)
        with self.assertRaises(ValueError):
            dial_shortest_path({1: {2: 1}}, 1, 1)
        with self.assertRaises(ValueError):
            dial_shortest_path({1: {}}, 1, 2)

    def test_example_topology(self):
        config = json.loads(Path(__file__).with_name('topology.json').read_text())
        graph = {i: {} for i in range(1, 21)}
        for a, b in config['edges']:
            graph[a][b] = graph[b][a] = 1
        result = dial_shortest_path(graph, 1, 20)
        self.assertEqual(result['shortest'], [1, 2, 3, 4, 5, 10, 15, 20])
        self.assertEqual(result['shortest_hops'], 7)
        self.assertEqual(result['distance'], 7)
        self.assertEqual(result['algorithm'], 'dijkstra-dial')


if __name__ == '__main__':
    unittest.main()
