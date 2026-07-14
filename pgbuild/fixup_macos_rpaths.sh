#!/usr/bin/env bash
#
# Rewrite absolute dylib install names in a Postgres install tree to @rpath-relative
# form, so the tree is relocatable and multiple installs (e.g. pginstall for PG16 and
# pginstall18 for PG18) can coexist in a single wheel.
#
# Why this is needed: Postgres bakes its absolute --prefix path into the install names
# and dependency references of every binary and dylib it builds. On macOS the wheel is
# made relocatable by `delocate`, which vendors those absolute-path deps into a single
# flat `.dylibs/` folder keyed by basename. With two Postgres versions in one wheel,
# both ship a `libpq.5.dylib`, so delocate aborts with:
#     DelocationError: Already planning to copy library with same basename as: libpq.5.dylib
# By rewriting each tree's internal references to @rpath/<name> (resolved via an
# @loader_path rpath into the tree's own lib dir), every dependency already resolves
# inside the wheel, delocate finds nothing external to copy, and the collision is gone.
#
# Usage: fixup_macos_rpaths.sh <install-prefix>
set -euo pipefail

PREFIX="${1:?usage: fixup_macos_rpaths.sh <install-prefix>}"

# macOS only; a no-op elsewhere (Linux/Windows repair tools mangle names and don't collide).
[ "$(uname)" = "Darwin" ] || exit 0

# All shared-library basenames shipped in this tree (newline-separated). Any dependency
# reference whose basename appears here points at one of our own libs and gets rewritten
# to @rpath/<name>. (Plain string + grep, to stay compatible with macOS's bash 3.2.)
OURS="$(find "$PREFIX/lib" -type f \( -name '*.dylib' -o -name '*.so' \) -exec basename {} \; | sort -u)"

is_mach_o() { file "$1" | grep -q 'Mach-O'; }

# Iterate every Mach-O file under bin/ and lib/.
while IFS= read -r f; do
    is_mach_o "$f" || continue

    # 1. Give dylibs an @rpath-relative install id.
    if [[ "$f" == *.dylib ]]; then
        install_name_tool -id "@rpath/$(basename "$f")" "$f"
    fi

    # 2. Rewrite every dependency that points at one of our own libs.
    while IFS= read -r dep; do
        base="$(basename "$dep")"
        if [[ "$dep" != "@rpath/$base" ]] && printf '%s\n' "$OURS" | grep -qxF "$base"; then
            install_name_tool -change "$dep" "@rpath/$base" "$f"
        fi
    done < <(otool -L "$f" | tail -n +2 | awk '{print $1}')

    # 3. Add an rpath so @rpath resolves to this tree's lib dir, relative to the file.
    reldir="$(cd "$(dirname "$f")" && pwd)"
    rel="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$PREFIX/lib" "$reldir")"
    install_name_tool -add_rpath "@loader_path/$rel" "$f" 2>/dev/null || true
done < <(find "$PREFIX/bin" "$PREFIX/lib" -type f)
