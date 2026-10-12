# Mininet + Ryu：20 交换机、DFS 最长路径与业务可视化

## 0. 实验范围与文件

将题目中的“20 个网络节点”解释为 20 台 OpenFlow 交换机 s1～s20，每台挂一台 h1～h20，共 40 个拓扑顶点。若老师对“节点”的定义不同，应以题目为准。

**指定拓扑尚未提供。本包中的 topology.json 是演示拓扑，不是老师给定的拓扑。** 它有 20 个交换机、24 条交换机间链路：一个环，另外加四条弦。替换连接表后再验收。

本示例采用无向、无权、单链路拓扑。最短/最长按交换机间链路跳数比较；路径不允许重复交换机。主机端到端链路数 = 交换机间跳数 + 2。所有主机位于同一 /24 网段。本例下发 IPv4 主机对规则，支持 ICMP/TCP/UDP，未实现 IPv6、VLAN 或按 TCP 端口区分的独立业务。

文件：

| 文件 | 用途 |
|---|---|
| topology.json | 唯一需要按指定拓扑修改的连接表 |
| topo20.py | 在 Linux 上创建交换机、主机和链路 |
| paths.py | DFS + 回溯，求两端之间所有简单路径的最短/最长者 |
| controller.py | Ryu 拓扑发现、PacketIn 主机学习、流表下发、REST 与计数 |
| static/index.html | 与 Ryu 同端口的拓扑和业务可视化 |
| requirements.txt | 教学环境依赖 |
| test_paths.py | BFS 与排列穷举独立验证 DFS |

代码已进行 Python/JavaScript 语法检查与 DFS 独立算法测试。本包制作环境是 macOS，没有在这里运行 Linux Mininet/OVS；流表和端到端结果必须在你的 Linux 环境按以下流程验收。

## 1. 先准备 Linux 环境

为复现旧版 Ryu 4.34，下面的依赖命令以 **Ubuntu 20.04、Python 3.8 的教学虚拟机**为基线；资源可用 2～4 核、4 GB 内存。不要把这些旧依赖直接套到 Python 3.10/3.12。若课程已有正常运行的 Ryu 环境，优先使用课程环境，不必重装。

建议 Mininet、OVS、Ryu 放同一台 Linux 虚拟机里，控制器地址统一用 127.0.0.1。这样先避免跨机器的 IP 和端口问题。

```bash
lsb_release -a
python3 --version

sudo apt update
sudo apt install -y mininet openvswitch-switch python3-venv python3-dev \
  build-essential libffi-dev libssl-dev curl jq unzip iperf tcpdump
sudo systemctl enable --now openvswitch-switch

sudo mn --version
ovs-vsctl --version
sudo mn --topo single,2 --controller none --switch ovs,failMode=standalone --test pingall
sudo mn -c
```

最后一条小拓扑测试只用于检查 Mininet/OVS 能工作，显式指定 standalone OVS 转发。它不验证 Ryu。若此处失败，先排查 OVS 服务与内核，不要继续叠加控制器问题。

## 2. 放置代码、创建 Ryu 虚拟环境

把 sdn-lab.zip 放到 Linux 的一个工作目录后：

```bash
unzip sdn-lab.zip
cd sdn-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install 'pip==23.3.2' 'setuptools==57.5.0' 'wheel==0.37.1'
python -m pip install --no-build-isolation -r requirements.txt

ryu-manager --version
python -m unittest -v test_paths
```

版本固定用于避开 Ryu 安装脚本与新版 setuptools、eventlet 的已知兼容问题。`ALREADY_HANDLED` 是常见的 eventlet 兼容报错，并不是拓扑算法问题。

注意两种 Python：

- Ryu 用 `.venv` 里的 `python` 和 `ryu-manager`。
- Mininet 用 `/usr/bin/python3`，因为 Mininet 由 apt 安装到系统 Python。

不要用 `sudo pip install` 混装，也不要用虚拟环境的 Python 启动 apt 版 Mininet。

