"""Independent checks: BFS shortest path and permutation-based longest path."""
import itertools
import json
import random
import unittest
from collections import deque
from pathlib import Path
from paths import dfs_paths, SearchLimit


class PathTests(unittest.TestCase):
    def test_small_graphs_against_independent_oracles(self):
        rng = random.Random(17)
        for _ in range(30):
            graph = {i: set() for i in range(6)}
            for a, b in itertools.combinations(graph, 2):
                if rng.random() < 0.4:
                    graph[a].add(b)
                    graph[b].add(a)
            distance, queue = {0: 0}, deque([0])
            while queue:
                a = queue.popleft()
                for b in graph[a]:
                    if b not in distance:
                        distance[b] = distance[a] + 1
                        queue.append(b)
            lengths = []
            for size in range(5):
                for middle in itertools.permutations(range(1, 5), size):
                    candidate = (0,) + middle + (5,)
                    if all(b in graph[a] for a, b in zip(candidate, candidate[1:])):
                        lengths.append(len(candidate) - 1)
            if 5 not in distance:
                with self.assertRaises(ValueError):
                    dfs_paths(graph, 0, 5)
            else:
                result = dfs_paths(graph, 0, 5)
                self.assertEqual(result['shortest_hops'], distance[5])
                self.assertEqual(result['longest_hops'], max(lengths))
                self.assertEqual(result['simple_path_count'], len(lengths))
                self.assertEqual(len(set(result['longest'])), len(result['longest']))

    def test_budget_never_returns_a_partial_longest_path(self):
        with self.assertRaises(SearchLimit):
            dfs_paths({0: {1}, 1: {0}}, 0, 1, max_visits=1)

    def test_example_topology(self):
        config = json.loads(Path(__file__).with_name('topology.json').read_text())
        graph = {i: set() for i in range(1, 21)}
        for a, b in config['edges']:
            graph[a].add(b)
            graph[b].add(a)
        result = dfs_paths(graph, 1, 20)
        self.assertEqual(result['shortest'], [1, 20])
        self.assertEqual(result['longest'], list(range(1, 21)))
        self.assertEqual(result['longest_hops'], 19)


if __name__ == '__main__':
    unittest.main()
