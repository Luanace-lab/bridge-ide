from setuptools import find_packages, setup


setup(
    name="bridge-ide",
    version="0.1.0",
    description="Bridge IDE local multi-agent platform wrapper CLI",
    python_requires=">=3.10",
    packages=find_packages(include=["bridge_ide", "bridge_ide.*"]),
    install_requires=[
        "websockets>=12.0,<16.0",
        "croniter>=1.4,<7.0",
        "websocket-client>=1.6,<2.0",
        "httpx>=0.25,<1.0",
        "mcp>=0.1",
        "watchdog>=3.0,<5.0",
    ],
    extras_require={
        "full": ["numpy>=1.26", "chromadb>=0.5", "playwright>=1.50"],
        "voice": ["openai>=1.0"],
        "office": ["openpyxl>=3.1", "python-pptx>=0.6", "pypdf>=3.0"],
    },
    entry_points={"console_scripts": ["bridge-ide=bridge_ide.cli:main"]},
)
