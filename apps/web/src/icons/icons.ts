/*
 * Icon set. Every icon is drawn on a 16 x 16 grid and rendered by AppIcon with
 * fill none, stroke currentColor, stroke-width 1.5, round caps and joins, so
 * the descriptors below carry geometry only. Keep 1 px clear of the edge.
 *
 * Attribution: the six icons `overview`, `agents`, `tasks`, `chat`,
 * `activity` and `logs` are reused verbatim from Mission Control by Builderz
 * Labs (MIT License, Copyright (c) 2026 Builderz Labs). See
 * THIRD_PARTY_NOTICES.md at the repository root. All other icons are drawn
 * for this project in the same style.
 */

export type IconName =
  // Reused from Mission Control (MIT, Builderz Labs)
  | 'overview'
  | 'agents'
  | 'tasks'
  | 'chat'
  | 'activity'
  | 'logs'
  // Drawn for this project
  | 'pi'
  | 'services'
  | 'mcp'
  | 'github'
  | 'bug'
  | 'cpu'
  | 'gpu'
  | 'memory'
  | 'swap'
  | 'disk'
  | 'temperature'
  | 'power'
  | 'network'
  | 'fan'
  | 'updates'
  | 'peers'
  | 'apps'
  | 'approval'
  | 'run'
  | 'stop'
  | 'trash'
  | 'clock'
  | 'tokens'
  | 'cost'
  | 'model'
  | 'alert'
  | 'check'
  | 'close'
  | 'plus'
  | 'copy'
  | 'back'
  | 'refresh'
  | 'send'
  | 'tag'
  | 'filter'
  | 'eye'
  | 'eye-off'
  | 'link'
  | 'user'
  | 'calendar'
  | 'flag'
  | 'chevron-down'
  | 'chevron-right'
  | 'hourglass'
  | 'search'
  | 'sun'
  | 'moon'
  | 'settings'

export interface IconElement {
  tag: 'path' | 'rect' | 'circle' | 'polyline' | 'line'
  attrs: Record<string, string | number>
}

const path = (d: string, extra: Record<string, string | number> = {}): IconElement => ({
  tag: 'path',
  attrs: { d, ...extra },
})
const rect = (x: number, y: number, width: number, height: number, rx: number): IconElement => ({
  tag: 'rect',
  attrs: { x, y, width, height, rx },
})
const circle = (cx: number, cy: number, r: number): IconElement => ({ tag: 'circle', attrs: { cx, cy, r } })
const polyline = (points: string): IconElement => ({ tag: 'polyline', attrs: { points } })
const line = (x1: number, y1: number, x2: number, y2: number): IconElement => ({
  tag: 'line',
  attrs: { x1, y1, x2, y2 },
})

/** A zero-length stroke with round caps draws a dot of the stroke width. */
const dot = (x: number, y: number): IconElement => path(`M${x} ${y}h.01`)

/** One fan blade; the three blades are this shape rotated about the hub. */
const blade = (deg: number): IconElement =>
  path('M8 6.8C5.2 6.4 4.8 3 7.2 1.6c2.8.2 3.2 3.2.8 5.2z', { transform: `rotate(${deg} 8 8)` })

