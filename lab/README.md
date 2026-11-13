# Project 2 · Dial 最短路与 Kruskal 广播实验

从 Project 1 的 Ryu 和 Mininet 环境开始。控制器仍使用 OpenFlow 1.3 和 LLDP。单播采用 Dial 桶式 Dijkstra 计算并配置双向最短路。广播采用 Kruskal 最小生成树，任选 h1 到 h20 中一台作为源，覆盖其余 19 台主机。

## 1. 在 Ubuntu 上准备实验环境

使用能执行 `sudo` 的 Ubuntu 和 Python 3.10。本实验的依赖版本按 Ubuntu 22.04 的系统 Python 3.10 配置。

```bash
sudo apt update
sudo apt install -y git mininet openvswitch-switch tcpdump curl \
  python3-venv python3-dev build-essential libffi-dev libssl-dev
sudo systemctl enable --now openvswitch-switch
/usr/bin/python3 --version
git clone --branch project2-DLC --single-branch \
  https://github.com/WilliamWilson-1/mininet-ryu-topology-lab.git ~/mininet-project2-dlc
cd ~/mininet-project2-dlc/lab
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip==23.3.2 setuptools==57.5.0 wheel==0.37.1
python -m pip install --no-build-isolation -r requirements.txt
python fix_ryu_wsgi.py
python -m pip check
ryu-manager --version
```

最后一条命令应输出 Ryu 4.34。若出现 `TimeoutError` 或无法导入 `ALREADY_HANDLED`，检查当前 shell 是否激活本目录的虚拟环境。前者可通过重新安装 `requirements.txt` 中的 Eventlet 和 dnspython 版本解决，后者需要在安装后运行 `python fix_ryu_wsgi.py`。

## 2. 启动并配置

先启动 Ryu，再打开第二个终端启动 Mininet。Ryu 使用虚拟环境中的 Python，Mininet 使用 apt 安装的系统 Python。

```bash
# 终端 A
cd ~/mininet-project2-dlc/lab
source .venv/bin/activate
export PYTHONPATH="$PWD"
ryu-manager --observe-links --ofp-tcp-listen-port 6653 \
  --wsapi-host 127.0.0.1 --wsapi-port 8080 \
  controller.py ryu.topology.switches \
  ryu.app.rest_topology ryu.app.ofctl_rest
```

```bash
# 终端 B
cd ~/mininet-project2-dlc/lab
sudo /usr/bin/python3 topo20.py
```

在 Linux 打开 `http://127.0.0.1:8080/`。从 Mac 访问 Ubuntu 虚拟机时，可在 Mac 运行以下命令，再打开 `http://127.0.0.1:18080/`。

```bash
ssh -N -L 18080:127.0.0.1:8080 ubuntu@192.168.64.8
```

默认网格拓扑下，等页面显示 20 台交换机、20 台主机和 31 条交换机间链路。使用其他预设时，链路数以第 7 节为准。在“网络拓扑”找到“Project 2 · Kruskal 广播”，选择 h1，点击“配置广播树”。也可从终端调用相同接口。

```bash
curl -fsS http://127.0.0.1:8080/api/broadcast \
  -H 'Content-Type: application/json' -d '{"src":"h1"}'
```

`POST /api/broadcast` 配置或替换广播业务。`GET /api/broadcast` 返回当前业务、定向树边、端口规则和命中计数。还未配置时返回 `{"service":null}`。页面每两秒轮询，点击“显示单播路径”可切回原拓扑视图。

## 3. 发送并验证

在 Mininet CLI 中先在两个接收端抓包，再从 h1 发送一份 UDP 报文。抓包命令在后台运行 30 秒。

```text
mininet> h7 timeout 30 tcpdump -ni h7-eth0 -c 1 'udp dst port 5005' > /tmp/project2-h7.log 2>&1 &
mininet> h20 timeout 30 tcpdump -ni h20-eth0 -c 1 'udp dst port 5005' > /tmp/project2-h20.log 2>&1 &
mininet> h1 python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1); s.bind(('10.0.0.1',0)); print(s.sendto(b'project2',('255.255.255.255',5005)))"
mininet> sh cat /tmp/project2-h7.log /tmp/project2-h20.log
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

发送命令应输出 `8`，表示 8 字节的 UDP 载荷已提交给本机协议栈。先等抓包进程输出文件里出现 `listening on`，再发送报文。`s.bind(('10.0.0.1',0))` 指定源 IP 和自动分配的源端口，帮助没有默认路由的 Mininet 主机选择广播出口。若省略它，发送到 `255.255.255.255` 可能出现 `OSError: [Errno 101] Network is unreachable`。

如果选择其他源，发送命令的主机名和 `bind` 中的源 IP 都要换成该源，并在其他主机抓包。单次发送后，新安装的 20 条广播规则应各命中一次。展开页面的端口表可以查看计数。要证明某个接收端实际收到报文，查看该主机网卡的抓包结果。

## 4. 浏览器演示

在 Mac 上只看算法演示时，从仓库根目录运行 `python3 -m http.server 8766 --bind 127.0.0.1 --directory docs`，打开 `http://127.0.0.1:8766/?demo=1` 并选择源主机。演示页在浏览器中计算树，端口表的命中计数显示为横线。