## 3. 按给定拓扑修改连接表

```bash
nano topology.json
python3 -m json.tool topology.json
```

连接 `[1, 6]` 表示 s1 与 s6 之间有一条物理双向链路。无向边只写一次，不要再加 `[6, 1]`。文件不接受自环、重复边或平行链路。若指定拓扑含平行链路，需要把图结构改为带端口的多重图。

主机连接已经由脚本自动创建，不需要写进 edges。每台交换机的端口 1 固定连接自己的主机，其余端口由 Mininet 分配。DPID 采用 16 位十六进制，例如 s20 的 DPID 为 `0000000000000014`，其整数值为 20。

控制器并不把 JSON 当作发现结果。它通过 LLDP 获取实际交换机邻接与出端口，JSON 只用于确认指定拓扑已全部发现，防止在不完整图上声称找到了整个网络的最长路。

修改后须重启 Mininet 和 Ryu，使两者重新读取一致的连接表。

## 4. 打开三个终端

三个终端都先进入同一个 sdn-lab 目录。

### 终端 A：启动 Ryu

```bash
source .venv/bin/activate
export PYTHONPATH="$PWD"
ryu-manager --observe-links --ofp-tcp-listen-port 6653 \
  --wsapi-host 0.0.0.0 --wsapi-port 8080 \
  controller.py ryu.topology.switches \
  ryu.app.rest_topology ryu.app.ofctl_rest
```

保持运行。`6653` 是交换机接入 OpenFlow 控制器的端口，`8080` 是 REST/展示网页的端口。`--observe-links` 打开 LLDP 链路发现。显式使用 OpenFlow 1.3。

### 终端 B：启动 Mininet

```bash
sudo mn -c
sudo /usr/bin/python3 topo20.py
```

出现 `mininet>` 后，以下命令在 Mininet 里输入（不要输入提示符）：

```text
nodes
net
links
h1 ip addr show h1-eth0
h1 ip neigh show
```

应看到 s1～s20、h1～h20 和 c0。h1 地址应为 10.0.0.1，邻居表里有其它主机的静态 MAC。

脚本会给每台主机发起一次对不存在地址 10.0.0.254 的探测，使首个 ARP PacketIn 进入 Ryu，完成主机位置学习；探测不通是预期行为。主机学习来源是实际收到的主机 MAC/交换机/端口；IP 使用实验固定地址约定。

### 终端 C：检查连接与拓扑

等待约 10 秒，若仍未完整发现再稍等；完整性检查以接口返回为准。

```bash
sudo ovs-vsctl show
sudo ovs-vsctl get-controller s1
sudo ovs-vsctl list Controller
ss -lntp | grep -E ':6653|:8080'

curl -s http://127.0.0.1:8080/api/topology | jq
curl -s http://127.0.0.1:8080/api/topology \
  | jq '{switches:(.switches|length), hosts:(.hosts|length), links:(.links|length)}'
```

演示拓扑应返回 20 台交换机、20 台主机、24 条无向交换机链路。控制器连接记录应显示 `is_connected: true`。

Ryu 原生拓扑接口也可检查：

```bash
curl -s http://127.0.0.1:8080/v1.0/topology/switches | jq
curl -s http://127.0.0.1:8080/v1.0/topology/links | jq
curl -s http://127.0.0.1:8080/v1.0/topology/hosts | jq
```

原生 links 通常以两个方向表示一条物理链路，所以可能有 48 条；本包 `/api/topology` 只展示 24 条无向边。

如果主机未发现，在 Mininet 重新触发探测：

```text
py [h.cmd('ping -c 1 -W 1 10.0.0.254 >/dev/null 2>&1 &') for h in net.hosts]
```

此阶段 `h1 ping h20` 失败是预期的：本控制器只转发已经明确配置的主机对。

## 5. 查看可视化

