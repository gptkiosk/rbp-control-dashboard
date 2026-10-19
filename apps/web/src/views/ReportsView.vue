<script setup lang="ts">
import ReportStoragePanel from '@/components/ReportStoragePanel.vue'
import OpsHealthPanel from '@/components/OpsHealthPanel.vue'
import ReportFindings from '@/components/ReportFindings.vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import PageHead from '@/components/PageHead.vue'
import AppSelect from '@/components/AppSelect.vue'
import { usePolledJson } from '@/composables/usePolledJson'
import { bytesLabel, dateLabel, type Reports, type ReportContent } from '@/lib/operations'
import { REPORT_KIND_LABEL, ago, filterReports, reportKind, type ReportKind } from '@/lib/opsHealth'
import { actionableFindings } from '@/lib/findings'
import { renderReport } from '@/lib/reportMarkdown'

const route = useRoute()
const router = useRouter()
const { data, error, loaded, refresh } = usePolledJson<Reports>('/api/reports', 60000)
// A `?report=<id>` link opens that exact report; without it the newest one is selected.
const selected = ref(typeof route.query.report === 'string' ? route.query.report : '')
const health = ref<{ refresh: () => void } | null>(null)
const query = ref('')
const kind = ref<ReportKind | 'all'>('all')
const now = ref(Date.now() / 1000)
const reports = computed(() => data.value?.reports ?? [])
const visible = computed(() => filterReports(reports.value, query.value, kind.value))
watch(data, () => { now.value = Date.now() / 1000 })
watch(reports, list => { if (!list.some(r => r.id === selected.value)) selected.value = list[0]?.id ?? '' })
const current = computed(() => reports.value.find(r => r.id === selected.value))
const archived = computed(() => !!current.value && reportKind(current.value) === 'archived')
const path = computed(() => selected.value ? `/api/reports/${selected.value}` : '/api/reports')
const { data: rawContent, error: contentError, loaded: contentLoaded, refresh: refreshContent } = usePolledJson<ReportContent | Reports>(path, 60000)
const content = computed(() => rawContent.value && 'content' in rawContent.value ? rawContent.value : null)
const historical = computed(() => !!current.value && Date.now() / 1000 - current.value.modified_at > 86400)
const html = computed(() => content.value?.format === 'markdown' ? renderReport(content.value.content) : '')
const findings = computed(() => content.value ? actionableFindings(content.value.content) : [])
function reportLink(id: string) { return { path: '/reports', query: { report: id } } }
// Projects opens its New-project dialog from this report; coordination still needs the operator's explicit approval there.
function planProject() { if (current.value) void router.push({ path: '/projects', query: { from_report: current.value.id } }) }
function refreshAll() { refresh(); health.value?.refresh(); if (selected.value) refreshContent() }
</script>
<template>
  <section aria-labelledby="reports-title">
    <PageHead id="reports-title" title="Ops reports" icon="logs" sub="Hermes and local reports, latest first." help="reports"><button class="btn" @click="refreshAll">Refresh</button></PageHead>
    <ReportStoragePanel @changed="refreshAll" />
    <OpsHealthPanel ref="health" :reports="reports" />
    <p v-if="error || data?.error" role="status" class="notice-warn">{{ error || data?.error }}</p>
    <p v-if="!loaded" role="status" class="muted">Loading reports…</p>
    <div v-else-if="!reports.length" class="card empty"><h2>No reports yet</h2><p class="muted">Markdown and UTF-8 text reports will appear here when Hermes writes them to the report folder.</p><code>{{ data?.root }}</code><p v-if="data && !data.available" class="muted">The report folder is not available yet.</p></div>
    <template v-else>
      <div class="report-controls card">
        <div class="filters">
          <label>Search reports<input v-model="query" type="search" class="input" placeholder="Search by title, file or source" autocomplete="off" /></label>
          <label>Kind<AppSelect v-model="kind" aria-label="Kind"><option v-for="(text, value) in REPORT_KIND_LABEL" :key="value" :value="value">{{ text }}</option></AppSelect></label>
        </div>
        <label>Report<AppSelect v-model="selected" aria-label="Report"><option v-for="r in reports" :key="r.id" :value="r.id" :data-description="`${r.source || 'Ops report folder'} · ${dateLabel(r.modified_at)} · ${bytesLabel(r.size)}`">{{ r.title || r.name }}</option></AppSelect></label>
        <p class="muted">{{ reports.length }} reports<span v-if="data?.limited"> · Showing a capped list of up to 200 reports</span> · Preview limit 512 KiB · {{ visible.length }} match the filters</p>
      </div>
      <div class="reports-layout">
        <nav class="report-list" aria-label="Reports">
          <p v-if="!visible.length" class="muted">No reports match these filters.</p>
          <button v-for="r in visible" :key="r.id" class="card report-row" :class="{ selected: r.id === selected }" :aria-pressed="r.id === selected" @click="selected = r.id">
            <strong>{{ r.title || r.name }}</strong>
            <small v-if="reportKind(r) === 'archived'" class="severity" data-severity="archived">Archived copy · original unchanged</small>
            <small class="muted">{{ r.source }} · {{ ago(r.modified_at, now) }} · {{ bytesLabel(r.size) }}</small>
            <small v-if="!r.readable" class="muted">Too large to preview</small>
          </button>
        </nav>
        <article class="card report-content" :aria-label="current?.title || current?.name || 'Report content'">
          <header v-if="current"><h2>{{ current.title || current.name }}</h2><p class="muted">{{ current.source }} · Captured {{ dateLabel(content?.modified_at ?? current.modified_at) }} · {{ bytesLabel(content?.size ?? current.size) }} · <RouterLink :to="reportLink(current.id)">Link to this report</RouterLink></p></header>
          <p v-if="archived" role="status" class="muted small">Archived copy of an earlier report. The original file and its source are unchanged.</p>
          <p v-if="historical" role="status" class="notice-warn">Historical report, more than 24 hours old. These findings describe its captured run, not current health.</p>
          <p v-if="content?.response_only" class="muted small">Showing the recorded Hermes response. The original job prompt is omitted.</p>
          <p v-if="contentError" role="status" class="notice-warn">{{ contentError }}<span v-if="content"> Showing the last successfully read version.</span></p>
          <p v-if="!contentLoaded" role="status" class="muted">Loading report…</p>
          <template v-if="current && findings.length">
            <ReportFindings :report-id="current.id" :report-modified="content?.modified_at ?? current.modified_at" :findings="findings" :linked="content?.finding_tasks ?? {}" @changed="refreshContent" />
            <p><button class="btn" @click="planProject">Plan project from this report</button></p>
          </template>
          <div v-if="content?.format === 'markdown'" class="markdown-report" v-html="html" />
          <pre v-else-if="content" class="log-window tall">{{ content.content }}</pre>
        </article>
      </div>
    </template>
  </section>
