export type CourseStatus = "CREATED" | "ANALYZING" | "READY" | "LEARNING" | "ARCHIVED";

export interface ProgressMetrics {
  coverage: number;
  mastery: number;
  important_coverage: number;
  important_mastery: number;
}

export interface Course {
  id: string;
  name: string;
  school?: string | null;
  teacher?: string | null;
  exam_date?: string | null;
  days_remaining?: number | null;
  status: CourseStatus;
  progress?: ProgressMetrics;
}

export interface RecommendationStudyUnit {
  id: string;
  title: string;
  importance_label: string;
  mastery_status: string;
  progress: number;
  estimated_minutes: number;
  canonical_kp_id?: string | null;
  canonical_graph_version?: string | null;
  ranking_position?: number | null;
  exam_evidence_tier?: string | null;
  practice_question_count?: number;
  practice_question_binding_ready?: boolean;
  learning_mode?: "EXPLANATION_FIRST" | "QUESTION_FIRST" | string;
  study_preference?: "ACTIVE" | "DEFERRED" | string;
  self_assessed_mastery?: boolean;
  verified_mastery_status?: string;
  exam_evidence_summary?: ExamEvidenceSummary;
  exposure_status?: "NOT_STARTED" | "IN_PROGRESS" | "EXPOSED" | string;
  coverage_status?: "NOT_COVERED" | "PARTIAL" | "COVERED" | string;
  coverage_percent?: number;
  mastery_percent?: number;
  practice_attempted_count?: number;
  valid_question_count?: number;
  active_session_id?: string | null;
}

export interface ExamEvidenceSummary {
  safe_question_count: number;
  exam_years: number[];
  material_names?: string[];
  text: string;
}

export interface Recommendation {
  study_unit: RecommendationStudyUnit;
  reason: { type: string; text: string };
  estimated_minutes: number;
  phase: string;
  days_remaining: number | null;
}

export interface Material {
  id: string;
  name: string;
  type: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  parsing_status?: "PENDING" | "PROCESSING" | "PARSED" | "LOW_QUALITY" | "FAILED" | "UNSUPPORTED";
  extraction_quality?: string | null;
  error_code?: string | null;
  rebuild_required?: boolean;
  upload_status?: "UPLOADED" | "REUSED";
  duplicate?: boolean;
  reused?: boolean;
  created_at?: string;
}

export interface CourseReadiness {
  ready: boolean;
  reason: string;
  eligible_teaching_material_count: number;
  study_unit_count: number;
}

export interface ReviewItem {
  study_unit_id: string;
  title: string;
  importance_label: string;
  importance_text: string;
  mastery_status: string;
  recent_accuracy: number | null;
  estimated_minutes: number;
}

export interface DashboardData {
  course: Course;
  progress: ProgressMetrics;
  recommendation: Recommendation | null;
  action_batch?: ActionBatch | null;
  review_items: ReviewItem[];
  materials: Material[];
  readiness?: CourseReadiness;
  exam_focus?: {
    real_exam_active_count: number;
    practice_ready_count: number;
    supplementary_count: number;
  };
}

export interface ActionBatch {
  phase: string;
  days_remaining?: number | null;
  title: string;
  reason: string;
  items: (RecommendationStudyUnit & { action_reason?: string })[];
}

export interface StudyUnitNode {
  id: string;
  title: string;
  importance_label: string;
  importance_text: string;
  mastery_status: string;
  coverage_status: string;
  progress: number;
  estimated_minutes: number;
  hierarchy?: { structural_path?: string[]; depth?: number; node_role?: string };
  canonical_kp_id?: string | null;
  ranking_position?: number | null;
  exam_evidence_tier?: string | null;
  practice_question_binding_ready?: boolean;
  study_preference?: string;
  self_assessed_mastery?: boolean;
}

export interface KnowledgeDomain {
  id: string;
  title: string;
  children: StudyUnitNode[];
  sections?: { id: string; title: string; children: StudyUnitNode[] }[];
}

export interface KnowledgeData {
  domains: KnowledgeDomain[];
  mode?: string;
  total?: number;
}

export interface WrongBookItem {
  question_id: string;
  study_unit_id: string;
  knowledge_point_title: string;
  title: string;
  content: string;
  previous_answer?: string | null;
  latest_answer?: string | null;
  correct_answer: string;
  explanation?: string | null;
  source_material?: string | null;
  exam_year?: number | null;
  question_number?: string | null;
  source_location?: string | null;
  resolved: boolean;
  latest_attempt_at?: string | null;
}

