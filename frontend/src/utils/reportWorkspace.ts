export interface EvidenceSnippet { location?: string; text: string; method?: string; page?: number; confidence?: number }
export interface PagePreview { image_url: string; page: number; width_pt: number; height_pt: number; boxes: number[][] }
export interface OcrEvidence { job_id: string; input_sha256: string; profile_sha256: string; extraction_sha256: string; observation_key: string; location: string; observation: import('../types').OcrObservation; preview?: PagePreview | null; limitations: string[] }
export interface IssueEvidence { job_id: string; issue_index: number; issue_key: string; input_sha256: string; profile_sha256: string; location?: unknown; snippets: EvidenceSnippet[]; sources: unknown[]; limitations: string[]; preview?: PagePreview | null }
export type ReviewStatus = 'pending' | 'checked' | 'suspected_false_positive'
export interface ReviewDraft { status: ReviewStatus; note: string }
export type ReviewDraftCache = Map<string, ReviewDraft>
export interface ReviewRecord { issue_key: string; status: ReviewStatus; note: string; updated_at: string }
export interface JobReviews { job_id: string; input_sha256: string; profile_sha256: string; version: number; items: Record<string, ReviewRecord> }
export interface ReviewPayload { version: number; issue_key: string; status: ReviewStatus; note: string; input_sha256: string; profile_sha256: string }
export type ComparisonGroup = 'resolved' | 'remaining' | 'new' | 'incomparable'
export interface ComparedCheck { rule_id: string; target?: string; location?: unknown; expected?: unknown; before?: unknown; after?: unknown; before_status?: string; after_status?: string; reason?: string }
export interface JobComparison { job_id?: string; source_job_id?: string; available: boolean; reason?: string; scope?: string; groups: Record<ComparisonGroup, ComparedCheck[]>; summary: Record<ComparisonGroup, number> }
