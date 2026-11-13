# Mininet + Ryu 拓扑实验 - 网络算法基础第 8 组

本分支 `project2-DLC` 实现 20 台 OpenFlow 交换机、20 台主机的 SDN 实验。LLDP 发现链路与两端端口，Dial 桶式 Dijkstra 计算并配置双向最短路，Kruskal 最小生成树承载一对多广播。深蓝色可视化页面展示拓扑、算法结果、业务和流表计数。

完整安装与操作流程见 [实验手册](lab/README.md)。原实验的代码和说明保存在 [project1 分支](https://github.com/WilliamWilson-1/mininet-ryu-topology-lab/tree/project1)。

## 页面与拓扑

- [在线演示](https://williamwilson-1.github.io/mininet-ryu-topology-lab/?demo=1) 支持在页面顶部切换四套拓扑，并选择主机计算最短路与广播树。
- 真实实验运行 Ryu 后打开 `http://127.0.0.1:8080/`，配置最短路和广播，并查看真实流表计数。
- 每套拓扑均有 20 台交换机和 20 台主机，提供 4×5 网格、弦环、双环互联和多园区互联四种预设。

演示算法在浏览器中执行。真实业务由 Ryu 下发流表后，通过 Mininet 的 ping、UDP 发包和抓包验证。

## 获取代码

```bash
git clone --branch project2-DLC --single-branch \
  https://github.com/WilliamWilson-1/mininet-ryu-topology-lab.git
cd mininet-ryu-topology-lab/lab
python3 topologies.py --list
python3 topologies.py --select grid
```

之后按 [实验手册](lab/README.md) 安装依赖、启动 Ryu 与 Mininet。

## 代码入口

| 文件 | 作用 |
| --- | --- |
| [lab/topo20.py](lab/topo20.py) | 创建选定的 Mininet 拓扑并连接远程控制器 |
| [lab/topologies.py](lab/topologies.py) | 列出、选择和校验拓扑 |
| [lab/controller.py](lab/controller.py) | LLDP 拓扑读取、主机发现、REST 接口、流表下发与计数 |
| [lab/paths.py](lab/paths.py) | Dial 循环桶 Dijkstra 最短路 |
| [lab/broadcast.py](lab/broadcast.py) | Kruskal 最小生成树及广播端口计划 |
| [lab/static/index.html](lab/static/index.html) | Ryu 提供的真实实验页面，支持 `?demo=1` |
| [docs/index.html](docs/index.html) | GitHub Pages 浏览器演示 |

## REST 接口

| 请求 | 作用 |
| --- | --- |
| `GET /api/topology` | 当前拓扑、交换机、主机、链路和端口 |
| `GET /api/paths?src=h1&dst=h20` | 计算 Dial 最短路 |
| `POST /api/services`，JSON 为 `{"src":"h1","dst":"h20"}` | 配置双向最短路 |
| `GET /api/services` | 单播业务及各跳双向计数 |
| `POST /api/broadcast`，JSON 为 `{"src":"h1"}` | 配置 Kruskal 广播树 |
| `GET /api/broadcast` | 广播树、端口规则和计数 |
| `GET /api/events` | 控制平面报文日志 |
| `GET /stats/flow/1` | 通过 `ryu.app.ofctl_rest` 读取 s1 的真实流表 |

默认网格中 h1→h20 为 7 跳、代价 7，安装正反向共 16 条单播规则。广播树有 19 条边，使用 20 条广播规则覆盖其余 19 台主机。跳数只统计交换机间链路。

## 测试与本地预览

```bash
cd lab
python3 -m unittest -v test_paths.py test_broadcast.py test_topologies.py test_demo_paths.py
```

算法测试独立核对最短距离，覆盖零权边和不同整数权重。拓扑测试覆盖四种预设的全部主机对及广播源。浏览器算法一致性测试需要 Node，未安装时自动跳过。

从仓库根目录启动演示预览。

```bash
python3 -m http.server 8766 --bind 127.0.0.1 --directory docs
```

打开 `http://127.0.0.1:8766/?demo=1`。
