from setuptools import setup

setup(
    name="metabridge-ipc",
    version="0.1.0",
    description="High-performance in-memory service pipes for intra-project function calls.",
    author="miguel-b-p",
    author_email="miguelpinotty@gmail.com",

    packages=['metabridge'],
    package_dir={'metabridge': 'src'},

    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
        "Intended Audience :: Developers",
    ],
    python_requires='>=3.7',
)
