import pathlib
import os
import freeselcall.fsk_build as fsk_build
import subprocess


def build(setup_kwargs):
    cwd = pathlib.Path().absolute()
    
    build_dir = pathlib.Path(cwd / "build_codec2")
    build_dir.mkdir(parents=True, exist_ok=True)

    os.chdir(str(build_dir))
    subprocess.run(['cmake', str(cwd / "codec2"),"-DBUILD_SHARED_LIBS=OFF"], check=True)
    subprocess.run(['make'], check=True)

    os.chdir(str(cwd))

    setup_kwargs.update(
        {"ext_modules": [fsk_build.ffibuilder.distutils_extension()]},
    )
    