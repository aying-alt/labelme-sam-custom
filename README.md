# labelme-with-segment-anything · 个人定制版

基于 [fry404006308/labelme-with-segment-anything](https://github.com/fry404006308/labelme-with-segment-anything) 的定制版本，上游为 [wkentaro/labelme](https://github.com/wkentaro/labelme)。

> **This is a modified version of labelme.** 本仓库自 2026-10 起在原项目基础上做了修改，
> 具体改动见下方「为什么要改」一节与 `git log`。原始代码版权归 Kentaro Wada 等原作者所有，
> 详见 [`LICENSE`](./LICENSE)。
>
> **本项目遵循 GPL-3.0**（见 `LICENSE`），修改部分同样以 GPL-3.0 发布，保留原作者版权声明。
> **仓库内不含任何标注数据、业务图片或标注文件**，仅包含代码。
> 上游原始 README 已保留为（英文文件名便于跨平台） [`README-upstream.md`](./README-upstream.md)。
>
> **这不是官方项目。** 本项目是与 [wkentaro/labelme](https://github.com/wkentaro/labelme)
> 及 [fry404006308/labelme-with-segment-anything](https://github.com/fry404006308/labelme-with-segment-anything)
> 均无隶属关系的第三方修改版，未获其背书；本项目特有的问题请提到**本仓库**，不要打扰上游作者。
> 第三方资源的著作权归各自所有者，来源见 [`NOTICE`](./NOTICE)。

---

## 为什么要改

用于图像掩膜（mask）标注。原版在实际长时间标注中存在四类明显问题：取消命名会崩溃、多边形边缘点不准、顶点疏密不可按规范调整、找图无序。本定制版针对这四点改造，并同步把模型换成精度更高的 HQ-SAM、适配显存较小的机器。

---

## 与原版的差异

| 文件 | 原 → 现（行） | 改动性质 |
|---|---|---|
| `labelme/widgets/canvas.py` | 1044 → 1742 | 主要改动集中于此 |
| `labelme/app.py` | 2117 → 2365 | 新增菜单与动作、重定义快捷键 |
| `labelme/shape.py` | 562 → 598 | 命中判定重写、视觉参数 |
| `labelme/widgets/label_list_widget.py` | 185 → 187 | 崩溃修复 |
| `labelme/config/default_config.yaml` | 122 → 112 | 新增配置项、快捷键重定义 |
| `labelme/sam_weight.py` | 新增 553 行 | 权重查找 / 多源下载 / 断点续传 / 完整性校验 |
| `start_custom_labelme.py` | 新增 358 行 | 自定义启动入口、启动后后台准备权重 |
| `download_model.py` | 新增 123 行 | 单独下载权重（`--check` / `--list` / `--model`） |
| `run_labelme.bat` | 新增 | Windows 启动器（多解释器探测 + 缺依赖点名） |
| `check_deps.py` | 新增 107 行 | 依赖自检，逐项报告缺失项并给出安装命令 |
| `requirements.txt` | 新增 | 运行依赖清单 |
| `NOTICE` | 新增 | 第三方资源与依赖的许可归属说明 |
| `setup.py` | 163 → 164 | 元数据修正：补 `python_requires=">=3.7"`、许可证标识符改 SPDX、去掉不支持的 3.5/3.6 声明 |
| `CITATION.cff` | 10 → 10 | 许可证标识符 `GPL-3` → `GPL-3.0-or-later`（原值不是合法 SPDX 标识符） |

**未收录的上游文件**：上游仓库里另有 5 个开发期间的实验备份，与功能无关，本仓库未包含：
`labelme/shape_1.0.py`、`labelme/shape_RETR_EXTERNAL.py`、`labelme/shape_RETR_LIST.py`、
`labelme/widgets/canvas_1.0.py`、`labelme/widgets/canvas_broken.py`。
除此之外上游的代码文件全部保留，没有删除任何功能实现。

---

## 一、缺陷修复

**1. 取消标签命名导致程序崩溃（修复）**

`label_list_widget.py` 的 `findItemByShape()` 在找不到对应形状时 `raise ValueError`。
在「标注完成 → 弹出命名框 → 取消 / 关闭」这条路径上，形状已从列表移除，后续按形状查找必然失败，
异常无人捕获，进程直接退出。

```python
# 原版
raise ValueError("cannot find shape: {}".format(shape))

# 现版
print(f"【警告】未找到Shape对象 {shape} 对应的标签列表项（不影响程序运行）")
return None
```

**2. 多边形边缘点击命中错误（修复）**

原实现调用 `labelme.utils.distancetoline()`，算的是点到**直线**的距离，点击落在某条边的
**延长线**上也会被判定为命中，导致选错边或选不到边。

现改为按投影参数 `t ∈ [0, 1]` 自行计算点到**线段**的垂距，并将命中阈值收紧到 `epsilon / 3`。

**3. 顶点操作手感（调整）**

- 顶点命中半径 `4 → 2`，点击更精准
- 悬停顶点颜色 `白色 → 黑色`，浅色图像上更易辨认

**4. 快捷键配置被误写成列表（修复）**

`default_config.yaml` 中 `create_polygon` / `edit_polygon` 被写成了 `[Ctrl+N, 1]`、`[Ctrl+J, 2]`。
YAML 会把 `1`、`2` 解析成**整数**，`setShortcuts()` 再把它当成键码转换成 `\x01`，
于是 `Ctrl+N` 之外又额外绑定了 `Ctrl+A`，两个功能抢同一个键。

现统一改为单个字符串（`create_polygon: Ctrl+N`、`edit_polygon: Ctrl+J`），并补齐被清空的原版按键
（`close: Ctrl+W`、`quit: Ctrl+Q` 等）。

> 另外，`Ctrl+N` 改为**始终可响应**：未打开图片时不再静默无反应，而是在状态栏提示
> 「请先打开一张图片（Ctrl+O），再按 Ctrl+N 创建多边形」；打开图片后即进入多边形创建模式。

---

## 二、模型升级：SAM → HQ-SAM

- **三档权重**：`vit_b / vit_l / vit_h`，按显存选择（8GB 显卡可用 `vit_b` / `vit_l`）
- **统一 float32**：模型参数、`set_image` 输入、`predictor.features` 三处强制 float32，解决 half/float 混用报错
- **权重获取**：先在本地找（`models/` → `%LOCALAPPDATA%` 缓存 → appdirs 缓存），都没有才联网；
  下载按 `hf-mirror.com` → `huggingface.co` 依次尝试，带**百分比进度、断点续传、完整性校验**，
  实现集中在 `labelme/sam_weight.py`
- **设备自适应**：`torch.cuda.is_available()` 为真用 GPU，否则回落 CPU
- **推理开销**：`with torch.no_grad()` 包裹图像编码与预测；加载后 `torch.cuda.empty_cache()` + `gc.collect()`
- **掩膜后处理**：`dilate(2×2)` + `MORPH_CLOSE(5×5, 2 次)` 填补掩膜缝隙
- **预处理**：缩放系数下限 0.5，插值改 `INTER_LANCZOS4`，兼容灰度与四通道图

---

## 三、交互定制

- **顶点密度可调**：快捷键实时增减多边形拟合精度 ε，画布右上角显示当前值
- **已标注多边形可重算顶点**：把选中多边形按当前 ε 重新拟合，标完还能改疏密
- **框选批量删顶点**：拖矩形框住多个顶点，一次删除；删后不足 3 点的形状自动跳过
- **矩形自由框选**多个形状
- **顶点吸附倍率**：`Ctrl + 点击` 支持 1 / 2 / 3 / 5 倍 epsilon
- **顶点高亮大小**：小 / 中 / 大
- **图片排序**：按名称（自然排序）/ 文件大小 / 修改日期
- **双击不再闭合多边形**（`double_click: null`），避免误操作
- **原版快捷键全部保留**：`Ctrl+W` / `Ctrl+Q` / `Ctrl+N` / `Ctrl+J` / `Ctrl+Z` / `Delete` / `A`·`D` 翻图等与上游一致，自定义键均为**新增**，不覆盖任何人原有的操作习惯

### 快捷键

| 按键 | 功能 | 按键 | 功能 |
|---|---|---|---|
| `1` | 普通多边形模式 | `6` | ε 增大（顶点变少） |
| `2` | 编辑模式 | `7` | ε 减小（顶点变多） |
| `` ` `` | SAM 多边形模式 | `0` | 重算选中多边形的顶点密度 |
| `Ctrl` + `` ` `` | SAM 精准矩形模式 | `4` | 删除选中顶点 / 框选顶点 |
| `3` | SAM 模式下确认生成 | `5` | 合并两个选中多边形（见已知问题） |
| `S`（绘制中） | 开启顶点吸附 | `Alt`（绘制中） | 临时关闭吸附 |
| `方向键`（编辑中） | 微调形状位置 | | |

---

## 四、启动入口

本仓库有三个入口，跑的是同一份 `labelme/` 代码，区别只在外层做了多少「照顾」：

| 入口 | 是否原版行为 | 什么时候检查权重 | 下载时界面 | 顶窗口 / 单实例 |
|---|---|---|---|---|
| `python -m labelme` | **是**，走 `labelme/__main__.py` | 第一次切到 SAM 模式 | **卡住**（同步下载） | 无，原版什么样就什么样 |
| `python start_custom_labelme.py` | 否，多一层壳 | 窗口一出现，后台线程 | 照常可用 | 有 |
| `run_labelme.bat` | 否 | 同上一行 | 照常可用 | 有（内部调上一行） |

**排查问题优先用 `python -m labelme`**：链路上没有中间层，缺哪个依赖、哪个配置写错、
权重从哪下的，全部原样打在控制台。双击 bat 万一闪退，你连错误都看不到。

三条路**共用同一份配置和权重**（`%USERPROFILE%\.labelmerc` + `models\`），
换入口不会换配置；区别只有上表那几项。`--config` 参数只有 `-m labelme` 认。

`start_custom_labelme.py` 额外做的事：

- 把项目目录插入 `sys.path[0]`，确保运行的是本仓库代码，而非 `site-packages` 里 pip 装过的其它 labelme
- 关闭 Qt 窗口状态记忆、默认软件 OpenGL，避免部分驱动下切换窗口后画面变黑或丢失
- **强制恢复正常窗口状态并置于前台**：
  两种「窗口没出现」的情况都被处理了——
  - 从终端 / 自动化脚本启动时，Windows 会把 `STARTUPINFO` 里的「最小化显示」传给子进程，
    窗口被建在 `(-21333, -21333)` 这种屏幕外坐标上；
  - 即便窗口位置正常，也会被 Windows 的**前台锁**（foreground lock）拦下来，被启动它的
    终端窗口盖住，`SetForegroundWindow` 静默失败。

  本版先清掉 `WindowMinimized` 再 `showNormal()`，随后用 Win32 分三次（120 / 600 / 1500 ms）
  尝试激活：常规 `SetForegroundWindow` → 失败则**「先最小化再恢复」**（实测这是唯一能绕过
  前台锁的方式，`AttachThreadInput` 也不行）→ 仍失败则 `FlashWindow` 闪任务栏。
  最后把窗口摆到主屏可用区域中央。
- **单实例**：若已有 labelme 窗口在运行，直接把它恢复并激活，不再堆新进程
  （反复双击不会积一堆看不见的进程）。要同时开多个窗口，设 `LABELME_ALLOW_MULTI=1`。
- **启动后自动准备模型权重**（**原版没有这一条，是本版给脚本 / bat 入口加的便利**；
  `python -m labelme` 完全不触发它，权重仍然只在切 SAM 时才处理）：窗口一显示就在后台线程
  检查 HQ-SAM 权重，缺失则自动下载，进度实时打印到控制台；下载期间界面照常可用。
  拿不到权重时只把 SAM 模式降级为普通多边形（弹一次提示），不会让程序崩溃。
  设 `LABELME_NO_AUTO_DOWNLOAD=1` 可关掉自动下载。
- 未捕获异常改为「打印完整堆栈 + 弹窗提示」，不再静默退出
- 默认不置顶（需要时设 `LABELME_ONTOP=1`），避免窗口悬浮却拿不到键盘焦点
- 支持直接传图片路径：`python start_custom_labelme.py a.jpg`

Windows 下双击 `run_labelme.bat`：依次尝试 `%LABELME_PYTHON%` → `python_path.txt` → `.venv`/`venv`/`env` → `python`/`python3`/`py -3`，
取**第一个能真正 import 全部依赖**的解释器；全部失败时逐项报告缺哪个包。任何一步失败都会打印原因并 `pause`，窗口不会一闪而过。

---

## 五、已知问题

**`5` 合并多边形不可用（代码保留，未在流程中启用）**

`Canvas._merge_adjacent_polygons()` 对两个多边形的点集求 `cv2.convexHull` **凸包**，
凹形区域会被填平、相邻但不连通的部分会被连成一片，与掩膜标注要求的精确轮廓相反。

正确做法应为多边形布尔并集：`shapely.ops.unary_union` 合并后取外环，既保留凹形轮廓，也能正确处理重叠。

---

## 六、安装与运行

**不需要专门为本项目创建虚拟环境。** 用系统 Python 也行，用你自己已有的虚拟环境也行 ——
虚拟环境只解决「依赖隔离」，不解决「依赖是否存在」。关键是**那个解释器里装没装下面这些包**。

### 0. 第一次使用：按顺序走完这 9 步

从下载仓库到能标注，只有下面这些动作。每一步都写了「**怎么确认这步成了**」和「**失败了怎么办**」，
卡住了最后还有一张对照表。

| 步 | 做什么 | 耗时 | 成功的标志 |
|---|---|---|---|
| 0 | 把代码拿到本地 | 1 分钟 | 目录里能看到 `run_labelme.bat` 和 `labelme\` 文件夹 |
| 1 | 装 Python（已装可跳） | 5 分钟 | `python --version` 有输出 |
| 2 | 建虚拟环境（可选，推荐） | 1 分钟 | 提示符前出现 `(.venv)` |
| 3 | 装依赖 | 5–20 分钟 | `Successfully installed ...` |
| 4 | 依赖自检 | 10 秒 | 13 项全 `[ OK ]` |
| 5 | 启动 | 30 秒 | 窗口出现 |
| 6 | 等模型自动下载（只用手工标注可跳过） | 3–20 分钟 | 日志出现 `[模型] 下载完成` |
| 7 | 没下成功时手动补 | 看带宽 | `models\sam_hq_vit_b.pth` 存在且大小对（默认档位是 vit_b） |
| 8 | 验证能用 | 2 分钟 | `Ctrl+N` 能打点，SAM 能分割 |

---

#### 第 0 步 · 把代码拿到本地

**方式 A：git clone**（推荐，以后能 `git pull` 更新）

```bat
cd /d "%USERPROFILE%\Desktop"
git clone <本仓库地址> labelme-sam-custom
cd labelme-sam-custom
```

**方式 B：下载 ZIP**（没装 git 就用这个）

仓库页面 → 绿色 `Code` 按钮 → `Download ZIP` → 解压到任意目录
（**解压路径可以有中文和空格**，已实测支持）。

**方式 C：已经拿到文件夹了** → 直接 `cd` 进去，跳过这步。

**成功标志**：当前目录下能 `dir` 到这些：

```text
run_labelme.bat
start_custom_labelme.py
check_deps.py
download_model.py
requirements.txt
labelme\            <- 一定要有这个文件夹
```

> **必须在这一层执行命令。** 后面所有 `python -m labelme` 都依赖「当前目录里有个 `labelme\`
> 文件夹」——不在这一层，`-m` 找到的是你 `pip` 装过的官方 labelme，界面里根本没有 SAM 菜单组。
>
> **别 `pip install .`**。本项目的包名和官方一样都叫 `labelme`，装进去会把你已有的官方版
> 覆盖掉，而且版本号还显示成官方的。**源码目录直接跑就行，不需要安装。**

---

#### 第 1 步 · 装 Python

**已经装过就跳过这一步**，直接 `python --version` 看有没有输出。

1. 打开 <https://www.python.org/downloads/windows/>
2. 选 **Python 3.10.x** 或 **3.11.x** 的 `Windows installer (64-bit)`
3. 安装第一屏**必须勾选 `Add python.exe to PATH`**，再点 `Install Now`
   （这个勾不选，后面所有 `python` 命令都会提示“不是内部或外部命令”）
4. 装完**新开**一个命令行窗口（已经开着的窗口读不到新的 PATH），执行：

```bat
python --version
where python
```

**成功标志**：先输出 `Python 3.10.11` 这类版本号，再输出解释器的完整路径，例如

```text
Python 3.10.11
C:\Users\你的用户名\AppData\Local\Programs\Python\Python310\python.exe
```

**没成功怎么办**

| 现象 | 原因 | 处理 |
|---|---|---|
| `'python' 不是内部或外部命令` | 安装时没勾 PATH | 重跑安装包 → `Modify` → 勾上 `Add Python to environment variables`；或临时改用 `py -3 --version` |
| 打开的是微软商店 | Windows 的 `python` 别名占位符 | 设置 → 应用 → 高级应用设置 → 应用执行别名 → 关掉 `python.exe` / `python3.exe` |
| 版本是 3.12 / 3.13 | 太新，个别包还没有预编译 wheel | 也能试，但撞到“需要编译”就换成 3.10/3.11（可与新版共存，用 `py -3.10` 指定） |

> **为什么推荐 3.10 / 3.11**：PyQt5、opencv-python、torch 的 Windows 预编译 wheel 在这两个版本上最齐全。
> 本项目实测可用的环境就是 3.10。

---

#### 第 2 步 · 建虚拟环境（可选，推荐）

> ⚠️ **先别急着敲 `python -m venv`。** 很多人电脑上装了好几个 Python，
> 直接敲 `python` 用的可能是 3.6 这种老版本（本项目要求 **3.7 以上，推荐 3.10 / 3.11**）。
> 用老版本建出来的虚拟环境，后面装依赖能装上，但程序起不来。

先看清楚机器上有哪些 Python：

```bat
py -0p
```

输出类似（`*` 是默认那个）：

```text
 -V:3.11 *        C:\Users\you\AppData\Local\Programs\Python\Python311\python.exe
 -V:3.10          C:\Users\you\AppData\Local\Programs\Python\Python310\python.exe
 -V:3.6           C:\Program Files\Python36\python.exe
```

**挑一个 ≥ 3.7 的版本来建环境**（下面以 3.11 为例，按你实际有的版本改数字）：

```bat
cd /d "C:\你的路径\labelme-sam-custom"
py -3.11 -m venv .venv
```

> 没有 `py` 命令（或者 `py -0p` 报错），就直接用完整路径建：
>
> ```bat
> "C:\Users\you\AppData\Local\Programs\Python\Python311\python.exe" -m venv .venv
> ```

建完**先验证这个环境里的 Python 版本对不对**，再往下走：

```bat
.venv\Scripts\python.exe -c "import sys; print(sys.version); print(sys.executable)"
```

**成功标志**：输出的版本是 3.7 以上，路径指向本项目的 `.venv\Scripts\python.exe`。
如果版本还是 3.6，**删掉 `.venv` 目录重来**，换成正确的版本。

不想激活也能用，后面所有命令直接写 `.venv\Scripts\python.exe` 的全路径即可（**推荐这样，不容易串环境**）。
想激活的话：

```bat
.venv\Scripts\activate
```

激活后提示符前面会多出 `(.venv)`。

Linux / macOS：

```bash
cd labelme-sam-custom
python3 --version          # 确认 >= 3.7
python3 -m venv .venv
.venv/bin/python -c "import sys; print(sys.version)"
```

> `run_labelme.bat` 也会优先用 `.venv`（候选顺序第 3 位），即使不激活也能找到。

---

#### 第 3 步 · 装依赖

**用虚拟环境里的 python 来装**，别用裸 `python`——那样可能装进系统 Python：

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

国内网络慢，加清华镜像：

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**成功标志**：最后一行是 `Successfully installed ...`，并且

```bat
.venv\Scripts\python.exe -m pip list
```

能看到 `PyQt5`、`torch`、`opencv-python-headless`、`segment-anything-hq`。

> 💡 `requirements.txt` 里的注释全是英文并刻意保持纯 ASCII。这不是崇洋，
> 是因为中文 Windows 上 pip 会按 GBK 去读这个文件，只要里面有中文就直接
> `UnicodeDecodeError` 崩掉，一个包都装不上。**请不要往这个文件里加中文注释。**

**这一步大概率会遇到的两种情况**

1. **`torch` 下载特别慢或超时**（它是这里面最大的包，CPU 版约 200 MB，CUDA 版 2 GB+）。
   单独装：

   ```bat
   python -m pip install torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

2. **想要 GPU 加速**：PyPI 上的 `torch` 在 Windows 默认是 CPU 版。按
   [PyTorch 官网](https://pytorch.org/get-started/locally/) 选你的 CUDA 版本生成命令单独装，例如：

   ```bat
   python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
   ```

   装完回来再跑一次 `pip install -r requirements.txt`，已经装好的 torch 不会被重装。

> 没有独立显卡、只想跑通流程：装 CPU 版就行，SAM 也能用，只是慢一些。
>
> `segment-anything-hq` 是纯 Python 包（约 52 KB），不需要 C++ 编译工具，不会卡在 build 阶段。

---

#### 第 4 步 · 依赖自检

```bat
python check_deps.py
```

它把 13 项依赖逐个标出来：

```text
  [ OK ] PyQt5             5.15.9       图形界面框架（主窗口、画布）
  [ OK ] torch             2.0.1+cu117  HQ-SAM 推理后端
  [ OK ] cv2               4.8.0        掩膜形态学、多边形拟合
  ...
全部依赖就绪
```

**成功标志**：13 项全 `[ OK ]`，末行 `全部依赖就绪`，退出码 0。

缺了哪项它会直接点名，并给出一条**已经带上当前解释器绝对路径**的安装命令，
直接复制就能装到同一个 Python 上，不会再出现“装了但程序还是说找不到”的情况。
只想要退出码（写脚本用）：`python check_deps.py --quiet`。

---

#### 第 5 步 · 启动

> **先花 5 秒确认你敲的 `python` 是哪个。** 明明装过依赖却报 `ModuleNotFoundError`，
> 九成是命令行里的 `python` 跟你装依赖的那个不是同一个（PATH 里排前面的可能是
> Python 3.6 这种老版本，而依赖装在 3.10 的 venv 里）。两条命令就能看出来：
>
> ```bat
> python -V
> python -c "import sys;print(sys.executable)"
> ```
>
> 打出来的路径不是你装依赖的那个 → 用完整路径启动（见方式 B/C），
> 或者直接双击 `run_labelme.bat`，它会自己挑对解释器。

**推荐命令行 + 原版入口**（在**项目根目录**执行，也就是含 `labelme\` 文件夹的那一层）：

```bat
python -m labelme
```

走的是 `labelme/__main__.py`，和原版完全一致。最大的好处是**出问题一定有字**：
缺依赖、配置项写错、权重下载失败，原因全部原样打在控制台，而不是弹个框就没了。

可以直接带图或目录：

```bat
python -m labelme D:\images\a.jpg
python -m labelme D:\images
```

> **必须在项目根目录执行。** `python -m labelme` 优先用**当前目录**的 `labelme` 包；
> `cd` 到别处再执行，找到的是 `pip` 装过的官方 labelme，你改的东西全不生效。

**正常启动时控制台什么都没有**，窗口直接出现。反过来也成立：
**只要控制台有字，就是有事要你看。**

其他两个入口（想要「顶窗口 + 不堆进程 + 启动就预热权重」时用）：

```bat
python start_custom_labelme.py
```

```bat
run_labelme.bat
```

**成功标志**：弹出 labelme 主窗口。

`run_labelme.bat` 会先打印三行探测信息再出窗口（`start_custom_labelme.py` 没有这三行）：

```text
[labelme] looking for a usable Python ...
[labelme] interpreter: C:\Python310\python.exe
[labelme] starting ...
```

**这三行之后控制台会一直停着，这是正常的** —— 它在等窗口关闭，不是卡住。

> 窗口如果被启动它的终端挡住：`-m labelme` 是原版行为，**不会**自动置前，看任务栏或
> `Alt+Tab`；`start_custom_labelme.py` / bat 会自动把它顶到最前（绕过 Windows 前台锁，
> 手段是「最小化再恢复」）。后两个入口还带单实例：重复启动不堆进程，已开着的窗口会被
> 恢复并置前。

---

#### 第 6 步 · 模型会自动下载（看懂日志）

**先分清「什么时候检查」——这取决于你用哪个入口，两种都保留着：**

| 启动方式 | 检查 / 下载时机 | 下载时界面 |
|---|---|---|
| `python -m labelme` | **第一次切到 SAM 模式**（工具栏 `Polygon (SAM)` 或 `Rectangle (SAM)`）。这就是原版行为，没改动 | **卡住**：下载在界面线程里同步跑，2.4 GB 下完前窗口是无响应的，但控制台日志一直在走 |
| `start_custom_labelme.py` / `run_labelme.bat` | 窗口一出现就开**后台线程**，不等你用 SAM | 照常标注，下完状态栏会提示 |

两条路共用同一套逻辑（`labelme/sam_weight.py`）：查找顺序、断点续传、多源切换、
大小校验完全一致，区别只在**谁来触发**。

> 上表**第一行才是原版行为**。源项目的下载代码就写在 `canvas.py` 的 `loadSamPredictor()`
> 里（`torch.hub.download_url_to_file`，单源、没有百分比进度、断了从头下）；
> 第二行的「启动就预热」是本版给 bat / 脚本入口额外加的，**不影响 `-m labelme`**。

> **所以用 `-m labelme` 时别急着点 SAM。** 第一次就这么点会白卡几分钟。
> 先单独把权重下好再启动，最省事：
>
> ```bat
> python download_model.py
> ```

**权重下好之后，用起来就是全自动的，不用点任何按钮。** 有壳入口的日志长这样：

- **已经有权重** → 只打印一行，立刻可用
- **没有权重** → 后台开始下载，窗口同时就能正常标注

下载日志长这样（真实输出格式，`[模型]` 是本项目加的）。**下面是 `vit_h` 档位的原始日志**，
默认档位已改为 `vit_b`，把文件名里的 `vit_h` 换成 `vit_b`、大小换成约 362 MB 就是默认情况下的样子：

```text
[模型] 检查 HQ-SAM 权重（档位 vit_h）...
[模型] 未找到 HQ-SAM 权重: sam_hq_vit_h.pth
[模型] 档位: vit_h  (vit_b / vit_h / vit_l)
[模型] 需要下载约 2.4 GB
[模型] 保存到: C:\你的路径\labelme-sam-custom\models\sam_hq_vit_h.pth
==============================================================
[模型] 尝试下载源: https://hf-mirror.com/lkeab/hq-sam/resolve/main/sam_hq_vit_h.pth
[模型] 已下载 512.0 MB / 2.4 GB  (20.8%)  8.4 MB/s  剩余 2 分 41 秒
```

那一行进度会**原地刷新**，数字一直往前走：已下载量 / 总量、百分比、当前速度、预计剩余时间。
下完会补一行收尾：

```text
[模型] 下载完成: 2.4 GB  (4 分 52 秒)
[模型] 已保存到: C:\你的路径\labelme-sam-custom\models\sam_hq_vit_h.pth
```

> **如果控制台输出被重定向到了文件**（不是终端窗口），进度不会原地刷新，
> 而是每 5% 打一整行，方便事后查：
>
> ```text
> [模型] 5%  122.9 MB / 2.4 GB  8.3 MB/s
> [模型] 10%  245.8 MB / 2.4 GB  8.5 MB/s
> ```

**几个设计上的细节，遇到怪现象时有用**

| 情况 | 程序的行为 |
|---|---|
| 下载中断 / 关了窗口 | 已经下到的部分留在 `sam_hq_vit_h.pth.part`，下次启动**从断点续传**，不会从 0 开始 |
| 日志出现 `发现未完成的下载，从 xxx 处续传` | 正常，说明断点续传生效了 |
| 日志出现 `服务器不支持续传，重新开始下载` | 正常，那个源没开 Range 支持，会从头下 |
| 第一个源连不上 | 自动换下一个源重试（默认先 `hf-mirror.com` 镜像，再 `huggingface.co` 官方） |
| 下载完但文件偏小 | 判定为不完整，删掉重试下一个源，不会拿残缺文件去加载 |
| 不想让它自动下 | 设 `LABELME_NO_AUTO_DOWNLOAD=1` 再启动。**两个入口都认**这个开关，缺权重时会打印「跳过自动下载」并列出该放哪；只想手工标注时很有用 |
| 只用手工标注 | 完全不用管权重，`Ctrl+N` 手画多边形和 SAM 一点关系都没有 |
| 速度只有几十 KB/s，剩余时间几小时 | 链路问题，不是程序问题 | 换 `vit_b`（362 MB）先跑通；或者按第 7 步的方式 2 用浏览器/下载工具下，通常比 Python 走代理快得多 |

> **怎么判断速度是不是正常**：进度行里的 `剩余 x 分 x 秒` 是按当前速度实时估算的。
> 如果它一直在涨、或者百分比不动，说明链路太慢，直接换第 7 步的手动方式更快。

**三个档位（用哪个由配置项 `sam.weights` 决定，默认 `vit_b`）**

> 默认给 `vit_b` 不是因为它最好，而是因为它**只有 362 MB**，首次启动几秒到一分钟就下完，
> 8 GB 显存也放得下。确认流程跑通后，再按下面的办法换成 `vit_l` 或 `vit_h`。

| 档位 | 文件名 | 大小 | 适合 |
|---|---|---|---|
| `vit_b` | `sam_hq_vit_b.pth` | 379,335,069 字节（约 362 MB） | 显存 6–8 GB / 想快点跑通 |
| `vit_l` | `sam_hq_vit_l.pth` | 1,254,865,805 字节（约 1.2 GB） | 精度与显存折中 |
| `vit_h` | `sam_hq_vit_h.pth` | 2,570,940,653 字节（约 2.4 GB） | 精度最高，显存要求也最高 |

##### 怎么换档位（不用改代码，改配置就行）

**但得改对文件。** labelme 的配置是三层叠加，后面的覆盖前面的：

| 优先级 | 位置 | 说明 |
|---|---|---|
| 1（最低） | `<项目根>\labelme\config\default_config.yaml` | 仓库里的出厂默认值 |
| 2 | `C:\Users\<你的用户名>\.labelmerc` | **第一次运行会自动从上一行复制一份**，之后一直读它 |
| 3（最高） | 命令行 `--config` 参数 | 只对本次运行生效 |

> **最常见的坑：改了项目里的 yaml 却没反应。**
> 只要 `%USERPROFILE%\.labelmerc` 存在（第一次启动就会自动生成），
> 项目里那份 `default_config.yaml` 就被它整个盖掉了。启动一看还是 `vit_h`，原因在这。

**做法 1：临时切一次，不碰任何文件（推荐先这样验证）**

```bat
python -m labelme --config "sam: {weights: vit_b}"
```

已实测可覆盖成功，一行搞定。想同时改显存设备也行：

```bat
python -m labelme --config "{sam: {weights: vit_b, device: cpu}}"
```

`start_custom_labelme.py` 不解析 `--config`，要用它就得按做法 2 写进文件。

**做法 2：永久改，动用户配置**

```bat
notepad %USERPROFILE%\.labelmerc
```

找到 `sam:` 这一段，改 `weights`：

```yaml
sam:
  weights: vit_b        # 原来是 vit_h；可选 vit_b / vit_l / vit_h
  maxside: 1280
  approxpoly_epsilon: 1
  device: cuda          # 没显卡或显存不够就写 cpu
```

**做法 3：全新环境**（还没启动过、没有 `.labelmerc`）才可以直接改项目里的
`labelme/config/default_config.yaml`，下次启动会自动复制过去。

**改完档位一定要下对应权重**，否则程序会去下新的那个：

```bat
python download_model.py --model vit_b
python download_model.py --check
```

`--check` 输出的第一行就是**当前配置的档位**，报问题时先看这行对不对：

```text
模型档位: vit_b    文件: sam_hq_vit_b.pth
```

**换档后旧权重要不要删？** 不用删。三个 `.pth` 可以在 `models\` 里共存（约 4 GB），
程序只加载当前配置的那一个。磁盘紧张时删掉不用的档即可。

**切到 SAM 之后要等多久（实测，`vit_h` 2.4 GB）**

| 硬件 | 加载权重到能用 | 之后每张图编码 | 说明 |
|---|---|---|---|
| NVIDIA 独显（CUDA） | 20–50 秒 | 1–3 秒 | 显卡越好越快 |
| 只有 CPU | 约 50 秒 | 约 27 秒 / 张 | 能用，但一张图要等半分钟 |

纯 CPU 也不会崩：程序检测到 `torch.cuda.is_available()` 为 `False` 会自动回落到 CPU，
只是慢。**这段时间界面没有响应是正常的**（`-m labelme` 是同步加载），不要以为死机，
更不要反复点——重复触发会让它重复加载。

---

#### 第 7 步 · 没自动下载怎么办

先看它停在哪一步：

- **日志里根本没有 `[模型]` 开头的行** → 说明启动脚本没跑到检查这一步，
  可能是依赖缺失时提前退出了。翻回第 4 步跑 `python check_deps.py`。
- **只打了 `检查 HQ-SAM 权重` 就没了** → 说明已经找到权重（正常），
  或者进程被杀了。用 `python download_model.py --check` 确认。
- **打了 `尝试下载源` 然后失败** → 网络问题，往下走。

程序会把失败原因和**手动方案**一起打印出来，大致是这样：

```text
==============================================================
HQ-SAM 权重自动下载失败
==============================================================
已尝试的下载源及失败原因：
  - https://hf-mirror.com/lkeab/hq-sam/resolve/main/sam_hq_vit_h.pth
      <urlopen error [Errno 11001] getaddrinfo failed>
  - https://huggingface.co/lkeab/hq-sam/resolve/main/sam_hq_vit_h.pth
      <urlopen error [Errno 11001] getaddrinfo failed>

不影响纯手工标注：不装权重也能画多边形，只是用不了 SAM 半自动。
```

**五种手动补下的方式（任选一种）**

**方式 1：换个网络再来一次（最省事）**

```bat
python download_model.py
```

单独下当前配置的档位，进度条和自动下载时一模一样。也可以指定档位：

```bat
python download_model.py --model vit_b
```

其他常用参数：

```bat
python download_model.py --check      # 只检查有没有、放在哪，不下载
python download_model.py --list       # 列出三个档位和大小
python download_model.py --quiet      # 不打印进度（写日志用）
```

**方式 2：浏览器下载，手动放进目录**

1. 浏览器打开其中一个地址（`vit_h` 为例，换档位就换文件名）：

   ```text
   https://hf-mirror.com/lkeab/hq-sam/resolve/main/sam_hq_vit_h.pth
   ```

   官方备用地址：

   ```text
   https://huggingface.co/lkeab/hq-sam/resolve/main/sam_hq_vit_h.pth
   ```

2. 把下好的文件**改名成** `sam_hq_vit_h.pth`（浏览器有时会加 `(1)` 后缀）
3. 放到项目根目录的 `models\` 文件夹里（没有就新建）：

   ```text
   labelme-sam-custom\
   └── models\
       └── sam_hq_vit_h.pth          ← 放这里
   ```

4. `python download_model.py --check` 确认，然后重启 labelme

**方式 3：命令行下载（Windows PowerShell）**

```powershell
cd "C:\你的路径\labelme-sam-custom"
New-Item -ItemType Directory -Force -Path models | Out-Null
curl.exe -L "https://hf-mirror.com/lkeab/hq-sam/resolve/main/sam_hq_vit_h.pth" -o "models\sam_hq_vit_h.pth"
```

CMD 下把 `curl.exe -L` 换成 `curl -L` 即可；`curl.exe` 是 Win10 1803+ 自带的，不用另装。

**方式 4：从官方仓库找链接**

- 代码仓库：<https://github.com/SysCV/sam-hq>（*Segment Anything in High Quality*, NeurIPS 2023）
- 权重页面：<https://huggingface.co/lkeab/hq-sam/tree/main>

**方式 5：让 AI 直接给你能下的直链**

官方页面打不开、或者不知道该点哪个的时候，把下面这段整段复制给任意 AI
（本项目配套的助手也行），它会回你 1–3 条能直接下到 `.pth` 的地址：

```text
我要下载 HQ-SAM 官方权重，档位 vit_h，对应文件 sam_hq_vit_h.pth（约 2.4 GB）。
请给我 1-3 个可以直接下载到 .pth 文件本身的完整 URL
（不要给需要再点一层按钮的页面），并注明哪条是官方、哪条是镜像。
```

拿到链接后不用管它从哪来的，**只做三件事**：

1. 文件**改名成** `sam_hq_vit_h.pth`（浏览器常会加 `(1)` 后缀，必须去掉）
2. 放进项目的 `models\` 文件夹（没有就新建）：

   ```text
   labelme-sam-custom\
   └── models\
       └── sam_hq_vit_h.pth          ← 必须是这个名字
   ```

3. `python download_model.py --check` 看到 `已就绪` 就成立，重启 labelme

> **别随手用网盘里的「SAM 权重」**。`.pth` 是 pickle，加载时可以执行任意代码，
> 来路不明的权重等于把电脑交出去。只认 `huggingface.co` / `hf-mirror.com` 的
> `lkeab/hq-sam` 仓库，或 `github.com/SysCV/sam-hq` 给出的地址。

**放好后怎么确认真的生效**

```bat
python download_model.py --check
```

正常输出：

```text
模型档位: vit_h    文件: sam_hq_vit_h.pth
状态: 已就绪 -> C:\你的路径\labelme-sam-custom\models\sam_hq_vit_h.pth
    C:\你的路径\labelme-sam-custom\models\sam_hq_vit_h.pth    [已就绪（2.4 GB）]
结论: 可用 -> C:\你的路径\labelme-sam-custom\models\sam_hq_vit_h.pth
```

如果显示 `[存在但只有 800.0 MB，不完整]`，说明是上次没下完的残骸 —— 删掉重下。

**权重放在哪，程序按这个顺序找**

1. 环境变量 `LABELME_MODEL_DIR` 指定的目录（想放别处时用）
2. **`<项目根>\models\`** ← README 一直让你放这里
3. `%LOCALAPPDATA%\labelme\labelme\Cache\`
4. `appdirs` 的 `user_cache_dir("labelme")`
5. 都没有 → 自动下载（存到第 2 项）

任何一个位置有完整文件就直接用，不会再触发下载。

---

#### 第 8 步 · 验证能用

1. `Ctrl+O` 打开一张图 —— 图片显示在画布上
2. `Ctrl+N` —— 进入多边形绘制状态，鼠标左键开始打点
3. 画完按 `Enter` —— 弹出标签输入框，输入类别名回车，左侧列表出现该形状
4. 切到 SAM 模式（工具栏 `Polygon (SAM)`）→ 在图上点一下 —— 自动生成贴合物体的多边形

> 第 4 条前先确认权重在不在：`python download_model.py --check`。
> 用 `-m labelme` 启动、权重又没下过的话，点下去会**当场开始下载并把窗口卡住**，
> 别误判成死机 —— 切回控制台能看到进度在走。

第 4 条能出结果，说明权重和 torch 都正常；1–3 条正常但第 4 条不行，说明只是 SAM 没配好，
纯手工标注不受影响。此时如果权重确实缺失，切 SAM 模式会弹一次提示并**自动退回普通多边形**，
不会让程序崩掉。

---

#### 卡住了对照这张表

| 现象 | 真实原因 | 处理 |
|---|---|---|
| `'python' 不是内部或外部命令` | 装 Python 时没勾 PATH | 见第 1 步的表格 |
| `No module named 'PyQt5'`（但 pip 说已装） | 装到了**另一个** Python | `python -c "import sys;print(sys.executable)"` 看是哪个，再用 `同一个.exe -m pip install ...` |
| `No module named 'qtpy'` | 同上；而且这个 `python` 很可能还是 3.6/3.7 老版本 —— labelme 5.x 要求 **Python ≥ 3.7** | 先 `python -V` + `python -c "import sys;print(sys.executable)"`；然后改用装了依赖的那个解释器的**完整路径**启动，见第 5 步 |
| 双击 bat 窗口一闪就没 | 早期包是 LF 行尾，cmd 解析失败 | 用命令行跑 `run_labelme.bat` 看完整报错；本版已改 CRLF，失败会 `pause` 停住 |
| 控制台停在 `[labelme] starting ...` | 正常，在等窗口关闭 | 不用管；窗口若被挡住，见第 5 步 |
| 停在 `[模型] checking` / 长时间无输出 | 在下载，网速慢时百分比涨得慢 | 看进度行的 MB/s 和“剩余”；实在下不动走第 7 步 |
| `HQ-SAM 权重自动下载失败` | 两个源都连不上 | 第 7 步四种方式任选 |
| `[存在但只有 xxx，不完整]` | 上次下载中断的残骸 | 删掉 `models\` 里那个文件重下 |
| `CUDA out of memory` | 显存不足 | 换 `vit_b`，或把配置里 `sam.device` 改成 `cpu` |
| SAM 点下去弹「SAM 不可用」 | 权重没就绪，已自动退回普通多边形 | 按第 7 步把权重补上，重启 |
| 点了 SAM，窗口整个卡死几分钟 | `-m labelme` 是同步下载，正在下 2.4 GB | 别关窗口，看控制台日志在走就没问题；想不卡就先用 `python download_model.py` 下好 |
| 改了配置但档位 / 快捷键没变 | `%USERPROFILE%\.labelmerc` 把项目里的 yaml 盖掉了 | 改 `%USERPROFILE%\.labelmerc`，或启动时加 `--config "sam: {weights: vit_b}"` |
| `No module named labelme` | 不在项目根目录，或装的不是源码目录 | `cd` 到含 `labelme\` 文件夹的那一层再执行 `python -m labelme` |
| `python -m labelme` 启动的是官方版（界面没有 SAM 菜单组） | 当前目录不对，`-m` 找到了 `pip` 装的那个 labelme | 同上，必须在项目根执行；或 `python start_custom_labelme.py` |
| 换了新版本，快捷键 / 新参数没变 | 真正生效的是 `%USERPROFILE%\.labelmerc`，不是项目里的 yaml | 见下面「从旧版换过来」一节 |
| 依赖自检提示「装的是【原版 segment-anything】」 | 不是报错，是精度提示：HQ 权重里的专用参数会被丢掉 | 能跑；想真 HQ 就按它给的两条命令换成 `segment-anything-hq` |
| `torch.cuda.is_available()` 为 `False` | 没有 NVIDIA 显卡，或装的是 CPU 版 torch | **这不算错**：程序自动用 CPU 跑，只是慢（见第 6 步耗时表）。有显卡却为 `False` 才是 torch 装成了 CPU 版 |
| 打开 `examples\` 里的图，弹 `version in file: 4.0.0` | 示例标注是旧版格式，程序能读，只是提示 | 忽略即可；自己新标的数据不会有这个提示 |
| `DLL load failed while importing ...` | 缺 VC++ 运行库 | 装 [Microsoft VC++ 2015–2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) |
| SAM 结果明显不如预期 / 有 `strict=False` 之类提示 | 装成了原版 `segment-anything` 而不是 HQ 版 | `pip uninstall segment-anything && pip install segment-anything-hq`，权重必须是 `sam_hq_*` 系列 |

---

#### 从旧版换过来：为什么快捷键 / 新参数不生效

`~/.labelmerc` 只在**第一次运行**时从项目复制一份，之后永远读它自己：

- 项目里的 `labelme/config/default_config.yaml` —— 叫「出厂值」，改它只对全新环境有效
- 你机器上真正生效的 —— `C:\Users\<你的用户名>\.labelmerc`
- 所以**换了新版本，新加的快捷键和新参数一个都不会自动同步**

**怎么确认自己中招了**：打开 `%USERPROFILE%\.labelmerc` 看 `shortcuts:` 段。
旧版的 `create_polygon` 是这样的（列表，多绑了一个 `1` 键）：

```yaml
create_polygon:
- Ctrl+N
- '1'
```

新版是单字符串：

```yaml
create_polygon: Ctrl+N
```

**修法（先备份，会丢你自己加的 labels）**：

```bat
ren "%USERPROFILE%\.labelmerc" ".labelmerc.bak"
```

再启动一次，它会重新生成一份与当前版本一致的干净配置。
备份里如果存过自己整理好的 `labels:` 列表，手动抄回新文件就行。

> `python -m labelme --reset-config` 清的是**窗口布局 / Qt 状态**，不是这份配置文件，
> 别拿它来重置快捷键。

---

### 1. 依赖清单（完整）

下表就是 `check_deps.py` 会逐项检查的全部依赖，缺任何一项都会直接点名告诉你。

| # | import 名 | pip 包名 | 版本要求 | 用途 | 缺失后的表现 |
|---|---|---|---|---|---|
| 1 | `PyQt5` | `PyQt5` | `!=5.15.3, !=5.15.4` | 图形界面框架（主窗口、画布、所有控件） | 启动即报 `No module named 'PyQt5'`，窗口根本不出现 |
| 2 | `yaml` | `PyYAML` | 任意 | 读取 `default_config.yaml`（快捷键、颜色、SAM 参数） | 读不到配置，快捷键与自定义参数全部失效 |
| 3 | `numpy` | `numpy` | 任意（建议与 torch 匹配） | 图像数组运算、多边形坐标处理 | 画布无法加载图像 |
| 4 | `cv2` | `opencv-python-headless` | 4.x | 掩膜腐蚀/膨胀、`approxPolyDP` 多边形拟合 | SAM 掩膜后处理与顶点密度功能报错 |
| 5 | `PIL` | `Pillow` | `>=2.8` | 读写 jpg/png/tif 等图像 | 打不开图片 |
| 6 | `qtpy` | `qtpy` | `!=1.11.2` | Qt 抽象层 | 启动报错 |
| 7 | `appdirs` | `appdirs` | 任意 | 定位权重缓存目录 | 找不到 SAM 权重路径 |
| 8 | `natsort` | `natsort` | `>=7.1.0` | 图片按文件名自然排序（`img2` 排在 `img10` 前） | 文件列表顺序错乱 |
| 9 | `imgviz` | `imgviz` | `>=0.11` | 标签配色、可视化工具 | 启动报错 |
| 10 | `termcolor` | `termcolor` | 任意 | 终端彩色日志 | 启动报错 |
| 11 | `torch` | `torch` | `>=1.7` | HQ-SAM 推理后端（CPU / CUDA 均可） | **启动即崩**。`labelme/widgets/canvas.py` 第 14 行在模块顶层 `import torch`，主窗口初始化就要用到，纯手工标注也一样起不来 |
| 12 | `torchvision` | `torchvision` | `>=0.8` | torch 配套 | 导入 torch 相关模块时报错，同样起不来 |
| 13 | `segment_anything` | `segment-anything-hq` | 任意 | HQ-SAM 模型注册与 `SamPredictor` | 同上（注意：不是 PyPI 上的 `segment-anything`，HQ 权重必须用这个分支） |

> **前 12 项是启动级依赖**：任何一项缺失，主窗口都不会出现，不存在「缺了也能纯手工标注」的情况。
> 只有 **第 13 项 `segment_anything`** 例外 —— 它只在切到 SAM 模式时才加载，缺了会降级成普通多边形并弹一次提示，手工标注照常可用。
> `matplotlib`、`colorama` 会随 `imgviz` / Windows 自动带入，不必单独装。

### 2. 启动方式（命令行 / 双击）

> 只想跑起来 → 方式 A 双击就行。
> **要排查问题、或者想少一层中间件 → 方式 B / C 里的 `python -m labelme`，走原版入口。**
> 两种入口的差别见第四节开头的对照表。

#### 方式 A：双击

**双击 `run_labelme.bat`**（Windows）。

它会按下面的顺序逐个试，**用第一个能真正 import 全部依赖的解释器**：

1. 环境变量 `%LABELME_PYTHON%`
2. 本目录下的 `python_path.txt`（一行，写 `python.exe` 的完整路径）
3. 本目录下的 `.venv` / `venv` / `env`
4. PATH 里的 `python` / `python3` / `py -3`

全都不行时，它会**自动调用 `check_deps.py` 逐项告诉你缺哪个包**，并给出两条修复命令。

> 若控制台停在 `[labelme] starting ...` 之后再无输出，而窗口没出现：
> 程序**没有崩**，窗口只是被启动它的终端盖住了（Windows 前台锁）。
> 本版会自动把它顶到最前（见第四节）；实在没看到就按 `Alt+Tab` 或点任务栏的 `labelme`。

#### 方式 B：PowerShell

下面出现的 `C:\Python310\python.exe` **只是占位示例**，请换成你自己机器上的路径。
不知道自己的路径是什么，先查一下：

```powershell
# 查 PATH 里的 python 在哪
(Get-Command python).Source

# 查某个 venv 里的 python，就是 venv 目录下 Scripts\python.exe
D:\venvs\labelme\Scripts\python.exe -V
```

```powershell
# 进到项目目录（clone 下来叫什么就用什么，下面以 labelme-sam-custom 为例）
cd "C:\Users\<你的用户名>\Desktop\labelme-sam-custom"

# 1) 原版入口：出问题一定有日志，排查问题用这个
& "C:\Python310\python.exe" -m labelme

# 2) 原版入口 + 直接开图 / 开目录
& "C:\Python310\python.exe" -m labelme "D:\data\001.jpg"
& "C:\Python310\python.exe" -m labelme "D:\data"

# 3) 临时换模型档位，不写任何文件
& "C:\Python310\python.exe" -m labelme --config "sam: {weights: vit_b}"

# 4) 带壳入口：顶窗口 + 单实例 + 启动就后台预热权重
& "C:\Python310\python.exe" .\start_custom_labelme.py
& "C:\Python310\python.exe" .\start_custom_labelme.py "D:\data\001.jpg"

# 5) 等同于双击
.\run_labelme.bat

# 6) 指定解释器（只对当前这个窗口有效）
$env:LABELME_PYTHON = "C:\Python310\python.exe"
.\run_labelme.bat

# 7) 只查依赖缺什么
& "C:\Python310\python.exe" .\check_deps.py

# 8) 只查 / 只下模型权重
& "C:\Python310\python.exe" .\download_model.py --check
& "C:\Python310\python.exe" .\download_model.py --model vit_b
```

> - 路径里有空格或中文时，整段用双引号包住；`&` 是调用运算符，必须保留。
> - 执行策略拦截 `.bat` 时，改用 `cmd /c .\run_labelme.bat`。
> - `$env:XXX` 只影响当前会话；想长期生效用 `setx LABELME_PYTHON "路径"`（**新开**的终端才认）。
> - `-m labelme` **必须在项目根目录执行**，否则找到的是 `pip` 装的官方版。

#### 方式 C：CMD

```bat
cd /d "C:\Users\<你的用户名>\Desktop\labelme-sam-custom"
set LABELME_PYTHON=C:\Python310\python.exe

rem 原版入口：出问题一定有日志（排查问题用这个）
"C:\Python310\python.exe" -m labelme
"C:\Python310\python.exe" -m labelme "D:\data\001.jpg"

rem 临时换档位，不写文件
"C:\Python310\python.exe" -m labelme --config "sam: {weights: vit_b}"

rem 带壳入口（顶窗口 + 单实例 + 启动预热权重）
"C:\Python310\python.exe" start_custom_labelme.py

rem 或者直接跑 bat
run_labelme.bat
```

#### 方式 D：让 bat 以后自动认准这个解释器

在本目录新建 `python_path.txt`（**一行，只写你自己的 `python.exe` 完整路径，不要加引号**），例如：

```text
C:\Python310\python.exe
```

或 venv 里的：

```text
D:\venvs\labelme\Scripts\python.exe
```

之后双击 `run_labelme.bat` 就直接用这个解释器，不必再设环境变量。
这个文件是**每台机器各自建一份**的：仓库里不含它（已在 `.gitignore` 中排除），
所以你 clone 下来不会有，别人也不会看到你的路径。

> **注 1**：`start_custom_labelme.py` 会把本目录放到 `sys.path` 最前面，
> 因此**一定运行本仓库的 `labelme/` 代码**，不会误用 `pip install labelme` 装进
> `site-packages` 的其它版本。若你的 venv 里装过 `labelme`，**不要**用 `labelme.exe`
> 或 `python -m labelme` 启动 —— 那跑的是另一份代码，本仓库的改动全部不生效。
>
> **注 2**：`models/`、虚拟环境目录、`python_path.txt` 均已在 `.gitignore` 中排除，不随仓库分发。

---

## 七、许可

GPL-3.0，详见 [`LICENSE`](./LICENSE)。本仓库修改部分同样以 GPL-3.0 发布。

- 原始版本：Copyright (C) 2016-2018 Kentaro Wada，Copyright (C) 2011 Michael Pitidis, Hussein Abdulwahid
- 本仓库的修改：2026-10 起，同样以 GPL-3.0 发布
- 如果你要再分发本项目（含二进制打包），必须**同样以 GPL-3.0 提供完整源代码**，并保留上述版权声明

### 7.1 GPL-3.0 的四项义务（本仓库逐条对照）

| 义务（条款） | 本仓库怎么做的 |
|---|---|
| §5(a) 显著声明「修改过」并注明日期 | `README.md` 顶部有 `This is a modified version of labelme` + `2026-10` |
| §5(b) 保留所有原版权声明 | 原版权声明（Kentaro Wada / Michael Pitidis 等）与 GPL 声明头原样保留在 `NOTICE` 第 1 节，未删改一个字 |
| §4/§6 随程序提供许可证副本 | `LICENSE` 是**纯 GPL-3.0 全文**（17 个条款 + 附录，5644 词），不掺任何其他文字 |
| §2 不得附加额外限制 | 全仓库无「禁止商用」「仅供学习」等限制性条款，已全文扫描确认 |

GPL 允许修改、允许再分发、允许收费，但**不允许改完之后闭源**。

> 上游 `LICENSE` 原本只有 15 行声明，没有许可正文——不满足 §4「随程序提供许可证副本」。
> 本仓库补上了官方全文，同时把原来的版权声明整段搬进 `NOTICE` 第 1 节。
> **为什么分开放**：GitHub 的许可证识别器要求 `LICENSE` 里只有标准许可文本，
> 前面掺上版权声明或说明文字就会被判成 `NOASSERTION / Other`（实测踩过）。
> 分开之后既满足 §5(b) 保留声明，又能让 GitHub 正确显示 `GPL-3.0`。

### 7.2 第三方资源与依赖

**运行依赖**（不随本仓库分发，由 `pip install` 从 PyPI 安装）：

| 依赖 | 许可证 | 与 GPL-3.0 是否兼容 |
|---|---|---|
| PyQt5 | GPL-3.0 / 商业双许可 | 兼容（同协议） |
| torch / torchvision | BSD-3-Clause | 兼容 |
| segment-anything、segment-anything-hq | Apache-2.0 | 兼容 |
| numpy / opencv-python / natsort / imgviz 等 | BSD / Apache / MIT | 兼容 |

> ⚠️ 若你要把本项目打包成 exe 并**闭源商业分发**，PyQt5 的商业许可需要单独向 Riverbank 购买。
> 以 GPL-3.0 开源分发则无需付费。

**示例数据**：`examples/` 下各教程的 `README.md` 保留，但**其中的示例图片与数据集文件
（`.jpg` / `.png` / `.gif` / `.npy` / `.xml`）不随本仓库分发**——它们来自 PASCAL VOC、APC2016
等第三方数据集，著作权归原始权利人，为避免再分发的授权争议已全部移除。
需要看图或跑通教程时，请到上游仓库
[fry404006308/labelme-with-segment-anything](https://github.com/fry404006308/labelme-with-segment-anything)
下载，或直接用你自己的图片。`examples/` 下保留 `.json` 标注样例与 `.txt` 类别名词表，可作格式参考。

`tests/labelme_tests/data/` 整个目录被 `.gitignore` 排除，**不在仓库内**，测试用的样例图同样不会分发。

`labelme/icons/` 下的图标来自 GNOME 图标主题，具体归属见 [`NOTICE`](./NOTICE)。

**模型权重不在本仓库内**。`sam_hq_*.pth` 由程序在首次使用时自动下载到本机缓存，不随仓库分发；
HQ-SAM 权重的许可为 Apache-2.0，发布方为 [SysCV/sam-hq](https://github.com/SysCV/sam-hq)。

## 八、致谢

- [wkentaro/labelme](https://github.com/wkentaro/labelme)：标注工具本体
- [fry404006308/labelme-with-segment-anything](https://github.com/fry404006308/labelme-with-segment-anything)：SAM 集成版本
- [SysCV/sam-hq](https://github.com/SysCV/sam-hq)：HQ-SAM 模型代码与官方权重
- [lkeab/hq-sam](https://huggingface.co/lkeab/hq-sam/tree/main)：HQ-SAM 权重托管（HuggingFace）
