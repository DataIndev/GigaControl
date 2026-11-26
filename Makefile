CC := gcc
CFLAGS := -O2 -Wall -Wextra -Werror -DAPP_VERSION=\"1.0.0\"
PYTHON := python3

BUILD_DIR := build
STAGE_DIR := $(BUILD_DIR)/stage
BIN_OUT := $(BUILD_DIR)/gigabyte-control-center
PYZ_OUT := $(BUILD_DIR)/gigabyte-control-center.pyz
HELPER_OUT := $(BUILD_DIR)/apply_power_tuning.sh
HOTKEY_INSTALLER_OUT := $(BUILD_DIR)/install-hotkeys-driver.sh

PREFIX ?= $(HOME)/.local
BINDIR := $(PREFIX)/bin
DATADIR := $(PREFIX)/share/gigabyte-control-center
ICONDIR := $(PREFIX)/share/icons/hicolor/scalable/apps
APPDIR := $(PREFIX)/share/applications

.PHONY: all compile-py install-user test clean kernel-module

all: $(BIN_OUT) $(PYZ_OUT) $(HELPER_OUT) $(HOTKEY_INSTALLER_OUT)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BIN_OUT): src/launcher.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ $<
	strip --strip-unneeded $@

$(PYZ_OUT): $(shell find gigacc -type f) assets/gigabyte-control-center.svg | $(BUILD_DIR)
	rm -rf $(STAGE_DIR)
	mkdir -p $(STAGE_DIR)
	cp -r gigacc $(STAGE_DIR)/gigacc
	cp assets/gigabyte-control-center.svg $(STAGE_DIR)/gigacc/app-icon.svg
	find $(STAGE_DIR) -name '__pycache__' -type d -exec rm -rf {} +
	$(PYTHON) -m compileall -q $(STAGE_DIR)/gigacc
	$(PYTHON) -m zipapp $(STAGE_DIR) -p "/usr/bin/python3" -m "gigacc.__main__:main" -c -o $@

$(HELPER_OUT): scripts/apply_power_tuning.sh | $(BUILD_DIR)
	cp $< $@
	chmod 0755 $@

$(HOTKEY_INSTALLER_OUT): scripts/install-hotkeys-driver.sh | $(BUILD_DIR)
	cp $< $@
	chmod 0755 $@

kernel-module:
	$(MAKE) -C kernel/gigactl-hotkeys

install-user: all
	mkdir -p $(BINDIR) $(DATADIR)/kernel/gigactl-hotkeys $(ICONDIR) $(APPDIR)
	install -m 0755 $(BIN_OUT) $(BINDIR)/gigabyte-control-center
	install -m 0644 $(PYZ_OUT) $(DATADIR)/gigabyte-control-center.pyz
	install -m 0755 $(HELPER_OUT) $(DATADIR)/apply_power_tuning.sh
	install -m 0755 $(HOTKEY_INSTALLER_OUT) $(DATADIR)/install-hotkeys-driver.sh
	install -m 0644 kernel/gigactl-hotkeys/gigactl_hotkeys.c $(DATADIR)/kernel/gigactl-hotkeys/gigactl_hotkeys.c
	install -m 0644 kernel/gigactl-hotkeys/Makefile $(DATADIR)/kernel/gigactl-hotkeys/Makefile
	install -m 0644 kernel/gigactl-hotkeys/dkms.conf $(DATADIR)/kernel/gigactl-hotkeys/dkms.conf
	install -m 0644 assets/gigabyte-control-center.svg $(ICONDIR)/gigabyte-control-center.svg
	install -m 0644 assets/gigabyte-control-center.svg $(ICONDIR)/io.github.gigactl.ControlCenter.svg
	sed "s|@BINDIR@|$(BINDIR)|g" assets/gigabyte-control-center.desktop.in > $(APPDIR)/io.github.gigactl.ControlCenter.desktop
	chmod 0644 $(APPDIR)/io.github.gigactl.ControlCenter.desktop
	@if [ -d "$(HOME)/.config/cosmic" ]; then \
		$(BINDIR)/gigabyte-control-center --install-hotkeys; \
	fi
	@if command -v update-desktop-database >/dev/null 2>&1; then \
		update-desktop-database $(APPDIR) >/dev/null 2>&1 || true; \
	fi
	@if command -v gtk-update-icon-cache >/dev/null 2>&1; then \
		gtk-update-icon-cache -f -t $(PREFIX)/share/icons/hicolor >/dev/null 2>&1 || true; \
	fi

test:
	$(PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf $(BUILD_DIR)
	-$(MAKE) -C kernel/gigactl-hotkeys clean >/dev/null 2>&1 || true
