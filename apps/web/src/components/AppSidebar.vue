<script setup lang="ts">
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import { navItems } from '@/router/routes'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ navigate: [] }>()
</script>

<template>
  <aside id="app-sidebar" class="sidebar" :class="{ open }">
    <p class="nav-label">Workspace</p>
    <nav aria-label="Main">
      <ul>
        <li v-for="item in navItems.filter(n => n.name !== 'profile')" :key="item.name">
          <RouterLink :to="item.path" class="link" @click="emit('navigate')">
            <AppIcon :name="item.icon" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </nav>
    <nav class="settings-nav" aria-label="Settings"><ul><li v-for="item in navItems.filter(n => n.name === 'profile')" :key="item.name"><RouterLink :to="item.path" class="link" @click="emit('navigate')"><AppIcon :name="item.icon" /><span>{{ item.label }}</span></RouterLink></li></ul></nav>
  </aside>
</template>

<style scoped>
.sidebar {
  display:flex;
  flex-direction:column;
  width: var(--sidebar-width);
  flex: none;
  background: var(--panel);
  background-image: var(--nav-glass);
  border-right: 1px solid var(--surface-border);
  padding: var(--gap);
  overflow-y: auto;
}
.sidebar > nav { flex:none; }
.settings-nav { margin-top:auto; padding-top:var(--gap); border-top:1px solid var(--surface-border); }
.sidebar > nav[aria-label="Main"] { margin-bottom:var(--gap-lg); }

.nav-label {
  margin: var(--gap-sm) var(--gap-sm) var(--gap);
  color: var(--text-muted);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-strong);
  letter-spacing: var(--nav-letter-spacing);
  text-transform: uppercase;
}

ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.link {
  display: flex;
  align-items: center;
  gap: var(--icon-gap);
  min-height: var(--touch-target);
  padding: var(--gap-sm);
  border: 1px solid transparent;
  border-radius: var(--radius);
  color: var(--text-muted);
  transition: background var(--transition), color var(--transition);
}

.link:hover {
  background: var(--panel-raised);
  color: var(--text);
}

.link[aria-current='page'] {
  background: var(--nav-active);
  border-color: var(--surface-border);
  box-shadow: inset var(--nav-indicator-width) 0 0 var(--accent);
  color: var(--text);
  font-weight: var(--font-weight-strong);
}

@media (prefers-reduced-transparency: reduce) { .sidebar { background-image: none; } }

@media (max-width: 767.98px) {
  .sidebar {
    position: fixed;
    top: var(--topbar-height);
    bottom: 0;
    left: 0;
    z-index: var(--z-sidebar);
    box-shadow: var(--shadow);
    transform: translateX(-100%);
    visibility: hidden;
    transition: transform var(--transition), visibility var(--transition);
  }

  .sidebar.open {
    transform: translateX(0);
    visibility: visible;
  }
}
</style>
