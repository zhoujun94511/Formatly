import { computed, ref, watch, type Ref } from 'vue'
import type { Issue } from '../types'
import { displayEvidence, displayLocation, displayRuleEvidence, displaySource, issueTitle, ruleLabel, sourceEntries } from '../utils/report'

export const issuesPerPage = 10

export function useReportIssues(source: Readonly<Ref<Issue[]>>, complete: Readonly<Ref<boolean>> = ref(false)) {
  const level = ref('all'), search = ref(''), page = ref(1)
  // Keep the original report position with every entry. Evidence and reviews
  // address this position even when the visible list is filtered or paginated.
  const indexed = computed(() => source.value.map((issue, index) => ({ issue, index })))
  const searchText = computed(() => indexed.value.map(({ issue }) => [
    issueTitle(issue), ruleLabel(issue.rule_id), issue.rule_id, issue.message,
    issue.location == null ? '' : displayLocation(issue.location),
    issue.expected == null ? '' : displayRuleEvidence(issue.expected, issue.rule_id),
    issue.actual == null ? '' : displayRuleEvidence(issue.actual, issue.rule_id),
    ...[issue.location, issue.expected, issue.actual].filter(value => value != null).map(displayEvidence),
    ...(issue.source == null ? [] : sourceEntries(issue.source).map(displaySource)),
  ].filter(Boolean).join('\n').toLowerCase()))
  const filtered = computed(() => {
    const query = search.value.trim().toLowerCase()
    return indexed.value.filter(({ issue, index }) => (level.value === 'all' || issue.level === level.value) &&
      (!query || searchText.value[index].includes(query)))
  })
  const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / issuesPerPage)))
  const start = computed(() => filtered.value.length ? (page.value - 1) * issuesPerPage + 1 : 0)
  const end = computed(() => Math.min(page.value * issuesPerPage, filtered.value.length))
  const visible = computed(() => complete.value ? indexed.value : filtered.value.slice(start.value ? start.value - 1 : 0, end.value))
  watch([source, level, search], () => { page.value = 1 }, { flush: 'sync' })
  function setPage(value: number) { page.value = Number.isFinite(value) ? Math.min(pageCount.value, Math.max(1, Math.trunc(value))) : 1 }
  return { level, search, page, pageCount, indexed, filtered, visible, start, end, setPage }
}
