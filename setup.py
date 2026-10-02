from setuptools import Extension, setup

pin_bridge_ext = Extension(
    "avd4linux._pin_bridge",
    sources=["src/avd4linux/_pin_bridge.c"],
    extra_compile_args=["-O2", "-Wall"],
)

setup(
    ext_modules=[pin_bridge_ext],
)
