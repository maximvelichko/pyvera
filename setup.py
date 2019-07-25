from setuptools import setup, find_packages

setup(name='pyvera',
      version='0.3.3',
      description='Python API for talking to Vera Z-Wave controllers',
      url='https://github.com/pavoni/pyvera',
      author='James Cole, Greg Dowling',
      author_email='mail@gregdowling.com',
      license='MIT',
      install_requires=['requests>=2.0'],
      packages=find_packages(),
      test_suite="tests",
      zip_safe=True)
