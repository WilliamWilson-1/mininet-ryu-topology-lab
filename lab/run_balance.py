"""Run the two iperf3 rounds from the Mininet CLI with run(net)."""
from contextlib import ExitStack
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import shutil
from subprocess import TimeoutExpired
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from load_balance import DEFAULT_SEED


def _request(base_url, path='', method='GET', data=None):
    request = Request(base_url.rstrip('/') + '/api/load-balance' + path,
                      method=method, data=json.dumps(data).encode() if data is not None else None,
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def _end_processes(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=2)
        except TimeoutExpired:
            process.kill()
            process.wait()


def _run_round(net, base_url, experiment, seconds, output):
    processes, servers, clients = [], [], []
    samples, seen = {}, set()
    _write_json(output / 'plan.json', experiment)
    with ExitStack() as files:
        try:
            for flow in experiment['demands']:
                host = net.get(f"h{flow['dst']}")
                command = ['iperf3', '-s', '-1', '-p', str(flow['port']), '-J']
                process = host.popen(command, stdout=files.enter_context(
                    (output / (flow['id'] + '-server.json')).open('w')),
                    stderr=files.enter_context((output / (flow['id'] + '-server.err')).open('w')))
                processes.append(process)
                servers.append((host, flow['port'], process))
            deadline = time.monotonic() + 5
            for host, port, process in servers:
                while not host.cmd(f"ss -H -ltn 'sport = :{port}' 2>/dev/null").strip():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError(f'{host.name} 的 iperf3 服务未就绪，请查看日志')
                    time.sleep(.05)
                if process.poll() is not None:
                    raise RuntimeError(f'{host.name} 的 iperf3 服务提前退出，请查看日志')
            for flow in experiment['demands']:
                host = net.get(f"h{flow['src']}")
                target = net.get(f"h{flow['dst']}")
                command = ['iperf3', '-c', target.IP(), '-u', '-p', str(flow['port']),
                           '-b', f"{flow['rate_mbps']}M", '-t', str(seconds),
                           '--connect-timeout', '5000', '-J']
                process = host.popen(command, stdout=files.enter_context(
                    (output / (flow['id'] + '-client.json')).open('w')),
                    stderr=files.enter_context((output / (flow['id'] + '-client.err')).open('w')))
                processes.append(process)
                clients.append(process)
            start = time.monotonic()
            warmup_end = start + 4
            deadline = start + seconds + 12
            while any(process.poll() is None for process in clients):
                if any(process.returncode not in (None, 0) for process in clients):
                    raise RuntimeError('有 iperf3 客户端执行失败，请查看本轮客户端日志')
                if time.monotonic() > deadline:
                    raise RuntimeError('iperf3 客户端超时，请查看日志')
                active = _request(base_url)['experiment']
                if (not active or active['id'] != experiment['id'] or
                        active['status'] != 'installed'):
                    raise RuntimeError('实验路径已改变，当前轮次无法比较')
                if all(process.poll() is None for process in clients):
                    for edge in active['links']:
                        if edge['measured_mbps'] is None or edge['sample_start'] < warmup_end:
                            continue
                        key = (edge['src'], edge['dst'])
                        sample = (*key, edge['sample_end'])
                        if sample not in seen:
                            seen.add(sample)
                            samples.setdefault(key, []).append(edge['measured_mbps'])
                time.sleep(.5)
            for _, _, server in servers:
                server.wait(timeout=5)
        finally:
            _end_processes(processes)

    if any(process.returncode != 0 for process in processes):
        raise RuntimeError('有 iperf3 进程执行失败，请查看本轮日志')
    flows = []
    for flow in experiment['demands']:
        result = json.loads((output / (flow['id'] + '-server.json')).read_text())
        summaries = result['end']
        received = summaries.get('sum_received') or summaries['sum']
        flows.append(dict(id=flow['id'], received_mbps=received['bits_per_second']/1e6,
                          lost_percent=received['lost_percent']))
    links = []
    for edge in experiment['links']:
        values = samples.get((edge['src'], edge['dst']), [])
        links.append(dict(src=edge['src'], dst=edge['dst'], port=edge['port'],
                          plan_mbps=edge[experiment['mode']+'_mbps'], samples=len(values),
                          measured_mbps=sum(values)/len(values) if values else None))
    if any(row['measured_mbps'] is None for row in links):
        print('部分链路缺少稳定窗口样本，请检查端口统计或延长发流时间')
    return dict(flows=flows, links=links)


def run(net, seed=DEFAULT_SEED, seconds=30, base_url='http://127.0.0.1:8080'):
    """Install baseline and balanced routes, replay the same 10 UDP demands."""
    if type(seconds) is not int or seconds < 15:
        raise ValueError('每轮持续时间至少 15 秒，以便排除启动阶段并采集端口统计')
    if not shutil.which('iperf3'):
        raise RuntimeError('Ubuntu 尚未安装 iperf3')
    # This runner is invoked in the same VM as Ryu; monotonic clocks share an origin.
    output = Path(__file__).resolve().parent / 'evidence' / (
        'load-balance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True)
    print(f'本次实验日志目录 {output}')
    rounds = {}
    experiment = None
    try:
        for mode in ('baseline', 'balanced'):
            experiment = _request(base_url, method='POST',
                                  data={'seed': seed, 'mode': mode})['experiment']
            if rounds and experiment['topology_version'] != baseline_version:
                raise RuntimeError('两轮拓扑不同，无法比较')
            baseline_version = experiment['topology_version']
            directory = output / mode
            directory.mkdir()
            print(f'开始 {mode}，10 条 UDP 流并发运行 {seconds} 秒')
            rounds[mode] = _run_round(net, base_url, experiment, seconds, directory)
            _write_json(directory / 'summary.json', rounds[mode])

        capacity = experiment['capacity_mbps']
        with (output / 'links.csv').open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['src', 'dst', 'capacity_mbps', 'baseline_plan_percent',
                             'balanced_plan_percent', 'baseline_measured_percent',
                             'balanced_measured_percent', 'baseline_samples', 'balanced_samples'])
            for before, after in zip(rounds['baseline']['links'], rounds['balanced']['links']):
                measured = [round(row['measured_mbps']*100/capacity, 2)
                            if row['measured_mbps'] is not None else ''
                            for row in (before, after)]
                writer.writerow([before['src'], before['dst'], capacity,
                                 before['plan_mbps']*100/capacity,
                                 after['plan_mbps']*100/capacity, *measured,
                                 before['samples'], after['samples']])
        for mode, summary in rounds.items():
            measured = [row['measured_mbps'] for row in summary['links']
                        if row['measured_mbps'] is not None]
            coverage = f"{len(measured)}/{len(summary['links'])}"
            peak = f'{max(measured)*100/capacity:.1f}%' if measured else '无样本'
            throughput = sum(flow['received_mbps'] for flow in summary['flows'])
            print(f'{mode}: 实测峰值 {peak}（采样覆盖 {coverage}），接收合计 {throughput:.2f} Mbps')
        print(f'链路对比已写入 {output / "links.csv"}')
        return str(output)
    finally:
        if experiment:
            try:
                _request(base_url, '?' + urlencode({'id': experiment['id']}), method='DELETE')
            except OSError as error:
                print(f'清理实验流表失败，请在页面撤回本轮规则。{error}')
