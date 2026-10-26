export type Passage = { id: string; content: string; assets?: string[] };
export type Question = { id: string; stem: string; module: string; source: string; estimated_seconds: number; options: Record<string, string>; stem_assets?: string[]; option_assets?: Record<string, string[]>; passage?: Passage | null };
export type GroupQuestionItem = {
  attempt_id: string | null;
  question_id: string;
  submitted: boolean;
  question: Question;
  started_at: string | null;
  selection?: AdaptiveSelection | null;
  selected_answer?: string | null;
  answer?: string;
  correct?: boolean;
  confidence?: number | null;
  elapsed_ms?: number;
  timing_valid?: boolean | number;
  explanation?: string;
  error_event?: ErrorEvent | null;
  review_schedule?: ReviewSchedule | null;
  ai_explanation?: TutorExplanationOutput | null;
  stem?: string;
  options?: Record<string, string>;
  stem_assets?: string[];
  option_assets?: Record<string, string[]>;
};
export type GroupSummary = {
  total: number;
  correct_count: number;
  accuracy_percent: number;
  total_elapsed_ms: number;
  avg_elapsed_ms: number;
  is_all_correct: boolean;
};
export type QuizGroup = {
  session_id: string;
  group_index: number;
  total_groups: number;
  passage: Passage | null;
  questions: GroupQuestionItem[];
  is_group_settled: boolean;
  summary: GroupSummary | null;
  all_completed: boolean;
  has_next_group: boolean;
  session_total: number;
  session_answered: number;
  started_at: string;
  server_now: string;
};
export type GroupSubmitResult = {
  session_id: string;
  summary: GroupSummary;
  results: Result[];
  has_next_group: boolean;
  session_completed: boolean;
  total_answered: number;
  total_questions: number;
};
export type LearningMode = 'PRACTICE' | 'REVIEW';
export type AdaptiveSelection = { position: number; policy_version: string; selection_score: number; selection_reason: string; component_scores: Record<string, number>; decided_at: string };
export type Current = { done: false; attempt_id: string; mode: LearningMode; started_at: string; server_now: string; question: Question; selection?: AdaptiveSelection | null };
export type ErrorEvent = { id: string; error_type: string; explanation: string; source: 'USER'; created_at: string };
export type ReviewSchedule = { rating: number; rating_reason: string; scheduler_version: string; rating_policy_version: string; state: number; due: string; review_count: number; lapse_count: number };
export type Result = { id: string; question_id: string; mode: LearningMode; selected_answer: string | null; audit_note?: string | null; answer: string; correct: boolean; confidence: number | null; elapsed_ms: number; timing_valid?: boolean | number; explanation: string; changed_answer: boolean; error_event: ErrorEvent | null; review_schedule: ReviewSchedule | null; selection?: AdaptiveSelection | null; stem?: string; module?: string; options?: Record<string, string>; stem_assets?: string[]; option_assets?: Record<string, string[]>; passage?: Passage | null; ai_explanation?: TutorExplanationOutput | null; position?: number };
export type Session = { id: string; mode: LearningMode; total: number; answered: number; status: 'active' | 'completed'; current: Current | null; latest_result: Result | null };
export type AdaptiveAudit = { session_id: string; policy_version: string; items: Array<{ question_id: string; position: number; policy_version: string; selection_score: number; selection_reason: string; component_scores: Record<string, number>; decided_at: string }> };
export type HintOutput = { hint_level: number; direction: string; method: string; partial_step: string; full_explanation: string; message: string; citation: string | null };
export type DiagnosisOutput = { error_type: string; error_label: string; confidence: number; cause: string; recommended_intervention: string; citation: string | null };
export type TutorExplanationOutput = { summary: string; core_concept: string; step_by_step: string[]; common_pitfalls: string[]; recommended_action: string; citation: string | null };
export type FollowUpMessage = { id: string; user_message_id?: string; attempt_id: string; role: 'user' | 'assistant'; content: string; created_at: string };
export type FollowUpHistory = { attempt_id: string; messages: FollowUpMessage[] };
export type ReviewStatus = { as_of: string; due_count: number; active_session: { id: string; mode: 'REVIEW'; started_at: string; status: 'active'; total: number; answered: number } | null };
export type NodeQuestionItem = {
  id: string;
  stem: string;
  module: string;
  difficulty: number;
  answer: string;
  explanation: string;
  attempt_count: number;
  last_attempt_id?: string | null;
  last_correct: boolean | null;
  last_submitted_at: string | null;
  last_selected_answer: string | null;
  has_review?: boolean;
  review_status?: string | null;
  review_summary?: string | null;
  review_user_self_report?: string | null;
  review_is_user_confirmed?: boolean;
};
export type MasteryNode = { id: string; parent_id: string | null; subject: string; module: string; name: string; node_type: string; description: string | null; sort_order: number; metadata_json: string; mastery_score: number; evidence_positive: number; evidence_negative: number; attempt_count: number; recent_accuracy: number | null; timed_accuracy: number | null; avg_time_ratio: number | null; hint_dependency: number; last_practiced_at: string | null; direct_question_count?: number; practiced_question_count?: number; error_question_count?: number; knowledge_node_code?: string | null };
export type MasteryData = { overall: number; nodes: MasteryNode[] };
export type DailyGoal = {
  date?: string;
  shenlun?: ShenlunDailyTask;
  target: number;
  completed: number;
  practice_count: number;
  review_count: number;
  progress_percent: number;
  remaining: number;
};
export type ShenlunDailyTask = {
  date: string;
  target: number;
  completed: number;
  remaining: number;
  progress_percent: number;
  available: boolean;
  candidate_count?: number;
  next_available?: boolean;
};
export type CredibilityAudit = {
  total_submitted: number;
  valid_stats_count: number;
  excluded_test_count: number;
  unknown_source_count: number;
  real_study_count: number;
  first_time_count: number;
  repeat_count: number;
  valid_timing_count: number;
  invalid_timing_count: number;
  measured_timing_count: number;
  estimated_timing_count: number;
  assisted_count: number;
  unassisted_count: number;
  unknown_exposure_count: number;
  rules_explanation: string[];
};

