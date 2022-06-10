from setuptools import setup
import os

version_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 
                            "freecad", "asm3", "__init__.py")
with open(version_path) as fp:
    exec(fp.read())

setup(name='freecad.asm3',
      version=str(__version__),
      packages=['freecad.asm3'],
      url="https://github.com/realthunder/FreeCAD_assembly3",
      description="Experimental attempt for the next generation assembly workbench for FreeCAD ",
      install_requires=["six"],
      include_package_data=True)