## 5. 从 LLDP 到转发流表

1. `controller.py` 的 `require_full_topology()` 刷新拓扑，检查交换机和链路是否与所选拓扑一致。邻接表 `graph[a][b]` 存的是 a 连接 b 的本地 OpenFlow 端口。主机端口来自原有的 PacketIn 学习。
2. `broadcast.py` 的 `kruskal_tree()` 将双向链路合并为无向边，按 `(权重, 较小 DPID, 较大 DPID)` 排序。实验链路统一为 10 Mbit/s、1 ms，因此每条边权重取 1。同权按编号排序，让结果可复现。
3. 并查集最初让每台交换机独立成组。扫描一条边时，查询两端所属组。不同组就选边并合并两组，同组就跳过以免成环。查询使用路径压缩，合并时将小组挂到大组。20 个顶点连成树需要 19 条边，本实验的最小总权重为 19。
4. `broadcast_plan()` 使用队列从源交换机遍历树，把每条边定向为父到子。根从源主机端口收包，只向子交换机输出。非根从父交换机端口收包，向本地主机及全部子交换机输出。每个非根恰有一个父节点，因此一份匹配的报文在每条树边上只传一次。
5. `install_broadcast()` 下发优先级 110 的 OpenFlow 规则。匹配入端口、源主机 MAC 和 IPv4 地址、目的广播 MAC、IPv4 目的地址 `255.255.255.255`、UDP 协议和目的端口 `5005`。按需列出多个 `OUTPUT`，由交换机复制报文。单播使用优先级 100 的双向最短路规则，通过独立 cookie 管理。
6. 控制器先给 19 个非根交换机下发规则并等待 Barrier，最后下发并确认根规则。出错时按新 cookie 撤回本批规则。重新配置时替换旧业务，LLDP 拓扑变化或交换机重连时将原业务标记为失效，需重新配置。Barrier 表示该连接上之前的请求已处理，实际收包要通过计数和抓包验证。

例如选 h1，s1 从 p1 收包，按该拓扑的默认端口编号向 p2（s2）和 p3（s6）输出。s2 从连接 s1 的 p2 收包，向 p1（h2）、p3（s3）、p4（s7）输出。实际规则以页面中的 LLDP 端口为准。

排序耗时 `O(E log E)`，并查集扫描耗时接近线性，树定向和生成规则各是 `O(V)`。同一个无向树可以选不同的根，变化的是树边方向、各交换机的输入端口和输出端口，以及报文的源匹配条件。

## 6. 检查算法与广播是否正确

在 Ubuntu 的普通终端激活实验虚拟环境后运行算法测试。

```bash
cd ~/mininet-project2-dlc/lab
source .venv/bin/activate
python -m unittest -v test_broadcast.py test_paths.py
```

`test_broadcast.py` 检查有不同权重的图是否选出最小生成树，并针对 20 种广播源，验证接收主机恰好各获得一份报文。`test_paths.py` 用 Floyd–Warshall 独立核对 Dial 最短路，并检查不同权重、零权环、距离更新和循环桶复用。广播树由 Kruskal 生成。

在普通终端读取广播状态与计数。

```bash
curl -fsS http://127.0.0.1:8080/api/broadcast | python3 -m json.tool
```

检查 `status` 为 `installed`，`links` 有 19 条，`total_weight` 为 19，`receivers` 有 19 台。发送一份报文后，等两至四秒，20 条规则的 `packets` 应各增加 1，`all_switches_seen` 应为 `true`。接收端网卡抓包用于确认报文已送到该主机。

若两次读取之间没有其他发送者，可用计数增量检查是否有重复转发。当前计数是本次流表安装后的累计值，重新配置广播树会产生新 cookie 并重新计数。

## 7. 用命令切换网络拓扑

以下四种预设各有 20 台交换机和 20 台主机，每台交换机固定连接一台同编号主机。链路统一配置为 10 Mbit/s、1 ms，广播树的边权取 1。

| 命令名称 | 拓扑 | 交换机间链路数 | 结构 |
| --- | --- | --- | --- |
| `grid` | 4×5 网格 | 31 | 原实验指定的横纵网格 |
| `ring-chords` | 弦环网络 | 28 | 20 节点环，加跨环弦与局部捷径 |
| `dual-ring` | 双环互联 | 27 | 两个 10 节点环，配备多条环间连接和环内捷径 |
| `campus` | 多园区互联 | 28 | 四个 5 节点园区环，园区之间有环形骨干和跨区连接 |

在实验目录列出预设，选择下一次启动的拓扑。

```bash
cd ~/mininet-project2-dlc/lab
python3 topologies.py --list
python3 topologies.py --select ring-chords
```

