# Vendored dependencies

## tomlkit 0.15.1 — MIT

    tomlkit-0.15.1-py3-none-any.whl
    sha256  177a05aece5a8ca5266fd3c448abb47b8d352f09d477d3ca8332db4d89b24304

Writes `registry.toml`. `tomllib` reads it and is stdlib, but cannot write, and a
rewrite that discards hand-written comments is not acceptable for a file you edit.

Vendored so clihub runs from a checkout with nothing installed. Shipped as the
upstream wheel rather than unpacked source: the unpacked form is 6,223 lines, more
than twice this project, and it would sit in every `grep`, file tree and line count.
The wheel is one file whose hash can be checked against PyPI.

Python imports from a zip natively, so the wheel goes on `sys.path` as-is. It is not
imported as `clihub._vendor.tomlkit` because tomlkit imports itself absolutely
(`from tomlkit.items import ...`).

The cost is that bytecode cannot be cached inside a zip, so tomlkit is recompiled
on each process that imports it — about 38 ms. Only registry mutations pay it;
dispatch, `list`, `find` and `doctor` never import it at all.

To update: drop in the new wheel, delete the old one, and update the version and
hash above.
