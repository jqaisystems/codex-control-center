export type Health = {
  ok: boolean;
  mode: string;
  uptime_seconds: number;
  host: string;
  db_label: string;
  codex_home_present: boolean;
  codex_version: string | null;
  control_mode_available: boolean;
  control_mode_reason: string;
  codex_login_status: string;
  last_sync: null | {
    detail: string;
    created_at: string;
    metadata: Record<string, number>;
  };
  session_files_scanned: number;
  otel: {
    status: "off" | "configured" | "receiving";
    configured: boolean;
    last_event_at: string | null;
  };
  auth_json_read: boolean;
  api_key_required: boolean;
};

export type Summary = {
  today: {
    sessions: number;
    total_tokens: number;
    tools: number;
    recent_sessions: number;
  };
  tasks: Array<{ status: string; count: number }>;
};

export type SystemModeName = "full" | "balanced" | "token_saver";

export type SystemMode = {
  mode: SystemModeName;
  token_saver_active: boolean;
  presets: Array<{
    id: SystemModeName;
    label: string;
    description: string;
  }>;
};

export type PublishReadiness = {
  generated_at: string;
  status: "ready" | "needs_review" | "blocked";
  package: {
    name: string;
    path_label: string;
    path_hash: string | null;
  };
  summary: {
    checks: number;
    ok: number;
    review: number;
    block: number;
  };
  safety_scan: {
    status: "READY" | "BLOCK";
    finding_count: number;
  };
  git: {
    available: boolean;
    changed: number;
    staged: number;
    untracked: number;
  };
  checks: Array<{
    id: string;
    label: string;
    status: "ok" | "review" | "block";
    detail: string;
  }>;
  next_steps: string[];
  does_not_publish: boolean;
};

export type UsageLimits = {
  available: boolean;
  stale: boolean;
  age_seconds: number | null;
  source: string;
  insights: {
    freshness_quality: "fresh" | "old" | "very_stale" | "unknown";
    task_advice: "normal" | "small_tasks" | "wait_for_reset";
    trend_direction: "falling" | "stable" | "recovering" | "unknown";
    observation_count: number;
    burn_rate: {
      primary: UsageBurnRate;
      secondary: UsageBurnRate;
    };
    trend_points: Array<{
      date: string;
      primary_remaining_percent: number | null;
      secondary_remaining_percent: number | null;
    }>;
    limit_hits: Array<{
      rate_limit_reached_type: string;
      observed_at: string;
    }>;
  };
  limit: null | {
    limit_id: string | null;
    plan_type: string | null;
    primary_used_percent: number | null;
    primary_remaining_percent: number | null;
    primary_window_minutes: number | null;
    primary_resets_at: number | null;
    secondary_used_percent: number | null;
    secondary_remaining_percent: number | null;
    secondary_window_minutes: number | null;
    secondary_resets_at: number | null;
    rate_limit_reached_type: string | null;
    source_session_id: string | null;
    observed_at: string | null;
    synced_at: string;
  };
};

export type UsageBurnRate =
  | {
      available: true;
      percent_spent: number;
      hours: number;
      percent_per_hour: number;
      observation_count: number;
    }
  | {
      available: false;
      reason: string;
    };

export type HealthScore = {
  generated_at: string;
  workspace: {
    id: number;
    name: string;
    path_label: string;
    is_default: number;
  };
  overall_score: number;
  system_score: number;
  workspace_score: number;
  findings: Finding[];
};

export type HealthReportMatch = {
  id: string;
  level: "ok" | "info" | "warn" | "bad";
  category: string;
  kind: string;
  name: string;
  relative_path: string;
  depth: number;
  reason: string;
  ignore_coverage: {
    status: "protected" | "not_ignored" | "unknown";
    detail: string;
    checked: number;
    source_label?: string;
  };
  review_key: string;
  review: {
    review_key: string;
    status: "needs_action" | "reviewed" | "accepted_risk" | "ignore_for_now";
    note: string | null;
    updated_at: string | null;
  };
};

