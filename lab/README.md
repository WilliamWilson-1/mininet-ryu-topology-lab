# Linux 完整实验手册：Mininet + Ryu + 4×5 网格可视化

本手册从一台可执行 `sudo` 的 Linux 开始，直到真实业务沿最长路通信，并在页面中看到每跳双向流表计数。按顺序完成每个检查点，前一项不通过时先排错，再继续。源码全部在仓库中，使用 Git 克隆，不需要压缩包。

[返回项目首页](../README.md) · [在线演示](https://williamwilson-1.github.io/mininet-ryu-topology-lab/)

## 目录

1. [环境与终端分工](#1-环境与终端分工)
2. [获取源码](#2-获取源码)
3. [安装 Linux 依赖](#3-安装-linux-依赖)
4. [创建 Ryu 虚拟环境并修复兼容性](#4-创建-ryu-虚拟环境并修复兼容性)
5. [确认指定拓扑与端口](#5-确认指定拓扑与端口)
6. [启动 Ryu](#6-启动-ryu)
7. [启动 Mininet 并发现主机](#7-启动-mininet-并发现主机)
8. [验收 LLDP 拓扑发现](#8-验收-lldp-拓扑发现)
9. [计算最短路与最长路](#9-计算最短路与最长路)
10. [下发最长路并验证通信](#10-下发最长路并验证通信)
11. [打开真实可视化页面](#11-打开真实可视化页面)
12. [实验验收与证据保存](#12-实验验收与证据保存)
13. [REST 接口说明](#13-rest-接口说明)
14. [按代码理解实验原理](#14-按代码理解实验原理)
15. [常见问题逐项排查](#15-常见问题逐项排查)
16. [停止重启与再次复用](#16-停止重启与再次复用)
17. [修改拓扑与验证边界](#17-修改拓扑与验证边界)

## 1. 环境与终端分工

本手册的目标组合是 **Ubuntu 22.04 LTS + Python 3.10 + apt Mininet/Open vSwitch + Ryu 4.34**。这是本项目选择的复现组合，不表示最新版软件组合；不建议直接换成 Python 3.12/3.13 或只升级某个依赖。其他发行版需要自行处理包名、Python 版本与内核差异。

- 建议虚拟机至少分配 2 个 CPU、4 GB 内存及足够的可用磁盘；这是起步配置，不是性能保证。
- Mininet 需要 Linux 内核、网络命名空间与 root 权限。在 macOS/Windows 上请使用 Linux 虚拟机或 Linux 实体机；不要直接在 macOS Python 中安装 Mininet 代替 Linux 数据平面。
- 本手册让 Ryu 和 Mininet 位于**同一台 Linux**，从而控制器地址统一为 `127.0.0.1`。
- 普通用户安装 venv；只在 apt、OVS、Mininet、tcpdump 等需要时使用 `sudo`。

先检查：

```bash
lsb_release -ds
/usr/bin/python3 --version
uname -r
sudo -v
```

Python 应是 3.10.x。如果不是，不要继续套用安装命令；先准备匹配的 Ubuntu/Python 环境。虚拟环境的 Python 与系统 Python 可以不同，但本手册使用系统 Python 3.10 创建 venv。

同时打开三个 Linux 终端，可以是虚拟机窗口或多个 SSH 会话：

| 名称 | 工作 | 后续提示符 |
| --- | --- | --- |
| 终端 A | 运行 Ryu，持续查看日志 | 命令运行后不返回 shell，保持运行 |
| 终端 B | 运行 Mininet 与主机命令 | `mininet>` |
| 终端 C | 执行 curl/jq/ovs-ofctl/tcpdump | 普通 Linux shell `$` |
| 可选本机终端 D | 从 Mac/Windows 建立 SSH 隧道 | 本机 shell，保持连接 |

文档的 `bash` 块在 Linux shell 执行；`text` 块中 `h1 ping ...`、`py ...`、`net` 等在 `mininet>` 执行。复制命令时不要复制 `$`、`mininet>` 或终端输出。

## 2. 获取源码

首次在 Linux 中执行：

```bash
cd ~
git clone https://github.com/WilliamWilson-1/mininet-ryu-topology-lab.git
cd ~/mininet-ryu-topology-lab/lab
ls
```

如果 Git 尚未安装，先执行第 3 节的 apt 命令，再回来克隆。

本手册后续统一以 `~/mininet-ryu-topology-lab/lab` 为工作目录。`controller.py`、`paths.py`、`topo20.py`、`topology.json`、`requirements.txt`、`fix_ryu_wsgi.py` 和 `static/index.html` 必须存在。

如果此前在 `~/prj2` 做过分步实验，可以保留旧目录，但本次先在上述新目录运行完整仓库，避免混用不同版本的脚本和 venv。所有启动终端都进入同一个 `lab` 目录。不要同时启动 `ryu_step6.py` 和本仓库 `controller.py`。

已有克隆时，先查看自己是否改过源码：

```bash
cd ~/mininet-ryu-topology-lab
git status --short
git pull --ff-only
```

若 pull 因本地修改或分支分叉被拒绝，先备份并处理冲突，不要使用 `reset --hard` 覆盖实验记录。需要精确复现时保存 `git rev-parse HEAD` 的提交号。

## 3. 安装 Linux 依赖

```bash
sudo apt update
sudo apt install -y git mininet openvswitch-switch \
  python3-venv python3-dev build-essential libffi-dev libssl-dev \
  curl jq iperf tcpdump
sudo systemctl enable --now openvswitch-switch
```

检查 Mininet、OVS 与系统 Python：

```bash
sudo systemctl is-active openvswitch-switch
sudo ovs-vsctl show
mn --version
ovs-vsctl --version
/usr/bin/python3 -c 'from mininet.net import Mininet; print("Mininet import OK")'
```

预期 OVS 服务为 `active`、系统 Python 输出 `Mininet import OK`。空 OVS 数据库还没有 s1～s20 是正常的，要等第 7 节才创建。

Mininet 是 apt 安装的系统包，后续必须使用 `sudo /usr/bin/python3 topo20.py`。不要在 Ryu venv 里再通过 pip 安装同名包，也不要用 venv 的 `python topo20.py`。

## 4. 创建 Ryu 虚拟环境并修复兼容性

以下在终端 A 的普通用户 shell 中执行：

```bash
cd ~/mininet-ryu-topology-lab/lab
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python --version
python -m pip install --upgrade pip==23.3.2 setuptools==57.5.0 wheel==0.37.1
python -m pip install --no-build-isolation -r requirements.txt
python fix_ryu_wsgi.py
python -m pip check
ryu-manager --version
```

预期 Python 是 3.10.x，`pip check` 没有依赖冲突，最后可以输出 Ryu 版本而不出现 traceback。版本输出的格式可能因发行包略有差异，重点是包含 4.34 且退出成功。

本仓库固定的直接依赖：

| 组件 | 版本 | 原因 |
| --- | --- | --- |
| Ryu | 4.34 | 与本项目使用的接口匹配 |
| Eventlet | 0.33.3 | 避免旧版本在 Python 3.10 上修改不可变 `TimeoutError` 类型 |
| dnspython | 2.2.1 | 与上述 Eventlet / Python 组合配套 |
| setuptools | 57.5.0 | 用于旧 Ryu 的安装元数据处理 |

`--no-build-isolation` 让旧 Ryu 的构建使用刚安装的 setuptools。先装构建工具，再装 requirements，不能只依赖系统最新 setuptools。这里固定的是直接依赖与构建工具，**不是包含所有传递依赖及系统包的完整锁文件**；环境安装成功后可保存实际解析结果：

```bash
python -m pip freeze > requirements.resolved.txt
git rev-parse HEAD
```

### 4.1 你之前遇到的 TimeoutError 报错

症状：

```text
TypeError: cannot set 'is_timeout' attribute of immutable type 'TimeoutError'
```

这是旧 Eventlet 与 Python 3.10 的兼容问题。若复用一个已有的 `.venv`，激活它后执行：

```bash
python -m pip install --upgrade eventlet==0.33.3 dnspython==2.2.1
python fix_ryu_wsgi.py
ryu-manager --version
```

本仓库的 `requirements.txt` 已更新，不要再装回 `eventlet==0.30.2` 和 `dnspython==1.16.0`。

### 4.2 为什么还要运行 fix_ryu_wsgi.py

Ryu 4.34 的 `ryu/app/wsgi.py` 仍导入 Eventlet 已移除的 `ALREADY_HANDLED`，升级 Eventlet 后可能出现第二个错误：

```text
ImportError: cannot import name 'ALREADY_HANDLED' from 'eventlet.wsgi'
```

[fix_ryu_wsgi.py](fix_ryu_wsgi.py) 只修改**当前激活 venv 内** Ryu 的 `_AlreadyHandledResponse` 类，使用新版 Eventlet 的已处理响应标记，先语法检查，再备份为 `wsgi.py.bak` 并写入。重复运行不会重复修改；找不到预期结构时会停止，不能盲目继续替换。普通 REST 页面并不需要 WebSocket，但 WSGI 模块在导入时就会触发旧代码，因此仍要修复。

检查版本和路径：

```bash
which python
which ryu-manager
python -m pip show ryu eventlet dnspython setuptools
```

`python` 和 `ryu-manager` 都应指向本目录 `.venv/bin/`。Ryu 重新安装后可能覆盖补丁，要再次运行脚本。不要 sudo 执行修复脚本或直接编辑系统 Python 包。

兼容处理的依据：[Ryu 4.34 原始 WSGI 类](https://github.com/faucetsdn/ryu/blob/v4.34/ryu/app/wsgi.py#L102)、[Eventlet 0.33.3 对 Python 3.10 的分支](https://github.com/eventlet/eventlet/blob/v0.33.3/eventlet/greenio/base.py#L30)、[Eventlet 0.33.3 WSGI 实现](https://github.com/eventlet/eventlet/blob/v0.33.3/eventlet/wsgi.py)。

## 5. 确认指定拓扑与端口

[topology.json](topology.json) 保存实验图的 31 条无向交换机边；[topo20.py](topo20.py) 和 [controller.py](controller.py) 都读取这一份文件。不要只改拓扑生成脚本而忘记控制器的预期配置。

```text
s1 ── s2 ── s3 ── s4 ── s5
│     │     │     │     │
s6 ── s7 ── s8 ── s9 ── s10
│     │     │     │     │
s11── s12── s13── s14── s15
│     │     │     │     │
s16── s17── s18── s19── s20
```

每台 si 下挂 hi，交换机端口 1 固定留给主机。DPID 是交换机编号的 16 位十六进制表示，例如 s10 为 `000000000000000a`；它不是字符串名称 s10。主机地址为 `10.0.0.i/24`，MAC 为 `02:00:00:00:00:%02x`，h10 末字节为 `0a`、h20 为 `14`。所有数据链路配置为 10 Mbps、1 ms 单向延迟，不含实际宿主机调度开销。

端口编号由创建链路的顺序决定：先创建主机链路，再按 JSON 顺序创建 16 条横向边、15 条纵向边。下表是该顺序下的参考值；真实下发依然使用 LLDP 发现的端口。若你调整了边的顺序，不能继续照抄此表抓包或手工下发。

| 编号 | 交换机 A / 端口 | 交换机 B / 端口 |
| --- | --- | --- |
| 1 | s1:p2 | s2:p2 |
| 2 | s2:p3 | s3:p2 |
| 3 | s3:p3 | s4:p2 |
| 4 | s4:p3 | s5:p2 |
| 5 | s6:p2 | s7:p2 |
| 6 | s7:p3 | s8:p2 |
| 7 | s8:p3 | s9:p2 |
| 8 | s9:p3 | s10:p2 |
| 9 | s11:p2 | s12:p2 |
| 10 | s12:p3 | s13:p2 |
| 11 | s13:p3 | s14:p2 |
| 12 | s14:p3 | s15:p2 |
| 13 | s16:p2 | s17:p2 |
| 14 | s17:p3 | s18:p2 |
| 15 | s18:p3 | s19:p2 |
| 16 | s19:p3 | s20:p2 |
| 17 | s1:p3 | s6:p3 |
| 18 | s2:p4 | s7:p4 |
| 19 | s3:p4 | s8:p4 |
| 20 | s4:p4 | s9:p4 |
| 21 | s5:p3 | s10:p3 |
| 22 | s6:p4 | s11:p3 |
| 23 | s7:p5 | s12:p4 |
| 24 | s8:p5 | s13:p4 |
| 25 | s9:p5 | s14:p4 |
| 26 | s10:p4 | s15:p3 |
| 27 | s11:p4 | s16:p3 |
| 28 | s12:p5 | s17:p4 |
| 29 | s13:p5 | s18:p4 |
| 30 | s14:p5 | s19:p4 |
| 31 | s15:p4 | s20:p3 |

其中 31 条是交换机间物理链路；LLDP 为两个方向分别发现，因此稳定时是 62 条有向记录。加上 20 条主机接入链路，Mininet 一共创建 51 条数据链路。控制器连接不计入这 51 条。

无需启动网络即可先检查配置与算法：

```bash
cd ~/mininet-ryu-topology-lab/lab
python3 -m json.tool topology.json
python3 -m unittest -v test_paths.py
```

算法测试不依赖 Mininet/Ryu，应全部通过；配置应为 `nodes: 20`、31 条不同的无向边。

## 6. 启动 Ryu

终端 A：

```bash
cd ~/mininet-ryu-topology-lab/lab
source .venv/bin/activate
export PYTHONPATH="$PWD"
mkdir -p evidence
ryu-manager --observe-links --ofp-tcp-listen-port 6653 \
  --wsapi-host 127.0.0.1 --wsapi-port 8080 \
  controller.py ryu.topology.switches \
  ryu.app.rest_topology ryu.app.ofctl_rest \
  2>&1 | tee evidence/ryu.log
```

保持这个进程运行，另开终端做后续操作。`tee` 用于保存日志；结束时 Ctrl+C。

各参数含义：

- `--observe-links`：启用 Ryu 拓扑模块的 LLDP 链路发现。
- `--ofp-tcp-listen-port 6653`：交换机连接控制器的 TCP 端口。
- `--wsapi-host 127.0.0.1 --wsapi-port 8080`：本机网页/API 的监听地址与端口。
- `controller.py`：本项目完整控制器，不要同时加载 `simple_switch_13` 等学习交换机应用。
- `ryu.topology.switches`：交换机与 LLDP 发现服务。
- `ryu.app.rest_topology`：提供 `/v1.0/topology/...` 诊断接口。
- `ryu.app.ofctl_rest`：提供 `/stats/...` 诊断接口；手册只使用其中的读取操作。
- `PYTHONPATH="$PWD"`：保证控制器能导入同目录的 `paths.py`。

终端 C 检查：

```bash
ss -lnt | grep -E ':(6653|8080)[[:space:]]'
curl -sS http://127.0.0.1:8080/api/topology | jq
```

预期两个端口监听，API 返回 JSON。此时尚未启动 Mininet，`switches`、`links`、`hosts` 为空是正常现象；网页能打开并不代表网络已建立。

## 7. 启动 Mininet 并发现主机

终端 B：

```bash
cd ~/mininet-ryu-topology-lab/lab
sudo mn -c
sudo /usr/bin/python3 topo20.py
```

`mn -c` 清理旧的 Mininet 实验资源，会影响该 Linux 上其他正在运行的 Mininet 网络；请只在没有需要保留的其他实验时执行。

预期出现 s1～s20、h1～h20，最后停在 `mininet>`。此后本节命令输入在该提示符中：

```text
nodes
net
h1 ip -4 addr show h1-eth0
h20 ip -4 addr show h20-eth0
h1 ip neigh show
```

应能看到 h1 的 `10.0.0.1/24`、h20 的 `10.0.0.20/24`。`net` 展示端口对应关系。脚本通过 `autoStaticArp=True` 为各主机预填邻居 MAC，因为本实验不在环路网格中泛洪 ARP。

### 主机发现探测

LLDP 发现交换机链路；主机位置则要靠主机发包产生 PacketIn。`topo20.py` 启动时会自动让每台主机向未使用的 `10.0.0.254` 发一个探测，从而产生 ARP PacketIn。`.254` 不存在，探测失败是正常的，不是业务连通性测试。

等待约 10 秒后，如果界面主机不足 20 台，可以在 `mininet>` 重发：

```text
py [h.cmd('ping -c 1 -W 1 10.0.0.254 >/dev/null 2>&1 &') for h in net.hosts]
```

如果手工清空过邻居表，先恢复真实主机之间的静态 ARP：

```text
py net.staticArp()
```

此时 `h1 ping h20` 不通仍是预期：控制器只发现拓扑、尚未安装这个主机对的转发规则。不要为了“先 ping 通”加 `NORMAL` 或 `FLOOD` 规则，那会破坏最长路转发的验收条件。

## 8. 验收 LLDP 拓扑发现

终端 C：

```bash
curl -sS http://127.0.0.1:8080/api/topology \
  | jq '{version, switches:(.switches|length), hosts:(.hosts|length), physical_links:(.links|length)}'
curl -sS http://127.0.0.1:8080/v1.0/topology/links | jq length
```

收敛后预期分别是 `switches=20`、`hosts=20`、`physical_links=31`；第二条命令是 Ryu 原生有向链路列表，应为 62。`version` 随发现过程变化，不要求固定为某个数字。

读取 31 条物理链路与两端端口并保存：

```bash
cd ~/mininet-ryu-topology-lab/lab
mkdir -p evidence
curl -sS http://127.0.0.1:8080/api/topology > evidence/topology.json
jq -r '.links[] | "s\(.src):p\(.src_port) <-> s\(.dst):p\(.dst_port)"' \
  evidence/topology.json
curl -sS http://127.0.0.1:8080/v1.0/topology/links \
  > evidence/lldp-directed.json
```

自定义 `/api/topology` 返回去重后的物理边，形如：

```json
{"src":1,"dst":2,"src_port":2,"dst_port":2}
```

即 s1 的端口 2 连接 s2 的端口 2。原生 Ryu 接口的 DPID/端口字段格式不同，通常是十六进制字符串，不应与这个自定义 JSON 结构混用。

进一步核对“边集合”而不是只核对数量：

```bash
python3 - <<'PY'
import json
from pathlib import Path
expected = json.loads(Path('topology.json').read_text())
actual = json.loads(Path('evidence/topology.json').read_text())
wanted = {tuple(sorted(e)) for e in expected['edges']}
seen = {tuple(sorted((e['src'], e['dst']))) for e in actual['links']}
assert set(actual['switches']) == set(range(1, 21))
assert len(actual['links']) == len(wanted) == 31
assert seen == wanted, (wanted - seen, seen - wanted)
assert {h['name'] for h in actual['hosts']} == {'h%d' % i for i in range(1, 21)}
assert all(e['src_port'] > 1 and e['dst_port'] > 1 for e in actual['links'])
print('PASS: 20 switches, 20 hosts, exact 31-edge grid')
PY
```

本仓库集成版的 `/api/topology` **没有 `ready` 字段，也不会自动写 `topology_snapshot.json`**；这些是之前分步脚本的行为。集成版在计算/下发时检查发现结果与 `topology.json` 是否完全一致。只见到 20 台交换机但少链路，仍不能继续配置业务。

可选抓取 LLDP，终端 C：

```bash
sudo tcpdump -ni s1-eth2 -c 4 'ether proto 0x88cc'
```

LLDP 周期发出，可能需要等一段时间；Ctrl+C 可退出。接口名称以实际 `net` 输出为准。

## 9. 计算最短路与最长路

终端 C：

```bash
cd ~/mininet-ryu-topology-lab/lab
curl -sS 'http://127.0.0.1:8080/api/paths?src=h1&dst=h20' \
  | tee evidence/paths-h1-h20.json | jq
```

URL 必须用引号包住，否则 shell 会把 `&` 当成后台执行符。若返回 `error`，先处理错误，不要将错误 JSON 当作路径结果。

指定网格的预期值：

```json
{
  "shortest": [1,2,3,4,5,10,15,20],
  "longest": [1,2,3,4,5,10,9,8,7,6,11,16,17,12,13,18,19,14,15,20],
  "shortest_hops": 7,
  "longest_hops": 19,
  "simple_path_count": 976,
  "exact": true
}
```

响应还包含 `src`、`dst`、`topology_version`、`dfs_visits` 等字段。当前排序规则下 h1→h20 约有 8076 次 DFS 调用；它与简单路径数量 976 含义不同。换一种邻居遍历顺序可能选出另一条同长路径，只要合法且跳数相同并不代表错误。

DFS 维护当前路径和当前路径已访问集合，抵达目标后记录并比较长度，然后回溯，继续探索其他分支。这里的“最长路”是**最长简单路径**，不允许重复交换机；允许重复顶点的环路不能作为这个实验的最长路。

h1 到 h20 的最短路 7 跳也可以用网格曼哈顿距离 `3+4` 交叉核对。最长路为 19 跳，使用全部 20 台交换机；两端主机接入再加 2，完整主机间路径分别有 9/21 条链路。不是每个主机对都能走满 19 跳。

接口只接受两台不同的 h1～h20。当前精确搜索上限为 500000 次访问、5 秒，超限返回 HTTP 422 和 `exact:false`，不会把搜索中途得到的候选冒充已证明的最长路，更不会继续下发。

## 10. 下发最长路并验证通信

### 10.1 配置双向 IPv4 业务

终端 C：

```bash
curl -sS -X POST http://127.0.0.1:8080/api/services \
  -H 'Content-Type: application/json' \
  -d '{"src":"h1","dst":"h20"}' \
  | tee evidence/service-h1-h20.json | jq
```

预期响应包含 `id:"h1-h20"`、`status:"installed"`、非零 `cookie`、`path` 和 `longest_hops:19`。集成版 POST 响应不包含 `rule_count` 或 `barrier_confirmed` 字段；`installed` 表示下发流程已等待 Barrier 且未收到已跟踪的 FlowMod 错误，仍需实测通信。

控制器重新计算最长路，并给路径上每台交换机安装正向和反向规则。20 台交换机共 **40 条业务 IPv4 规则**，另有 table-miss/LLDP 等基础规则，因此 `dump-flows` 的总行数并不是 40。

### 10.2 在 Mininet 中产生真实流量

终端 B 的 `mininet>`：

```text
h1 ping -c 5 h20
h20 ping -c 5 h1
```

预期每组统计 `0% packet loss`。第一次测试如发生少量丢包，待链路与规则稳定后再测试；持续丢包则按第 15 节检查，不能只凭页面的 `installed` 断言实验成功。

这个实验做二层 OpenFlow 转发，不是逐跳 IP 路由，交换机不会像路由器那样每跳递减 TTL。不要使用普通 traceroute 期待它列出 20 台 OVS；验证最长路应结合规则的端口动作、非最短路链路抓包及每跳计数。

### 10.3 读取每跳计数

终端 C，等待一个或两个采样周期后：

```bash
curl -sS http://127.0.0.1:8080/api/services \
  | tee evidence/services-after-ping.json | jq
jq '.[] | {id,status,both_directions_seen_on_all_hops,counter_rows:(.counters|length)}' \
  evidence/services-after-ping.json
```

h1↔h20 应有 40 条计数记录；全部正反向规则被近期完整样本读到且包数大于 0 后，`both_directions_seen_on_all_hops` 才为 true。采样约每 2 秒一次，超过 6 秒的样本不作为新鲜证据。

### 10.4 核对规则与最长路端口

终端 C：

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
sudo ovs-ofctl -O OpenFlow13 dump-flows s6
sudo ovs-ofctl -O OpenFlow13 dump-flows s20
```

查找 `priority=100`、`nw_src=10.0.0.1,nw_dst=10.0.0.20` 及反向项；字段顺序和显示格式可能不同。在当前 JSON 链路顺序及上面的最长路下：

| 交换机 | h1→h20 | h20→h1 |
| --- | --- | --- |
| s1 | in_port=1 → output:2 | in_port=2 → output:1 |
| s6 | in_port=2 → output:4 | in_port=4 → output:2 |
| s20 | in_port=2 → output:1 | in_port=1 → output:2 |

s6 不在示例最短路上，但位于最长路中，因此可以作为辅助验证点。若实际算法返回另一条等长路径，应依据返回的 `path` 和实际 LLDP 端口核对，而不是机械套用表格。

先在终端 C 开始抓包：

```bash
sudo tcpdump -ni s6-eth4 -c 6 'icmp and host 10.0.0.1 and host 10.0.0.20'
```

再在 Mininet 执行 `h1 ping -c 3 h20`。抓到请求和回复，结合路径端口规则与各跳计数，支持业务确实沿所配置路径转发。不要期待单个抓包点独立证明整条路径。

### 10.5 可选 TCP 吞吐测试

这里安装的是 `iperf`（iperf2），命令不要与 iperf3 混用。在 `mininet>`：

```text
h20 iperf -s -p 5001 > /tmp/h20-iperf.log 2>&1 &
h1 iperf -c 10.0.0.20 -p 5001 -t 10 -i 1
h20 cat /tmp/h20-iperf.log
```

结束该实验服务器：

```text
h20 pkill -f '^iperf -s -p 5001'
```

同一主机对的 ICMP/TCP/UDP 共享本项目的 IPv4 源/目的规则；这里的“业务”按主机对区分，不按 TCP 五元组区分。由于链路限制、延迟和虚拟机性能，实际速率不保证等于 10 Mbps。

## 11. 打开真实可视化页面

### 11.1 在 Linux 内访问

在 Linux 浏览器输入 `http://127.0.0.1:8080/`，不要添加 `?demo=1`。页面由同一个 Ryu 进程提供，向同源 `/api/...` 请求真实数据，无需单独启动前端服务，也无需 npm install。

操作顺序：

1. 看顶部状态是否为“控制器已连接”，确认 20 台交换机、20 台主机、31 条链路。
2. 在主机选择器选择 h1 和 h20。
3. 点击“计算路径”，在拓扑和路径分析中查看 7 跳最短路、19 跳最长路及完整交换机序列。
4. 点击配置最长路的按钮；该操作会调用 POST `/api/services` 并重新计算路径。
5. 在 Mininet 内运行 ping 或 iperf。网页按钮不会在主机命名空间里替你产生流量。
6. 进入“业务监测”，选择对应业务的“查看路径”或“每跳计数”。
7. 等待采样更新，检查正向/反向的包数、字节数和采样状态。

浅色/深色/跟随系统及减少透明效果在外观设置中切换。网格图中交换机与主机位置是按编号固定排列；链接和端口信息来自 API。鼠标悬停交换机间连线可查看两端端口。

### 11.2 从 Mac 或 Windows 浏览器访问虚拟机

Linux 端保持前述 `--wsapi-host 127.0.0.1` 配置。在 Linux 安装并启动 SSH 服务：

```bash
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
hostname -I
```

在**本机**终端 D 中运行，替换实际用户名和可达的 Linux IP：

```bash
ssh -N -L 18080:127.0.0.1:8080 ubuntu@192.168.1.100
```

该进程没有新的 shell 输出且持续运行是正常现象。随后本机浏览器打开 `http://127.0.0.1:18080/`。本机 18080 通过 SSH 转发到 Linux 8080；地址中的 `127.0.0.1` 在不同电脑上不是同一个网络位置。

如果虚拟机使用 NAT，先确保本机能 SSH 到虚拟机，例如按虚拟机软件配置 SSH 端口转发，再在 ssh 命令中使用相应 `-p`。不要假设 `hostname -I` 打印的每个地址都能被本机访问。

隧道断开页面就失去实时数据。若本机 18080 已被占用，可改成 `-L 18081:127.0.0.1:8080` 并访问本机 18081。停止隧道用 Ctrl+C。

### 11.3 区分演示页和实验页

- `https://williamwilson-1.github.io/mininet-ryu-topology-lab/`：Pages 演示，永远是模拟模式，配置按钮禁用。
- `http://127.0.0.1:8080/`：Linux 的真实 Ryu 页面。
- `http://127.0.0.1:18080/`：本机经 SSH 隧道访问同一个真实页面。
- `lab/static/index.html` 加 `?demo=1`：人为进入模拟模式，不能据此验收实验。

不要直接双击 HTML 使用 `file://`，也不要用 `python -m http.server` 期待它提供 Ryu REST API。GitHub Pages 的 HTTPS 页面不能直接代替本地 HTTP 控制器页面；本项目使用控制器同源页面规避额外的跨域配置。

### 11.4 正确解读绿色状态

绿色表示这条业务所关联的每跳双向规则在近期完整采样里都有正累计计数。它不能证明此刻持续发包，也不能替代端到端 ping。

例如 ping 停止后，OVS 规则仍保留累计包数，下一次采样仍可能是正值，所以页面可以继续绿色。不要把 20 个交换机上同一个数据包的计数相加当作业务总包数；页面也没有把计数差分换算为实时 Mbps。

## 12. 实验验收与证据保存

逐项记录，截图应来自真实控制器页面而非 Pages 演示：

| 检查项 | 操作/证据 | 预期 |
| --- | --- | --- |
| 环境 | `python --version`、`ryu-manager --version`、`pip check` | Python 3.10、Ryu 可导入、无冲突 |
| 控制通道 | OVS get-controller / is_connected | 20 台交换机连接 Ryu |
| 指定拓扑 | `evidence/topology.json` 与 JSON 边集合比较 | 20 / 20 / 31，端口 > 1 |
| 双向发现 | `/v1.0/topology/links` | 62 条有向记录 |
| 精确搜索 | `evidence/paths-h1-h20.json` | exact=true，7/19 跳，976 条 |
| 流表 | dump-flows 及 POST 响应 | 当前业务 cookie、双向 priority=100 输出规则 |
| 端到端 | Mininet 两个方向 ping | 正常稳定时 0% 丢包 |
| 最长路证据 | s6 非最短路端口抓包、完整路径规则/计数 | 与已计算最长路一致 |
| 页面业务 | 业务列表、每跳计数截图和 JSON | 40 行；全部有近期双向正计数后验证为 true |

终端 C 保存环境和关键流表：

```bash
cd ~/mininet-ryu-topology-lab/lab
source .venv/bin/activate
mkdir -p evidence
git rev-parse HEAD > evidence/commit.txt
uname -a > evidence/kernel.txt
python -m pip freeze > evidence/pip-freeze.txt
ovs-vsctl --version > evidence/ovs-version.txt
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 > evidence/s1-flows.txt
sudo ovs-ofctl -O OpenFlow13 dump-flows s6 > evidence/s6-flows.txt
sudo ovs-ofctl -O OpenFlow13 dump-flows s20 > evidence/s20-flows.txt
```

如需保存 ping 原文，在 `mininet>`：

```text
h1 ping -c 10 h20 > /tmp/h1-h20-ping.txt 2>&1
h1 cat /tmp/h1-h20-ping.txt
```

再回到终端 C：

```bash
cp /tmp/h1-h20-ping.txt evidence/
```

默认 Mininet 主机共享文件系统，所以 `/tmp` 文件可由宿主 Linux 读取。`evidence/` 已被 `.gitignore` 忽略，避免把每次运行的日志当源码提交。

## 13. REST 接口说明

以下是**仓库集成版**，统一使用 8080；与之前分步脚本的字段和状态码不能混用。

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/` | 真实页面 |
| GET | `/api/topology` | `{version,switches,links,hosts}`；links 含两端端口 |
| GET | `/api/paths?src=h1&dst=h20` | 精确最短/最长简单路径和数量；不下发规则 |
| POST | `/api/services` | JSON `{src,dst}`；计算最长路、下发双向规则、等待 Barrier |
| GET | `/api/services` | 业务数组，含状态及每跳正反向计数 |
| GET | `/v1.0/topology/switches` | Ryu 原生交换机诊断列表 |
| GET | `/v1.0/topology/links` | Ryu 原生有向 LLDP 链路列表 |
| GET | `/stats/switches` | ofctl_rest 已连接 DPID 列表 |
| GET | `/stats/flow/1` | ofctl_rest 查询 DPID 1 的流表 |

最后四项依赖第 6 节命令中加载的 `rest_topology`、`ofctl_rest`。`/api/monitor/services` 是之前分步实现的命名，**本仓库集成版没有这个路径**；统一读取 `/api/services`。

自定义路径/配置接口正常返回 HTTP 200。输入不合法、拓扑未匹配、主机未发现或已识别的下发异常通常返回 HTTP 400 和 `{"error":"..."}`；DFS 预算耗尽返回 HTTP 422 和 `exact:false`。不要照搬分步脚本中的 409/502 判断。需要看 HTTP 状态时：

```bash
curl -i 'http://127.0.0.1:8080/api/paths?src=h1&dst=h20'
```

一个无序主机对使用一个业务 ID，例如 h1/h20 与 h20/h1 都是 `h1-h20`。再次配置同一主机对会撤掉旧 cookie 的规则，再安装新 cookie；可能短暂中断，也会重新积累计数，不是无中断切换。当前没有单独的 DELETE 业务接口；结束整个实验按第 16 节清理。

## 14. 按代码理解实验原理

建议先完整跑通一次，再按下面的顺序阅读并逐段改写源码。完整运行只启动 `controller.py`，不需要同时启动多个分步控制器。

### 14.1 topo20.py：数据平面与静态 ARP

`LabTopo.build()` 先创建 20 台 `OVSSwitch` 和 20 台主机，把所有交换机设为 `OpenFlow13`、`failMode='secure'`，并固定主机口为 1。再读取 JSON 的每一条边调用 `addLink`；重复边、自环或非法编号会被检查拒绝。

`main()` 使用 `RemoteController` 指向 Ryu；`autoStaticArp=True` 填充主机邻居表。`secure` 使没有匹配规则的业务不会自行依赖 OVS 的普通二层交换策略完成转发。脚本启动后发探测、进入 CLI，最终在 `finally` 中停止网络。

### 14.2 controller.py 的 features / packet_in：控制通道和主机位置

`OFP_VERSIONS` 约束 OpenFlow 1.3。`features()` 给每台连接的交换机安装优先级 0 的 table-miss，输出到控制器，且 `OFPCML_NO_BUFFER` 请求完整报文。未配置业务只触发 PacketIn，不自动转发。

`packet_in()` 忽略 LLDP，只在交换机端口 1 且源 MAC 与该编号的实验主机相符时登记主机。IP 按实验固定地址约定生成；这不是 DHCP、ARP 安全认证或任意外部网络的通用主机发现逻辑。

### 14.3 refresh：LLDP 与端口邻接表

Ryu 的 switches 模块发送/接收 LLDP，`get_switch()`、`get_link()` 获取当前发现结果。`refresh()` 只把两个方向都已被发现的链路放入图，邻接表 `graph[a][b]` 表示**在交换机 a 上通向 b 的输出端口**。例如 `graph[6][11]=4`，反向的 `graph[11][6]` 需要从另一端独立读取。

图的节点/端口指纹变化时增加版本，将既有业务标记 stale 并按 cookie 撤回规则。计算路径前要求完整节点/边集合匹配 `topology.json`，搜索结束和下发后再次检查版本，避免使用已经变化的图继续完成配置。

### 14.4 paths.py：DFS、回溯与精确最值

`dfs_paths()` 用 `path` 记录路径，`visited` 只记录**当前路径**的节点。探索相邻节点前加入它，递归返回后 `pop` 并从 visited 删除；如果将 visited 永久保留，后面的合法分支会被漏掉，就不再是枚举所有简单路径。

到达目标节点后比较当前长度，更新 shortest/longest 并计数，再回溯。多个等长解取排序遍历中首次发现的路径。每 1000 次递归调用执行协作回调让 Ryu 有机会处理其他事件；时间/访问预算耗尽抛出 `SearchLimit`，不返回部分最优解。

一般图的最长简单路径搜索可能指数增长。这个教学实现适合本题给定小网格，不能因为有预算限制就当作大规模网络的高性能最优路由器。

### 14.5 install：为什么正向通了还要反向规则

对于路径 `v0,...,vk`：起点入端口是主机口 1，中间点入端口来自前一台交换机；终点出端口是主机口 1，中间点出端口来自下一台交换机。反方向将路径倒序，并交换源/目的 IP。

每条业务规则匹配 `in_port + eth_type=0x0800 + ipv4_src + ipv4_dst`，优先级 100，动作只输出到精确端口。IPv4 ping 的请求和回复都需要规则，因此仅装单向规则会导致请求到达而回复不通。

每个业务 cookie 区分该次下发；Barrier 用于等待先前发送的 OpenFlow 消息在对应交换机上被处理，控制器也追踪 FlowMod 错误。Barrier 本身不能证明 ping 能通，所以必须再做数据平面验收。安装异常时按 cookie 删除本轮规则。

### 14.6 monitor / flow_stats / service_list：计数如何回到网页

后台任务每 2 秒刷新拓扑并发送 FlowStats 请求。`flow_stats()` 按交换机与 xid 收集 multipart 分段回复，完整后才作为该轮统计；`service_list()` 按业务 cookie 和源 IP 关联正反向计数，过滤超过 6 秒的样本。

页面每 2 秒读取 `/api/topology` 和 `/api/services`；计算按钮调用 `/api/paths`，配置按钮 POST `/api/services`。数据链路是：

```text
浏览器 → Ryu REST → DFS / FlowMod → OVS
浏览器 ← Ryu REST ← FlowStatsReply ← OVS
```

集成版统计面向受控实验，没有完整实现乱序回复隔离、控制器重连恢复、按输出动作再核验等生产级机制；之前分步统计代码与此仓库接口也不完全相同。验收应结合实时 ping 与 OVS 原始规则，不只依赖 UI 状态。

## 15. 常见问题逐项排查

### 15.1 ryu-manager 仍出现 traceback

先核对 `which python`、`which ryu-manager`、`python --version`、`pip show` 的路径和版本，再按第 4 节修复。

- `TimeoutError / is_timeout`：仍装了旧 Eventlet，或实际执行的是另一个环境里的 ryu-manager。
- `cannot import name ALREADY_HANDLED`：升级了 Eventlet，但未在该 venv 运行 `python fix_ryu_wsgi.py`。
- `easy_install.get_script_args` 或安装元数据失败：先固定 setuptools==57.5.0，再使用 `--no-build-isolation` 安装。
- `No module named paths`：没有进入 `lab` 或漏了 `export PYTHONPATH="$PWD"`。
- `No module named mininet`：Mininet 误用了 venv Python，改用 `sudo /usr/bin/python3 topo20.py`。

如果用了 `ryu-manager ... | tee ...`，shell 最后看到的退出状态可能只是 tee 的状态；以 traceback 和端口是否实际监听为准。

### 15.2 6653/8080 被占用

```bash
sudo ss -lntp | grep -E ':(6653|8080)[[:space:]]'
```

找到旧实验终端并 Ctrl+C，确认进程身份后再处理，不要不加区分地杀掉其他服务。若改 OpenFlow 端口，例如 Ryu 改 6654，Mininet 也要用 `topo20.py --port 6654`。若只改 Web API 端口，例如 8081，curl/浏览器/SSH 隧道目标也要一起改；这不改变 OpenFlow 6653。

### 15.3 交换机数为 0 或不足 20

```bash
sudo ovs-vsctl show
sudo ovs-vsctl get-controller s1
sudo ovs-vsctl --columns=target,is_connected list Controller
sudo ovs-ofctl -O OpenFlow13 show s1
```

预期 s1 目标是 `tcp:127.0.0.1:6653`，Controller 条目连接为 true。确认 Ryu 先启动、OVS 服务正常、Mininet 使用同一 Linux。若控制器分开部署，`127.0.0.1` 指向各自机器，必须用 `topo20.py --controller 可达控制器IP`，并保证控制端口可达；这属于扩展部署，需要自己核对网络路径。

### 15.4 有 20 台交换机但链路不是 31/62

确认带 `--observe-links` 和 `ryu.topology.switches` 启动，先等待约 10 秒，再检查原生 LLDP 接口、`net`、`ovs-ofctl show` 及链路状态。恢复/断开链路的发现存在 LLDP 超时延迟，不承诺 2 秒内完成。

只见 31 条时，先分清查的是去重的 `/api/topology` 还是有向的 `/v1.0/topology/links`。边数正确但集合不同也不合格，按第 8 节脚本比较完整集合。不要把主机接入 20 条计入交换机 LLDP 链路。

### 15.5 主机少于 20 或提示主机尚未发现

按第 7 节在 Mininet 中重发 `.254` 探测，检查 hi 的 IP/MAC 与交换机口 1 是否匹配。LLDP 本身不发现普通主机。本项目没有从任意端口学习主机的通用逻辑，主机接到了其他端口就需要修改实现或恢复拓扑。

### 15.6 业务 installed，但 ping 不通

先检查 POST 是否真的返回 installed，有无 `error`；再在 Mininet 中检查静态 ARP并重建：

```text
h1 ip neigh show
py net.staticArp()
```

然后核对路径上每台交换机的正反向 priority=100 规则、cookie、输入/输出端口，以及 Ryu 日志里的 OpenFlow error / Barrier 超时。确认没有额外加载学习交换机应用，没有手工添加 FLOOD/NORMAL 规则。链路变化后业务 stale，需恢复完整图后重新 POST。

`pingall` 会测试未配置的主机对，不能把其失败直接归因于 h1↔h20 业务。当前配置一次只处理一个主机对。

### 15.7 页面显示演示或配置按钮禁用

确认地址是 Ryu 的 HTTP 页面而非 github.io，移除 `?demo=1`，检查右上角是否连接。选择两台不同主机；相同主机按钮会禁用。不要把 `docs/index.html` 复制到真实 static 目录，因为它带强制模拟元标记。

### 15.8 页面能打开，但没有实时数据

直接在同一浏览器/地址访问 `/api/topology`。若返回 404、HTML 或连不上，说明打开了纯静态服务器或 SSH 隧道/端口错误。先在 Linux 用 curl 确认 Ryu API 正常，再排查本机隧道。浏览器强制刷新，排除旧缓存。

### 15.9 计数一直为 0、等待更新或断开后仍有绿色

网页不产生主机流量，先执行真实 ping。等待 2～4 秒，查看 `/api/services` 中 `fresh`、`present` 和 `packets`；若没有匹配规则，回查 cookie 和 OVS 原始表。若 API 断开，不把离线快照当作新证据。若只是停止 ping，但采样仍成功，累计计数保留正值是正常现象，绿色不等于瞬时流量。

### 15.10 断链后为什么不能自动改走另一条路

当前实现是“严格复现指定拓扑”：发现图必须与 JSON 完整匹配。断链后撤回旧业务并标 stale，不会自动选择剩余图重新下发。在 `mininet>` 恢复链路，例如：

```text
link s1 s2 up
```

等待 LLDP 恢复到精确 31 条边，重新计算并配置。若要验证撤回，可先 `link s1 s2 down`，但先保存正常实验结果；该操作会影响当前业务。

## 16. 停止重启与再次复用

推荐清理顺序：

1. 在 Mininet 中停止测试流量，在 `mininet>` 执行 `exit`，等待脚本清理网络。
2. 终端 A Ctrl+C 停止 Ryu。
3. Linux shell 执行 `sudo mn -c` 清理异常退出遗留资源。
4. 如使用本机 SSH 隧道，在本机 Ctrl+C 停止。

再次实验时重新执行第 6～11 节；无须重复 apt 安装或创建 venv，但每个新终端启动 Ryu前要激活同一个 `.venv`。修改依赖或重新安装 Ryu 后需再次运行兼容修复。

业务列表、主机发现、统计、cookie 都保存在控制器内存中，重启不持久化。不要只重启 Ryu 而保留旧 OVS 流表继续验收：应停止旧 Mininet 并清理，重新创建网络、发现、POST 配置。每次运行保存独立 evidence 目录可避免覆盖上一次报告。

## 17. 修改拓扑与验证边界

本次默认配置已经是题目指定的 4×5 网格，不再是早期环形加弦拓扑。若拉取后仍看到 h1→h20 最短 1 跳、24 条边，说明仍在运行旧版本或旧目录。

要扩展拓扑，先停止整个实验，再修改 JSON；拓扑脚本、控制器预期和路径测试必须一起核对。当前实现固定 20 个编号，不能只把 `nodes` 改为更大值就宣称支持任意规模。链路顺序改变会改变端口；任意形状的图也需要调整固定网格前端坐标。Pages 的演示数据单独内嵌在 `docs/index.html`，修改真实 JSON 不会自动改它。

仓库算法测试可以在普通 Python 上独立运行，用 BFS 与小图穷举交叉检查；Python 源码与前端脚本可做语法检查。它们不代替真实 Linux 上的 Mininet/OVS/Ryu 控制通道、FlowMod/Barrier、端到端通信与统计验收。本手册给出的是可执行流程与预期判据，没有把模拟接口或本机静态页面检查当作真实联网结果。

参考资料：[Mininet 官方 Walkthrough](https://mininet.org/walkthrough/)、[Ryu 源码](https://github.com/faucetsdn/ryu)、[本项目路径测试](test_paths.py)。
