import pytest

from data.gen import synth


@pytest.fixture(scope="session")
def tables():
    return synth.generate()
