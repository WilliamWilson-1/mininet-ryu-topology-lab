# Mininet + Ryu 拓扑实验 - 网络算法基础第 8 组

一个可以在 Linux 上复用的 SDN 实验：**20 台 OpenFlow 交换机、20 台主机、4×5 网格、31 条交换机间链路**。使用 LLDP 发现链路和两端端口，以 DFS 穷举简单路径，计算最短路与最长路，再沿最长路下发双向 IPv4 流表，通过深蓝色前端页面展示拓扑、业务及每跳计数。

**Project 2 的安装、广播配置和抓包验证见 [Kruskal 广播操作手册](lab/README.md)。** 下方为 Project 1 的单播实验概览。

## 两种使用方式

| 入口 | 可以做什么 | 数据来源 |
| --- | --- | --- |
| [GitHub Pages 在线预览](https://williamwilson-1.github.io/mininet-ryu-topology-lab/) | 任选两台主机计算最短/最长简单路径，查看拓扑与示例业务；流表配置禁用 | 示例网格 + 浏览器本地 DFS，始终标注“演示模式” |
| Linux 控制器页面 `http://127.0.0.1:8080/` | 发现真实拓扑、计算路径、配置最长路、读取 OVS 计数 | 本机 Mininet + Ryu |

GitHub Pages 只托管静态 HTML，不能启动 Linux 进程或连接你的虚拟机。要完成实验，必须运行 Linux 端，再打开控制器提供的页面；不需要把虚拟机 API 暴露到公网。跨电脑访问方式见手册的 SSH 隧道部分。

## 任意主机对的演示计算

打开 [交互演示](https://williamwilson-1.github.io/mininet-ryu-topology-lab/?demo=1)，选择 h1～h20 中任意两台不同主机，点击“计算路径”。也可以交换源/目的，再次计算；在“路径分析”查看完整序列、跳数及简单路径数量。

演示模式在浏览器中以 DFS + 回溯完整枚举指定 4×5 示例网格的简单路径，无需 Ryu、Mininet、登录或后端 API。h1→h20 为 7/19 跳、976 条路径；其他主机对按实际搜索结果显示。同一主机不可作为两端，搜索超限会报错，不显示部分最优解。

真实控制器页面同样支持加 `?demo=1` 临时进入本地演示。GitHub Pages 默认启用演示；Linux 页面不带此参数时仍使用真实 API。演示只计算与展示，不安装流表，不作为联网实验验收依据。

## 指定拓扑

```text
s1 ── s2 ── s3 ── s4 ── s5
│     │     │     │     │
s6 ── s7 ── s8 ── s9 ── s10
│     │     │     │     │
s11── s12── s13── s14── s15
│     │     │     │     │
s16── s17── s18── s19── s20
```

每个 `si` 的端口 1 连接 `hi`。主机地址为 `10.0.0.i/24`，MAC 为 `02:00:00:00:00:XX`，`XX` 是主机编号的两位十六进制表示，例如 h20 为 `…:14`。

- 横向链路 16 条，纵向链路 15 条，共 31 条；双向 LLDP 通常显示 62 条有向记录。
- 主机接入链路另有 20 条，整个数据平面共有 51 条链路。
- h1→h20 的最短路是 **7 跳**，最长简单路径是 **19 跳**，共有 **976 条简单路径**。跳数只计交换机间链路；加上两端主机接入链路后分别为 9 和 21。
- 最长路不重复经过交换机。不同主机对的最长路长度可能不同，不保证每对主机都经过全部 20 台交换机。

## 文件与阅读顺序

```text
.
├── README.md                 # 项目入口
├── docs/
│   ├── .nojekyll
│   └── index.html            # Pages 演示页，强制模拟模式
└── lab/
    ├── README.md             # 完整 Linux 操作手册与实现原理
    ├── requirements.txt      # Ryu / Eventlet / dnspython 固定版本
    ├── fix_ryu_wsgi.py        # 当前虚拟环境内的 Ryu 兼容修复
    ├── topology.json         # 指定 4×5 网格，链路顺序决定端口编号
    ├── topo20.py             # 创建交换机、主机、链路与静态 ARP
    ├── paths.py              # DFS、回溯、搜索预算
    ├── test_paths.py         # BFS / 小图穷举交叉验证与指定网格回归
    ├── test_demo_paths.py    # 可选 Node 检查：两份页面的全部主机对与 Python 一致
    ├── controller.py         # LLDP、主机发现、REST、双向流表、统计
    └── static/index.html     # 真实控制器页面，默认请求同源 API
```

仓库以 `controller.py` 作为完整运行入口。各步骤与实际代码的对应关系见 [手册第 14 节](https://github.com/WilliamWilson-1/mininet-ryu-topology-lab/blob/project1/lab/README.md#14-按代码理解实验原理)。

## 环境准备后的日常启动

以下只适用于**已完成手册安装与兼容修复**的 Ubuntu 22.04 / Python 3.10 环境。首次使用不要跳过安装步骤。

终端 A，启动控制器并保持运行：

```bash
cd ~/mininet-ryu-topology-lab/lab
source .venv/bin/activate
export PYTHONPATH="$PWD"
ryu-manager --observe-links --ofp-tcp-listen-port 6653 \
  --wsapi-host 127.0.0.1 --wsapi-port 8080 \
  controller.py ryu.topology.switches \
  ryu.app.rest_topology ryu.app.ofctl_rest
```

终端 B，创建网络并停留在 `mininet>`：

```bash
cd ~/mininet-ryu-topology-lab/lab
sudo mn -c
sudo /usr/bin/python3 topo20.py
```

终端 C，等待 `/api/topology` 显示 20 台交换机、20 台主机、31 条链路，然后计算、配置：

```bash
curl -sS 'http://127.0.0.1:8080/api/paths?src=h1&dst=h20' | jq
curl -sS -X POST http://127.0.0.1:8080/api/services \
  -H 'Content-Type: application/json' \
  -d '{"src":"h1","dst":"h20"}' | jq
```

终端 B 的 Mininet 提示符内测试：

```text
h1 ping -c 5 h20
```

打开 Linux 浏览器的 `http://127.0.0.1:8080/`，在“业务监测 → 每跳计数”查看双向累计计数。新建业务会显示“已配置 · 等待流量证据”；产生 ping 流量并等待采样后，才可能显示“各跳双向计数已验证”。

## 复现时应当知道

- 控制器监听 OpenFlow TCP 6653，页面与 REST 使用 TCP 8080；两者用途不同。
- Ryu 使用 `.venv`，Mininet 使用 apt 安装包所在的 `/usr/bin/python3`。不要用 `sudo ryu-manager` 绕过虚拟环境。
- 本仓库为 Python 3.10 选择 `eventlet==0.33.3`、`dnspython==2.2.1`，并提供 Ryu 4.34 的 WSGI 兼容脚本。旧的 Eventlet 0.30.2 会触发已知的 `TimeoutError` 属性错误。
- 只配置指定主机对，不做全网泛洪；未配置业务时 `pingall` 失败是预期现象。
- 页面绿色是各跳当前业务规则的近期采样中出现过双向正累计计数，不能代替端到端 ping，也不是瞬时带宽。
- 链路变化后业务标为 `stale` 并撤回；当前实现要求发现结果与 `topology.json` 完整一致，恢复链路后需要重新配置，不提供自动故障绕行。
- 每次重启实验应先退出旧 Mininet、停止旧 Ryu，再 `sudo mn -c`，避免旧流表与新控制器记录混用。

详细检查与常见问题：[验收清单](https://github.com/WilliamWilson-1/mininet-ryu-topology-lab/blob/project1/lab/README.md#12-实验验收与证据保存) · [排错](https://github.com/WilliamWilson-1/mininet-ryu-topology-lab/blob/project1/lab/README.md#15-常见问题逐项排查) · [REST 接口](https://github.com/WilliamWilson-1/mininet-ryu-topology-lab/blob/project1/lab/README.md#13-rest-接口说明)。

## 本地开发与验证

纯静态页面无需 Node 构建、npm 安装或 CDN：

```bash
python3 -m http.server 8081 --directory docs
```

访问 `http://127.0.0.1:8081/`，仍为演示模式。修改真实界面请编辑 `lab/static/index.html`；修改在线预览请同步修改 `docs/index.html`，并保留后者的 `sdn-mode=demo` 元标记。

算法测试可在没有 Mininet 的电脑上执行：

```bash
cd lab
python3 -m unittest -v test_paths.py
```

测试使用 BFS 验证最短路，以小图排列穷举验证最长路和简单路径数量，并核对指定网格的 7/19 跳与 976 条路径。**这些检查不等于 Linux/OVS 端到端验收**；实际交换机连接、Barrier、ping 和统计必须按实验手册在 Linux 中验证。

浏览器演示算法还提供可选一致性检查（需本机安装 Node；不影响网页使用）：在 `lab` 中执行 `python3 -m unittest -v test_demo_paths.py`，核对两份页面全部 380 个有向主机对的路径、跳数和路径数量，并以 BFS 独立核对最短跳数。未安装 Node 时该项会跳过。
