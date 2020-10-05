from setuptools import find_packages, setup

from locust.version import LOCUST_VERSION

long_description = ""
with open("README.md") as ifp:
    long_description = ifp.read()

setup(
    name="locust",
    version=LOCUST_VERSION,
    packages=find_packages(),
    install_requires=[
        "pygit2",
    ],
    extras_require={"dev": ["black", "mypy"]},
    description="Locust: Track changes to Python code across git refs",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Neeraj Kashyap",
    author_email="neeraj@simiotics.com",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Programming Language :: Python",
    ],
    url="https://github.com/simiotics/locust",
    entry_points={"console_scripts": ["locust=locust.cli:main"]},
)