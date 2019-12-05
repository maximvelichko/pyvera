from setuptools import setup, find_packages

setup(name='pyvera',
      version='0.3.7',
      description='Python API for talking to Vera Z-Wave controllers',
      url='https://github.com/pavoni/pyvera',
      author='James Cole, Greg Dowling',
      author_email='mail@gregdowling.com',
      license='MIT',
      setup_requires=['pytest'],
      install_requires=['requests>=2.0'],
      tests_require=['mock', 'pytest', 'coverage', 'pytest-cov'],
      packages=find_packages(),
      zip_safe=True)
