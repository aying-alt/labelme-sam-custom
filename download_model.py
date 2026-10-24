"""单独下载 HQ-SAM 权重。

平时不需要手动跑它：启动 labelme 时如果找不到权重，程序会自动在后台下载，
控制台会显示百分比进度。只有自动下载失败（网络受限 / 中途断掉）时，才用它。

用法：
    python download_model.py                  # 用 default_config.yaml 里配置的档位
    python download_model.py --model vit_b    # 指定档位，先下小的试水
    python download_model.py --check          # 只检查有没有，不下载
    python download_model.py --list           # 列出可选档位和大小
    python download_model.py --quiet          # 不打印进度

退出码：
    0  权重可用
    1  权重不可用（下载失败 / 未找到）
"""

import argparse
import os
import sys

# 保证 import 到的是本目录的 labelme，而不是 site-packages 里 pip 装的那份
_HERE = os.path.dirname(os.path.abspath(__file__))
if not sys.path or sys.path[0] != _HERE:
    sys.path.insert(0, _HERE)

from labelme.sam_weight import (  # noqa: E402
    EXPECTED_SIZE,
    WEIGHT_FILES,
    SamWeightError,
    download_dir,
    ensure_weight,
    find_weight,
    fmt_size,
    human_report,
    normalize_key,
)


def configured_model():
    """读 default_config.yaml 里 sam.weights 的值，读不到就退回 vit_h。"""
    try:
        import yaml

        cfg_path = os.path.join(_HERE, "labelme", "config", "default_config.yaml")
        with open(cfg_path, "r", encoding="utf-8") as fp:
            cfg = yaml.safe_load(fp) or {}
        return cfg.get("sam", {}).get("weights", "vit_h")
    except Exception:
        return "vit_h"


def print_table():
    print("可选档位：")
    print("  {:<8} {:<24} {:>10}   说明".format("档位", "文件名", "大小"))
    notes = {
        "vit_b": "显存 6-8GB / 先跑通",
        "vit_l": "精度与显存折中",
        "vit_h": "精度最高，显存要求也最高",
    }
    for key in ("vit_b", "vit_l", "vit_h"):
        print(
            "  {:<8} {:<24} {:>10}   {}".format(
                key, WEIGHT_FILES[key], fmt_size(EXPECTED_SIZE[key][0]), notes[key]
            )
        )
    print("")
    print("权重存放目录: {}".format(download_dir()))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="下载 HQ-SAM 权重（labelme 定制版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="vit_b / vit_l / vit_h，默认读配置（当前为 %s）" % configured_model(),
    )
    parser.add_argument("--check", action="store_true", help="只检查，不下载")
    parser.add_argument("--list", action="store_true", help="列出可选档位")
    parser.add_argument("--quiet", "-q", action="store_true", help="不打印下载进度")
    args = parser.parse_args(argv)

    if args.list:
        print_table()
        return 0

    raw_key = args.model or configured_model()

    try:
        key = normalize_key(raw_key)
    except ValueError as exc:
        print("错误: {}".format(exc))
        print_table()
        return 2

    if args.check:
        print(human_report(key))
        path = find_weight(key)
        print("")
        if path:
            print("结论: 可用 -> {}".format(path))
            return 0

        print("结论: 不可用，需要下载")
        print("")
        print("下一步（任选一种）：")
        print("")
        print("  1) 让它下载（约 {}，断了会接着下）".format(fmt_size(EXPECTED_SIZE[key][0])))
        print("         python download_model.py --model {}".format(key))
        print("")
        print("  2) 用浏览器 / 迅雷下好，改成本名后放进这个目录：")
        print("         {}".format(download_dir()))
        print("     下载地址：")
        print("         https://hf-mirror.com/lkeab/hq-sam/resolve/main/{}".format(WEIGHT_FILES[key]))
        print("")
        print("  3) 不下载也能用：纯手工多边形标注完全不受影响，只是没有 SAM 半自动。")
        print("")
        print("提示: 上面的 python 若不是你装依赖的那个解释器，换成完整路径再跑。")
        return 1

    try:
        path = ensure_weight(key, allow_download=True, quiet=args.quiet)
    except SamWeightError as exc:
        print(str(exc))
        print("")
        print("提示: 也可以改用更小的档位先跑通，例如")
        print("    python download_model.py --model vit_b")
        return 1

    print("权重已就绪: {}".format(path))
    print("现在可以直接启动: run_labelme.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