export type DashboardData = {
  metrics: {
    attempt_count: number;
    accuracy: number | null;
    timed_accuracy: number | null;
    average_elapsed_ms: number | null;
    mastery: number;
    high_confidence_errors: number;
    hint_dependency: number;
  };
  credibility_audit?: CredibilityAudit;
  daily_goal?: DailyGoal;
  weakest: MasteryNode | null;
  recommendation: string;
};
export type DiagnosisHypothesis = {
  hypothesis_id: string;
  misconception_code?: string;
  stage_code?: string;
  label: string;
  rationale: string;
  missing_info: string;
};

export type ProblemSolvingStage = {
  code: string;
  label: string;
  desc: string;
};

export type ReviewKnowledgeNode = {
  node_id: string;
  node_name: string;
  full_path: string;
  description: string;
  knowledge_code?: string;
};

export type ReviewPreferenceMode = 'AUTO_ASK' | 'MANUAL' | 'EXPLANATION_ONLY';

export type InteractiveDiagnosisRecord = {
  id: string;
  attempt_id: string;
  question_id: string;
  status: 'NOT_STARTED' | 'HYPOTHESIZED' | 'CLARIFYING' | 'CONFIRMED' | 'CORRECTED' | 'SKIPPED' | 'INSUFFICIENT_INFO';
  observed_facts: {
    stem: string;
    standard_answer: string;
    user_selected: string;
    is_correct: boolean;
    confidence: number | null;
    elapsed_ms: number;
    estimated_seconds: number;
    module: string;
  };
  hypotheses: DiagnosisHypothesis[];
  clarification_question: string | null;
  clarification_options: string[];
  user_feedback_type: 'CONFIRMED' | 'CORRECTED' | 'SKIPPED' | null;
  user_feedback_text: string | null;
  final_diagnosis: {
    misconception_code?: string;
    label?: string;
    rationale?: string;
    tailored_advice?: string;
    source?: string;
    user_self_report?: string;
  } | null;
  is_user_confirmed: boolean;
  citation: string | null;
  suggested_action: string;
  summary?: string | null;
  selected_error_type?: string | null;
  cause_source?: 'USER_DIRECT' | 'USER_CONFIRMED_AI' | 'USER_SELF_REPORT' | 'AI_INFERRED' | 'PENDING' | string | null;
  cause_history?: Array<{
    error_type: string;
    stage_code?: string;
    stage_label?: string;
    knowledge_node?: string;
    source: string;
    explanation?: string;
    supplementary?: string;
    changed_at: string;
  }>;
  failed_message_id?: string | null;
  last_message_at?: string | null;
  ai_explanation?: TutorExplanationOutput | null;
  ai_explanation_scope?: 'QUESTION_LEGACY_UNATTRIBUTED' | null;
  knowledge_node?: ReviewKnowledgeNode;
  problem_solving_stages?: ProblemSolvingStage[];
  messages?: Array<{
    id: string;
    attempt_id: string;
    question_id?: string;
    role: 'user' | 'assistant';
    content: string;
    turn_type?: string;
    status?: string;
    created_at: string;
  }>;
};

