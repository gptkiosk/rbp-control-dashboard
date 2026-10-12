# Third-party notices

## Mac Control Dashboard (MCD)

RCD is derived from [Mac Control Dashboard](https://github.com/gptkiosk/mac-control-dashboard), used under the MIT License. MCD's copyright notices are kept in this repository's [LICENSE](LICENSE). The Mission Control notice below is carried forward unchanged from MCD.

## Agent runtimes launched by RCD

RCD includes adapters that start these runtimes as separate processes. Their code and binaries are not included in this repository. Users download and install them. RCD is not affiliated with or endorsed by either project.

| Runtime | Source | License |
| --- | --- | --- |
| ZeroClaw | [zeroclaw-labs/zeroclaw](https://github.com/zeroclaw-labs/zeroclaw) | MIT OR Apache-2.0, at the licensee's choice. The project also ships a `NOTICE` file. The ZeroClaw name and logo are trademarks of ZeroClaw Labs. |
| PicoClaw | [sipeed/picoclaw](https://github.com/sipeed/picoclaw) | MIT |

If you redistribute either binary, include its license files, and for ZeroClaw its `NOTICE` file. The full dependency review is in the [license audit](docs/release/license-audit.md).

## Mission Control icons

Six icons in `apps/web/src/icons/icons.ts` come from Mission Control by Builderz Labs, used under the MIT License below. They are `overview`, `agents`, `tasks`, `chat`, `activity` and `logs`. The other icons in that file were drawn for this project in the same style.

### MIT License

Copyright (c) 2026 Builderz Labs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
