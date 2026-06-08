.PHONY: lint toc check test
lint:
	python -m yamllint config/

toc:
	python scripts/gen_automations_toc.py

test:
	python -m pytest tests/ -v && bash tests/test_normalize_nodered.sh

check:
	ssh blacky 'docker exec homeassistant python -m homeassistant --script check_config -c /config'
