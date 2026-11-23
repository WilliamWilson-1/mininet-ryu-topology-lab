"""Traffic demands and minimax routing on the lab's equal-capacity links."""
from collections import deque
import random

from paths import dial_shortest_path
from topologies import LINK_CAPACITY_MBPS

BALANCE_COOKIE = 0x4c42000000000000
BALANCE_COOKIE_MASK = 0xffff000000000000
BALANCE_PRIORITY = 105
DEFAULT_SEED = 17


def _route_under_peak(graph, source, target, load, rate):
    peak = max(load.values(), default=0)
    projected = {edge: value + rate for edge, value in load.items()}
    for limit in sorted({max(peak, value) for value in projected.values()}):
        previous = {source: None}
        pending = deque([source])
        while pending and target not in previous:
            node = pending.popleft()
            for neighbor in sorted(graph[node]):
                if neighbor not in previous and projected[node, neighbor] <= limit:
                    previous[neighbor] = node
                    pending.append(neighbor)
        if target in previous:
            path = [target]
            while path[-1] != source:
                path.append(previous[path[-1]])
            return path[::-1]
    raise ValueError('源和目的之间没有可达路径')


def plan_balance(graph, seed):
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError('seed 必须为 0 到 4294967295 之间的整数')
    if len(graph) != 20:
        raise ValueError('实验需要 20 台交换机')
    rng = random.Random(seed)
    hosts = rng.sample(sorted(graph), len(graph))
    demands = [
        dict(id=f'f{i:02d}', src=src, dst=dst, rate_mbps=rng.randint(1, 10), port=5200+i)
        for i, (src, dst) in enumerate(zip(hosts[::2], hosts[1::2]), 1)
    ]
    costs = {node: dict.fromkeys(neighbors, 1) for node, neighbors in graph.items()}
    baseline = dict.fromkeys(((u, v) for u in graph for v in graph[u]), 0)
    balanced = baseline.copy()
    for demand in demands:
        route = dial_shortest_path(costs, demand['src'], demand['dst'])['shortest']
        demand['baseline_path'] = route
        for edge in zip(route, route[1:]):
            baseline[edge] += demand['rate_mbps']
    for demand in sorted(demands, key=lambda item: -item['rate_mbps']):
        route = _route_under_peak(graph, demand['src'], demand['dst'],
                                  balanced, demand['rate_mbps'])
        demand['balanced_path'] = route
        for edge in zip(route, route[1:]):
            balanced[edge] += demand['rate_mbps']

    # A greedy batch can perform worse than the baseline on some demand sets.
    used_baseline = max(balanced.values()) > max(baseline.values())
    if used_baseline:
        balanced = baseline.copy()
        for demand in demands:
            demand['balanced_path'] = demand['baseline_path']
    return dict(seed=seed, capacity_mbps=LINK_CAPACITY_MBPS, demands=demands,
                used_baseline=used_baseline, baseline_peak_mbps=max(baseline.values()),
                balanced_peak_mbps=max(balanced.values()),
                links=[dict(src=u, dst=v, port=graph[u][v],
                            baseline_mbps=baseline[u, v], balanced_mbps=balanced[u, v])
                       for u, v in sorted(baseline)])
