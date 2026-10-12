#!/usr/bin/env python3
"""Run with the system Python, which owns the apt-installed Mininet package."""
import argparse
import json
from pathlib import Path
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel


class LabTopo(Topo):
    def build(self, config):
        n = config['nodes']
        assert n == 20, '本实验要求 20 台交换机'
        for i in range(1, n + 1):
            self.addSwitch('s%d' % i, dpid='%016x' % i,
                           protocols='OpenFlow13', failMode='secure')
            self.addHost('h%d' % i, ip='10.0.0.%d/24' % i,
                         mac='02:00:00:00:00:%02x' % i)
            # Every host-facing switch port is explicitly port 1.
            self.addLink('s%d' % i, 'h%d' % i, port1=1, bw=10, delay='1ms')
        seen = set()
        for a, b in config['edges']:
            assert 1 <= a <= n and 1 <= b <= n and a != b
            edge = tuple(sorted((a, b)))
            assert edge not in seen, '本示例不支持平行链路或重复边'
            seen.add(edge)
            self.addLink('s%d' % a, 's%d' % b, bw=10, delay='1ms')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--controller', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=6653)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name('topology.json').read_text())
    net = Mininet(topo=LabTopo(config=config), controller=None,
                  switch=OVSSwitch, link=TCLink, autoStaticArp=True)
    net.addController('c0', controller=RemoteController,
                      ip=args.controller, port=args.port)
    try:
        net.start()
        # Cause one ARP PacketIn from each host so Ryu learns its attachment.
        # Static ARP already handles all real peer addresses; .254 is a probe.
        for host in net.hosts:
            host.cmd('ping -c 1 -W 1 10.0.0.254 >/dev/null 2>&1 &')
        print('等待 LLDP 收敛约 10 秒；探测 .254 不通是正常现象。')
        CLI(net)
    finally:
        net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    main()