同机浏览器访问 `http://127.0.0.1:8080/`。远程 Linux 若不方便直接访问，可在自己电脑的终端做转发：

```bash
ssh -L 8080:127.0.0.1:8080 用户名@Linux地址
```

随后在自己电脑打开 `http://127.0.0.1:8080/`。这是命令行启动服务、浏览器展示，无需在 Linux 安装桌面。若本地 8080 被占用，把转发左侧改为 18080，并访问本地 18080。

页面显示实际发现的交换机、主机和链路；鼠标放到交换机链路上可看到两端端口。

页面 UI 已按 Liquid Glass 规范重做：浅灰蓝/深灰蓝主题、深蓝色强调，玻璃顶栏/侧栏/操作区，以及清晰的拓扑与路径内容卡片。三个视图分别为“网络拓扑”“路径分析”“业务监测”。顶部外观按钮支持跟随系统、浅色、深色和减少透明效果；偏好保存在本地浏览器。分段切换支持点击、横向拖动和方向键/Home/End；触屏保留竖向滚动。画布支持放大/缩小，放大后可在画布内滚动；业务支持主机搜索、状态筛选和每跳计数详情抽屉。

如果暂时没有 Linux/Ryu 环境，可只看模拟数据的 UI 预览：

```bash
python3 -m http.server 8081 --bind 127.0.0.1 --directory static
```

浏览器访问 `http://127.0.0.1:8081/?demo=1`。演示模式会明确标注模拟数据，禁用主机选择和配置操作，不调用真实网络 API。实际实验继续使用 Ryu 的 8080 端口，不带 `demo=1`。

新版 UI 已用浏览器检查 1440/1024/768/390/320px 的布局、浅深主题、减少透明/动效、键盘与拖动、筛选、详情和断线状态。接口交互使用模拟 Ryu 响应校验；这些前端检查不能代替真实 Linux 网络验收。

## 6. 用 DFS 求 h1 到 h20 的最短路和最长路

终端 C：

```bash
curl -s 'http://127.0.0.1:8080/api/paths?src=h1&dst=h20' | jq
```

演示结果中应有：

```text
shortest = [1, 20]           shortest_hops = 1
longest  = [1, 2, ..., 20]   longest_hops = 19
exact = true
```

这里省略号仅为说明，实际 JSON 会返回完整序列。主机端到端最短/最长路径分别为 3/21 条链路。

算法在 `paths.py`：

1. 初始路径只有源节点，把它加入当前路径 visited。
2. 按邻居编号依次深入，只进入当前路径未访问的邻居。
3. 到达目标后保存当前路径，并更新最短和最长结果；不再从目标继续扩展。
4. 递归返回时移除节点并撤销 visited 标记，继续其它分支。
5. 全部搜索完成后返回精确结果；长度相同时按邻居排序产生的先遇到路径取值。

visited 表示“当前路径已经经过的节点”，而不是整个搜索过程永久访问过的节点；否则会漏掉候选路径。普通 DFS 遍历一次只会得到一条遍历树，不能直接当作最长路径答案。

无重复节点是必要条件：有环网络如果允许无限绕圈，所谓最长路没有有限上限。一般图的简单路径枚举可能达到阶乘数量级；20 个节点也不保证一定快。本包按 5 秒/500000 次递归预算限制搜索，超限返回 HTTP 422，且拒绝下发。部分搜索发现的最长候选不能当作严格最长路；稠密指定拓扑需要更强的精确算法或明确改用近似要求。

## 7. 用最长路下发双向通信规则

终端 C：

```bash
curl -s -X POST http://127.0.0.1:8080/api/services \
  -H 'Content-Type: application/json' \
  -d '{"src":"h1","dst":"h20"}' | jq
```

也可在网页选择两台主机，先计算路径，再点“配置最长路”。换成 h3/h14 等任意不同主机即可配置其它主机对。

