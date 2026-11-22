# The lettering font

`LiberationSans-Regular.ttf` is Liberation Sans 2.1.5 Regular, unmodified, from
the Liberation Fonts project (https://github.com/liberationfonts), as packaged by
Debian and Ubuntu (`fonts-liberation` 1:2.1.5-3). SHA-256:
`4659bc0c58c5028dd488ec928d41d9265db43d9b669fc14ca8b0832daca7b144`.

It is licensed under the SIL Open Font License 1.1, in `OFL.txt` beside it; the
font may be bundled with software and is not sold by itself.

`build.py` passes this file's path to `text()`. A script never names a font or a
path: the slim Gateway image has no system fonts, and a path from a script would
reach the file system. Liberation Sans has the widths of Arial, the font CadQuery
names by default, so lettering sized for CadQuery elsewhere comes out the same
width here, and it is about half the size of DejaVu Sans.
