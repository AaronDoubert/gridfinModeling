"""Lets a bare `pytest` find the package.

The tests import `gridfin`, but nothing installs it - this project is cloned and
run in place, so there is no setup.py or pyproject.toml. `python -m pytest`
works by accident, because `-m` puts the working directory on `sys.path`; a bare
`pytest` does not, and collection fails with `No module named 'gridfin'`.

pytest adds the directory holding the root conftest.py to `sys.path`, so this
file existing is what makes both spellings work.
"""
