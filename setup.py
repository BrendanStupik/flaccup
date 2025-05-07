from setuptools import setup, find_packages
import os

def get_version(package_name):
    version_path = os.path.join(package_name, '__init__.py')
    with open(version_path, 'r') as f:
        for line in f:
            if line.startswith('__version__'):
                return line.split('=')[1].strip().strip('"').strip("'")
    return None

PROJECT_VERSION = get_version('flaccup')
if PROJECT_VERSION is None:
    raise RuntimeError("Version could not be found in flaccup/__init__.py")

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="flaccup",
    version="1.0.0",
    author="Brendan Stupik",
    author_email="flaccup@brendanstupik.anonaddy.com",
    description="FLAC Integrity Checker and Backup Utility",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/BrendanStupik/flaccup",
    packages=find_packages(exclude=["tests*", "*.tests", "*.tests.*", "tests"]),
    install_requires=[],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Topic :: System :: Archiving :: Backup",
        "Topic :: Multimedia :: Sound/Audio :: Analysis",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
    entry_points={
        "console_scripts": [
            "flaccup=flaccup.cli:main",
            "flaccup.scheduler=flaccup.scheduler:main_cli",
        ],
    },
)
