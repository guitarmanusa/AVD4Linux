# Packaging & Flathub Distribution Guide for AVD4Linux

This document describes how to build, bundle, test, and distribute **AVD4Linux** (native Linux client for Azure Virtual Desktop) as a standalone Flatpak and submit it to Flathub.

---

## 1. Building a Standalone Flatpak Bundle Locally

### Prerequisites
Install `flatpak` and `flatpak-builder` on your build machine:
```bash
# Ubuntu / Debian
sudo apt install flatpak flatpak-builder

# Fedora
sudo dnf install flatpak flatpak-builder

# Arch Linux
sudo pacman -S flatpak flatpak-builder
```

Install the GNOME 47 Platform & SDK:
```bash
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.gnome.Platform//47 org.gnome.Sdk//47
```

### Build the Application
From the repository root:
```bash
# Build into a local build directory
flatpak-builder --force-clean --user --install-deps-from=flathub build-dir packaging/flatpak/org.avd4linux.AVD4Linux.yaml

# Create a single-file standalone .flatpak bundle
flatpak-builder --export-only --repo=repo build-dir packaging/flatpak/org.avd4linux.AVD4Linux.yaml
flatpak build-bundle repo org.avd4linux.AVD4Linux.flatpak org.avd4linux.AVD4Linux
```

You now have a standalone `org.avd4linux.AVD4Linux.flatpak` binary!

---

## 2. Installing the Standalone Bundle on Any Linux Machine

Anyone can install and run the standalone `.flatpak` bundle with:
```bash
# Install the bundle
flatpak install --user org.avd4linux.AVD4Linux.flatpak

# Run the application
flatpak run org.avd4linux.AVD4Linux

# Or launch it from your desktop application launcher (GNOME, KDE, etc.)
```

---

## 3. Submitting to Flathub

Flathub is the central app store for Linux applications. The submission process is fully automated via GitHub:

### Step 1: Fork the Flathub Repository
1. Visit [https://github.com/flathub/flathub](https://github.com/flathub/flathub).
2. Create a new branch named `new-pr/org.avd4linux.AVD4Linux`.

### Step 2: Add Manifest and Metadata
Copy the following files into the branch root:
- `org.avd4linux.AVD4Linux.yaml` (from `packaging/flatpak/`)
- `org.avd4linux.AVD4Linux.metainfo.xml` (from `data/`)
- `org.avd4linux.AVD4Linux.desktop` (from `data/`)
- `org.avd4linux.AVD4Linux.svg` (from `data/`)

### Step 3: Open a Pull Request
1. Open a Pull Request against `flathub/flathub`.
2. Flathub's automated buildbot will compile the package across `x86_64` and `aarch64`.
3. Once approved by Flathub reviewers, your application repository `flathub/org.avd4linux.AVD4Linux` will be created automatically.
4. Users worldwide can then install your app with a single command:
   ```bash
   flatpak install flathub org.avd4linux.AVD4Linux
   ```

---

## 4. Automated CI/CD (GitHub Actions)

This repository includes a GitHub Actions workflow at `.github/workflows/flatpak.yml`:
- On every push and pull request, GitHub Actions compiles the Flatpak and validates AppStream metadata.
- When you push a git release tag (e.g. `git tag v0.9.0 && git push origin v0.9.0`), GitHub Actions automatically builds `org.avd4linux.AVD4Linux.flatpak` and attaches the binary to your GitHub Release!