export type HealthReport = HealthScore & {
  scan: {
    scan_mode: "standard" | "deep";
    entries_scanned: number;
    truncated: boolean;
    max_entries: number;
    max_depth: number;
    matched_locations: number;
    gitignore_coverage: {
      protected: number;
      not_ignored: number;
      unknown: number;
      ignore_files_read: number;
      ignore_files_unreadable: number;
    };
    review_summary: {
      total: number;
      needs_action: number;
      reviewed: number;
      accepted_risk: number;
      ignore_for_now: number;
    };
  };
  matches: HealthReportMatch[];
};

export type HealthReportPaths = {
  revealed_at: string;
  workspace: {
    id: number;
    name: string;
    path_label: string;
    root_path: string;
  };
  matches: Array<{
    id: string;
    full_path: string;
  }>;
};

export type Session = {
  session_id: string;
  source: string;
  model: string;
  project_label: string;
  started_at: string;
  updated_at: string;
  status: string;
  event_count: number;
  tool_count: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
};

export type ToolStat = {
  tool_name: string;
  calls: number;
  failures: number;
};

export type Skill = {
  id: number;
  name: string;
  scope: string;
  description: string;
  path_label: string;
  plugin_name: string | null;
  enabled: number;
  last_modified: string;
};

export type SkillPath = {
  id: number;
  path: string;
  path_label: string;
};

export type Finding = {
  level: "ok" | "info" | "warn" | "bad";
  title: string;
  detail: string;
};

export type Workspace = {
  id: number;
  name: string;
  path_label: string;
  path_hash: string;
  is_default: number;
  created_at: string;
  updated_at: string;
};

export type WorkspaceBrowserItem = {
  label: string;
  token: string;
  kind: "home" | "drive" | "folder";
};

export type WorkspaceBrowserFolder = {
  current: WorkspaceBrowserItem;
  breadcrumbs: WorkspaceBrowserItem[];
  children: WorkspaceBrowserItem[];
  truncated: boolean;
};

export type Task = {
  id: number;
  title: string;
  description: string;
  status: string;
  priority: number;
  sandbox: string;
  workspace_id: number | null;
  cwd_label: string;
  cwd_hash: string | null;
  scheduled_for: string | null;
  approved_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  exit_code: number | null;
  event_count: number;
  tool_count: number;
  thread_id: string | null;
  failure_reason: string | null;
  archived: number;
  created_at: string;
  updated_at: string;
  output_summary: string | null;
  error_message: string | null;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  reasoning_output_tokens: number | null;
  total_tokens: number | null;
};

export type TaskTokenUsage = {
  generated_at: string;
  days: number;
  source: "dashboard-launched-tasks";
  today: {
    launched_tasks: number;
    unknown_task_count: number;
    total_tokens: number;
  };
  totals: {
    launched_tasks: number;
    unknown_task_count: number;
    input_tokens: number;
    cached_input_tokens: number;
    output_tokens: number;
    reasoning_output_tokens: number;
    total_tokens: number;
  };
  latest_task: null | {
    id: number;
    status: string;
    completed_at: string | null;
    updated_at: string;
    total_tokens: number | null;
  };
  trend_points: Array<{
    date: string;
    task_count: number;
    total_tokens: number;
    unknown_task_count: number;
  }>;
  note: string;
};

export type TaskHistoryStats = {
  total: number;
  done: number;
  failed: number;
  cancelled: number;
  active: number;
  avg_duration_ms: number;
  total_tools: number;
};

export type Schedule = {
  id: number;
  name: string;
  cron_expression: string;
  task_title: string;
  task_description: string;
  enabled: number;
  workspace_id: number | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_task_id: number | null;
  materialized_count: number;
  created_at: string;
  updated_at: string;
};

const jsonHeaders = { "Content-Type": "application/json" };

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: jsonHeaders,
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "DELETE" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export function compactNumber(value: number | undefined | null): string {
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    value ?? 0
  );
}
