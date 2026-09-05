from os.path import join
from pathlib import Path
import subprocess, sys
from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory


class PygameRecipe(CompiledComponentsPythonRecipe):
    version = "2.1.0"
    url = "https://github.com/pygame/pygame/archive/{version}.tar.gz"
    name = "pygame"
    site_packages_name = "pygame"
    depends = ["sdl2", "sdl2_image", "sdl2_mixer", "sdl2_ttf", "setuptools", "jpeg", "png"]
    call_hostpython_via_targetpython = False
    install_in_hostpython = False

    def prebuild_arch(self, arch):
        super().prebuild_arch(arch)
        with current_directory(self.get_build_dir(arch.arch)):
            inc = "src_c/cython"
            for pyx in sorted(Path(inc).rglob("*.pyx")):
                if pyx.parent.name == "_sdl2":
                    out = Path("src_c/_sdl2") / (pyx.stem + ".c")
                    out.parent.mkdir(parents=True, exist_ok=True)
                else:
                    stem = pyx.stem
                    if not stem.startswith("_"):
                        stem = "_" + stem
                    out = Path("src_c") / (stem + ".c")
                print("cython", pyx, "->", out)
                subprocess.check_call(
                    [sys.executable, "-m", "cython", "-3", "-I", inc, str(pyx), "-o", str(out)]
                )
            setup_template = open(join("buildconfig", "Setup.Android.SDL2.in")).read()
            png = self.get_recipe("png", self.ctx)
            png_lib_dir = join(png.get_build_dir(arch.arch), ".libs")
            png_inc_dir = png.get_build_dir(arch)
            jpeg = self.get_recipe("jpeg", self.ctx)
            jpeg_inc_dir = jpeg_lib_dir = jpeg.get_build_dir(arch.arch)
            sdl_mixer_includes = ""
            for include_dir in self.get_recipe("sdl2_mixer", self.ctx).get_include_dirs(arch):
                sdl_mixer_includes += f"-I{include_dir} "
            setup_file = setup_template.format(
                sdl_includes=(
                    " -I" + join(self.ctx.bootstrap.build_dir, "jni", "SDL", "include")
                    + " -L" + join(self.ctx.bootstrap.build_dir, "libs", str(arch))
                    + " -L" + png_lib_dir
                    + " -L" + jpeg_lib_dir
                    + " -L" + arch.ndk_lib_dir_versioned
                ),
                sdl_ttf_includes="-I" + join(self.ctx.bootstrap.build_dir, "jni", "SDL2_ttf"),
                sdl_image_includes="-I" + join(self.ctx.bootstrap.build_dir, "jni", "SDL2_image", "include"),
                sdl_mixer_includes=sdl_mixer_includes,
                jpeg_includes="-I" + jpeg_inc_dir,
                png_includes="-I" + png_inc_dir,
                freetype_includes="",
            )
            open("Setup", "w").write(setup_file)

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env["USE_SDL2"] = "1"
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"
        return env


recipe = PygameRecipe()
