# MCD brand assets

- `../public/favicon.svg`: browser tab icon (tile on a thin dark frame so it stays large at 16 px).
- `app-icon.svg`: full-bleed source for the PNG app icons (the OS applies its own corner mask).
- Mark: an M-shaped pulse (monitoring + "M" for Mac Control) in a rounded tile with a status dot,
  gradient #4c9aff -> #39c5cf (the dashboard's accent and series-6 colours).

Regenerate the PNGs on macOS:

    qlmanage -t -s 512 -o /tmp/mcd brand/app-icon.svg
    sips -z 512 512 /tmp/mcd/app-icon.svg.png --out public/icon-512.png
    sips -z 192 192 /tmp/mcd/app-icon.svg.png --out public/icon-192.png
    sips -z 180 180 /tmp/mcd/app-icon.svg.png --out public/apple-touch-icon.png
