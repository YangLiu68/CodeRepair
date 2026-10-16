"""Milestone 2: sandboxed test execution.

Unit tests cover result parsing, workspace preparation, the runner bundle, the
Seatbelt profile and the exact ``docker run`` command line. Integration tests
run real sandboxed sessions for every backend available on this machine
(Seatbelt on macOS, Docker where a daemon and image exist) and are skipped,
with the reason shown, elsewhere.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from helpers import ALL_TASK_IDS, snapshot_of, task

from coderepair.agent import STATUS_PROPOSED, propose_patch
from coderepair.benchmark.evaluate import STATUS_RESOLVED, evaluate_patch, judge
from coderepair.benchmark.oracle import OracleBackend
from coderepair.benchmark.validate import SandboxFixtureRunner, validate_task
from coderepair.cli import main
from coderepair.config import PROJECT_ROOT
from coderepair.execution import describe_result, run_repo_tests
from coderepair.patch import Edit, PatchProposal, apply_proposal
from coderepair.sandbox import seatbelt as seatbelt_mod
from coderepair.sandbox.base import (
    LIMIT_WALL_TIME,
    SandboxError,
    SandboxJob,
    SandboxLimits,
    SandboxResult,
    SandboxUnavailable,
)
from coderepair.sandbox.bundle import (
    BUNDLE_DISTRIBUTIONS,
    bundle_contents,
    bundle_digest,
    ensure_runner_bundle,
)
from coderepair.sandbox.docker import DockerSandbox, build_run_argv
from coderepair.sandbox.factory import make_sandbox
from coderepair.sandbox.probes import PROBES, _p, run_probe
from coderepair.sandbox.process import _Capture, run_monitored
from coderepair.sandbox.results import (
    MAX_RESULTS_BYTES,
    ResultsError,
    TestResults,
    parse_results,
    read_results_file,
)
from coderepair.sandbox.seatbelt import SeatbeltSandbox, build_profile
from coderepair.sandbox.workspace import new_run_dir, prepare_run_dir

TASKS_DIR = PROJECT_ROOT / "benchmarks" / "tasks"


@pytest.fixture(scope="session")
def bundle_dir(tmp_path_factory) -> Path:
    return ensure_runner_bundle(tmp_path_factory.mktemp("cache"))


# ---------------------------------------------------------------- result parsing


def _payload(nonce="n", **overrides) -> bytes:
    data = {"nonce": nonce, "tests": {"t.py::a": "passed"}, "collect_errors": [], "exitstatus": 0}
    data.update(overrides)
    return json.dumps(data).encode()


def test_results_round_trip():
    results = parse_results(_payload(tests={"t.py::a": "passed", "t.py::b": "failed"}), "n")
    assert results.counts() == {"error": 0, "failed": 1, "passed": 1, "skipped": 0}
    assert results.ids_with("failed") == ["t.py::b"]
    assert not results.all_passed


@pytest.mark.parametrize(
    "data, message",
    [
        (_payload(nonce="other"), "nonce"),
        (b"not json", "not valid JSON"),
        (b"[]", "JSON object"),
        (_payload(tests=[]), "wrong shape"),
        (_payload(tests={"a": "exploded"}), "unknown outcome"),
        (_payload(tests={"a\nb": "passed"}), "invalid test id"),
        (_payload(exitstatus="0"), "exitstatus"),
        (_payload(exitstatus=True), "exitstatus"),
        (_payload(collect_errors=[1]), "collection error"),
    ],
)
def test_untrusted_results_are_rejected(data, message):
    with pytest.raises(ResultsError, match=message):
        parse_results(data, "n")


def test_results_file_size_and_symlinks_are_refused(tmp_path):
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (MAX_RESULTS_BYTES + 1))
    with pytest.raises(ResultsError, match="larger than"):
        read_results_file(big, "n")
    real = tmp_path / "real.json"
    real.write_bytes(_payload())
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(ResultsError, match="opened safely"):
        read_results_file(link, "n")
    with pytest.raises(ResultsError, match="no results file"):
        read_results_file(tmp_path / "missing.json", "n")
    assert read_results_file(real, "n").outcomes == {"t.py::a": "passed"}


# ------------------------------------------------------------- jobs and workspace


@pytest.mark.parametrize("selector", ["-p", "--rootdir=/", "../x/test_a.py", "a b", "x;rm"])
def test_bad_selectors_are_refused(tmp_path, selector):
    with pytest.raises(SandboxError):
        SandboxJob(tmp_path, selectors=(selector,)).pytest_args()


def test_selectors_are_passed_after_fixed_options(tmp_path):
    args = SandboxJob(tmp_path, selectors=("tests/test_a.py::test_x[1-2]",)).pytest_args()
    assert args[:2] == ["-p", "coderepair_results"]
    assert args[-1] == "tests/test_a.py::test_x[1-2]"


def test_workspace_is_written_from_the_snapshot_with_overlay_and_extras():
    snapshot = snapshot_of("t01_paginate_off_by_one")
    before = {p: snapshot.text(p) for p in snapshot.paths()}
    path = "pager/core.py"
    with prepare_run_dir(
        snapshot,
        overlay={path: "PATCHED\n"},
        extra_files={"tests/test_hidden_x.py": "def test_x():\n    pass\n"},
    ) as run_dir:
        assert (run_dir.workspace / path).read_text() == "PATCHED\n"
        assert (run_dir.workspace / "tests" / "test_hidden_x.py").exists()
        assert stat.S_IMODE(run_dir.root.stat().st_mode) == 0o700
        written = sorted(
            str(p.relative_to(run_dir.workspace)) for p in run_dir.workspace.rglob("*.py")
        )
        expected = [p for p in snapshot.paths() if p.endswith(".py")]
        assert written == sorted([*expected, "tests/test_hidden_x.py"])
        root = run_dir.root
    assert not root.exists()
    on_disk = {p: (snapshot.root / p).read_text(encoding="utf-8") for p in snapshot.paths()}
    assert on_disk == before


@pytest.mark.parametrize(
    "overlay, extra, message",
    [
        ({"new_file.py": "x"}, {}, "outside the snapshot"),
        ({}, {"pager/core.py": "x"}, "overwrite repository files"),
        ({}, {"../escape.py": "x"}, "unsafe workspace path"),
        ({}, {"/abs.py": "x"}, "unsafe workspace path"),
        ({}, {"a/./b.py": "x"}, "unsafe workspace path"),
    ],
)
def test_workspace_rejects_unsafe_files(overlay, extra, message):
    with pytest.raises(SandboxError, match=message):
        prepare_run_dir(snapshot_of("t01_paginate_off_by_one"), overlay=overlay, extra_files=extra)


# ------------------------------------------------------------------ runner bundle


def test_bundle_is_pure_python_content_addressed_and_read_only(tmp_path):
    contents = bundle_contents()
    assert "bootstrap.py" in contents and "coderepair_results.py" in contents
    assert not [p for p in contents if p.endswith((".so", ".dylib", ".pyd"))]
    tops = {p.split("/")[0] for p in contents}
    for dist in BUNDLE_DISTRIBUTIONS:
        assert any(t.lower().startswith(dist.lower()) for t in tops)
    first = ensure_runner_bundle(tmp_path)
    assert ensure_runner_bundle(tmp_path) == first
    assert first.name == f"runner-{bundle_digest(contents)[:16]}"
    assert not os.access(first / "bootstrap.py", os.W_OK)
    assert [p.name for p in tmp_path.iterdir()] == [first.name]


# ------------------------------------------------------------ backend definitions


def test_seatbelt_profile_denies_by_default_and_limits_writes(tmp_path):
    profile = build_profile(
        read_paths=[Path("/opt/py/lib"), tmp_path / "ws"],
        write_paths=[tmp_path / "tmp"],
        exec_paths=[Path("/opt/py/bin/python3")],
    )
    lines = profile.splitlines()
    assert lines[:2] == ["(version 1)", "(deny default)"]
    assert "network" not in profile
    assert "process-fork" not in profile
    write_rule = next(line for line in lines if line.startswith("(allow file-write*"))
    assert str(tmp_path / "ws") not in write_rule and str(tmp_path / "tmp") in write_rule
    exec_rule = next(line for line in lines if line.startswith("(allow process-exec"))
    assert exec_rule == '(allow process-exec (literal "/opt/py/bin/python3"))'
    assert str(Path.home() / ".ssh") not in profile


@pytest.mark.parametrize("bad", ['/tmp/a"b', "/tmp/a\\b", "relative/path", "/tmp/a\nb"])
def test_seatbelt_profile_rejects_unquotable_paths(bad):
    with pytest.raises(SandboxError):
        build_profile(read_paths=[Path(bad)], write_paths=[], exec_paths=[])


def _docker_argv(tmp_path, **limits):
    run_dir = new_run_dir()
    try:
        job = SandboxJob(run_dir.workspace, limits=SandboxLimits(**limits), nonce="abc")
        return build_run_argv(
            job,
            container_name="coderepair-test",
            image="python:3.12-slim",
            bundle_dir=tmp_path / "bundle",
            out_dir=run_dir.out,
        ), run_dir
    finally:
        run_dir.cleanup()


def _flag_values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


def test_docker_command_applies_every_isolation_control(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEREPAIR_HOST_CANARY", "do-not-leak")
    argv, run_dir = _docker_argv(tmp_path, memory_mb=300, max_processes=32, tmp_mb=16)
    assert argv[:2] == ["docker", "run"]
    assert _flag_values(argv, "--network") == ["none"]
    (user,) = _flag_values(argv, "--user")
    assert not user.startswith("0:") and user == f"{os.getuid()}:{os.getgid()}"
    assert _flag_values(argv, "--cap-drop") == ["ALL"]
    assert _flag_values(argv, "--security-opt") == ["no-new-privileges"]
    assert _flag_values(argv, "--pull") == ["never"]
    assert _flag_values(argv, "--memory") == ["300m"] == _flag_values(argv, "--memory-swap")
    assert _flag_values(argv, "--pids-limit") == ["32"]
    assert "--read-only" in argv and "--init" in argv
    assert _flag_values(argv, "--tmpfs")[0].startswith("/tmp:rw,nosuid,nodev,noexec,size=16m")
    mounts = _flag_values(argv, "--mount")
    assert f"type=bind,source={run_dir.workspace},target=/workspace,readonly" in mounts
    assert any(m.endswith("target=/opt/coderepair,readonly") for m in mounts)
    writable = [m for m in mounts if not m.endswith(",readonly")]
    assert writable == [f"type=bind,source={run_dir.out},target=/out"]
    env = dict(e.split("=", 1) for e in _flag_values(argv, "--env"))
    assert env["CODEREPAIR_RESULTS_NONCE"] == "abc" and env["HOME"] == "/tmp"
    assert "CODEREPAIR_HOST_CANARY" not in env and "do-not-leak" not in " ".join(argv)
    joined = " ".join(argv)
    for forbidden in ("docker.sock", "--privileged", "--network host", "-v ", ".ssh"):
        assert forbidden not in joined
    image_at = argv.index("python:3.12-slim")
    assert argv[image_at + 1 :][:4] == ["-I", "-S", "-B", "/opt/coderepair/bootstrap.py"]


def test_docker_command_finds_python_and_reports_cpu_limits(tmp_path):
    # Both broke the first real run under Colima: the official images keep python3 in
    # /usr/local/bin (every container exited 127), and with soft == hard CPU limits Linux
    # sends SIGKILL (137) instead of SIGXCPU (152), so a spin loop was not labelled.
    argv, _ = _docker_argv(tmp_path)
    env = dict(e.split("=", 1) for e in _flag_values(argv, "--env"))
    assert "/usr/local/bin" in env["PATH"].split(":")
    assert _flag_values(argv, "--entrypoint") == ["python3"]
    (cpu,) = [u for u in _flag_values(argv, "--ulimit") if u.startswith("cpu=")]
    soft, hard = (int(v) for v in cpu.removeprefix("cpu=").split(":"))
    assert soft == SandboxLimits().cpu_seconds and hard > soft


def test_docker_command_rejects_unsafe_mounts_and_images(tmp_path):
    run_dir = new_run_dir()
    try:
        job = SandboxJob(run_dir.workspace)
        with pytest.raises(SandboxError, match="image"):
            build_run_argv(
                job,
                container_name="x",
                image="--privileged",
                bundle_dir=tmp_path,
                out_dir=run_dir.out,
            )
        with pytest.raises(SandboxError, match="bind-mounted"):
            build_run_argv(
                job,
                container_name="x",
                image="python:3.12-slim",
                bundle_dir=tmp_path / "a,readonly=false",
                out_dir=run_dir.out,
            )
    finally:
        run_dir.cleanup()


def test_factory_never_falls_back_to_the_host(bundle_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(DockerSandbox, "available", lambda self: (False, "no docker"))
    monkeypatch.setattr(SeatbeltSandbox, "available", lambda self: (False, "not macOS"))
    with pytest.raises(SandboxUnavailable, match="no repository code will be run"):
        make_sandbox("auto", tmp_path)
    with pytest.raises(SandboxUnavailable, match="unknown sandbox"):
        make_sandbox("host", tmp_path)


def test_factory_prefers_a_container(monkeypatch, tmp_path):
    monkeypatch.setattr(DockerSandbox, "available", lambda self: (True, "ok"))
    monkeypatch.setattr(SeatbeltSandbox, "available", lambda self: (True, "ok"))
    assert make_sandbox("auto", tmp_path).name == "docker"
    assert make_sandbox("seatbelt", tmp_path).name == "seatbelt"


# ------------------------------------------------------------- process monitoring


def test_capture_keeps_head_and_tail():
    capture = _Capture(keep_bytes=40)
    capture.feed(b"A" * 10 + b"B" * 100 + b"C" * 30)
    assert capture.truncated and capture.total == 140
    text = capture.text()
    assert text.startswith("A" * 10) and text.endswith("C" * 30)
    assert "100 bytes omitted" in text


def test_run_monitored_enforces_deadline_and_output_cap(tmp_path):
    sleeper = run_monitored(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        env={},
        cwd=str(tmp_path),
        wall_timeout_s=0.5,
        keep_output_bytes=100,
        output_hard_cap_bytes=1000,
    )
    assert sleeper.limit_exceeded == LIMIT_WALL_TIME and sleeper.duration_s < 10
    flood = run_monitored(
        [sys.executable, "-c", "import sys\nwhile True: sys.stdout.write('x' * 10000)"],
        env={},
        cwd=str(tmp_path),
        wall_timeout_s=20,
        keep_output_bytes=100,
        output_hard_cap_bytes=100_000,
    )
    assert flood.limit_exceeded == "output" and flood.output_truncated
    assert len(flood.stdout) < 200


# --------------------------------------------------------------------- judging


def _result(outcomes=None, **kw) -> SandboxResult:
    results = None if outcomes is None else TestResults(outcomes, (), 0)
    return SandboxResult("test", "test", 0, 0.1, results=results, **kw)


def test_judge_requires_every_expected_test():
    t = task("t01_paginate_off_by_one")
    everything = {test_id: "passed" for test_id in t.expected_tests}
    assert judge(t, _result(everything)).status == STATUS_RESOLVED
    missing_one = dict(everything)
    missing_one.pop(t.pass_to_pass[0])
    verdict = judge(t, _result(missing_one))
    assert not verdict.resolved and verdict.pass_to_pass_broken == {t.pass_to_pass[0]: "missing"}
    f2p_failing = {**everything, t.fail_to_pass[0]: "failed"}
    assert "fail-to-pass" in judge(t, _result(f2p_failing)).reason
    assert not judge(t, _result(None, problems=["no results file"])).resolved
    assert not judge(t, _result(everything, limit_exceeded="memory")).resolved
    assert not judge(t, _result(everything, problems=["exit status mismatch"])).resolved


# ------------------------------------------------- integration: real sandbox runs


@pytest.mark.parametrize("probe", PROBES, ids=[p.name for p in PROBES])
def test_abuse_probe_is_contained(sandbox, probe):
    report = run_probe(sandbox, probe)
    assert report.contained, report.details


def test_probes_detect_an_unconfined_runner(bundle_dir, monkeypatch):
    """Negative control: the same probes must report escapes when isolation is removed.

    Only probes that are harmless without a sandbox are used (they touch a temp
    canary, the temp workspace and an environment variable set by this test).
    """
    ok, why = SeatbeltSandbox(bundle_dir).available()
    if not ok:
        pytest.skip(why)
    real_env = seatbelt_mod.sandbox_env
    monkeypatch.setattr(seatbelt_mod, "build_profile", lambda **kw: "(version 1)(allow default)")
    monkeypatch.setattr(seatbelt_mod, "sandbox_env", lambda **kw: {**os.environ, **real_env(**kw)})
    unconfined = SeatbeltSandbox(bundle_dir)
    read_canary = _p(
        "read-canary",
        "read a secret",
        """
        def test_read():
            leak(open(CFG["canary_file"]).read())
        """,
        {"blocked"},
    )
    by_name = {p.name: p for p in PROBES}
    for probe in (read_canary, by_name["host-writes"], by_name["environment"]):
        report = run_probe(unconfined, probe)
        assert not report.contained, f"{probe.name} did not detect an unconfined run"


def test_fixture_outcomes_match_in_the_sandbox(sandbox):
    t = task("t06_coupon_threshold_multifile")
    report = validate_task(
        t, trusted_root=TASKS_DIR, runner=SandboxFixtureRunner(sandbox, SandboxLimits())
    )
    assert report.ok, report.problems


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_gold_patch_resolves_and_buggy_repo_does_not(sandbox, task_id):
    t = task(task_id)
    snapshot = snapshot_of(task_id)
    gold = apply_proposal(snapshot, t.load_solution())
    assert evaluate_patch(t, gold.changed_files, sandbox).resolved
    buggy = evaluate_patch(t, {}, sandbox)
    assert not buggy.resolved
    assert {k for k, v in buggy.fail_to_pass.items() if v != "passed"} == set(t.fail_to_pass)


def test_plausible_but_wrong_patch_is_not_resolved(sandbox):
    """The t08 patch a local model produced in the M1 smoke run breaks a pass-to-pass test."""
    t = task("t08_money_half_up")
    snapshot = snapshot_of("t08_money_half_up")
    wrong = PatchProposal(
        edits=[
            Edit(
                path="ledger/money.py",
                old="    return round(float(amount) * 100)\n",
                new="    return round(float(amount) * 100 + 0.5)\n",
            )
        ]
    )
    patch = apply_proposal(snapshot, wrong)
    assert patch.ok
    verdict = evaluate_patch(t, patch.changed_files, sandbox)
    assert not verdict.resolved
    assert (
        "tests/test_hidden_ledger.py::test_hidden_exact_cent_values_are_unchanged"
        in verdict.pass_to_pass_broken
    )


def test_visible_test_run_reports_failures(sandbox):
    result = run_repo_tests(snapshot_of("t01_paginate_off_by_one"), sandbox)
    assert result.completed
    assert result.results.ids_with("failed") == [
        "tests/test_core.py::test_first_page_starts_at_first_item"
    ]
    summary = describe_result(result)
    assert "1 failed" in summary and "FAILED  tests/test_core.py" in summary


def test_agent_runs_visible_tests_on_a_patched_copy(sandbox, tmp_path):
    t = task("t01_paginate_off_by_one")
    snapshot = snapshot_of("t01_paginate_off_by_one")
    run = propose_patch(
        snapshot,
        t.read_issue(),
        OracleBackend(t),
        runs_dir=tmp_path,
        task_id=t.id,
        sandbox=sandbox,
    )
    assert run.status == STATUS_PROPOSED
    assert run.tests is not None and run.tests.results.all_passed
    summary = run.summary_dict()
    assert summary["tests"]["counts"]["passed"] == 5 and summary["tests"]["failing"] == []
    kinds = [json.loads(line)["kind"] for line in (run.run_dir / "trace.jsonl").open()]
    assert kinds.index("sandbox_start") < kinds.index("sandbox_tests") < kinds.index("result")
    assert (t.repo_dir / "pager" / "core.py").read_text() == snapshot.text("pager/core.py")


def test_cli_evaluate_and_selftest(sandbox, capsys, monkeypatch):
    monkeypatch.setenv("CODEREPAIR_SANDBOX", sandbox.name)
    assert main(["evaluate", "t07_safe_join_prefix_escape", "--no-save", "--no-color"]) == 0
    assert "evaluation: RESOLVED" in capsys.readouterr().out
    assert main(["sandbox", "selftest", "--probe", "network", "--probe", "early-exit"]) == 0
    assert "2/2 probes contained" in capsys.readouterr().out


# ------------------------------------------------- regressions from the M2 review


def test_results_fifo_does_not_block(tmp_path):
    fifo = tmp_path / "results.json"
    os.mkfifo(fifo)
    with pytest.raises(ResultsError, match="not a regular file"):
        read_results_file(fifo, "n")


def test_results_with_huge_integers_are_rejected_not_crashing():
    data = b'{"nonce": "n", "tests": {}, "collect_errors": [], "exitstatus": ' + b"9" * 5000 + b"}"
    with pytest.raises(ResultsError, match="not valid JSON"):
        parse_results(data, "n")


def test_skipped_tests_do_not_count_as_failures():
    assert TestResults({"a": "passed", "b": "skipped"}, (), 0).all_passed
    assert not TestResults({"a": "skipped"}, (), 0).all_passed
    assert not TestResults({"a": "passed", "b": "error"}, (), 0).all_passed
    assert not TestResults({"a": "passed"}, ("tests/x.py",), 2).all_passed


def test_child_is_killed_when_the_monitor_fails(tmp_path):
    started: list[int] = []

    def broken_watchdog(pid):
        started.append(pid)
        raise RuntimeError("watchdog bug")

    with pytest.raises(RuntimeError):
        run_monitored(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env={},
            cwd=str(tmp_path),
            wall_timeout_s=30,
            keep_output_bytes=100,
            output_hard_cap_bytes=1000,
            watchdog=broken_watchdog,
        )
    with pytest.raises(ProcessLookupError):
        os.kill(started[0], 0)


def test_control_characters_are_stripped_from_captured_output():
    capture = _Capture(keep_bytes=1000)
    capture.feed(b"ok\x1b[2J\x00\tend\n")
    assert capture.text() == "ok�[2J�\tend\n"


def test_seatbelt_profile_hides_other_processes():
    profile = build_profile(read_paths=[], write_paths=[], exec_paths=[Path("/bin/x")])
    assert "(deny process-info*)" in profile
    assert "(allow process-info* (target self))" in profile
    sysctl_rule = next(line for line in profile.splitlines() if "sysctl-read" in line)
    assert "sysctl-name" in sysctl_rule and "kern.proc" not in sysctl_rule
    assert "(allow sysctl-read)" not in profile


def test_process_info_probe_catches_the_old_profile(bundle_dir, monkeypatch):
    """Negative control for the review finding: without the process-info rule, a test
    could read another process's environment through KERN_PROCARGS2."""
    ok, why = SeatbeltSandbox(bundle_dir).available()
    if not ok:
        pytest.skip(why)
    real = seatbelt_mod.build_profile

    def old_profile(**kw):
        return real(**kw).replace("(deny process-info*)\n", "")

    monkeypatch.setattr(seatbelt_mod, "build_profile", old_profile)
    sentinel_only = _p(
        "sentinel-env",
        "read the sentinel's environment",
        """
        import ctypes

        def test_read():
            libc = ctypes.CDLL(None, use_errno=True)
            mib = (ctypes.c_int * 3)(1, 49, CFG["sentinel_pid"])
            size = ctypes.c_size_t(1 << 16)
            buf = ctypes.create_string_buffer(1 << 16)
            assert libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0
        """,
        {"blocked"},
    )
    assert not run_probe(SeatbeltSandbox(bundle_dir), sentinel_only).contained


