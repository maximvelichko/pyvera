from setuptools import setup

setup(name='python-vera',
      version='0.1.1',
      description='Python API for talking to Vera Z-Wave controllers',
      url='https://github.com/jamespcole/home-assistant-vera-api',
      author='James Cole',
      license='GPLv2',
      install_requires=['requests>=2.0'],
      packages=['pyvera'],
      zip_safe=True)