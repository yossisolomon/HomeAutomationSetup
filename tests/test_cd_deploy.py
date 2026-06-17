from scripts import cd_deploy as c


# ── classify_changes (pure) ──────────────────────────────────────────────────
def test_classify_none_for_docs_and_other_services():
    for f in ["README.md", "docs/state-of-world.md", "grafana/provisioning/alerting/rules.yml",
              "prometheus/config/prometheus.yml", "scripts/cd_deploy.py", ".github/workflows/ci.yml",
              "config/AGENTS.md"]:
        assert c.classify_changes([f])["action"] == "none", f


def test_classify_reload_single():
    p = c.classify_changes(["config/automations.yaml"])
    assert p["action"] == "reload"
    assert p["reload_services"] == ["automation/reload"]


def test_classify_reload_merges_services_sorted_unique():
    p = c.classify_changes([
        "config/automations.yaml", "config/scripts.yaml", "config/scenes.yaml",
        "config/template/purifier_auto.yaml", "config/blueprints/script/x.yaml",
    ])
    assert p["action"] == "reload"
    # blueprints contribute automation+script reload; dedup with the explicit ones
    assert p["reload_services"] == [
        "automation/reload", "scene/reload", "script/reload", "template/reload",
    ]


def test_classify_restart_for_configuration():
    assert c.classify_changes(["config/configuration.yaml"])["action"] == "restart"


def test_classify_restart_for_heavy_paths():
    for f in ["config/secrets.yaml", "config/packages/foo.yaml",
              "config/custom_components/hacs/x.py", "docker-compose.yml",
              "requirements-dev.txt", "scripts/requirements.txt", "hacs-manifest.yaml",
              "config/input_boolean.yaml"]:
        assert c.classify_changes([f])["action"] == "restart", f


def test_classify_mixed_reload_and_restart_is_restart():
    # superset-safe: any restart-trigger forces a restart even alongside reload-safe files
    p = c.classify_changes(["config/automations.yaml", "config/configuration.yaml"])
    assert p["action"] == "restart"
    assert p["reload_services"] == []


def test_classify_ignores_non_ha_alongside_reload():
    # docs changed with a reload-safe file -> still just a reload
    p = c.classify_changes(["config/automations.yaml", "docs/x.md", "grafana/y.json"])
    assert p["action"] == "reload"


def test_is_ha_relevant_excludes_markdown_under_config():
    assert c.is_ha_relevant("config/AGENTS.md") is False
    assert c.is_ha_relevant("config/automations.yaml") is True


def test_reload_services_for_blueprints():
    assert c.reload_services_for("config/blueprints/automation/z.yaml") == [
        "automation/reload", "script/reload"]


# ── parse_secret (pure) ──────────────────────────────────────────────────────
def test_parse_secret_plain():
    assert c.parse_secret("cd_deploy_token: abc123\n", "cd_deploy_token") == "abc123"


def test_parse_secret_strips_double_quotes():
    # the #18 footgun: a quote-wrapped token must be unwrapped or auth 401s
    assert c.parse_secret('prometheus_token: "ey.J.tok"\n', "prometheus_token") == "ey.J.tok"


def test_parse_secret_strips_single_quotes():
    assert c.parse_secret("k: 'v'\n", "k") == "v"


def test_parse_secret_missing_returns_none():
    assert c.parse_secret("a: 1\nb: 2\n", "c") is None


def test_parse_secret_exact_key_no_prefix_collision():
    text = "telegram_bot_token_backup: WRONG\ntelegram_bot_token: RIGHT\n"
    assert c.parse_secret(text, "telegram_bot_token") == "RIGHT"


def test_parse_secret_skips_comments():
    assert c.parse_secret("# k: commented\nk: real\n", "k") == "real"


