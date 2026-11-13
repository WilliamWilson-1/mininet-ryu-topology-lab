"""Teaching controller: LLDP discovery, Dial shortest paths and MST broadcast flows."""
import json
import time
from collections import deque
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
from paths import dial_shortest_path
from topologies import load_topology, topology_catalog
from broadcast import (broadcast_plan, BROADCAST_COOKIE, BROADCAST_COOKIE_MASK,
                       BROADCAST_MAC, BROADCAST_IP, BROADCAST_PORT, BROADCAST_PRIORITY)


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
        self.broadcast = None
        self.stats = {}
        self.pending_barriers = {}
        self.pending_mods = {}
        self.lock = hub.Semaphore(1)
        config = self.topology_config = load_topology()
        self.expected_nodes = set(range(1, config['nodes'] + 1))
        self.expected_edges = {tuple(sorted(edge)) for edge in config['edges']}
        self.next_cookie = 0x20000000
        # OpenFlow message log exposed to the visualization via GET /api/events.
        # Named msg_log: `events` is Ryu's internal event queue attribute.
        self.msg_log = deque(maxlen=3000)
        # Teaching-critical messages kept for the whole session (survive the
        # LLDP flood that fills msg_log).
        self.milestones = deque(maxlen=300)
        self.next_event = 1
        self.lldp_windows = {}
        self.last_stats_event = 0.0
        kwargs['wsgi'].register(LabAPI, {'lab': self})
        self.worker = hub.spawn(self.monitor)

    def emit(self, kind, direction, dpid, summary, detail=None):
        event = dict(id=self.next_event, t=round(time.time(), 3), kind=kind,
                     dir=direction, dpid=dpid, summary=summary)
        if detail is not None:
            event['detail'] = detail
        self.msg_log.append(event)
        if kind in ('connect', 'state', 'host_learn', 'flow_mod', 'flow_del',
                    'barrier', 'barrier_reply', 'service', 'error', 'topology'):
            self.milestones.append(event)
        self.next_event += 1

    def _note_lldp(self, dpid, port):
        window = self.lldp_windows.get(dpid)
        if window is None:
            self.lldp_windows[dpid] = [time.time(), 1]
        else:
            window[1] += 1

    def _flush_lldp(self):
        now = time.time()
        for dpid, window in list(self.lldp_windows.items()):
            if now - window[0] >= 2.0:
                self.emit('lldp', '←', dpid,
                          's%d 收到邻居 LLDP ×%d(2 秒聚合)' % (dpid, window[1]))
                del self.lldp_windows[dpid]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features(self, ev):
        dp = ev.msg.datapath
        self.dps[dp.id] = dp
        self.invalidate_broadcast('交换机重新连接，请重新配置')
        self.delete_flows(dp, BROADCAST_COOKIE, BROADCAST_COOKIE_MASK)
        self.emit('connect', '←', dp.id,
                  'FeaturesReply:OpenFlow 1.3 握手完成,交换机上线')
        p, o = dp.ofproto_parser, dp.ofproto
        self.flow(dp, 0, p.OFPMatch(),
                  [p.OFPActionOutput(o.OFPP_CONTROLLER, o.OFPCML_NO_BUFFER)])
        self.emit('flow_mod', '→', dp.id,
                  'FlowMod table-miss(priority=0):未匹配报文完整送控制器')

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.dps[dp.id] = dp
            self.emit('state', '←', dp.id, '控制通道进入 MAIN 状态')
        elif self.dps.get(dp.id) is dp:
            self.dps.pop(dp.id, None)
            self.hosts.pop(dp.id, None)
            self.stats.pop(dp.id, None)
            self.invalidate_broadcast('交换机断开，请重新配置')
            self.emit('state', '←', dp.id, '控制通道断开,清除该交换机状态')

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
        if not eth:
            return
        dpid = msg.datapath.id
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            self._note_lldp(dpid, msg.match['in_port'])
            return
        expected = '02:00:00:00:00:%02x' % dpid
        # Learn only actual host-facing packets; never learn a transit port.
        if msg.match['in_port'] == 1 and eth.src == expected:
            entry = dict(name='h%d' % dpid, switch=dpid, port=1,
                         mac=eth.src, ip='10.0.0.%d' % dpid)
            if self.hosts.get(dpid) != entry:
                self.hosts[dpid] = entry
                self.emit('host_learn', '←', dpid,
                          'PacketIn 主机发现:s%d:p1 源 %s → h%d(10.0.0.%d)'
                          % (dpid, eth.src, dpid, dpid))
            return
        self.emit('packet_in', '←', dpid,
                  'PacketIn s%d:p%d 源 %s 目的 %s(未配置业务,不转发)'
                  % (dpid, msg.match['in_port'], eth.src, eth.dst))
        # Unconfigured traffic is intentionally not forwarded.
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
            self.invalidate_broadcast('拓扑变化，请重新配置')
            for service in self.services.values():
                if service['status'] != 'stale':
                    self.remove_cookie(service['cookie'])
                    service['status'] = 'stale'
                    service['reason'] = '拓扑变化，请重新配置'
            self.logger.info('Topology version=%s, switches=%s, links=%s',
                             self.version, len(graph),
                             sum(map(len, graph.values())) // 2)
            links = sum(map(len, graph.values())) // 2
            self.emit('topology', '·', 0,
                      '拓扑指纹变化 → 版本 %d:%d 台交换机 / %d 条链路' %
                      (self.version, len(graph), links))
            if self.services:
                self.emit('topology', '·', 0,
                          '业务标记 stale,并按 cookie 撤回全部规则')
            discovered = {(a, b) for a, ports in graph.items()
                          for b in ports if a < b}
            if set(graph) == self.expected_nodes \
                    and discovered == self.expected_edges:
                self.emit('topology', '·', 0,
                          '已发现拓扑与 %s 完全一致（%d 交换机 / %d 链路）' %
                          (self.topology_config['title'], len(self.expected_nodes),
                           len(self.expected_edges)))

    def remove_cookie(self, cookie):
        self.emit('flow_del', '→', 0,
                  'FlowMod DELETE:cookie=0x%x 的规则从全部交换机撤销' % cookie)
        for dp in list(self.dps.values()):
            self.delete_flows(dp, cookie)

    @staticmethod
    def delete_flows(dp, cookie, mask=0xffffffffffffffff):
        p, o = dp.ofproto_parser, dp.ofproto
        dp.send_msg(p.OFPFlowMod(datapath=dp, cookie=cookie,
                    cookie_mask=mask, table_id=o.OFPTT_ALL,
                    command=o.OFPFC_DELETE, out_port=o.OFPP_ANY,
                    out_group=o.OFPG_ANY, match=p.OFPMatch()))

    def invalidate_broadcast(self, reason):
        service = self.broadcast
        if service and service['status'] == 'installed':
            service.update(status='stale', reason=reason)
            self.remove_cookie(int(service['cookie'], 16))
            self.emit('service', '·', 0, '广播业务撤回。' + reason)

    def monitor(self):
        while True:
            try:
                self._flush_lldp()
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
            now = time.time()
            if now - self.last_stats_event > 1.5:
                self.last_stats_event = now
                self.emit('stats', '←', dp.id,
                          'FlowStatsReply 采样轮开始(各交换机陆续回复)')
        for entry in ev.msg.body:
            if entry.priority in (100, BROADCAST_PRIORITY):
                previous['rows'].append(dict(cookie=entry.cookie,
                    src=entry.match.get('ipv4_src'), packets=entry.packet_count,
                    bytes=entry.byte_count))
        previous['complete'] = not bool(ev.msg.flags & dp.ofproto.OFPMPF_REPLY_MORE)
        previous['timestamp'] = time.time()

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def barrier_reply(self, ev):
        dpid = ev.msg.datapath.id
        self.pending_barriers.pop((dpid, ev.msg.xid), None)
        self.emit('barrier_reply', '←', dpid,
                  'BarrierReply:s%d 在途 FlowMod 已全部处理' % dpid)

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error(self, ev):
        msg = ev.msg
        self.logger.error('OpenFlow error dpid=%s type=%s code=%s xid=%s',
                          msg.datapath.id, msg.type, msg.code, msg.xid)
        self.emit('error', '←', msg.datapath.id,
                  'OpenFlow Error type=%s code=%s xid=%s' %
                  (msg.type, msg.code, msg.xid))
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

    def require_full_topology(self):
        self.refresh()
        discovered = {(a, b) for a, ports in self.graph.items()
                      for b in ports if a < b}
        if set(self.graph) != self.expected_nodes or discovered != self.expected_edges:
            raise ValueError('已发现拓扑与所选 %s 尚未一致，请检查两端拓扑选择并等待 LLDP 收敛' %
                             self.topology_config['name'])

    def compute(self, src, dst):
        self.require_full_topology()
        a, b = self.host_id(src), self.host_id(dst)
        if a == b:
            raise ValueError('请选择两个不同主机')
        if a not in self.hosts or b not in self.hosts:
            raise ValueError('主机尚未通过 PacketIn 被发现，请重新执行探测')
        version = self.version
        graph = {node: dict(ports) for node, ports in self.graph.items()}
        costs = {node: dict.fromkeys(ports, 1) for node, ports in graph.items()}
        result = dial_shortest_path(costs, a, b, cooperate=lambda: hub.sleep(0))
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
            path = result['shortest']
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
                        self.emit('flow_mod', '→', node,
                                  'FlowMod s%d:in_port=%d,ipv4_src=%s,'
                                  'ipv4_dst=%s → output:%d' %
                                  (node, incoming, '10.0.0.%d' % source,
                                   '10.0.0.%d' % target, outgoing),
                                  'priority=100 cookie=0x%x' % cookie)
                self.confirm_flows((self.dps[node] for node in path), batch)
                self.refresh()
                if result['topology_version'] != self.version:
                    raise ValueError('下发期间拓扑发生变化')
                service = dict(result, id=key, cookie=cookie, status='installed',
                               path=path, created_at=time.time())
                self.services[key] = service
                self.emit('service', '·', 0,
                          '业务 %s 下发完成，%d 跳 Dial 最短路、%d 条 FlowMod、'
                          '%d 条 Barrier 全部收到回复' %
                          (key, len(path) - 1, 2 * len(path), len(path)))
                return service
            except Exception:
                self.remove_cookie(cookie)
                raise
            finally:
                self.clear_batch(batch)

    def confirm_flows(self, datapaths, batch):
        for dp in datapaths:
            msg = dp.ofproto_parser.OFPBarrierRequest(dp)
            dp.set_xid(msg)
            key = (dp.id, msg.xid)
            self.pending_barriers[key] = True
            batch['barriers'].append(key)
            dp.send_msg(msg)
            self.emit('barrier', '→', dp.id,
                      'BarrierRequest s%d(xid=%d)' % key)
        deadline = time.monotonic() + 3
        while any(key in self.pending_barriers for key in batch['barriers']):
            if batch['errors']:
                break
            if time.monotonic() > deadline:
                raise ValueError('等待 OpenFlow Barrier 超时')
            hub.sleep(0.01)
        if batch['errors']:
            raise ValueError('；'.join(batch['errors']))

    def clear_batch(self, batch):
        for key in batch['mods']:
            self.pending_mods.pop(key, None)
        for key in batch['barriers']:
            self.pending_barriers.pop(key, None)

    def install_broadcast(self, src):
        with self.lock:
            self.require_full_topology()
            source = self.host_id(src)
            if self.expected_nodes - self.hosts.keys():
                raise ValueError('请等待全部主机通过 PacketIn 被发现')
            version = self.version
            datapaths = {node: self.dps[node] for node in self.graph}
            plan = broadcast_plan(self.graph, self.hosts, source)
            host = self.hosts[source]
            self.next_cookie += 1
            cookie = BROADCAST_COOKIE | (self.next_cookie & 0xffffffff)
            self.invalidate_broadcast('正在重新配置广播')
            batch = dict(mods=[], barriers=[], errors=[])
            try:
                root, *downstream = plan['rules']
                for stage in (downstream, [root]):
                    for rule in stage:
                        dp = datapaths[rule['switch']]
                        p = dp.ofproto_parser
                        match = p.OFPMatch(
                            in_port=rule['in_port'], eth_src=host['mac'],
                            eth_dst=BROADCAST_MAC, eth_type=ether_types.ETH_TYPE_IP,
                            ipv4_src=host['ip'], ipv4_dst=BROADCAST_IP,
                            ip_proto=17, udp_dst=BROADCAST_PORT)
                        self.flow(dp, BROADCAST_PRIORITY, match,
                                  [p.OFPActionOutput(port) for port in rule['out_ports']],
                                  cookie, batch)
                        self.emit('flow_mod', '→', dp.id,
                                  '广播 FlowMod s%d:p%d → %s' %
                                  (dp.id, rule['in_port'], rule['out_ports']),
                                  'priority=%d cookie=0x%x' % (BROADCAST_PRIORITY, cookie))
                    self.confirm_flows((datapaths[rule['switch']] for rule in stage), batch)
                    self.refresh()
                    if version != self.version or any(self.dps.get(node) is not dp
                                                      for node, dp in datapaths.items()):
                        raise ValueError('下发期间拓扑或交换机连接发生变化')
                self.broadcast = dict(plan, topology_version=version,
                                      cookie='0x%x' % cookie, status='installed')
                self.emit('service', '·', 0, '%s 广播已配置，覆盖 %d 台接收主机' %
                          (plan['src'], len(plan['receivers'])))
                return self.broadcast_status()
            except Exception:
                self.remove_cookie(cookie)
                raise
            finally:
                self.clear_batch(batch)

    def broadcast_status(self):
        service = self.broadcast
        if service is None:
            return None
        now = time.time()
        cookie = int(service['cookie'], 16)
        counters = []
        for rule in service['rules']:
            data = self.stats.get(rule['switch'], {})
            fresh = data.get('complete', False) and now - data.get('timestamp', 0) < 6
            row = next((row for row in data['rows'] if row['cookie'] == cookie), None) if fresh else None
            counters.append(dict(switch=rule['switch'], fresh=fresh, present=row is not None,
                                 packets=row['packets'] if row else 0))
        seen = service['status'] == 'installed' and all(
            row['fresh'] and row['present'] and row['packets'] > 0 for row in counters)
        return dict(service, counters=counters, all_switches_seen=seen)

    def topology(self):
        self.refresh()
        edges = [dict(src=a, dst=b, src_port=port, dst_port=self.graph[b][a])
                 for a, ports in sorted(self.graph.items())
                 for b, port in sorted(ports.items()) if a < b]
        return dict(version=self.version, name=self.topology_config['name'],
                    title=self.topology_config['title'], layout=self.topology_config['layout'],
                    expected_links=len(self.expected_edges), switches=sorted(self.graph),
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

    @route('lab_topology_catalog', '/topologies.json', methods=['GET'])
    def topology_catalog(self, req, **kwargs):
        return self.response(topology_catalog())

    @route('lab_topology', '/api/topology', methods=['GET'])
    def topology(self, req, **kwargs):
        return self.response(self.lab.topology())

    @route('lab_paths', '/api/paths', methods=['GET'])
    def paths(self, req, **kwargs):
        try:
            result, _ = self.lab.compute(req.params['src'], req.params['dst'])
            return self.response(result)
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
        except (ValueError, KeyError) as exc:
            return self.response({'error': str(exc)}, 400)

    @route('lab_broadcast', '/api/broadcast', methods=['GET'])
    def broadcast(self, req, **kwargs):
        return self.response({'service': self.lab.broadcast_status()})

    @route('lab_install_broadcast', '/api/broadcast', methods=['POST'])
    def install_broadcast(self, req, **kwargs):
        try:
            data = req.json
            if not isinstance(data, dict) or 'src' not in data:
                raise ValueError('请提供源主机 src')
            return self.response({'service': self.lab.install_broadcast(data['src'])})
        except (ValueError, KeyError) as exc:
            return self.response({'error': str(exc)}, 400)

    @route('lab_events', '/api/events', methods=['GET'])
    def events(self, req, **kwargs):
        try:
            since = max(0, int(req.params.get('since') or 0))
        except ValueError:
            since = 0
        try:
            limit = max(1, min(int(req.params.get('limit') or 200), 500))
        except ValueError:
            limit = 200
        kinds = {k for k in (req.params.get('type') or '').split(',') if k}
        buffered = {e['id']: e for e in
                    list(self.lab.msg_log) + list(self.lab.milestones)}
        recent = [buffered[i] for i in sorted(buffered) if i > since]
        # Keep session milestones (teaching highlights) inside the cap first.
        milestone_ids = {e['id'] for e in self.lab.milestones}
        picks = [e for e in recent if e['id'] in milestone_ids]
        rest = [e for e in recent if e['id'] not in milestone_ids]
        if kinds:
            picks = [e for e in picks if e['kind'] in kinds]
            rest = [e for e in rest if e['kind'] in kinds]
        room = limit - len(picks)
        if room > 0:
            picks = picks + rest[-room:]
        items = sorted(picks, key=lambda e: e['id'])
        return self.response({'events': items,
                              'last_id': items[-1]['id'] if items else since,
                              'total_buffered': len(buffered)})

    @route('lab_ui', '/', methods=['GET'])
    def index(self, req, **kwargs):
        body = Path(__file__).with_name('static').joinpath('index.html').read_bytes()
        return Response(content_type='text/html', charset='utf-8', body=body)
