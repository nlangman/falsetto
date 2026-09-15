import pytest
from router import Message


@pytest.fixture
def msg():
    return Message(thread_key="t-42", body="ops: disk full")