流表分配思路：沿最长路径每台交换机安装正向与反向各一条规则，匹配 `in_port + eth_type=0x0800 + ipv4_src + ipv4_dst`，动作是精确的 `OUTPUT:出端口`。首尾主机端口为 1，其余端口从 LLDP 链路映射取得。

示例路径 s1→s2→s3：

| 交换机 | 正向入端口 | 正向出端口 |
|---|---|---|
| s1 | 主机端口 1 | LLDP 发现的 s1→s2 端口 |
| s2 | LLDP 发现的 s2→s1 端口 | LLDP 发现的 s2→s3 端口 |
| s3 | LLDP 发现的 s3→s2 端口 | 主机端口 1 |

反向把源/目的地址交换，并按路径逆序计算入/出端口。只下发正向会让 Echo Request 到达，但 Echo Reply 回不来。

演示的最长路径经过 20 台交换机，因此应有 40 条业务规则，分散在 20 台交换机上。它们优先级为 100，永久保留到重配置/拓扑变化/实验结束。每次安装使用新的 cookie，防止旧计数误当作新配置流量。

控制器等待各交换机 Barrier 回应并检查相关 OpenFlow 错误；这些只说明消息处理完成，不能证明端到端成功。最长路径首包测试在收到 POST 响应后开始。

## 8. 验证真实通信与路径

终端 B 的 Mininet：

```text
h1 ping -c 5 h20
h20 ping -c 5 h1
```

应无丢包或重试后恢复稳定。若失败，先按排错表检查，不要直接把绿色路径当作成功。

终端 C 查每台交换机的业务流表：

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
sudo ovs-ofctl -O OpenFlow13 dump-flows s2
sudo ovs-ofctl -O OpenFlow13 dump-flows s20

curl -s http://127.0.0.1:8080/stats/flow/1 \
  | jq '."1"[] | select(.priority == 100)'

