"""Exact DFS enumeration of simple paths, with an explicit resource limit."""
import time


class SearchLimit(RuntimeError):
    pass


def dfs_paths(graph, source, target, max_visits=500000, seconds=5,
              cooperate=lambda: None):
    if source not in graph or target not in graph:
        raise ValueError('源或目的交换机不在已发现拓扑中')
    start = time.monotonic()
    shortest = longest = None
    path = [source]
    visited = {source}
    count = visits = 0

    def walk(node):
        nonlocal shortest, longest, count, visits
        visits += 1
        if visits > max_visits or time.monotonic() - start > seconds:
            raise SearchLimit('DFS 超出预算；没有返回或下发未经证明的最长路')
        if visits % 1000 == 0:
            cooperate()
        if node == target:
            count += 1
            if shortest is None or len(path) < len(shortest):
                shortest = list(path)
            if longest is None or len(path) > len(longest):
                longest = list(path)
            return
        for neighbor in sorted(graph[node]):
            if neighbor not in visited:
                visited.add(neighbor)
                path.append(neighbor)
                walk(neighbor)
                path.pop()
                visited.remove(neighbor)

    walk(source)
    if shortest is None:
        raise ValueError('源和目的之间没有可达路径')
    return dict(shortest=shortest, longest=longest,
                shortest_hops=len(shortest) - 1,
                longest_hops=len(longest) - 1,
                simple_path_count=count, dfs_visits=visits, exact=True)
