from __future__ import annotations

import pytest
from helpers import ALL_TASK_IDS, snapshot_of

from coderepair.security import (
    PolicyError,
    is_sensitive_path,
    redact_secrets,
    resolve_repo_root,
    scan_for_injection,
)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env.production",
        "deploy/id_rsa",
        "certs/server.pem",
        "keys/signing.key",
        "infra/terraform.tfstate",
        ".ssh/config",
        "nested/.aws/credentials",
        "credentials.json",
        ".netrc",
    ],
)
def test_sensitive_paths(path):
    assert is_sensitive_path(path)


@pytest.mark.parametrize(
    "path", [".env.example", "src/app.py", "keys.py", "docs/environment.md", "tests/test_env.py"]
)
def test_non_sensitive_paths(path):
    assert not is_sensitive_path(path)


def test_resolve_repo_root_accepts_repo_inside_allowed_root(tmp_path):
    repo = tmp_path / "allowed" / "repo"
    repo.mkdir(parents=True)
    assert (
        resolve_repo_root(repo, (tmp_path / "allowed",), home=tmp_path / "home") == repo.resolve()
    )


def test_resolve_repo_root_rejects_outside_allowed_root(tmp_path):
    repo = tmp_path / "elsewhere"
    repo.mkdir()
    with pytest.raises(PolicyError, match="outside the allowed roots"):
        resolve_repo_root(repo, (tmp_path / "allowed",), home=tmp_path / "home")


def test_resolve_repo_root_rejects_home_and_its_parents(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for candidate in (home, tmp_path):
        with pytest.raises(PolicyError, match="home directory"):
            resolve_repo_root(candidate, (tmp_path,), home=home)


def test_resolve_repo_root_rejects_denied_locations_even_if_allowed(tmp_path):
    home = tmp_path / "home"
    ssh_repo = home / ".ssh" / "repo"
    ssh_repo.mkdir(parents=True)
    with pytest.raises(PolicyError, match="denied location"):
        resolve_repo_root(ssh_repo, (home,), home=home)


def test_resolve_repo_root_follows_symlinks_before_checking(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PolicyError, match="outside the allowed roots"):
        resolve_repo_root(allowed / "link", (allowed,), home=tmp_path / "home")


def test_resolve_repo_root_rejects_missing_and_files(tmp_path):
    with pytest.raises(PolicyError, match="does not exist"):
        resolve_repo_root(tmp_path / "missing", (tmp_path,), home=tmp_path / "home")
    file = tmp_path / "file.txt"
    file.write_text("x")
    with pytest.raises(PolicyError, match="not a directory"):
        resolve_repo_root(file, (tmp_path,), home=tmp_path / "home")


def test_redact_secrets_masks_known_formats():
    text = "\n".join(
        [
            "AWS_KEY = AKIAIOSFODNN7EXAMPLE",
            "token: ghp_" + "a" * 36,
            'password = "hunter2hunter2"',
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
            "x = compute_total(items)",
            "OPENROUTER = sk-or-v1-" + "0f" * 32,
        ]
    )
    redacted, found = redact_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "0f" * 32 not in redacted
    assert "ghp_" + "a" * 36 not in redacted
    assert "hunter2hunter2" not in redacted
    assert "MIIEow" not in redacted
    assert "x = compute_total(items)" in redacted
    assert {r.kind for r in found} == {
        "aws-access-key-id",
        "github-token",
        "assignment",
        "private-key",
        "openrouter-key",
    }


def test_redact_secrets_leaves_ordinary_code_alone():
    code = 'def get_token(name):\n    return lookup("token", name)\n'
    assert redact_secrets(code) == (code, [])


def test_injection_scanner_flags_the_planted_payloads():
    snapshot = snapshot_of("t10_deep_merge_injection")
    loader = scan_for_injection(snapshot.text("confmerge/loader.py"), "confmerge/loader.py")
    readme = scan_for_injection(snapshot.text("README.md"), "README.md")
    assert {f.rule for f in loader} >= {
        "override-instructions",
        "remote-code-execution",
        "credential-exfiltration",
    }
    assert {f.rule for f in readme} >= {"system-override", "role-reassignment", "concealment"}
    assert all(f.source == "confmerge/loader.py" for f in loader)


@pytest.mark.parametrize("task_id", [t for t in ALL_TASK_IDS if t != "t10_deep_merge_injection"])
def test_injection_scanner_has_no_false_positives_on_clean_fixtures(task_id):
    snapshot = snapshot_of(task_id)
    findings = [
        f for path in snapshot.paths() for f in scan_for_injection(snapshot.text(path), path)
    ]
    assert findings == []
