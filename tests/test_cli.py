from __future__ import annotations

import json

from helpers import DEMO_DIR, make_repo

from coderepair.cli import colorize_diff, main


def test_tasks(capsys):
    assert main(["tasks"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 10 and "t10_deep_merge_injection" in out


def test_propose_with_oracle_prints_banner_and_diff(capsys):
    assert main(["propose", "t01_paginate_off_by_one", "--no-save", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "it is NOT a repair result" in out
    assert "+    start = (page - 1) * per_page" in out
    assert "Nothing was written to the repository" in out


def test_propose_json_output(capsys):
    assert main(["propose", "t03_interval_merge_unsorted", "--no-save", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "proposed" and data["diff"].startswith("diff --git")


def test_propose_rejects_malicious_script(capsys):
    code = main(
        [
            "propose",
            "t10_deep_merge_injection",
            "--backend",
            "scripted",
            "--script",
            str(DEMO_DIR / "malicious_response.json"),
            "--no-save",
            "--no-color",
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "status:   rejected" in out
    assert "path traversal" in out


def test_propose_outside_allowed_roots_is_refused(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    issue = tmp_path / "issue.md"
    issue.write_text("# x is wrong\n")
    assert main(["propose", "--repo", str(repo), "--issue", str(issue), "--no-save"]) == 2
    assert "outside the allowed roots" in capsys.readouterr().err


def test_propose_local_repo_inside_allowed_roots(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path / "repo", {"calc.py": "def double(x):\n    return x + x + x\n"})
    issue = tmp_path / "issue.md"
    issue.write_text("# double() triples its input\n")
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            [{"summary": "fix", "edits": [{"path": "calc.py", "old": "x + x + x", "new": "x + x"}]}]
        )
    )
    monkeypatch.setenv("CODEREPAIR_ALLOWED_ROOTS", str(tmp_path))
    code = main(
        [
            "propose",
            "--repo",
            str(repo),
            "--issue",
            str(issue),
            "--backend",
            "scripted",
            "--script",
            str(script),
            "--no-color",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "+    return x + x" in out
    assert (repo / "calc.py").read_text() == "def double(x):\n    return x + x + x\n"


def test_oracle_requires_a_task(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    issue = tmp_path / "issue.md"
    issue.write_text("# x\n")
    monkeypatch.setenv("CODEREPAIR_ALLOWED_ROOTS", str(tmp_path))
    assert main(["propose", "--repo", str(repo), "--issue", str(issue), "--backend", "oracle"]) == 2
    assert "only works for benchmark tasks" in capsys.readouterr().err


def test_search_retrieve_show_and_eval(capsys):
    assert main(["search", "t05_lru_recency", "move_to_end"]) == 0
    assert "cachekit/lru.py:37:" in capsys.readouterr().out
    assert main(["search", "t05_lru_recency", "LRUCache.get", "--symbol"]) == 0
    assert "method LRUCache.get" in capsys.readouterr().out
    assert main(["retrieve", "t04_duration_whitespace", "-n", "2"]) == 0
    assert "traceback frame (line 22)" in capsys.readouterr().out
    assert main(["show", "t02_mutable_default_tags"]) == 0
    assert "agent-visible" in capsys.readouterr().out
    assert main(["eval-retrieval"]) == 0
    assert "recall@3=1.00" in capsys.readouterr().out


def test_unknown_task(capsys):
    assert main(["show", "t99_nope"]) == 2
    assert "unknown task" in capsys.readouterr().err


def test_validate_single_fixture(capsys):
    assert main(["validate-fixtures", "t01_paginate_off_by_one"]) == 0
    assert "1/1 fixtures valid" in capsys.readouterr().out


def test_colorize_diff():
    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    assert colorize_diff(diff, False) == diff
    colored = colorize_diff(diff, True)
    assert "\033[32m+b" in colored and "\033[31m-a" in colored
