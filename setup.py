import distutils.spawn
import os
import re
import shlex
import subprocess
import sys

from setuptools import find_packages
from setuptools import setup


def get_version():
    filename = "labelme/__init__.py"
    with open(filename, encoding="utf-8") as f:
        match = re.search(
            r"""^__version__ = ['"]([^'"]*)['"]""", f.read(), re.M
        )
    if not match:
        raise RuntimeError("{} doesn't contain __version__".format(filename))
    version = match.groups()[0]
    return version


def get_install_requires():
    install_requires = [
        "imgviz>=0.11",
        "matplotlib",
        "natsort>=7.1.0",
        "numpy",
        "Pillow>=2.8",
        "PyYAML",
        "qtpy!=1.11.2",
        "termcolor",
        "torch>=1.7",
        "opencv-python-headless",
        "torchvision>=0.8",
        "appdirs",
        # Must be the HQ build. The original segment-anything (facebookresearch)
        # silently drops HQ-specific parameters when loading sam_hq_*.pth, so it
        # would run but with plain-SAM quality. Keep this in sync with
        # requirements.txt - a mismatch here means `pip install .` installs the
        # wrong variant.
        "segment-anything-hq",
    ]

    # Find python binding for qt with priority:
    # PyQt5 -> PySide2
    # and PyQt5 is automatically installed on Python3.
    QT_BINDING = None

    try:
        import PyQt5  # NOQA

        QT_BINDING = "pyqt5"
    except ImportError:
        pass

    if QT_BINDING is None:
        try:
            import PySide2  # NOQA

            QT_BINDING = "pyside2"
        except ImportError:
            pass

    if QT_BINDING is None:
        # PyQt5 can be installed via pip for Python3
        # 5.15.3, 5.15.4 won't work with PyInstaller
        install_requires.append("PyQt5!=5.15.3,!=5.15.4")
        QT_BINDING = "pyqt5"

    del QT_BINDING

    if os.name == "nt":  # Windows
        install_requires.append("colorama")

    return install_requires


def get_long_description():
    # encoding must be explicit: README.md is UTF-8 and contains Chinese.
    # Without it, on a zh-CN Windows box open() uses the GBK locale codec and
    # `pip install .` dies with UnicodeDecodeError before doing anything.
    with open("README.md", encoding="utf-8") as f:
        long_description = f.read()
    try:
        # when this package is being released
        import github2pypi

        return github2pypi.replace_url(
            slug="wkentaro/labelme", content=long_description, branch="main"
        )
    except ImportError:
        # when this package is being installed
        return long_description


def main():
    version = get_version()

    if sys.argv[1] == "release":
        try:
            import github2pypi  # NOQA
        except ImportError:
            print(
                "Please install github2pypi\n\n\tpip install github2pypi\n",
                file=sys.stderr,
            )
            sys.exit(1)

        if not distutils.spawn.find_executable("twine"):
            print(
                "Please install twine:\n\n\tpip install twine\n",
                file=sys.stderr,
            )
            sys.exit(1)

        commands = [
            "git push origin main",
            "git tag v{:s}".format(version),
            "git push origin --tags",
            "python setup.py sdist",
            "twine upload dist/labelme-{:s}.tar.gz".format(version),
        ]
        for cmd in commands:
            print("+ {:s}".format(cmd))
            subprocess.check_call(shlex.split(cmd))
        sys.exit(0)

    setup(
        name="labelme",
        version=version,
        packages=find_packages(),
        description="Image Polygonal Annotation with Python",
        long_description=get_long_description(),
        long_description_content_type="text/markdown",
        author="Kentaro Wada",
        author_email="www.kentaro.wada@gmail.com",
        url="https://github.com/wkentaro/labelme",
        install_requires=get_install_requires(),
        python_requires=">=3.7",
        license="GPL-3.0-or-later",
        keywords="Image Annotation, Machine Learning",
        classifiers=[
            "Development Status :: 5 - Production/Stable",
            "Intended Audience :: Developers",
            "Intended Audience :: Science/Research",
            "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
            "Natural Language :: English",
            "Operating System :: OS Independent",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3 :: Only",
        ],
        package_data={"labelme": ["icons/*", "config/*.yaml"]},
        entry_points={
            "console_scripts": [
                "labelme=labelme.__main__:main",
                "labelme_draw_json=labelme.cli.draw_json:main",
                "labelme_draw_label_png=labelme.cli.draw_label_png:main",
                "labelme_json_to_dataset=labelme.cli.json_to_dataset:main",
                "labelme_on_docker=labelme.cli.on_docker:main",
            ],
        },
    )


if __name__ == "__main__":
    main()
