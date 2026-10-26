import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AUDIT_DISABLED"] = "1"


class FakeLLM:
    """Returns scripted replies in order and records the prompts it received."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class Msg:
            content = self.replies.pop(0)

        return Msg()


def make_db(tmp_dir: Path) -> Path:
    from data.generate_data import main

    return main(Path(tmp_dir) / "roaming.db")
