from cmaketools import setup
from setuptools import setup as setup_orig

import freeselcall.fsk_build as fsk_build


def build(a):
    setup(
        ext_modules=[fsk_build.ffibuilder.distutils_extension()],
    )
    setup_orig(
        ext_modules=[fsk_build.ffibuilder.distutils_extension()],
    )
