# Project 2 · Kruskal 广播实验

从 Project 1 的 Ryu 和 Mininet 环境开始。控制器仍使用 OpenFlow 1.3 和 LLDP。实验新增一条可重新配置的广播业务，任选 h1 到 h20 中一台作为源，覆盖其余 19 台主机。

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

等页面显示 20 台交换机、20 台主机和 31 条交换机间链路。在“网络拓扑”找到“Project 2 · Kruskal 广播”，选择 h1，点击“配置广播树”。也可从终端调用相同接口。

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

1. `controller.py` 的 `require_full_topology()` 刷新拓扑，检查交换机和链路是否与 `topology.json` 一致。邻接表 `graph[a][b]` 存的是 a 连接 b 的本地 OpenFlow 端口。主机端口来自原有的 PacketIn 学习。
2. `broadcast.py` 的 `kruskal_tree()` 将双向链路合并为无向边，按 `(权重, 较小 DPID, 较大 DPID)` 排序。实验链路统一为 10 Mbit/s、1 ms，因此每条边权重取 1。同权按编号排序，让结果可复现。
3. 并查集最初让每台交换机独立成组。扫描一条边时，查询两端所属组。不同组就选边并合并两组，同组就跳过以免成环。查询使用路径压缩，合并时将小组挂到大组。20 个顶点连成树需要 19 条边，本实验的最小总权重为 19。
4. `broadcast_plan()` 使用队列从源交换机遍历树，把每条边定向为父到子。根从源主机端口收包，只向子交换机输出。非根从父交换机端口收包，向本地主机及全部子交换机输出。每个非根恰有一个父节点，因此一份匹配的报文在每条树边上只传一次。
5. `install_broadcast()` 下发优先级 110 的 OpenFlow 规则。匹配入端口、源主机 MAC 和 IPv4 地址、目的广播 MAC、IPv4 目的地址 `255.255.255.255`、UDP 协议和目的端口 `5005`。按需列出多个 `OUTPUT`，由交换机复制报文。优先级 100 的 Project 1 单播规则保留自己的匹配条件和 cookie。
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

`test_broadcast.py` 检查有不同权重的图是否选出最小生成树，并针对 20 种广播源，验证接收主机恰好各获得一份报文。`test_paths.py` 检查原有的 DFS 路径算法。当前控制器的最短路径由 DFS 枚举得到，广播树由 Kruskal 生成。

在普通终端读取广播状态与计数。

```bash
curl -fsS http://127.0.0.1:8080/api/broadcast | python3 -m json.tool
```

检查 `status` 为 `installed`，`links` 有 19 条，`total_weight` 为 19，`receivers` 有 19 台。发送一份报文后，等两至四秒，20 条规则的 `packets` 应各增加 1，`all_switches_seen` 应为 `true`。接收端网卡抓包用于确认报文已送到该主机。

若两次读取之间没有其他发送者，可用计数增量检查是否有重复转发。当前计数是本次流表安装后的累计值，重新配置广播树会产生新 cookie 并重新计数。
