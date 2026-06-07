#!/usr/bin/env python

from setuptools import setup

__version__ = "1.5.0"

with open("README.md") as fh:
    long_description = fh.read()

with open("requirements.txt") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="metagoofil",
    version=__version__,
    description="Metagoofil - Search Google, DuckDuckGo, Startpage, SearXNG, MetaGer, and Mojeek and download specific file types.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="opsdisk",
    url="https://github.com/opsdisk/metagoofil",
    license="GPLv3",
    python_requires=">=3.8",
    install_requires=requirements,
    py_modules=["metagoofil"],
    entry_points={
        "console_scripts": [
            "metagoofil=metagoofil:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Information Technology",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Topic :: Security",
    ],
)
