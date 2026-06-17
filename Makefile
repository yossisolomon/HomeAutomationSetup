.PHONY: lint toc check test
lint:
	python -m yamllint config/

toc:
	python scripts/gen_automations_toc.py

test:
	python -m pytest tests/ -v && bash tests/test_normalize_nodered.sh

# Manual one-shot config check. The CD poller (scripts/cd_deploy.py, backlog #17)
# now runs this automatically on every push to main and reloads/rolls back — so
# `make check` is just for ad-hoc local validation, no longer the deploy gate.
check:
	ssh blacky 'docker exec homeassistant python -m homeassistant --script check_config -c /config'
