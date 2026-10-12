"""Teaching controller: LLDP discovery, exact DFS, bidirectional IPv4 flows."""
import json
import time
from pathlib import Path
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (set_ev_cls, CONFIG_DISPATCHER,
                                    MAIN_DISPATCHER, DEAD_DISPATCHER)
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.topology.api import get_switch, get_link
from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from webob import Response
from paths import dfs_paths, SearchLimit


class LabController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(LabController, self).__init__(*args, **kwargs)
        self.dps = {}
        self.hosts = {}
        self.graph = {}
        self.fingerprint = None
        self.version = 0
        self.services = {}
        self.stats = {}
        self.pending_barriers = {}
        self.pending_mods = {}
        self.lock = hub.Semaphore(1)
        config = json.loads(Path(__file__).with_name('topology.json').read_text())
        self.expected_nodes = set(range(1, config['nodes'] + 1))
        self.expected_edges = {tuple(sorted(edge)) for edge in config['edges']}
        self.next_cookie = 0x20000000
        kwargs['wsgi'].register(LabAPI, {'lab': self})
        self.worker = hub.spawn(self.monitor)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features(self, ev):
        dp = ev.msg.datapath
        self.dps[dp.id] = dp
        p, o = dp.ofproto_parser, dp.ofproto
        self.flow(dp, 0, p.OFPMatch(),
                  [p.OFPActionOutput(o.OFPP_CONTROLLER, o.OFPCML_NO_BUFFER)])

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.dps[dp.id] = dp
        elif self.dps.get(dp.id) is dp:
            self.dps.pop(dp.id, None)
            self.hosts.pop(dp.id, None)
            self.stats.pop(dp.id, None)

    def flow(self, dp, priority, match, actions, cookie=0, batch=None):
        p, o = dp.ofproto_parser, dp.ofproto
        instructions = [p.OFPInstructionActions(o.OFPIT_APPLY_ACTIONS, actions)]
        msg = p.OFPFlowMod(datapath=dp, cookie=cookie, priority=priority,
                          match=match, instructions=instructions,
                          idle_timeout=0, hard_timeout=0)
        if batch is not None:
            dp.set_xid(msg)
            key = (dp.id, msg.xid)
            self.pending_mods[key] = batch
            batch['mods'].append(key)
        dp.send_msg(msg)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        eth = packet.Packet(msg.data).get_protocol(ethernet.ethernet)
        if not eth or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        dpid = msg.datapath.id
        expected = '02:00:00:00:00:%02x' % dpid
        # Learn only actual host-facing packets; never learn a transit port.
        if msg.match['in_port'] == 1 and eth.src == expected:
            self.hosts[dpid] = dict(name='h%d' % dpid, switch=dpid, port=1,
                                   mac=eth.src, ip='10.0.0.%d' % dpid)
        # Unconfigured traffic and broadcasts are intentionally not forwarded.
        # Mininet supplies static ARP; configured IPv4 traffic stays in OVS.

    def refresh(self):
        graph = {sw.dp.id: {} for sw in get_switch(self, None)
                 if sw.dp.id in self.dps}
        directed = {}
        for link in get_link(self, None):
            if link.src.dpid in graph and link.dst.dpid in graph:
                directed[(link.src.dpid, link.dst.dpid)] = link.src.port_no
        # Only expose edges whose two LLDP directions have been discovered.
        for (a, b), port in directed.items():
            if (b, a) in directed:
                graph[a][b] = port
        signature = tuple((a, tuple(sorted(ports.items())))
                          for a, ports in sorted(graph.items()))
        if signature != self.fingerprint:
            self.graph = graph
            self.fingerprint = signature
            self.version += 1
            for service in self.services.values():
                if service['status'] != 'stale':
                    self.remove_cookie(service['cookie'])
                    service['status'] = 'stale'
                    service['reason'] = '拓扑变化，请重新配置'
            self.logger.info('Topology version=%s, switches=%s, links=%s',
                             self.version, len(graph),
                             sum(map(len, graph.values())) // 2)

    def remove_cookie(self, cookie):
        for dp in list(self.dps.values()):
            p, o = dp.ofproto_parser, dp.ofproto
            dp.send_msg(p.OFPFlowMod(datapath=dp, cookie=cookie,
                        cookie_mask=0xffffffffffffffff, table_id=o.OFPTT_ALL,
                        command=o.OFPFC_DELETE, out_port=o.OFPP_ANY,
                        out_group=o.OFPG_ANY, match=p.OFPMatch()))

    def monitor(self):
        while True:
            try:
                self.refresh()
                for dp in list(self.dps.values()):
                    dp.send_msg(dp.ofproto_parser.OFPFlowStatsRequest(dp))
            except Exception:
                self.logger.exception('Monitor failed')
            hub.sleep(2)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats(self, ev):
        dp = ev.msg.datapath
        # Store each multipart fragment; clear at the start of a new xid.
        previous = self.stats.get(dp.id)
        if previous is None or previous['xid'] != ev.msg.xid:
            previous = dict(xid=ev.msg.xid, rows=[], timestamp=time.time(),
                            complete=False)
            self.stats[dp.id] = previous
        for entry in ev.msg.body:
            if entry.priority == 100:
                previous['rows'].append(dict(cookie=entry.cookie,
                    src=entry.match.get('ipv4_src'), packets=entry.packet_count,
                    bytes=entry.byte_count))
        previous['complete'] = not bool(ev.msg.flags & dp.ofproto.OFPMPF_REPLY_MORE)
        previous['timestamp'] = time.time()

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def barrier_reply(self, ev):
        self.pending_barriers.pop((ev.msg.datapath.id, ev.msg.xid), None)

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error(self, ev):
        msg = ev.msg
        self.logger.error('OpenFlow error dpid=%s type=%s code=%s xid=%s',
                          msg.datapath.id, msg.type, msg.code, msg.xid)
        batch = self.pending_mods.get((msg.datapath.id, msg.xid))
        if batch is not None:
            batch['errors'].append('s%d: type=%d code=%d' %
                                   (msg.datapath.id, msg.type, msg.code))

    @staticmethod
    def host_id(value):
        value = str(value)
        number = int(value[1:] if value.startswith('h') else value)
        if not 1 <= number <= 20:
            raise ValueError('主机范围为 h1 到 h20')
        return number

    def compute(self, src, dst):
        self.refresh()
        discovered = {(a, b) for a, ports in self.graph.items()
                      for b in ports if a < b}
        if set(self.graph) != self.expected_nodes or discovered != self.expected_edges:
            raise ValueError('已发现拓扑与 topology.json 尚未完全一致，请等待 LLDP 收敛或检查链路')
        a, b = self.host_id(src), self.host_id(dst)
        if a == b:
            raise ValueError('请选择两个不同主机')
        if a not in self.hosts or b not in self.hosts:
            raise ValueError('主机尚未通过 PacketIn 被发现，请重新执行探测')
        version = self.version
        graph = {node: dict(ports) for node, ports in self.graph.items()}
        result = dfs_paths(graph, a, b, cooperate=lambda: hub.sleep(0))
        self.refresh()
        if version != self.version:
            raise ValueError('搜索期间拓扑发生变化，请重试')
        result.update(src='h%d' % a, dst='h%d' % b, topology_version=version)
        return result, graph

    def install(self, src, dst):
        with self.lock:
            result, graph = self.compute(src, dst)
            a, b = self.host_id(src), self.host_id(dst)
            low, high = sorted((a, b))
            key = 'h%d-h%d' % (low, high)
            self.next_cookie += 1
            cookie = self.next_cookie
            path = result['longest']
            old_service = self.services.pop(key, None)
            if old_service:
                self.remove_cookie(old_service['cookie'])
            # A new cookie prevents delayed old replies from proving new traffic.
            batch = dict(mods=[], barriers=[], errors=[])
            try:
                for route_nodes, source, target in [(path, a, b),
                                                   (path[::-1], b, a)]:
                    for index, node in enumerate(route_nodes):
                        incoming = (1 if index == 0 else
                                    graph[node][route_nodes[index - 1]])
                        outgoing = (1 if index == len(route_nodes) - 1 else
                                    graph[node][route_nodes[index + 1]])
                        dp = self.dps[node]
                        p = dp.ofproto_parser
                        match = p.OFPMatch(in_port=incoming, eth_type=0x0800,
                                     ipv4_src='10.0.0.%d' % source,
                                     ipv4_dst='10.0.0.%d' % target)
                        self.flow(dp, 100, match, [p.OFPActionOutput(outgoing)],
                                  cookie, batch)
                for node in path:
                    dp = self.dps[node]
                    msg = dp.ofproto_parser.OFPBarrierRequest(dp)
                    dp.set_xid(msg)
                    barrier_key = (node, msg.xid)
                    self.pending_barriers[barrier_key] = True
                    batch['barriers'].append(barrier_key)
                    dp.send_msg(msg)
                deadline = time.monotonic() + 3
                while any(k in self.pending_barriers for k in batch['barriers']):
                    if batch['errors']:
                        raise ValueError('; '.join(batch['errors']))
                    if time.monotonic() > deadline:
                        raise ValueError('等待 OpenFlow Barrier 超时')
                    hub.sleep(0.01)
                if batch['errors']:
                    raise ValueError('; '.join(batch['errors']))
                self.refresh()
                if result['topology_version'] != self.version:
                    raise ValueError('下发期间拓扑发生变化')
                service = dict(result, id=key, cookie=cookie, status='installed',
                               path=path, created_at=time.time())
                self.services[key] = service
                return service
            except Exception:
                self.remove_cookie(cookie)
                raise
            finally:
                for k in batch['mods']:
                    self.pending_mods.pop(k, None)
                for k in batch['barriers']:
                    self.pending_barriers.pop(k, None)

    def topology(self):
        self.refresh()
        edges = [dict(src=a, dst=b, src_port=port, dst_port=self.graph[b][a])
                 for a, ports in sorted(self.graph.items())
                 for b, port in sorted(ports.items()) if a < b]
        return dict(version=self.version, switches=sorted(self.graph),
                    links=edges, hosts=list(self.hosts.values()))

    def service_list(self):
        services = []
        for service in self.services.values():
            item = dict(service)
            item['counters'] = []
            for node in service['path']:
                data = self.stats.get(node, {})
                fresh = (data.get('complete', False) and
                         time.time() - data.get('timestamp', 0) < 6)
                counts = {r['src']: r for r in data.get('rows', [])
                          if r['cookie'] == service['cookie']} if fresh else {}
                for host in (service['src'], service['dst']):
                    ip = '10.0.0.%d' % self.host_id(host)
                    row = counts.get(ip)
                    item['counters'].append(dict(switch=node, src=host,
                           fresh=fresh, present=row is not None,
                           packets=row['packets'] if row else 0,
                           bytes=row['bytes'] if row else 0))
            item['both_directions_seen_on_all_hops'] = (
                item['status'] == 'installed' and
                all(r['fresh'] and r['present'] and r['packets'] > 0
                    for r in item['counters']))
            services.append(item)
        return services


class LabAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(LabAPI, self).__init__(req, link, data, **config)
        self.lab = data['lab']

    @staticmethod
    def response(data, status=200):
        return Response(status=status, content_type='application/json',
                        charset='utf-8',
                        body=json.dumps(data, ensure_ascii=False).encode('utf-8'))

    @route('lab_topology', '/api/topology', methods=['GET'])
    def topology(self, req, **kwargs):
        return self.response(self.lab.topology())

    @route('lab_paths', '/api/paths', methods=['GET'])
    def paths(self, req, **kwargs):
        try:
            result, _ = self.lab.compute(req.params['src'], req.params['dst'])
            return self.response(result)
        except SearchLimit as exc:
            return self.response({'error': str(exc), 'exact': False}, 422)
        except (ValueError, KeyError) as exc:
            return self.response({'error': str(exc)}, 400)

    @route('lab_services', '/api/services', methods=['GET'])
    def services(self, req, **kwargs):
        return self.response(self.lab.service_list())

    @route('lab_install', '/api/services', methods=['POST'])
    def install(self, req, **kwargs):
        try:
            data = req.json
            service = self.lab.install(data['src'], data['dst'])
            return self.response(service)
        except SearchLimit as exc:
            return self.response({'error': str(exc), 'exact': False}, 422)
        except (ValueError, KeyError) as exc:
            return self.response({'error': str(exc)}, 400)

    @route('lab_ui', '/', methods=['GET'])
    def index(self, req, **kwargs):
        body = Path(__file__).with_name('static').joinpath('index.html').read_bytes()
        return Response(content_type='text/html', charset='utf-8', body=body)