export const ICONS: Record<IconName, IconElement[]> = {
  // ---- Mission Control (verbatim) ----
  overview: [rect(1, 1, 6, 6, 1), rect(9, 1, 6, 6, 1), rect(1, 9, 6, 6, 1), rect(9, 9, 6, 6, 1)],
  agents: [circle(8, 5, 3), path('M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6')],
  tasks: [rect(2, 1, 12, 14, 1.5), path('M5 5h6M5 8h6M5 11h3')],
  chat: [
    path('M13 3H3a1 1 0 0 0-1 1v6l3-2h8a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1z'),
    path('M6 11v1a1 1 0 0 0 1 1h4l2 2v-4a1 1 0 0 0-1-1h-1'),
  ],
  activity: [polyline('1,8 4,8 6,3 8,13 10,6 12,8 15,8')],
  logs: [path('M3 2h10a1 1 0 011 1v10a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1z'), path('M5 5h6M5 8h6M5 11h3')],
  bug: [
    path('M5.5 6.5a2.5 3.5 0 0 1 5 0v3a2.5 3.5 0 0 1-5 0z'),
    path('M6.5 3.3L5.5 2M9.5 3.3L10.5 2'),
    path('M5.5 7.5H3M5.5 10H3.5M10.5 7.5H13M10.5 10H12.5'),
    path('M8 6.5v6'),
  ],

  // ---- Drawn for this project ----
  // A single-board computer: board outline, SoC and a row of header pins.
  pi: [rect(1, 3, 14, 10, 1.5), rect(5, 6, 4, 4, 0.5), path('M11 6h.01M11 8h.01M11 10h.01')],
  services: [
    path('M8 1.5L14.5 5 8 8.5 1.5 5z'),
    path('M1.5 8L8 11.5 14.5 8'),
    path('M1.5 11L8 14.5 14.5 11'),
  ],
  mcp: [path('M6 1.5V4M10 1.5V4'), path('M4 4h8v3a4 4 0 0 1-8 0z'), path('M8 11v3.5')],
  github: [
    circle(4.5, 3.5, 1.5),
    circle(4.5, 12.5, 1.5),
    circle(11.5, 5.5, 1.5),
    path('M4.5 5v6'),
    path('M11.5 7v.5a3 3 0 0 1-3 3H4.5'),
  ],
  cpu: [rect(4, 4, 8, 8, 1), path('M6 1.5V4M10 1.5V4M6 12v2.5M10 12v2.5M1.5 6H4M1.5 10H4M12 6h2.5M12 10h2.5')],
  gpu: [rect(1, 2.5, 14, 9, 1.5), circle(8, 7, 2.5), path('M4 11.5V14M8 11.5V14')],
  memory: [
    rect(1, 3, 14, 8, 1),
    path('M4.5 5.5v3M8 5.5v3M11.5 5.5v3'),
    path('M3 11v2.5M6 11v2.5M10 11v2.5M13 11v2.5'),
  ],
  swap: [
    path('M3 7V6a2 2 0 0 1 2-2h8'),
    path('M11 2l2 2-2 2'),
    path('M13 9v1a2 2 0 0 1-2 2H3'),
    path('M5 10l-2 2 2 2'),
  ],
  disk: [rect(2, 2, 12, 12, 2), path('M2 9h12'), dot(11, 11.5)],
  temperature: [path('M6 9.2V3.5a2 2 0 0 1 4 0v5.7a3 3 0 1 1-4 0z')],
  power: [path('M9 1.5L3 9h5l-1 5.5L13 7H8z')],
  network: [path('M5 14V2M2 5l3-3 3 3'), path('M11 2v12M8 11l3 3 3-3')],
  fan: [blade(0), blade(120), blade(240), circle(8, 8, 1)],
  updates: [path('M8 1.5v8M4.5 6.5L8 10l3.5-3.5'), path('M2 10.5V13a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-2.5')],
  peers: [
    circle(8, 3.5, 1.5),
    circle(3.5, 12, 1.5),
    circle(12.5, 12, 1.5),
    line(7.3, 4.8, 4.2, 10.7),
    line(8.7, 4.8, 11.8, 10.7),
    line(5, 12, 11, 12),
  ],
  apps: [rect(1, 5, 10, 9, 1.2), path('M1 8h10'), path('M4 5V3a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3')],
  approval: [path('M8 1.5L13.5 3.5v4c0 3.5-2.4 5.8-5.5 7-3.1-1.2-5.5-3.5-5.5-7v-4z'), path('M5.5 8l2 2 3-3.5')],
  run: [path('M4.5 2.5v11l9-5.5z')],
  stop: [rect(3, 3, 10, 10, 2)],
  trash: [
    path('M2 4h12'),
    path('M6 4V2.5h4V4'),
    path('M3.5 4l.7 9.5a1 1 0 0 0 1 .9h5.6a1 1 0 0 0 1-.9L12.5 4'),
    path('M6.5 7v4M9.5 7v4'),
  ],
  clock: [circle(8, 8, 6.5), polyline('8,4.5 8,8 10.5,9.5')],
  tokens: [path('M6.5 2L5.5 14M11.5 2l-1 12'), path('M3 5.5h11M2 10.5h11')],
  cost: [
    path('M8 1.5v13'),
    path('M11 5c0-1.2-1.3-2-3-2s-3 .9-3 2.2c0 3.1 6 1.6 6 4.6 0 1.3-1.3 2.2-3 2.2s-3-.8-3-2'),
  ],
  model: [path('M8 1.5L14 4.75v6.5L8 14.5 2 11.25v-6.5z'), path('M2 4.75L8 8l6-3.25M8 8v6.5')],
  alert: [path('M8 2l6.5 11.5h-13z'), path('M8 6.5v3'), dot(8, 11.5)],
  check: [polyline('3,8.5 6.5,12 13,4')],
  close: [path('M3.5 3.5l9 9M12.5 3.5l-9 9')],
  plus: [path('M8 3v10M3 8h10')],
  copy: [rect(5.5, 5.5, 8.5, 8.5, 1.5), path('M10.5 5.5V3a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v6.5a1 1 0 0 0 1 1h2.5')],
  back: [path('M13.5 8h-11M7 3.5L2.5 8 7 12.5')],
  refresh: [path('M13.5 8a5.5 5.5 0 1 1-1.7-4'), path('M13.5 2v3.5H10')],
  send: [path('M14 2L7 9'), path('M14 2l-4.5 12-2.5-5.5L1.5 6z')],
  tag: [path('M2.5 8.2V3a.5.5 0 0 1 .5-.5h5.2l5.3 5.3a1 1 0 0 1 0 1.4l-4 4a1 1 0 0 1-1.4 0z'), dot(5.5, 5.5)],
  filter: [path('M2 3h12L9.5 8.5V13l-3 1.5V8.5z')],
  eye: [path('M2 8s2.3-4.5 6-4.5S14 8 14 8s-2.3 4.5-6 4.5S2 8 2 8z'), circle(8, 8, 2)],
  'eye-off': [
    path('M4.4 5.1C3 6.2 2 8 2 8s2.3 4.5 6 4.5c.9 0 1.7-.2 2.4-.6'),
    path('M6.8 3.7c.4-.1.8-.2 1.2-.2 3.7 0 6 4.5 6 4.5s-.5.9-1.4 1.9'),
    path('M6.6 6.6a2 2 0 0 0 2.8 2.8'),
    path('M2.5 2.5l11 11'),
  ],
  link: [
    path('M6.5 9.5l3-3'),
    path('M7 4.5l.8-.8a2.5 2.5 0 0 1 3.5 3.5l-.8.8'),
    path('M9 11.5l-.8.8a2.5 2.5 0 0 1-3.5-3.5l.8-.8'),
  ],
  user: [circle(8, 5.5, 2.5), path('M3 14v-.5A3.5 3.5 0 0 1 6.5 10h3a3.5 3.5 0 0 1 3.5 3.5v.5')],
  calendar: [rect(2, 3, 12, 11, 1.5), path('M2 7h12M5.5 1.5v3M10.5 1.5v3')],
  flag: [path('M3.5 14.5V2'), path('M3.5 3h8.5l-2 3 2 3H3.5')],
  'chevron-down': [polyline('4,6 8,10 12,6')],
  'chevron-right': [polyline('6,4 10,8 6,12')],
  hourglass: [
    path('M4 1.5h8M4 14.5h8'),
    path('M5 1.5c0 3 3 4 3 6.5s-3 3.5-3 6.5'),
    path('M11 1.5c0 3-3 4-3 6.5s3 3.5 3 6.5'),
  ],
  search: [circle(7, 7, 4.5), path('M10.5 10.5L14 14')],
  sun: [circle(8, 8, 3), path('M8 1v1M8 14v1M1 8h1M14 8h1M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1')],
  moon: [path('M13.5 9.5A5.8 5.8 0 0 1 6.5 2a6 6 0 1 0 7 7.5z')],
  settings: [path('M3 2v12M8 2v12M13 2v12'), circle(3,5,1.5),circle(8,11,1.5),circle(13,6,1.5)],
}
