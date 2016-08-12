import inspect, os
os.chdir(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='op5lib',
    version='1.0',
    author='Ozan Safi',
    author_email='ozansafi@gmail.com',
    py_modules=['op5'],
    description="A python library for OP5's REST API",
    install_requires=[
        "requests>=2.3.0",
        "termcolor>=1.1.0",
    ],
)
