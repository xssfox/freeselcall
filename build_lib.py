from setuptools import setup

import freeselcall.fsk_build as fsk_build


def build(a):
    setup(
        ext_modules=[fsk_build.ffibuilder.distutils_extension()],
    )
