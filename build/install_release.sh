#!/usr/bin/env bash
# Install the EnergyPlus 26.2.0 release for Linux, as distributed by its developers, into
# ~/EnergyPlus/EnergyPlus-26-2-0 (no root needed), checking the download against its SHA-256.
# This is the "release" configuration of the paper. Another folder can be given as the first
# argument; then set ENERGYPLUS_RELEASE to it before running the tests (see configurations.py).
# Usage (repository root): build/install_release.sh [install folder]
set -euo pipefail

TAG=v26.2.0
DEST=${1:-"$HOME/EnergyPlus/EnergyPlus-26-2-0"}
ARCH=$(uname -m)
. /etc/os-release

# Release assets of v26.2.0 (commit 4bd7a1f26f) and their SHA-256. The paper's runs used the
# Ubuntu 24.04 x86_64 build.
case "$ID-$ARCH" in
  ubuntu-x86_64)
    ASSET=EnergyPlus-26.2.0-4bd7a1f26f-Linux-Ubuntu24.04-x86_64.tar.gz
    SHA=b848da8236482a2171a67d7eab00c82162105b653ffab3ae3b6c2217c433a8a1 ;;
  ubuntu-aarch64)
    ASSET=EnergyPlus-26.2.0-4bd7a1f26f-Linux-Ubuntu24.04-arm64.tar.gz
    SHA=55c56e47dfca6ca3a967c9442d2f1d934e4806bcec40a0e41c3d03d1ad67fae8 ;;
  *-x86_64)
    ASSET=EnergyPlus-26.2.0-4bd7a1f26f-Linux-AlmaLinux9.6-x86_64.tar.gz
    SHA=dd7f50ee1573e6eed6f870e43fcf09d2e34d30941d836a29df305b20f69e0180 ;;
  *) echo "No Linux release build for $ID on $ARCH" >&2; exit 1 ;;
esac

if [ -x "$DEST/energyplus" ]; then
  echo "Already installed: $("$DEST/energyplus" --version)"
  exit 0
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL -o "$TMP/$ASSET" "https://github.com/NatLabRockies/EnergyPlus/releases/download/$TAG/$ASSET"
echo "$SHA  $TMP/$ASSET" | sha256sum -c -
mkdir -p "$(dirname "$DEST")"
tar -xzf "$TMP/$ASSET" -C "$TMP"
mv "$TMP/${ASSET%.tar.gz}" "$DEST"
echo "Installed: $("$DEST/energyplus" --version)"
