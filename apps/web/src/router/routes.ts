import type { Component } from 'vue'
import type { IconName } from '@/icons/icons'

export interface NavItem {
  path: string
  name: string
  label: string
  /** Shared by the sidebar link and the page title. */
  icon: IconName
  phase: string
  description: string
  component: () => Promise<Component>
}

/** Sidebar items, in display order. Also the source of the router's routes. */
export const navItems: NavItem[] = [
  {
    path: '/',
    name: 'overview',
    label: 'Overview',
    icon: 'overview',
    phase: '2',
    description: 'A single-glance summary of Pi health, services and running work.',
    component: () => import('@/views/OverviewView.vue'),
  },
  {
    path: '/pi',
    name: 'pi',
    label: 'Pi health',
    icon: 'pi',
    phase: '2',
    description: 'Hardware health for the Raspberry Pi: temperature, throttling, disk, memory and CPU.',
    component: () => import('@/views/PiView.vue'),
  },
  {
    path: '/services',
    name: 'services',
    label: 'Services',
    icon: 'services',
    phase: '2',
    description: 'Status and controls for the background services running on this Pi.',
    component: () => import('@/views/ServicesView.vue'),
  },
  { path: '/projects', name: 'projects', label: 'Projects', icon: 'tasks', phase: '8', description: 'Editable planning maps, Hermes coordination and shared project handoffs.', component: () => import('@/views/ProjectsView.vue') },
  {
    path: '/tasks',
    name: 'tasks',
    label: 'Tasks',
    icon: 'tasks',
    phase: '3',
    description: 'A task board that dispatches work to AI agents and tracks its progress.',
    component: () => import('@/views/TasksView.vue'),
  },
  {
    path: '/telemetry', name: 'telemetry', label: 'Telemetry', icon: 'activity', phase: '9',
    description: 'Jobs and their telemetry: assignee, agent and model, time and cost.',
    component: () => import('@/views/TelemetryView.vue'),
  },
  {
    path: '/agents',
    name: 'agents',
    label: 'Agents',
    icon: 'agents',
    phase: '3',
    description: 'The AI agents available on this machine and what each one is working on.',
    component: () => import('@/views/AgentsView.vue'),
  },
  {
    path: '/chat',
    name: 'chat',
    label: 'Chat',
    icon: 'chat',
    phase: '3b',
    description: 'Talk directly with an agent and review earlier conversations.',
    component: () => import('@/views/ChatView.vue'),
  },
  {
    path: '/mcp',
    name: 'mcp',
    label: 'MCP',
    icon: 'mcp',
    phase: '3b',
    description: 'Manage the MCP servers and tools that agents can call.',
    component: () => import('@/views/McpView.vue'),
  },
  {
    path: '/github',
    name: 'github',
    label: 'GitHub',
    icon: 'github',
    phase: '6',
    description: 'Repositories, open pull requests and issues for the projects managed here.',
    component: () => import('@/views/GithubView.vue'),
  },
  {
    path: '/reports', name: 'reports', label: 'Ops reports', icon: 'logs', phase: '6',
    description: 'Read the latest operational reports written by Hermes.',
    component: () => import('@/views/ReportsView.vue'),
  },
  {
    path: '/help', name: 'help', label: 'Help & how-tos', icon: 'chat', phase: '7',
    description: 'Step-by-step guides and local help chat with links to every feature.',
    component: () => import('@/views/HelpView.vue'),
  },
  { path: '/profile', name: 'profile', label: 'Settings', icon: 'settings', phase: '8', description: 'Your planning preferences, encrypted credentials and Discord connection.', component: () => import('@/views/ProfileView.vue') },
]

/** The icon for a section, by route name. */
export function navIcon(name: string): IconName {
  const item = navItems.find((n) => n.name === name)
  if (!item) throw new Error(`No nav item named ${name}`)
  return item.icon
}