export type QuestionReviewHistory = {
  question_id: string;
  attempts: Array<{
    attempt_id: string;
    question_id: string;
    submitted_at: string;
    selected_answer: string;
    correct: boolean;
    confidence: number;
    elapsed_ms: number;
    has_review: boolean;
    review_status: string | null;
    review_summary: string | null;
    is_user_confirmed: boolean;
    user_feedback_text: string | null;
    last_message_at: string | null;
    message_count: number;
  }>;
};

export type ErrorAnalytics = {
  events: Array<ErrorEvent & {
    attempt_id: string;
    question_id: string;
    stem: string;
    module: string;
    confidence: number;
    elapsed_ms: number;
    error_label: string;
    has_review?: boolean;
    review_status?: string | null;
    review_summary?: string | null;
    review_is_user_confirmed?: boolean;
  }>;
  breakdown: Array<{ error_type: string; label: string; count: number }>;
  undiagnosed_count: number;
};

export type ImportJob = {
  id: string;
  source_document_id: string;
  source_document_version_id: string | null;
  filename: string;
  status: string;
  stage: string;
  total_candidates: number;
  parsed_questions: number;
  validated_questions: number;
  needs_review: number;
  published_questions: number;
  failed_questions: number;
  auto_accepted_count: number;
  review_reasons_summary: Record<string, number>;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type ReviewItem = {
  draft_id: string;
  job_id: string;
  question_number: number;
  stem: string;
  stem_assets: string[];
  options: Record<string, string>;
  option_assets: Record<string, string[]>;
  passage_text: string | null;
  answer: string | null;
  answer_source: string | null;
  answer_matched: number;
  explanation: string;
  module: string;
  suggested_knowledge_node_code: string | null;
  suggested_skill_code: string | null;
  confidence: number;
  review_reasons: string[];
  source_page: number | null;
  source_locator: string | null;
  validation_status: string;
};

export type PublishResult = {
  job_id: string;
  total_drafts: number;
  published_count: number;
  skipped_count: number;
  failed_count: number;
  published_question_ids: string[];
  errors: Array<{ draft_id: string; question_number: number; error: string }>;
};

export class ApiError extends Error {
  isConflict?: boolean;
  currentNote?: any;
  constructor(public status: number, message: string, options?: { isConflict?: boolean; currentNote?: any }) {
    super(message);
    Object.setPrototypeOf(this, ApiError.prototype);
    this.name = 'ApiError';
    this.isConflict = options?.isConflict;
    this.currentNote = options?.currentNote;
  }
}
// Optional shared token for AI-spending endpoints. Only relevant when the
// backend has GONGKAO_AI_TOKEN set; otherwise this header is ignored.
function studyTokenHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = window.localStorage.getItem('study_token');
  return token ? { 'X-Study-Token': token } : {};
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method: body === undefined ? 'GET' : 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', ...studyTokenHeaders() }, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, '无法连接到后端服务，请确认后端已启动。');
  }
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    let message: string;
    let isConflict = false;
    let currentNote: any = undefined;

    if (response.status === 409 && typeof value.detail === 'object') {
      isConflict = true;
      currentNote = value.detail.current_note;
      message = value.detail.message || '笔记已被其他页面更新，为防止覆盖，当前编辑已暂停。';
    } else if (typeof value.detail === 'string') {
      message = value.detail;
    } else if (Array.isArray(value.detail)) {
      message = value.detail.map((e: any) => e.msg || String(e)).join('；');
    } else {
      message = `请求失败（HTTP ${response.status}），请稍后重试。`;
    }
    throw new ApiError(response.status, message, { isConflict, currentNote });
  }
  return response.json();
}