切换一次完整实验时，先在原 Mininet CLI 输入 `exit`，等待网络退出，再在原 Ryu 终端按 Ctrl+C。随后运行 `--select`，按第 2 节原有命令重新启动 Ryu 和 Mininet。两端都读取本目录的 `.active-topology` 选择文件，Ryu 在启动时固定此次实验所需的节点与链路。该选择文件由本机生成，并已加入 Git 忽略列表。

切换其他预设只需更换名称。

```bash
python3 topologies.py --select dual-ring
python3 topologies.py --select campus
python3 topologies.py --select grid
```

上面的命令是三个可选示例，实际运行其中一条即可。若依次执行，最终选择的是 `grid`。选择完成后重启两端，以新拓扑重新计算并配置业务。

Mininet 也接受 `sudo /usr/bin/python3 topo20.py --topology campus`，用于显式指定预设。此时 Ryu 所在目录也应先选择 `campus`。若两端不一致，控制器会拒绝配置业务并提示检查拓扑选择。

普通终端检查当前控制器使用的拓扑。

```bash
curl -fsS http://127.0.0.1:8080/api/topology | python3 -m json.tool
```

`name`、`title` 和 `expected_links` 分别显示预设名称、展示名称和期望链路数。页面按预设使用网格、圆环、双环或四园区布局。待 LLDP 发现完整后，广播配置、UDP 发送和抓包步骤与第 3 节相同，每棵广播树仍有 19 条边。

浏览器演示页面的“演示拓扑”下拉菜单支持即时切换这四种拓扑。切换会更新布局，重新计算当前主机对的路径，并重建已演示的广播树。网址的 `topology` 参数也会同步更新，可以复制分享。也可以用网址直接选择拓扑。

```text
http://127.0.0.1:8766/?demo=1&topology=grid
http://127.0.0.1:8766/?demo=1&topology=ring-chords
http://127.0.0.1:8766/?demo=1&topology=dual-ring
http://127.0.0.1:8766/?demo=1&topology=campus
```

在仓库根目录按第 4 节启动 HTTP 服务后打开这些地址。`lab/topologies.json` 保存新增预设，原网格继续从 `lab/topology.json` 读取。`docs/topologies.json` 是浏览器演示使用的同内容目录，测试会核对两者一致性。

检查全部预设的连通性、所有主机对的路径结果和所有广播源的转发计划。

```bash
python -m unittest -v test_topologies.py test_broadcast.py test_paths.py
```

## 8. 配置并验证 Dijkstra 最短路

在页面选择两台不同主机，点击“计算路径”，即可查看 Dial 桶式 Dijkstra 得到的最短路、路径代价、已确定节点数、成功松弛次数和循环桶数量。点击“配置最短路”下发双向 IPv4 流表。

从普通终端可以调用同一组接口。

```bash
curl -fsS 'http://127.0.0.1:8080/api/paths?src=h1&dst=h20' | python3 -m json.tool
curl -fsS http://127.0.0.1:8080/api/services \
  -H 'Content-Type: application/json' -d '{"src":"h1","dst":"h20"}' | python3 -m json.tool
```

默认网格的 h1→h20 最短路为 `s1→s2→s3→s4→s5→s10→s15→s20`，交换机间共 7 跳、代价 7。结果的 `algorithm` 为 `dijkstra-dial`，`shortest` 是计算路径，安装后的 `path` 是实际下发路径。每条链路统一代价为 1，因此路径代价等于交换机间跳数。

在 Mininet CLI 发送 ICMP，并读取实际流表。

```text
mininet> h1 ping -c 5 h20
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s20
```

默认 h1↔h20 经过 8 台交换机，每台安装正反两条规则，共 16 条优先级 100 的业务规则。在页面“业务监测”查看各跳双向命中计数，继续运行第 3 节的 UDP 广播验证。广播业务也会显示在“业务监测”中，可点击“查看广播树”切回树视图。

`paths.py` 的 `dial_shortest_path()` 接受权重邻接表 `costs[u][v]`。控制器的 `graph[u][v]` 存放 OpenFlow 端口，因此在调用算法前单独建立每条边代价为 1 的权重表。

Dial 使用 `W+1` 个循环桶，W 是最大边权。暂定距离 d 的节点进入 `buckets[d % (W+1)]`。距离指针从小到大扫描，取出最近的候选节点，尝试用 `dist[u]+cost(u,v)` 改进邻居的暂定距离。改进成功就记录前驱并加入对应桶，过期的旧候选会在取出时跳过。目的节点被确定后，通过前驱表逆向恢复路径。

算法支持非负整数权重，本实验 W=1，因此使用两个循环桶。桶扫描与边松弛的总复杂度为 `O(E+VW)`，同权时按邻居编号与桶内 FIFO 顺序确定一条可复现的最短路。算法测试包含不同权重，以便验证 Dial 的距离更新与桶循环逻辑。

真实实验升级后，按第 7 节退出 Mininet 和 Ryu，再从当前分支更新并重新启动两端，重新配置业务。
