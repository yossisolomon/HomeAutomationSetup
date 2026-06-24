import pathlib, importlib.util

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "gen_automations_toc.py")
gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)


def write(p, text): p.write_text(text, encoding="utf-8")


def test_parse_meta_basic():
    m = gen.parse_meta('intent="turn on filter"; waf=high; mode=auto')
    assert m == {"intent": "turn on filter", "waf": "high", "mode": "auto"}


def test_parse_automations_with_meta(tmp_path):
    f = tmp_path / "automations.yaml"
    write(f, '# meta: intent="boiler done"; waf=med; mode=cta\n'
             '- alias: "boiler-thermostat-click"\n'
             '  trigger: []\n')
    entries = gen.parse_automations(f)
    assert len(entries) == 1
    e = entries[0]
    assert e.name == "boiler-thermostat-click"
    assert e.engine == "HA-automation"
    assert e.meta == {"intent": "boiler done", "waf": "med", "mode": "cta"}


def test_parse_automations_missing_meta(tmp_path):
    f = tmp_path / "automations.yaml"
    write(f, '- alias: "no-meta-here"\n  trigger: []\n')
    entries = gen.parse_automations(f)
    assert entries[0].meta is None


def test_parse_scripts_dict(tmp_path):
    f = tmp_path / "scripts.yaml"
    write(f, '# meta: intent="ask via telegram"; waf=low; mode=cta\n'
             'notify_owner:\n'
             '  alias: "presence-notify-owner"\n'
             '  sequence: []\n')
    entries = gen.parse_scripts(f)
    assert entries[0].name == "presence-notify-owner"
    assert entries[0].engine == "HA-script"
    assert entries[0].meta["mode"] == "cta"


def test_parse_scripts_multiple_each_keep_meta(tmp_path):
    f = tmp_path / "scripts.yaml"
    write(f, '# meta: intent="first cta"; waf=med; mode=cta\n'
             'first_script:\n'
             '  alias: "climate-cta-window-vs-ac"\n'
             '  sequence: []\n'
             '# meta: intent="second cta"; waf=low; mode=cta\n'
             'second_script:\n'
             '  alias: "climate-cta-window-ac-off-prompt"\n'
             '  sequence: []\n')
    entries = gen.parse_scripts(f)
    assert len(entries) == 2
    by_name = {e.name: e for e in entries}
    assert by_name["climate-cta-window-vs-ac"].meta["intent"] == "first cta"
    assert by_name["climate-cta-window-ac-off-prompt"].meta == {
        "intent": "second cta", "waf": "low", "mode": "cta"}


def test_empty_list_file(tmp_path):
    f = tmp_path / "automations.yaml"; write(f, "[]\n")
    assert gen.parse_automations(f) == []


def test_flows_absent_dir(tmp_path):
    assert gen.parse_flows(tmp_path / "nope") == []


def test_parse_flows_tab_meta(tmp_path):
    d = tmp_path / "flows"; d.mkdir()
    write(d / "climate.json",
          '[{"id":"a","type":"tab","label":"climate-window-cta",'
          '"info":"some notes\\nmeta: intent=\\"window vs ac\\"; waf=med; mode=cta"}]')
    entries = gen.parse_flows(d)
    assert entries[0].name == "climate-window-cta"
    assert entries[0].engine == "NodeRED"
    assert entries[0].meta["mode"] == "cta"


def test_render_table_columns():
    e = gen.Entry("boiler-thermostat-click", "HA-automation", "automations.yaml",
                  {"intent": "boiler done", "waf": "med", "mode": "cta"})
    table = gen.render_table([e])
    assert "| name | engine | file | intent | waf | mode |" in table
    assert "boiler-thermostat-click" in table and "cta" in table


def test_replace_block_roundtrip(tmp_path):
    doc = tmp_path / "automations.md"
    write(doc, f"# Automations\n\n{gen.START}\nOLD\n{gen.END}\n\nfooter\n")
    gen.replace_block(doc, "NEWTABLE")
    out = doc.read_text(encoding="utf-8")
    assert "NEWTABLE" in out and "OLD" not in out and "footer" in out


def test_check_missing_meta_fails():
    problems = gen.check([gen.Entry("x", "HA-automation", "automations.yaml", None)])
    assert any("meta" in p for p in problems)


def test_check_duplicate_names_fails():
    es = [gen.Entry("dup", "HA-automation", "a.yaml", {"intent": "i", "waf": "low", "mode": "auto"}),
          gen.Entry("dup", "NodeRED", "b.json", {"intent": "i", "waf": "low", "mode": "auto"})]
    problems = gen.check(es)
    assert any("duplicate" in p.lower() for p in problems)
