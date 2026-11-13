"""Dijkstra shortest paths using Dial's cyclic buckets for integer costs."""
from collections import deque


def dial_shortest_path(graph, source, target, cooperate=lambda: None):
    """graph[u][v] is a nonnegative integer cost, independent of OVS ports."""
    if source not in graph or target not in graph:
        raise ValueError('源或目的交换机不在已发现拓扑中')
    maximum = 0
    for neighbors in graph.values():
        for neighbor, cost in neighbors.items():
            if neighbor not in graph:
                raise ValueError('链路端点不在拓扑中')
            if type(cost) is not int or cost < 0:
                raise ValueError('Dial 要求非负整数链路权重')
            maximum = max(maximum, cost)

    buckets = [deque() for _ in range(maximum + 1)]
    distances = {source: 0}
    predecessors = {}
    settled = set()
    buckets[0].append((0, source))
    current, pending, relaxations = 0, 1, 0
    while pending:
        bucket = buckets[current % len(buckets)]
        if not bucket:
            current += 1
            continue
        distance, node = bucket.popleft()
        pending -= 1
        # Improved labels leave old entries behind until their bucket is read.
        if node in settled or distance != distances[node]:
            continue
        settled.add(node)
        if len(settled) % 128 == 0:
            cooperate()
        if node == target:
            break
        for neighbor, cost in sorted(graph[node].items()):
            candidate = distance + cost
            if candidate < distances.get(neighbor, float('inf')):
                distances[neighbor] = candidate
                predecessors[neighbor] = node
                buckets[candidate % len(buckets)].append((candidate, neighbor))
                pending += 1
                relaxations += 1
    if target not in settled:
        raise ValueError('源和目的之间没有可达路径')
    path = [target]
    while path[-1] != source:
        path.append(predecessors[path[-1]])
    path.reverse()
    return dict(shortest=path, shortest_hops=len(path) - 1,
                distance=distances[target], settled_count=len(settled),
                relaxations=relaxations, bucket_count=len(buckets),
                algorithm='dijkstra-dial', exact=True)
