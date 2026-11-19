import type { Artifact, Capabilities, DoctorReport, DocumentFormat, Job, JobPage, MaterialCollection, Plugin, Preflight, Profile, ProfileWarning, RepairPlan, Requirement, School, WorkspaceWarning } from './types'
import type { Batch } from './types'
import type { ProfileFields } from './utils/profileFields'
import type { SchoolDraftRecord } from './composables/useSchoolDraftPersistence'
import type { SavedRequirementDraft } from './composables/useRequirementEditor'
import type { IssueEvidence, JobComparison, JobReviews, ReviewPayload } from './utils/reportWorkspace'
export class ApiError extends Error { status: number; constructor(message: string, status = 0) { super(message); this.name = 'ApiError'; this.status = status } }
async function request<T>(path: string, options: { method?: string; body?: BodyInit | object; timeout?: number } = {}): Promise<T> {
  const controller = new AbortController(); const timer = window.setTimeout(() => controller.abort(), options.timeout ?? 30000)
  const headers: Record<string, string> = { Accept: 'application/json' }; const init: RequestInit = { method: options.method ?? 'GET', signal: controller.signal, credentials: 'same-origin', headers }
  if (options.body instanceof FormData) init.body = options.body
  else if (options.body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(options.body) }
  try { const response = await fetch(path, init); let data: any; try { data = await response.json() } catch { throw new ApiError('服务器未返回有效结果，请检查服务是否正常运行。', response.status) }; if (!response.ok) { const raw = data?.error ?? data?.message; throw new ApiError(typeof raw === 'string' ? raw : raw?.message || `请求失败（HTTP ${response.status}）。`, response.status) }; return data as T }
  catch (error: any) { if (error?.name === 'AbortError') throw new ApiError('请求超时，请刷新查看任务状态，避免重复提交。'); if (error instanceof ApiError) throw error; throw new ApiError('无法连接本地服务，请确认 Formatly 仍在运行。') }
  finally { window.clearTimeout(timer) }
}
const jobPath = (id: string) => `/api/jobs/${encodeURIComponent(id)}`
export const api = {
  createDocumentPreview: (body: FormData) => request<import('./types').DocumentPreview>('/api/document-previews', { method: 'POST', body, timeout: 60000 }),
  documentPreviewStyles: (id: string, query = '', offset = 0) => request<import('./types').DocumentStyleCatalog>(`/api/document-previews/${encodeURIComponent(id)}/styles?${new URLSearchParams({ q: query, offset: String(offset), limit: '10' })}`),
  documentPreviewSections: (id: string, offset = 0) => request<import('./types').DocumentSectionCatalog>(`/api/document-previews/${encodeURIComponent(id)}/sections?${new URLSearchParams({ offset: String(offset), limit: '10' })}`),
  discardDocumentPreview: (id: string) => request<{ discarded: boolean }>(`/api/document-previews/${encodeURIComponent(id)}/discard`, { method: 'POST', body: {} }),
  profileFields: () => request<ProfileFields>('/api/profile-fields'),
  trialProfile: (id: string, kind: string) => request<Job>(`/api/profiles/${encodeURIComponent(id)}/trial`, { method: 'POST', body: { kind }, timeout: 60000 }),
  schoolDraft: (id: string) => request<SchoolDraftRecord>(`/api/schools/${encodeURIComponent(id)}/draft`),
  saveSchoolDraft: (id: string, body: SavedRequirementDraft & { expected_draft_version: number }) => request<SchoolDraftRecord>(`/api/schools/${encodeURIComponent(id)}/draft`, { method: 'POST', body }),
  discardSchoolDraft: (id: string, expected_draft_version: number) => request<SchoolDraftRecord>(`/api/schools/${encodeURIComponent(id)}/draft/discard`, { method: 'POST', body: { expected_draft_version } }),
  issueEvidence: (id: string, index: number) => request<IssueEvidence>(`${jobPath(id)}/evidence?issue=${index}`, { timeout: 60000 }),
  ocrEvidence: (id: string, location: string) => request<import('./utils/reportWorkspace').OcrEvidence>(`${jobPath(id)}/ocr-evidence?location=${encodeURIComponent(location)}`, { timeout: 60000 }),
  jobComparison: (id: string) => request<JobComparison>(`${jobPath(id)}/comparison`),
  jobReviews: (id: string) => request<JobReviews>(`${jobPath(id)}/reviews`),
  saveJobReview: (id: string, body: ReviewPayload) => request<JobReviews>(`${jobPath(id)}/reviews`, { method: 'POST', body }),
  cancelJob: (id: string) => request<Job>(`${jobPath(id)}/cancel`, { method: 'POST', body: {} }),
  createBatch: (body: FormData) => request<Batch>('/api/batches', { method: 'POST', body, timeout: 120000 }),
  batch: (id: string) => request<Batch>(`/api/batches/${encodeURIComponent(id)}`),
  profiles: () => request<{ items: Profile[]; warnings?: ProfileWarning[] }>('/api/profiles'),
  plugins: () => request<{ items: Plugin[] }>('/api/plugins'),
  jobs: (options: { offset?: number; limit?: number; q?: string; status?: string } = {}) => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(options)) if (value !== undefined && value !== '') params.set(key, String(value))
    return request<JobPage>(`/api/jobs${params.size ? `?${params}` : ''}`)
  },
  job: (id: string) => request<Job>(jobPath(id)),
  createJob: (body: FormData) => request<Job>('/api/jobs', { method: 'POST', body, timeout: 60000 }),
  retry: (id: string) => request<Job>(`${jobPath(id)}/retry`, { method: 'POST', body: {} }),
  repairPlan: (id: string) => request<RepairPlan>(`${jobPath(id)}/repairs`, { timeout: 60000 }),
  applyRepairs: (id: string, plan_id: string, selected_ids: string[]) => request<Job>(`${jobPath(id)}/repairs`, { method: 'POST', body: { plan_id, selected_ids }, timeout: 60000 }),
  artifacts: (id: string) => request<{ items: Artifact[] }>(`${jobPath(id)}/artifacts`),
  doctor: () => request<DoctorReport>('/api/doctor', { timeout: 60000 }),
  saveProfile: (profile: object) => request<Profile>('/api/profiles', { method: 'POST', body: profile }),
  capabilities: () => request<Capabilities>('/api/capabilities', { timeout: 60000 }),
  preflight: (id: string, kind: string, format: DocumentFormat = 'docx') => request<Preflight>(`/api/profiles/${encodeURIComponent(id)}/preflight?kind=${encodeURIComponent(kind)}&format=${encodeURIComponent(format)}`, { timeout: 60000 }),
  schools: () => request<{ items: School[]; warnings?: WorkspaceWarning[] }>('/api/schools'),
  school: (id: string) => request<School>(`/api/schools/${encodeURIComponent(id)}`),
  schoolSourceStyles: (id: string, source: string, query = '', offset = 0) => request<import('./types').SchoolStyleCatalog>(`/api/schools/${encodeURIComponent(id)}/sources/${encodeURIComponent(source)}/styles?${new URLSearchParams({ q: query, offset: String(offset), limit: '10' })}`),
  schoolSourceContext: (id: string, source: string, locator = '', excerpt = '') => request<import('./types').SchoolSourceContext>(`/api/schools/${encodeURIComponent(id)}/sources/${encodeURIComponent(source)}/context?${new URLSearchParams({ locator: locator.slice(0, 200), excerpt: excerpt.slice(0, 200) })}`),
  createSchool: (name: string) => request<School>('/api/schools', { method: 'POST', body: { name } }),
  addSchoolSource: (id: string, body: FormData) => request<School>(`/api/schools/${encodeURIComponent(id)}/sources`, { method: 'POST', body, timeout: 240000 }),
  confirmSchool: (id: string, requirements: Requirement[], expected_version: number | undefined) => request<{ school: School; profiles: Profile[] }>(`/api/schools/${encodeURIComponent(id)}/confirm`, { method: 'POST', body: { requirements, expected_version } }),
  collections: () => request<{ items: MaterialCollection[]; warnings?: WorkspaceWarning[] }>('/api/collections'),
  collection: (id: string) => request<MaterialCollection>(`/api/collections/${encodeURIComponent(id)}`),
  createCollection: (name: string, required_kinds: string[]) => request<MaterialCollection>('/api/collections', { method: 'POST', body: { name, required_kinds } })
}
