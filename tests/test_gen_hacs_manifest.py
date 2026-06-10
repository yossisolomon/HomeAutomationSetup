import os

import pytest
from scripts import gen_hacs_manifest as f

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "hacs_repositories_sample.json")


def test_load_store_returns_repo_list():
    rows = f.load_store(FIXTURE)
    assert isinstance(rows, list)
    assert len(rows) == 3
    assert any(r["full_name"] == "marsh4200/ar_smart_ir" for r in rows)


def test_load_store_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        f.load_store("/no/such/hacs.repositories")


def test_installed_plugins_filters_and_normalizes():
    rows = f.load_store(FIXTURE)
    plugins = f.installed_plugins(rows)
    names = [p["full_name"] for p in plugins]
    # only installed, sorted by full_name
    assert names == ["marsh4200/ar_smart_ir", "rospogrigio/localtuya"]


def test_installed_plugins_version_pin_tag_then_commit():
    plugins = {p["full_name"]: p for p in f.installed_plugins(f.load_store(FIXTURE))}
    assert plugins["rospogrigio/localtuya"]["version"] == "2025.5.0"
    assert plugins["marsh4200/ar_smart_ir"]["version"] == \
        "commit:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_installed_plugins_defaults_source_and_derives_repo():
    p = f.installed_plugins(f.load_store(FIXTURE))[0]
    assert p["source"] == "custom-repo"
    assert p["repo"] == "https://github.com/marsh4200/ar_smart_ir"
    assert p["category"] == "integration"
    assert p["domain"] == "ar_smart_ir"


def test_render_manifest_has_runbook_and_entries():
    plugins = f.installed_plugins(f.load_store(FIXTURE))
    text = f.render_manifest(plugins)
    assert "REBUILD RUNBOOK" in text
    assert "plugins:" in text
    assert "full_name: marsh4200/ar_smart_ir" in text
    assert "version: 'commit:bbbbbbbb" in text  # commit pins quoted
    assert "version: '2025.5.0'" in text
    # deterministic ordering: ar_smart_ir entry precedes localtuya entry
    assert text.index("marsh4200/ar_smart_ir") < text.index("rospogrigio/localtuya")


def test_resolve_storage_prefers_explicit():
    assert f.resolve_storage_path("/x/y", env={}) == "/x/y"


def test_resolve_storage_uses_sudo_user():
    got = f.resolve_storage_path(None, env={"SUDO_USER": "yossi"})
    assert got == "/home/yossi/homeassistant/config/.storage/hacs.repositories"


def test_main_writes_manifest(tmp_path):
    out = tmp_path / "hacs-manifest.yaml"
    rc = f.main(["--storage", FIXTURE, "--out", str(out)])
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "marsh4200/ar_smart_ir" in body and "rospogrigio/localtuya" in body


def test_main_zero_installed_is_error(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text('{"data": []}', encoding="utf-8")
    out = tmp_path / "m.yaml"
    rc = f.main(["--storage", str(empty), "--out", str(out)])
    assert rc != 0
    assert not out.exists()


def test_render_manifest_quotes_version_to_keep_it_a_string():
    plugins = [{"full_name": "x/y", "domain": "y", "category": "integration",
                "version": "1.9", "source": "custom-repo", "repo": "https://github.com/x/y"}]
    text = f.render_manifest(plugins)
    assert "version: '1.9'" in text


def test_main_malformed_store_is_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    out = tmp_path / "m.yaml"
    rc = f.main(["--storage", str(bad), "--out", str(out)])
    assert rc == 2
    assert not out.exists()


def test_installed_plugins_sort_is_case_insensitive():
    rows = [
        {"full_name": "XiaoMi/ha_xiaomi_home", "installed": True},
        {"full_name": "hacs/integration", "installed": True},
    ]
    names = [p["full_name"] for p in f.installed_plugins(rows)]
    assert names == ["hacs/integration", "XiaoMi/ha_xiaomi_home"]