</template>
<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--gap); }
.empty code { overflow-wrap: anywhere; }
.report-controls { margin: var(--gap-lg) 0; display: grid; gap: var(--gap); }
.filters { display: flex; gap: var(--gap); flex-wrap: wrap; }
.filters label { flex: 1 1 200px; }
label { display: grid; gap: var(--gap-sm); color: var(--text-muted); }
.report-controls p { margin-bottom: 0; font-size: var(--font-size-xs); }
.reports-layout { display: grid; grid-template-columns: minmax(200px, 300px) minmax(0, 1fr); gap: var(--gap-lg); align-items: start; }
.report-list { display: grid; gap: var(--gap-sm); max-height: 70vh; overflow-y: auto; }
.report-row { text-align: left; display: grid; gap: var(--gap-sm); cursor: pointer; color: var(--text); font: inherit; overflow-wrap: anywhere; }
.report-row.selected { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.report-content { min-width: 0; overflow-wrap: anywhere; }
.severity { justify-self: start; padding: 0 var(--gap-sm); border: 1px solid currentColor; border-radius: var(--radius-sm); font-size: var(--font-size-xs); font-weight: 600; color: var(--text-muted); }
h2 { font-size: var(--font-size-lg); margin-top: 0; }
header { border-bottom: 1px solid var(--surface-border); margin-bottom: 0; }
header p { font-size: var(--font-size-xs); }
.markdown-report { line-height: 1.7; }
.markdown-report :deep(> :first-child) { margin-top: 0; }
.markdown-report :deep(p) { margin: .8em 0; }
.markdown-report :deep(ul), .markdown-report :deep(ol) { padding-left: 1.5em; margin: .8em 0; }
.markdown-report :deep(ul) { list-style: disc; }
.markdown-report :deep(ol) { list-style: decimal; }
.markdown-report :deep(li) { margin: .25em 0; }
.markdown-report :deep(a) { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.markdown-report :deep(hr) { border-color: var(--surface-border); margin: 1.2em 0; }
.markdown-report :deep(h1), .markdown-report :deep(h2), .markdown-report :deep(h3) { line-height: 1.3; margin: 1.5em 0 .6em; }
.markdown-report :deep(h1) { font-size: 1.6rem; }
.markdown-report :deep(h2) { font-size: 1.3rem; }
.markdown-report :deep(h3) { font-size: 1.1rem; }
.markdown-report :deep(pre) { overflow: auto; padding: var(--gap); background: var(--bg); border: 1px solid var(--surface-border); border-radius: var(--radius-sm); }
.markdown-report :deep(pre code) { white-space: pre; }
.markdown-report :deep(code) { color: var(--accent); font-size: .9em; }
.markdown-report :deep(blockquote) { margin-left: 0; padding-left: var(--gap); border-left: 3px solid var(--accent); color: var(--text-muted); }
.markdown-report :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.markdown-report :deep(th), .markdown-report :deep(td) { padding: var(--gap-sm); border: 1px solid var(--surface-border); }
@media (max-width: 760px) { .reports-layout { grid-template-columns: 1fr; } .report-list { display: none; } }
</style>
