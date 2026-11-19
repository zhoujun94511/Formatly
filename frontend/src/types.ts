import type { EffectiveSummary } from './utils/profileFields'
export type Page = 'new' | 'batch' | 'history' | 'result' | 'profiles' | 'plugins' | 'doctor' | 'schools' | 'collections'
export type DocumentKind = 'thesis' | 'intern' | 'certificate'
export type DocumentFormat = 'docx' | 'pdf' | 'txt' | 'md' | 'json'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'interrupted' | 'cancelled'
export type IssueLevel = 'error' | 'warning' | 'manual'
export interface Profile { id: string; name: string; version?: number; description?: string; plugins?: string[]; settings?: Record<string, unknown>; kinds?: DocumentKind[]; school?: Record<string, unknown>; requirements?: Requirement[]; scoped_rules?: (Requirement & { plugin_id: string })[] }
export interface Plugin { id: string; name?: string; description?: string; available?: boolean; reason?: string; formats?: DocumentFormat[] }
export interface Issue { level?: IssueLevel; rule_id?: string; location?: unknown; message?: string; expected?: unknown; actual?: unknown; source?: unknown; plugin?: string; category?: string }
export type CheckStatus = 'passed' | 'failed' | 'manual' | 'not_checked' | 'unsupported' | 'error' | 'not_applicable'
export interface RuleCheck { rule_id?: string; target?: string; label?: string; status?: CheckStatus; location?: unknown; expected?: unknown; actual?: unknown; source?: unknown; plugin?: string; kind?: string; message?: string; reason?: string; excluded?: boolean; exclusion_reason?: string; locator?: Record<string, unknown> }
export interface Coverage { checks?: RuleCheck[]; summary?: Partial<Record<CheckStatus, number>>; format_checks?: number; complete?: boolean; scope?: string }
export interface ExtractionPage { number?: number; width_mm?: number; height_mm?: number; method?: string; confidence?: number }
export interface OcrObservation {
  page?: number
  location?: string
  status: 'disagreement' | 'consistent' | 'not_checked'
  reason?: string
  primary_text: string
  bbox?: number[]
  alternative?: { text: string }
}
export interface OcrReview { observation_count: number; disagreement_count: number; consistent_count: number; not_checked_count: number; observations: OcrObservation[]; truncated?: boolean }
export interface DocumentExtraction { format?: DocumentFormat; method?: string; text_method?: string; pages?: ExtractionPage[]; page_count?: number; processed_pages?: number; complete?: boolean; requires_review?: boolean; warnings?: string[]; ocr_review?: OcrReview }
export interface Capabilities { office?: { available: boolean; renderers?: string[]; reason?: string }; formats: DocumentFormat[]; pdf: { available: boolean; reason?: string }; ocr: { available: boolean; reason?: string; languages?: string[] }; limits?: { file_bytes?: number } }
export interface Result { status?: string; profile_id?: string; kind?: string; input_format?: DocumentFormat; document_extraction?: DocumentExtraction; created_at?: string; input_sha256?: string; input_unchanged?: boolean; original_unchanged?: boolean; pdf_sha256?: string; pdf_unchanged?: boolean; original_pdf_unchanged?: boolean; counts?: { error?: number; warning?: number; manual?: number }; document_counts?: { error?: number; warning?: number; manual?: number }; execution_errors?: number; issues?: Issue[]; engines?: Engine[] | Record<string, Engine>; coverage?: Coverage; profile_snapshot?: Profile; profile_sha256?: string; repair?: RepairMetadata }
export interface Engine { id?: string; name?: string; status?: string; duration_ms?: number; error?: unknown; evidence?: unknown }
export interface RepairCandidate { id: string; rule_id: string; label?: string; target: string; location: unknown; expected: unknown; actual: unknown }
export interface RepairSkipped { rule_id?: string; location?: unknown; reason: string }
export interface RepairPlan { job_id: string; plan_id: string; input_sha256: string; available: boolean; reason?: string; candidates: RepairCandidate[]; skipped?: RepairSkipped[] }
export interface RepairMetadata { source_job_id: string; source_filename: string; applied_count: number; input_sha256: string; output_sha256: string; dropped_paired_pdf: boolean }
export interface Job { id: string; filename?: string; profile_id?: string; kind?: string; collection_id?: string; status: JobStatus; stage?: string; stage_detail?: string; cancel_requested?: boolean | number; revision_of_job_id?: string; batch_id?: string; input_format?: DocumentFormat; created_at?: string; error?: unknown; result?: Result | null; counts?: { error?: number }; repair?: RepairMetadata }
export interface BatchItem { index: number; filename: string; job_id?: string; job?: Job; error?: string }
export interface Batch { batch_id: string; items: BatchItem[] }
export interface Artifact { url?: string; name?: string; path?: string; size?: number; integrity?: 'sealed' | 'unverified' }
export interface DoctorCheck { id?: string; name?: string; status?: string; message?: string; detail?: string }
export interface ExternalEngineStatus {
  plugin_id: 'legacy-school'
  profile_id: 'school-specific'
  available: boolean
  stage: 'missing' | 'files' | 'python' | 'dependencies' | 'rules' | 'ready' | 'error'
  discovery: 'default' | 'environment' | 'configuration'
  root_configured: boolean
  python_configured: boolean
  kinds: Array<'thesis' | 'intern'>
  formats: Array<'docx'>
  checks: Array<{ id: string; label: string; status: 'ok' | 'error' | 'pending'; message: string }>
  required_files: Array<{ path: string; present: boolean }>
}
export interface DoctorReport { status?: string; checks?: DoctorCheck[]; external_engine?: ExternalEngineStatus }

