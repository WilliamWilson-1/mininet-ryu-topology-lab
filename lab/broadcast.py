"""Build a minimum spanning tree and map it to one-way broadcast rules."""
from collections import deque

BROADCAST_MAC = 'ff:ff:ff:ff:ff:ff'
BROADCAST_IP = '255.255.255.255'
BROADCAST_PORT = 5005
BROADCAST_PRIORITY = 110
BROADCAST_COOKIE = 0x4252430000000000
BROADCAST_COOKIE_MASK = 0xffffffff00000000


def kruskal_tree(nodes, edges):
    """Return (weight, a, b) edges, ordered by weight then endpoint IDs."""
    parent = {node: node for node in nodes}
    size = dict.fromkeys(parent, 1)

    def find(node):
        while node != parent[node]:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    selected = []
    for weight, a, b in sorted((w, min(a, b), max(a, b)) for w, a, b in edges):
        left, right = find(a), find(b)
        if left == right:
            continue
        if size[left] < size[right]:
            left, right = right, left
        parent[right] = left
        size[left] += size[right]
        selected.append((weight, a, b))
        if len(selected) == len(parent) - 1:
            break
    if not parent or len(selected) != len(parent) - 1:
        raise ValueError('交换机拓扑不连通，无法建立广播树')
    return selected


def broadcast_plan(graph, hosts, source):
    """Orient the MST from source and use LLDP port numbers at both ends."""
    edges = [(1, a, b) for a, neighbors in graph.items()
             for b in neighbors if a < b]
    tree = {node: {} for node in graph}
    selected = kruskal_tree(graph, edges)
    for weight, a, b in selected:
        tree[a][b] = tree[b][a] = weight

    parents = {source: None}
    pending = deque([source])
    links, rules = [], []
    while pending:
        node = pending.popleft()
        parent = parents[node]
        incoming = hosts[node]['port'] if parent is None else graph[node][parent]
        outputs = [] if parent is None else [hosts[node]['port']]
        for child, weight in sorted(tree[node].items()):
            if child == parent:
                continue
            parents[child] = node
            pending.append(child)
            outputs.append(graph[node][child])
            links.append(dict(src=node, dst=child, weight=weight,
                              src_port=graph[node][child], dst_port=graph[child][node]))
        rules.append(dict(switch=node, in_port=incoming, out_ports=outputs))
    return dict(src=hosts[source]['name'], source_switch=source,
                receivers=[hosts[node]['name'] for node in sorted(graph) if node != source],
                links=links, rules=rules, total_weight=sum(weight for weight, _, _ in selected),
                ipv4_dst=BROADCAST_IP, udp_dst=BROADCAST_PORT)
