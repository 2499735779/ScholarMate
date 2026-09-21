export type Status = {
  has_key: boolean;
  has_profile: boolean;
  model: string;
  vision?: boolean;
  profile_id?: string;
  profile_name?: string;
  profile_count?: number;
  credential_error?: string;
};
export type Profile = {
  id?: string;
  name?: string;
  major: string;
  degree: string;
  research_field: string;
  specific_interests: string[];
  short_term_goal: string;
  long_term_goal: string;
  weekly_hours: number;
  language_preference: string;
  custom_instructions: string;
  active?: boolean;
};
export type ProfileList = { items: Profile[]; active_id: string };
export type ChatThread = {
  id: string;
  title: string;
  profile_id: string;
  profile_name: string;
  message_count: number;
  preview: string;
  created_at: string;
  updated_at: string;
};
export type Attachment = {
  id: string;
  name: string;
  kind: "image" | "document";
  media_type: string;
  type_label: string;
  bytes: number;
  characters: number;
  created_at?: string;
  note?: string;
};
export type Message = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  display_content?: string;
  plan_candidate?: {
    title: string;
    goal: string;
    plan_content: string;
    detection: string;
  } | null;
  adopted_plan_id?: string | null;
  plan_rejected?: boolean | number;
  attachments?: Attachment[];
};
export type Plan = {
  id: string;
  title: string;
  goal: string;
  plan_content: string;
  status: string;
  created_at: string;
  source_message_id?: string | null;
  source_content?: string | null;
  start_date?: string;
  paused_on?: string | null;
};
export type Paper = {
  id: string;
  title: string;
  authors: string;
  abstract: string;
  pdf_url: string;
  published: string;
  local_path?: string;
  summary?: string;
  downloaded?: boolean;
  title_zh?: string;
  category?: string;
  tags?: string;
  language?: string;
  source?: string;
  doi?: string;
  venue?: string;
  volume?: string;
  issue?: string;
  pages?: string;
  publisher?: string;
  place?: string;
  publication_type?: string;
  landing_url?: string;
  enrichment_error?: string;
  storage_mode?: "linked" | "managed";
  metadata_evidence?: string;
  citation_checked?: number;
  summary_scope?: string;
  summary_characters?: number;
};
export type Citation = {
  text: string;
  omitted: string[];
  review: string[];
  missing: string[];
  complete: boolean;
  style: string;
  note: string;
  evidence: string;
  checked?: boolean;
  paper?: Paper;
};
export type StorageReport = {
  data_dir: string;
  managed_dir: string;
  download_dir: string;
  managed_count: number;
  managed_bytes: number;
  linked_count: number;
};
export type StorageSettings = {
  data_dir: string;
  default_data_dir: string;
  data_dir_custom: boolean;
  data_dir_bytes: number;
  download_dir: string;
  default_download_dir: string;
  download_dir_custom: boolean;
  system_drive: string;
  freed_bytes?: number;
};
export type DuplicateCopy = {
  id: string;
  title: string;
  copy: string;
  original: string;
  bytes: number;
};
export type PlanTask = {
  id: string;
  plan_id: string;
  week: number;
  title: string;
  done: number;
};
export type ScheduledPlan = Plan & {
  current_week: number;
  tasks: PlanTask[];
  week_tasks: PlanTask[];
  done_count: number;
  task_count: number;
};