export interface JobStats { total: number; completed: number; needs_changes: number }
export interface JobPage { items: Job[]; total: number; stats: JobStats; offset: number; limit: number }
export interface ProfileWarning { id: string; file: string; message: string }
export interface WorkspaceWarning { file: string; message: string }
export interface Preflight { available: boolean; plugins: Plugin[]; warnings?: string[]; input_format?: DocumentFormat; summary?: EffectiveSummary; document_scope?: { required: boolean; supported: boolean; items: ScopeRequirement[] } }
export interface Requirement { id: string; kind: DocumentKind; target: string; expected: unknown; label: string; source_id: string; source_locator: string; source_excerpt: string; mode: 'automatic' | 'manual'; confirmed: boolean; excluded?: boolean; exclusion_reason?: string; scope_style_ids?: string[]; scope_section_indices?: number[]; parameters?: Record<string, unknown>; scope_binding_status?: 'bound' | 'unbound'; source_scope_style_ids?: string[]; source_scope_section_indices?: number[]; source_parameters?: Record<string, unknown> }
export interface ScopeRequirement { id: string; target: string; label: string; expected: unknown; scope_type: 'styles' | 'sections'; source_scope_style_ids?: string[]; source_scope_section_indices?: number[]; source_excerpt?: string; source_locator?: string }
export interface DocumentPreview { id: string; input_sha256: string; profile_sha256: string; profile_id: string; kind: DocumentKind; input_format: DocumentFormat; expires_at: string; requirements: ScopeRequirement[]; warnings: string[] }
export interface DocumentStyleCatalog { items: ParagraphStyleChoice[]; total: number; offset: number; limit: number; input_sha256: string }
export interface DocumentSectionChoice { index: number; label: string; paragraph_count: number; samples: { text: string; location: string }[] }
export interface DocumentSectionCatalog { items: DocumentSectionChoice[]; total: number; offset: number; limit: number; input_sha256: string }
export type ScopeBinding = { requirement_id: string; status: 'bound'; style_ids?: string[]; section_indices?: number[] } | { requirement_id: string; status: 'unbound'; reason: string }
export interface DocumentScopeBindings { schema_version: 1; input_sha256: string; profile_sha256: string; kind: DocumentKind; items: ScopeBinding[] }
export interface SchoolSource { id: string; filename: string; kind: DocumentKind; role: string; sha256?: string; text_sha256?: string; text?: string; parse_status?: string; extraction_status?: string; warnings?: string[]; extraction?: DocumentExtraction; text_method?: string; extracted_text_sha256?: string; transcription_sha256?: string }
export interface ParagraphStyleChoice { id: string; name: string; based_on?: string | null; declared: boolean; paragraph_count: number; samples: { text: string; location: string }[] }
export interface SchoolStyleCatalog { school_id: string; source_id: string; source_sha256: string; items: ParagraphStyleChoice[]; total: number; offset: number; limit: number }
export interface SchoolSourceContext { school_id: string; source_id: string; source_sha256: string; text_sha256: string; location: string; text: string; matched_excerpt: string; match_found: boolean; truncated: boolean }
export interface School { id: string; name: string; version?: number; sources: SchoolSource[]; candidates?: Requirement[]; requirements?: Requirement[]; conflicts?: unknown[]; profiles?: Profile[] | string[]; status?: string }
export interface MaterialCollection { id: string; name: string; required_kinds?: DocumentKind[]; items?: Job[]; checks?: RuleCheck[]; summary?: Partial<Record<CheckStatus, number>>; status?: string; job_ids?: string[]; selected_job_ids?: string[]; excluded_revision_ids?: string[]; scope?: string }
