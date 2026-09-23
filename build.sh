#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
revision=2d71c3b90185b85ca0e7530d128cb8ea175192c0
if [[ ! -d vendor/libqrencode/.git ]]; then
    mkdir -p vendor
    git clone --single-branch --branch invalid_null https://github.com/fukuchi/libqrencode.git vendor/libqrencode
    git -C vendor/libqrencode checkout "$revision"
fi
[[ "$(git -C vendor/libqrencode rev-parse HEAD)" == "$revision" ]] || { echo 'Unexpected vendor revision' >&2; exit 1; }
mkdir -p build
cc -O2 -fPIC -shared -DSTATIC_IN_RELEASE= -DMAJOR_VERSION=3 -DMINOR_VERSION=9 -DMICRO_VERSION=0 '-DVERSION="3.9.0-invalid_null"' \
  -o build/libqrencode-tail.so \
  qr-tail-encode.c \
  vendor/libqrencode/{qrinput,bitstream,qrspec,rsecc,split,mask,mqrspec,mmask}.c