def test_docker_output_dir_is_size_capped(tmp_path):
    from coderepair.sandbox.docker import _OutputDirWatchdog

    watchdog = _OutputDirWatchdog(tmp_path, limit_mb=1)
    assert watchdog(0) is None
    (tmp_path / "big").write_bytes(b"\1" * (2 * 1024 * 1024))
    assert watchdog(0) == "disk"


ABORTING_CONFTEST = """\
def pytest_runtest_logreport(report):
    if report.when == "call" and report.nodeid.endswith("test_b"):
        raise RuntimeError("plugin crash")
"""


def test_an_aborted_session_is_never_complete(sandbox, tmp_path):
    """pytest writes the results file even after INTERNALERROR; those results are partial."""
    from coderepair.execution import run_repo_tests
    from coderepair.repo import ingest_repository

    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "conftest.py").write_text(ABORTING_CONFTEST)
    (root / "tests" / "test_x.py").write_text(
        "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n\n\ndef test_c():\n    pass\n"
    )
    result = run_repo_tests(ingest_repository(root, (tmp_path,)), sandbox)
    assert result.exit_code == 3
    assert not result.completed
    assert any("aborted (internal error" in p for p in result.problems), result.problems


def test_collection_errors_are_reported_not_treated_as_an_abort(sandbox, tmp_path):
    from coderepair.execution import run_repo_tests
    from coderepair.repo import ingest_repository

    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_x.py").write_text(
        "import missing_module\n\n\ndef test_a():\n    pass\n"
    )
    result = run_repo_tests(ingest_repository(root, (tmp_path,)), sandbox)
    assert result.exit_code == 2
    assert result.completed and result.problems == []
    assert result.results.collect_errors == ("tests/test_x.py",)
    assert not result.results.all_passed


def test_an_interrupted_session_without_collection_errors_is_never_complete(sandbox, tmp_path):
    from coderepair.execution import run_repo_tests
    from coderepair.repo import ingest_repository

    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_x.py").write_text(
        "import pytest\n\n\ndef test_a():\n    pass\n\n\n"
        "def test_b():\n    pytest.exit('stop here')\n\n\ndef test_c():\n    pass\n"
    )
    result = run_repo_tests(ingest_repository(root, (tmp_path,)), sandbox)
    assert result.exit_code == 2 and result.results is not None
    assert not result.results.collect_errors
    assert not result.completed
    assert any("aborted (interrupted" in p for p in result.problems), result.problems
