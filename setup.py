from setuptools import setup

setup(
    name='saltbot',
    packages=['saltbot'],
    include_package_data=True,
    install_requires=[
        'requests',
        'jinja2',
        'beautifulsoup4'
    ],
    scripts=['saltbot/saltbot.py']
)
