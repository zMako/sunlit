#!/bin/sh
# Fetch the vendored runtime assets (not in git): three.js 0.170 build + addons (with Draco decoders) and three CC0 HDRIs.
set -e; cd "$(dirname "$0")"; mkdir -p three hdri
cd three && curl -sL -o three.tgz https://registry.npmjs.org/three/-/three-0.170.0.tgz && tar -xzf three.tgz && rm -rf build jsm && mv package/build . && mv package/examples/jsm ./jsm && rm -rf package three.tgz && cd ..
cd hdri && for n in studio_small_09 kloofendal_48d_partly_cloudy_puresky brown_photostudio_02; do curl -sL -o $n.hdr "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/${n}_2k.hdr"; done