# ── main() flows (imperative helpers stubbed) ────────────────────────────────
class _CP:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _wire(monkeypatch, *, prev, target, files, check_rc=0, secrets="", reload_status=200,
          healthy=True):
    """Stub every imperative helper; record git subcommands + restart calls."""
    calls = {"git": [], "restart": 0, "reload": [], "alerts": []}

    def fake_git(args, cwd):
        calls["git"].append(args)
        return _CP(returncode=0)

    monkeypatch.setattr(c, "git", fake_git)
    monkeypatch.setattr(c, "rev", lambda cwd, ref: prev if ref == "HEAD" else target)
    monkeypatch.setattr(c, "changed_files", lambda cwd, a, b: list(files))
    monkeypatch.setattr(c, "check_config", lambda container: check_rc)
    monkeypatch.setattr(c, "_read_secrets", lambda path: secrets)
    monkeypatch.setattr(c, "reload_via_api",
                        lambda base, tok, svc, **k: (calls["reload"].append(svc) or reload_status))
    monkeypatch.setattr(c, "restart_container",
                        lambda ha_dir, container: calls.update(restart=calls["restart"] + 1) or 0)
    monkeypatch.setattr(c, "wait_healthy", lambda base, **k: healthy)
    monkeypatch.setattr(c, "send_telegram",
                        lambda tok, chat, text: calls["alerts"].append(text))
    return calls


def _run(tmp_path, extra=None):
    argv = ["--ha-dir", str(tmp_path), "--lock", str(tmp_path / "lock")]
    return c.main(argv + (extra or []))


def test_main_noop_when_up_to_date(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, prev="aaaaaaaa", target="aaaaaaaa", files=[])
    assert _run(tmp_path) == 0
    assert calls["restart"] == 0 and calls["alerts"] == []
    assert not any(a[0] == "pull" for a in calls["git"])  # never pulled


def test_main_check_config_fail_rolls_back(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, prev="aaaaaaaa", target="bbbbbbbb",
                  files=["config/configuration.yaml"], check_rc=1)
    assert _run(tmp_path) == 4
    assert ["reset", "--hard", "aaaaaaaa"] in calls["git"]
    assert calls["restart"] == 0
    assert any("check_config FAILED" in a for a in calls["alerts"])


def test_main_reload_happy_path_no_restart(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, prev="aaaaaaaa", target="bbbbbbbb",
                  files=["config/automations.yaml"],
                  secrets="cd_deploy_token: tok\ntelegram_bot_token: t\ntelegram_chat_id: ch\n")
    assert _run(tmp_path) == 0
    assert calls["reload"] == ["automation/reload"]
    assert calls["restart"] == 0
    assert any("via reload" in a for a in calls["alerts"])


def test_main_reload_without_token_escalates_to_restart(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, prev="aaaaaaaa", target="bbbbbbbb",
                  files=["config/automations.yaml"], secrets="")  # no cd_deploy_token
    assert _run(tmp_path) == 0
    assert calls["reload"] == []          # never attempted (no token)
    assert calls["restart"] == 1          # escalated


def test_main_reload_api_failure_escalates_to_restart(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, prev="aaaaaaaa", target="bbbbbbbb",
                  files=["config/automations.yaml"],
                  secrets="cd_deploy_token: tok\n", reload_status=500)
    assert _run(tmp_path) == 0
    assert calls["reload"] == ["automation/reload"]  # attempted, failed
    assert calls["restart"] == 1                      # then escalated


def test_main_restart_unhealthy_rolls_back(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, prev="aaaaaaaa", target="bbbbbbbb",
                  files=["config/configuration.yaml"], healthy=False)
    assert _run(tmp_path) == 5
    assert ["reset", "--hard", "aaaaaaaa"] in calls["git"]
    assert calls["restart"] == 2  # initial recreate + post-rollback restart
    assert any("rolled back" in a for a in calls["alerts"])


def test_main_dry_run_applies_nothing(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, prev="aaaaaaaa", target="bbbbbbbb",
                  files=["config/configuration.yaml"])
    assert _run(tmp_path, ["--dry-run"]) == 0
    assert calls["restart"] == 0
    assert not any(a[0] == "pull" for a in calls["git"])
