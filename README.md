# 拓扑实验室 · Mininet + Ryu

深蓝色 Liquid Glass 界面的 SDN 教学实验：20 台交换机与 20 台主机、拓扑发现、DFS 最短/最长简单路径、双向 IPv4 流表和每跳计数展示。

## 在线页面

GitHub Pages 发布 `docs/`，自动进入演示模式，明确标注模拟数据。网络配置操作禁用；GitHub Pages 不运行 Ryu 或 Mininet。

## 真实 Linux 实验

完整环境、启动命令与验收步骤见 [实验手册](lab/README.md)。

```bash
cd lab
# 按手册安装 Ubuntu/Python/Ryu/Mininet 依赖后
source .venv/bin/activate
export PYTHONPATH="$PWD"
ryu-manager --observe-links --ofp-tcp-listen-port 6653 \
  --wsapi-host 0.0.0.0 --wsapi-port 8080 \
  controller.py ryu.topology.switches \
  ryu.app.rest_topology ryu.app.ofctl_rest
# 另一终端
sudo /usr/bin/python3 topo20.py
```

随后访问控制器的 `http://127.0.0.1:8080/`，不带 `demo=1`。

## 页面功能

- 网络拓扑、路径分析、业务监测三个视图。
- 浅色/深色/跟随系统，深蓝强调色与减少透明效果。
- 胶囊分段支持点击、横向拖动与方向键/Home/End。
- 画布缩放、业务搜索/筛选、每跳计数详情和响应式布局。
- 原生对话框、键盘焦点、减少动效与强制配色回退。

## 开发预览

```bash
python3 -m http.server 8081 --directory docs
```

访问 `http://127.0.0.1:8081/`。纯 HTML/CSS/JavaScript，不需要构建或 CDN。

`lab/topology.json` 当前为 20 节点环加 4 条弦的演示拓扑，并非尚未提供的课程指定拓扑。最长路径不重复交换机；稠密图搜索超限时拒绝下发。

## 验证范围

DFS 已与 BFS/小图排列穷举交叉验证；前端已检查多种屏幕宽度、主题、键盘、拖动、过滤、详情、断线及模拟 API 合约。真实 Linux 网络仍需按手册验收。