curl -s http://127.0.0.1:8080/api/services | jq
```

查看 `nw_src/nw_dst`、`in_port`、`actions=output:...` 和 `n_packets/n_bytes`。s2 在最短路 s1→s20 上并不会被经过；s2 的相关规则计数增长，是流量走绕行最长路径的直接证据之一。进一步应检查沿路径每一台交换机的规则计数。

仅在**未修改的演示连接表**中，s1-eth2 是 s1→s2，s1-eth3 是 s1→s20。需要抓包时在终端 C 使用：

```bash
sudo tcpdump -ni s1-eth2 'icmp and host 10.0.0.1 and host 10.0.0.20'
```

同时重新运行 h1 ping h20，应该看到 ICMP。改用 s1-eth3 抓同一过滤条件时不应看到这组 ICMP。修改连接表后端口编号可能改变，必须重新根据 `net`、LLDP 或 `ovs-ofctl show` 确认，不能照搬 eth2/eth3。

## 9. 产生业务流量并在平台展示

Mininet：

```text
h20 iperf -s -p 5001 > /tmp/h20-iperf.log 2>&1 &
h1 iperf -c 10.0.0.20 -p 5001 -t 20 -i 1
h20 cat /tmp/h20-iperf.log
```

使用 iperf 2，即 apt 包 `iperf`；不要和 iperf3 服务端混用。网页选择已配置业务的“查看”，观察最长路径及每跳规则计数。每条链路设为 10 Mbps，因此吞吐通常低于或接近该瓶颈速率；路径更长会增加传播时延，不会让瓶颈带宽按跳数相加。

页面状态分为：

- 橙色：精确最长路径已经配置，等待流量证据。
- 绿色：该业务所有路径交换机上正反向规则的近期读取累计计数都大于 0。
- 失效：拓扑变化，旧配置已撤销，需要重新配置。

绿色是计数证据，不能替代 ping，也不表示业务此刻持续发送。该页面展示的是 IPv4 主机对业务；同一主机对的 ping 和 iperf 共用一组规则及计数。如课程要求按应用独立显示，需要增加 `ip_proto`、TCP/UDP 端口匹配和独立 cookie。

## 10. 结束与常见排错

Mininet 输入 `exit`，Ryu 终端 Ctrl+C，最后执行：

```bash
sudo mn -c
```

| 现象 | 排查 |
|---|---|
| import mininet 失败 | 用 sudo /usr/bin/python3 topo20.py；检查 apt 的 mininet 安装 |
| ALREADY_HANDLED 或 GreenSocket 报错 | 核对 Python 3.8 与锁定依赖；确认启动的是 .venv/bin/ryu-manager |
| No module named paths | cd 到 sdn-lab 并 export PYTHONPATH="$PWD" 后启动 Ryu |
| 交换机已连接但 links 为空 | 检查 --observe-links、ryu.topology.switches 和 LLDP 等待时间 |
| controller is_connected 为 false | 检查地址、6653 监听、OpenFlow13 与控制器日志 |
| hosts 缺失 | 在 Mininet 重新对 .254 发探测；检查各主机 MAC 和交换机端口 1 |
| 拓扑与 JSON 不一致 | 检查实际边数、重复边、链路 down、两份配置是否同步；等待 LLDP 收敛 |
| 搜索超限 | 这是预算限制，不是没有路径；不应把未完成搜索结果叫作严格最长路 |
| ping 不通 | 确认先 POST 配置、双向规则、静态 ARP 与精确出端口；核对 OpenFlow 错误 |
| 网页有路径但计数为 0 | 等待 2～4 秒统计周期，确认正在产生该主机对的 IPv4 流量 |
| pingall 大量失败 | 本例只配置所选主机对；全网 pingall 需要逐对配置全部 190 个无序主机对 |

不要在该有环拓扑上同时运行 simple_switch_13；它的学习/泛洪规则会干扰本控制器。也不要用 OFPP_FLOOD 处理未知 ARP，或另加 NORMAL 默认转发绕过显式路径。本包用静态 ARP 做教学简化；动态主机环境可改成控制器代理 ARP。

## 11. 实验报告建议收集的证据

1. 指定拓扑连接表，以及 20 台交换机/20 台主机/正确链路数。
2. Controller is_connected 与 LLDP API 返回。
3. DFS 伪代码，visited 回溯说明，最短/最长完整序列与跳数。
4. 最长路径首、中、尾交换机的双向业务流表及端口映射。
5. ping 无丢包结果、iperf 客户端/服务端输出。
6. 可视化拓扑、路径高亮、各跳计数证据。

可保存接口证据：

```bash
mkdir -p evidence
curl -s http://127.0.0.1:8080/api/topology > evidence/topology.json
curl -s 'http://127.0.0.1:8080/api/paths?src=h1&dst=h20' > evidence/paths.json
curl -s http://127.0.0.1:8080/api/services > evidence/services.json
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 > evidence/s1-flows.txt
sudo ovs-ofctl -O OpenFlow13 dump-flows s20 > evidence/s20-flows.txt
```

## 官方参考

- Mininet 安装与命令行：[Download](https://mininet.org/download/)、[Walkthrough](https://mininet.org/walkthrough/)。
- Ryu 拓扑发现实现：[switches.py](https://github.com/faucetsdn/ryu/blob/master/ryu/topology/switches.py)。
- Ryu 原生拓扑 REST：[rest_topology.py](https://github.com/faucetsdn/ryu/blob/master/ryu/app/rest_topology.py)。
- Ryu 流表下发：[Switching Hub](https://book.ryu-sdn.org/en/html/switching_hub.html)、[OpenFlow 1.3 API](https://ryu.readthedocs.io/en/latest/ofproto_v1_3_ref.html)。
- Ryu/eventlet 已知兼容问题：[Ryu issue 138](https://github.com/faucetsdn/ryu/issues/138)。
- DFS 简单路径枚举与规模：[NetworkX all_simple_paths](https://networkx.org/documentation/networkx-1.7/reference/generated/networkx.algorithms.simple_paths.all_simple_paths.html)。
