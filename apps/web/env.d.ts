/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Short git SHA of the web build, baked in by vite.config.ts ('' if unavailable). */
  readonly VITE_APP_VERSION?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
