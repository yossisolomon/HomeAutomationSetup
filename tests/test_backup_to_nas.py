import datetime
import os

import pytest
from scripts import backup_to_nas as b


def test_load_excludes_strips_comments_and_blanks(tmp_path):
    f = tmp_path / "ex.txt"
    f.write_text(
        "# a comment\n"
        "prometheus/data/\n"
        "\n"
        "   # indented comment\n"
        "*.log\n"
        "  config/home-assistant_v2.db  \n",
        encoding="utf-8",
    )
    assert b.load_excludes(str(f)) == [
        "prometheus/data/",
        "*.log",
        "config/home-assistant_v2.db",
    ]
