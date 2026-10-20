# Porthaven: see and manage every app listening on a port.
.PHONY: run build dev test install uninstall

run: web/dist/index.html          ## start Porthaven and open it in the browser
	bin/porthaven

build:                             ## build the web UI into web/dist
	cd web && npm install --no-audit --no-fund && npm run build

web/dist/index.html:
	$(MAKE) build

dev:                               ## UI with hot reload on :7476 (start `bin/porthaven --no-open` first)
	cd web && npm run dev

test:                              ## backend tests (stdlib unittest) and UI type check
	PYTHONPATH=. python3 -m unittest discover -s tests -v
	cd web && npm run typecheck

install:                           ## put `porthaven` on your PATH (~/.local/bin)
	mkdir -p $(HOME)/.local/bin && ln -sf $(CURDIR)/bin/porthaven $(HOME)/.local/bin/porthaven
	@echo "Installed: $(HOME)/.local/bin/porthaven  (make sure ~/.local/bin is on your PATH)"

uninstall:
	rm -f $(HOME)/.local/bin/porthaven
