"""依赖自检：逐项报告缺什么，并直接给出可复制的修复命令。

用法：
    python check_deps.py            # 逐项打印
    python check_deps.py --quiet    # 不打印，全部通过时退出码 0，否则 1

退出码：0 = 必需依赖齐全；1 = 有缺失。
"""

import importlib
import sys

# labelme 5.x 与它依赖的新版 torch / numpy 的最低门槛。
# 低于这个版本时不要给 pip 命令 —— 装了也启动不起来，只会让人白折腾。
MIN_PY = (3, 7)
# 低于这个版本只提示「能跑但建议升级」，不拦。
REC_PY = (3, 10)

# (import 名, pip 包名, 用途, 是否必需)
REQUIRED = [
    ("PyQt5", "PyQt5!=5.15.3,!=5.15.4", "图形界面框架（主窗口、画布）", True),
    ("yaml", "PyYAML", "读取 default_config.yaml（快捷键/参数）", True),
    ("numpy", "numpy", "图像数组运算", True),
    ("cv2", "opencv-python-headless", "掩膜腐蚀/膨胀、多边形拟合", True),
    ("PIL", "Pillow>=2.8", "图像读写", True),
    ("qtpy", "qtpy", "Qt 抽象层", True),
    ("appdirs", "appdirs", "定位权重缓存目录", True),
    ("natsort", "natsort>=7.1.0", "图片按文件名自然排序", True),
    ("imgviz", "imgviz>=0.11", "标签配色与可视化", True),
    ("termcolor", "termcolor", "终端彩色日志", True),
    ("torch", "torch>=1.7", "HQ-SAM 推理后端", True),
    ("torchvision", "torchvision>=0.8", "torch 配套", True),
    ("segment_anything", "segment-anything-hq", "HQ-SAM 模型注册与预测器", True),
]


def _say(text):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def _segment_variant():
    """判断 site-packages 里装的是 HQ 版还是原版 segment-anything。

    import 名两者都是 segment_anything，光靠 import 分不出来，只能查发行包名。
    返回 ("hq"|"orig", 版本) 或 None（查不到，比如 Python < 3.8 又没有 backport）。
    """
    try:
        from importlib.metadata import PackageNotFoundError, distribution
    except ImportError:  # Python < 3.8
        try:
            from importlib_metadata import (  # type: ignore
                PackageNotFoundError,
                distribution,
            )
        except ImportError:
            return None

    for dist_name, tag in (
        ("segment-anything-hq", "hq"),
        ("segment-anything", "orig"),
    ):
        try:
            return tag, distribution(dist_name).version
        except PackageNotFoundError:
            continue
    return None


def _warn_original_segment(exe):
    """装了原版 segment-anything 时给出提示：能跑，但 HQ 精度拿不到。"""
    _say("")
    _say("!" * 68)
    _say("注意：装的是【原版 segment-anything】，不是 HQ 版。")
    _say("      程序能正常跑，但加载 sam_hq_*.pth 时 HQ 专用参数会被丢弃，")
    _say("      实际精度等同普通 SAM —— 想真正用上 HQ-SAM，换包：")
    _say("")
    _say('    "{}" -m pip uninstall -y segment-anything'.format(exe))
    _say('    "{}" -m pip install segment-anything-hq'.format(exe))
    _say("!" * 68)


def _warn_python_too_old():
    """解释器版本低于门槛时，只讲「先换 Python」，绝不给 pip 命令。

    在 3.6 上给 pip 命令是最坑的一种「帮倒忙」：命令能跑通，依赖也装上了，
    但 labelme 5.x 起不来，用户会以为是代码坏了。
    """
    ver = "{}.{}".format(*sys.version_info[:2])
    _say("=" * 68)
    _say("解释器: {}".format(sys.executable))
    _say("版本  : {}   <-- 太低，不能用".format(sys.version.split()[0]))
    _say("=" * 68)
    _say("")
    _say("这个 Python（{}）跑不了本项目：".format(ver))
    _say("  - labelme 5.x 要求 Python 3.7 以上")
    _say("  - torch / numpy 的新版本已经没有 {} 的安装包".format(ver))
    _say("")
    _say("**不要**在这个解释器上装依赖，装了也启动不了。")
    _say("")
    _say("正确做法：装一个 Python 3.10（官方安装包，一路下一步）")
    _say("    https://www.python.org/downloads/")
    _say("")
    _say("安装时务必勾上 [Add Python 3.10 to PATH]，")
    _say("装完关掉当前终端重新打开，再运行：")
    _say("")
    _say("    python check_deps.py")
    _say("")
    _say("（如果你已经有好用的 Python，直接用它跑本脚本即可：")
    _say("      \"C:\\Python310\\python.exe\" check_deps.py ）")
    _say("=" * 68)


def main():
    quiet = "--quiet" in sys.argv
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass

    if sys.version_info < MIN_PY:
        if not quiet:
            _warn_python_too_old()
        return 1

    missing = []
    seg_variant = None
    if not quiet:
        _say("=" * 68)
        _say("解释器: {}".format(sys.executable))
        _say("版本  : {}".format(sys.version.split()[0]))
        if sys.version_info < REC_PY:
            _say("        （能用，但偏低；建议升到 3.10，否则部分依赖只能装老版本）")
        _say("=" * 68)

    for mod, pkg, usage, required in REQUIRED:
        try:
            m = importlib.import_module(mod)
            version = getattr(m, "__version__", "") or "-"
            if mod == "segment_anything":
                seg_variant = _segment_variant()
                if seg_variant:
                    tag, dist_ver = seg_variant
                    version = "{} {}".format(
                        dist_ver, "(HQ 版)" if tag == "hq" else "(原版)"
                    )
            if not quiet:
                _say("  [ OK ] {:<18} {:<12} {}".format(mod, version, usage))
        except Exception as exc:  # ImportError 或导入期报错
            missing.append((mod, pkg, usage, required, type(exc).__name__))
            if not quiet:
                flag = "[缺失]" if required else "[可选缺失]"
                _say("  {} {:<18} {}".format(flag, mod, usage))

    if not missing:
        if not quiet:
            if seg_variant and seg_variant[0] == "orig":
                _warn_original_segment(sys.executable)
            _say("")
            _say("依赖齐全，可以直接启动。")
        return 0

    if quiet:
        return 1

    hard = [m for m in missing if m[3]]
    soft = [m for m in missing if not m[3]]

    _say("")
    _say("-" * 68)
    _say("缺失 {} 项：".format(len(missing)))
    for mod, pkg, usage, required, err in missing:
        _say("  {:<18} 包名: {:<26} 用途: {} ({})".format(mod, pkg, usage, err))

    if hard:
        pkgs = " ".join('"' + m[1] + '"' for m in hard)
        _say("")
        _say("一条命令补齐（复制到 PowerShell 或 CMD 都能跑）：")
        _say("")
        _say('    "{}" -m pip install {}'.format(sys.executable, pkgs))
        _say("")
        _say("或者直接装本项目的依赖清单：")
        _say("")
        _say('    "{}" -m pip install -r requirements.txt'.format(sys.executable))

    if soft:
        _say("")
        _say("提示：可选依赖只影响 SAM 半自动标注，纯手工多边形标注不受影响。")

    _say("")
    _say("注意：以上命令必须用在**同一个**解释器上，否则装了也用不上。")
    _say("     装了 torch 想用 CPU 版，改用：")
    _say('          "{}" -m pip install torch torchvision --index-url '
         "https://download.pytorch.org/whl/cpu".format(sys.executable))
    return 1


if __name__ == "__main__":
    sys.exit(main())
