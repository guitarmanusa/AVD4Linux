# Phase 1 build tooling for the AVD Linux client

PKG_CONFIG_PATH ?= /opt/freerdp3/usr/lib/x86_64-linux-gnu/pkgconfig
CFLAGS := -Wall -Wextra
LDFLAGS := -Wl,-rpath,/usr/lib/x86_64-linux-gnu

all: smartcard_channel_probe

smartcard_channel_probe: smartcard_channel_probe.c
	PKG_CONFIG_PATH=$(PKG_CONFIG_PATH) \
	cc $(CFLAGS) -o $@ $< $$(PKG_CONFIG_PATH=$(PKG_CONFIG_PATH) pkg-config --cflags --libs freerdp3) $(LDFLAGS)

check-pcsc:
	python3 pcsc_probe.py --select-piv

check-cli:
	python3 phase1_cli_baseline.py

check: check-pcsc check-cli smartcard_channel_probe
	./smartcard_channel_probe

clean:
	rm -f smartcard_channel_probe

.PHONY: all check check-pcsc check-cli clean