export type UserNote = {
  id: string;
  user_id: string;
  note_type: 'question' | 'knowledge_node' | 'dialogue_clipping' | 'shenlun_summary';
  content: string;
  title?: string | null;
  question_id?: string | null;
  attempt_id?: string | null;
  knowledge_node_id?: string | null;
  knowledge_node_code?: string | null;
  module?: string | null;
  source_type: 'manual' | 'review_ai_message' | 'review_user_message' | 'shenlun_dimension';
  source_message_id?: string | null;
  source_quote?: string | null;
  shenlun_session_id?: string | null;
  shenlun_dimension?: string | null;
  question_stem?: string | null;
  question_answer?: string | null;
  node_name?: string | null;
  version: number;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
  is_shenlun_live?: boolean;
};

export type NoteListResult = {
  items: UserNote[];
  total: number;
  shenlun_notes?: UserNote[];
};

export type SaveNoteInput = {
  note_id?: string;
  expected_version?: number;
  note_type?: 'question' | 'knowledge_node' | 'dialogue_clipping' | 'shenlun_summary';
  content?: string;
  title?: string | null;
  question_id?: string;
  attempt_id?: string;
  knowledge_node_id?: string | null;
  knowledge_node_code?: string | null;
  module?: string | null;
  source_type?: 'manual' | 'review_ai_message' | 'review_user_message' | 'shenlun_dimension';
  source_message_id?: string;
  source_quote?: string;
  metadata?: Record<string, any>;
};

export type ClipMessageInput = {
  message_content: string;
  source_message_id?: string;
  turn_type?: string;
  message_role?: 'user' | 'assistant';
  title?: string;
};

export async function listNotes(params: {
  question_id?: string;
  attempt_id?: string;
  knowledge_node_id?: string;
  knowledge_node_code?: string;
  module?: string;
  note_type?: string;
  query?: string;
  limit?: number;
  offset?: number;
  include_shenlun?: boolean;
} = {}): Promise<NoteListResult> {
  const q = new URLSearchParams();
  if (params.question_id) q.set('question_id', params.question_id);
  if (params.attempt_id) q.set('attempt_id', params.attempt_id);
  if (params.knowledge_node_id) q.set('knowledge_node_id', params.knowledge_node_id);
  if (params.knowledge_node_code) q.set('knowledge_node_code', params.knowledge_node_code);
  if (params.module) q.set('module', params.module);
  if (params.note_type) q.set('note_type', params.note_type);
  if (params.query) q.set('query', params.query);
  if (params.limit !== undefined) q.set('limit', String(params.limit));
  if (params.offset !== undefined) q.set('offset', String(params.offset));
  if (params.include_shenlun !== undefined) q.set('include_shenlun', String(params.include_shenlun));

  const queryStr = q.toString() ? `?${q.toString()}` : '';
  return api<NoteListResult>(`/notes${queryStr}`);
}

export async function saveNote(data: SaveNoteInput): Promise<UserNote> {
  return api<UserNote>('/notes', data);
}

export async function deleteNote(noteId: string): Promise<{ status: string; id: string }> {
  let response: Response;
  try {
    response = await fetch(`/api/notes/${noteId}`, { method: 'DELETE', headers: { ...studyTokenHeaders() } });
  } catch {
    throw new ApiError(0, '无法连接到后端服务');
  }
  if (!response.ok) {
    throw new ApiError(response.status, '删除笔记失败');
  }
  return response.json();
}

export async function clipReviewMessage(attemptId: string, data: ClipMessageInput): Promise<UserNote> {
  return api<UserNote>(`/attempts/${attemptId}/clip-message`, data);
}

export async function associateNoteWithNode(noteId: string, nodeId: string | null, expectedVersion?: number): Promise<UserNote> {
  return api<UserNote>(`/notes/${noteId}/associate-node`, { knowledge_node_id: nodeId, expected_version: expectedVersion });
}