export interface Question {
  id: string;
  type: string;
  content: string;
  options?: string[] | null;
  segmentation_status?: string | null;
  content_quality?: string | null;
  effective_question_context?: string | null;
  is_mapping_eligible: boolean;
  trust_ready?: boolean;
  trust_issues?: string[];
  trust_confidence?: "HIGH" | "MEDIUM" | "NONE";
  objective_signal?: boolean;
  explanation_quality?: string;
  exam_year?: number | null;
  question_number?: string | null;
  source_location?: string | null;
  source_type?: string | null;
  source_material_name?: string | null;
  source_display?: { label: string; exam_year?: number | null; question_number?: string | null };
}

export interface SessionData {
  session_id: string;
  course_id?: string;
  state: string;
  mode?: "EXPLANATION_FIRST" | "QUESTION_FIRST" | string;
  practice_question_binding_ready?: boolean;
  study_unit?: { id: string; title: string } | null;
}

export type PracticeBindingStatus =
  | "READY_PRIMARY_QUESTION"
  | "NO_PRIMARY_QUESTION"
  | "IMAGE_DEPENDENCY_NOT_SERVABLE";

export interface RankingItem {
  canonical_kp_id: string;
  ranking_position: number;
  ranking_score?: number | null;
  display_priority_score?: number | null;
  display_score_is_probability?: boolean;
  ranking_entity_role?: string | null;
  name_cn?: string | null;
  name_en?: string | null;
  title?: string | null;
  exam_evidence_tier?: string | null;
  evidence_aggregation_mode?: string | null;
  exam_occurrence_count?: number | null;
  study_unit_id: string | null;
  study_unit_binding_status?: string | null;
  mastery_status?: string | null;
  coverage_status?: string | null;
  progress?: number | null;
  practice_question_binding_ready: boolean;
  practice_binding_status: PracticeBindingStatus;
}

export interface RankingData {
  policy_version: string;
  ranking_view: string;
  score_semantics?: string | null;
  total: number;
  filtered_total: number;
  offset: number;
  limit: number;
  items: RankingItem[];
}

export interface StartSessionData {
  session_id: string;
  state: string;
}

export interface ExplanationData {
  title: string;
  content: string;
  sources: { type: string; location?: string; display_label?: string; source_file?: string; evidence_status?: string }[];
  explanation_mode?: "EXPLANATION_EVIDENCE" | "STRUCTURE_ONLY" | "GENERIC_FALLBACK";
  evidence_status?: string | null;
  evidence_items?: { excerpt: string; source_file: string; location: string; display_label?: string; match_method?: string | null }[];
}

export interface NextQuestionData {
  question: Question | null;
  progress: { current: number; total_estimated: number };
  status?: "ACTIVE" | "COMPLETE";
}

export interface KnowledgeUpdate {
  mastery_status: string;
  practice_score: number;
  verified_mastery_status?: string;
}

export interface AnswerResult {
  correct: boolean;
  correct_answer: string;
  explanation?: string | null;
  knowledge_update: KnowledgeUpdate;
  next_action: "NEXT_QUESTION" | "COMPLETE";
  next_question_id: string | null;
  teaching_feedback?: TeachingFeedback;
}

export interface TeachingFeedback {
  mode: "QUESTION_EXPLANATION" | "CONCEPT_EVIDENCE" | "ANSWER_ONLY" | string;
  title: string;
  explanation?: string | null;
  concept_evidence: { excerpt: string; source?: string | null }[];
  source?: string | null;
  study_unit_title: string;
  next_step: string;
}

export interface PilotKnowledgePoint {
  id: string;
  name_cn: string;
  name_en: string;
  parent?: string | null;
  chapter?: string | null;
  section?: string | null;
  definition?: string | null;
  core_rule?: string | null;
  mechanism?: string | null;
  example?: string | null;
  common_mistakes?: string | null;
  related_concepts: string[];
  source_file: string;
  source_section?: string | null;
  source_excerpt?: string | null;
  studyunit_status: string;
}

export interface PilotQuestion {
  id: string;
  type: string;
  content: string;
  options: string[];
  source_file?: string | null;
  source_location?: string | null;
  standard_answer: string;
  solution?: string | null;
  primary_knowledge_point?: { id: string; name: string } | null;
  secondary_knowledge_points: { id: string; name: string }[];
  mapping_reason?: string | null;
  knowledge_explanation?: string | null;
  related_concepts: string[];
  confidence?: number | null;
  mapping_status: string;
  provider?: string | null;
  model?: string | null;
}

export interface PilotData {
  course: { id: string; name: string };
  knowledge_points: PilotKnowledgePoint[];
  questions: PilotQuestion[];
  counts: { knowledge_points: number; questions: number; matched: number; unmatched: number; ambiguous: number };
}
