import {
  Activity,
  AlertTriangle,
  Archive,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Clock,
  Copy,
  Eye,
  Folder,
  FolderOpen,
  HardDrive,
  KeyRound,
  ListChecks,
  Play,
  RefreshCw,
  Save,
  ShieldCheck,
  Square,
  Terminal,
  Trash2,
  Workflow
} from "lucide-react";
import type { FormEvent, ReactNode } from "react";
import { useState } from "react";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  RouterProvider,
  useParams
} from "@tanstack/react-router";
import {
  apiGet,
  apiPost,
  apiDelete,
  compactNumber,
  Finding,
  Health,
  HealthReport,
  HealthReportMatch,
  HealthReportPaths,
  HealthScore,
  PublishReadiness,
  Schedule,
  Session,
  Skill,
  SkillPath,
  Summary,
  SystemMode,
  SystemModeName,
  Task,
  TaskHistoryStats,
  TaskTokenUsage,
  ToolStat,
  UsageBurnRate,
  UsageLimits,
  Workspace,
  WorkspaceBrowserFolder,
  WorkspaceBrowserItem
} from "./lib/api";
import { EmptyState, Panel, Pill } from "./components/Panel";

const queryClient = new QueryClient();

type SafeTaskTemplate = {
  id: string;
  label: string;
  title: string;
  description: string;
};

type SessionGroupMode = "day" | "week" | "month" | "year";

type SessionGroup = {
  key: string;
  label: string;
  sessions: Session[];
};

type ResultCategory = "audit" | "docs" | "security" | "structure" | "cleanup" | "general";
type ResultCategoryFilter = "all" | ResultCategory;
type FollowUpKind = "docs" | "security" | "cleanup" | "structure";

const RESULT_CATEGORIES: Array<{ id: ResultCategoryFilter; label: string; description: string }> = [
  { id: "all", label: "All", description: "Every task result." },
  { id: "audit", label: "Audit", description: "Full workspace and readiness reviews." },
  { id: "docs", label: "Docs", description: "README, setup, and documentation work." },
  { id: "security", label: "Security", description: "Safety, secrets, and publishing risk checks." },
  { id: "structure", label: "Structure", description: "Repository layout and entry-point reviews." },
  { id: "cleanup", label: "Cleanup", description: "Generated files, ignore rules, and tidy-up tasks." },
  { id: "general", label: "General", description: "Everything else." }
];

const FOLLOW_UP_TASKS: Record<FollowUpKind, { label: string; title: string; description: string }> = {
  docs: {
    label: "Docs follow-up",
    title: "Documentation follow-up review",
    description:
      "Review the selected workspace in read-only mode and identify the smallest useful documentation follow-up. Focus on README clarity, setup notes, usage examples, test commands, safety notes, and missing public-facing docs. Do not edit files. Do not include full local paths. Do not read private config files, databases, raw logs, raw prompt history, or account data."
  },
  security: {
    label: "Security follow-up",
    title: "Read-only security follow-up",
    description:
      "Review the selected workspace in read-only mode for public-sharing and local-safety risks using safe metadata and public-safe source files only. Focus on risky filenames, ignore coverage, overbroad scripts, unsafe defaults, and practical next steps. Do not edit files. Do not include full local paths. Do not read private config files, databases, raw logs, raw prompt history, or account data."
  },
  cleanup: {
    label: "Cleanup follow-up",
    title: "Read-only cleanup follow-up",
    description:
      "Inspect the selected workspace in read-only mode and suggest a small cleanup plan. Focus on generated folders, build outputs, dependency folders, ignore-rule gaps, stale local artifacts, and public-ready file organization. Do not edit or delete files. Do not include full local paths. Do not read private config files, databases, raw logs, raw prompt history, or account data."
  },
  structure: {
    label: "Structure follow-up",
    title: "Repository structure follow-up",
    description:
      "Inspect the selected workspace in read-only mode and explain the main structure, entry points, ownership boundaries, build and test hints, and the next safest task. Do not edit files. Do not include full local paths. Do not read private config files, databases, raw logs, raw prompt history, or account data."
  }
};

const SAFE_TASK_TEMPLATES: SafeTaskTemplate[] = [
  {
    id: "full-safe-audit",
    label: "Full safe audit",
    title: "Full safe workspace audit",
    description:
      "Inspect the selected workspace in read-only mode and produce a full safe audit. Cover workspace purpose and main structure, public documentation quality, setup/build/test hints, security and publishing risks based on safe metadata, missing README/docs/.gitignore/AGENTS.md/safety notes, generated folders that should stay ignored, and suggested next safe tasks. Do not edit files. Do not read auth files, .env files, databases, raw logs, raw prompts, private session files, or secrets. Do not include full local paths. Use file or folder names only when safe."
  },
  {
    id: "summarize-public-files",
    label: "Summarize public files",
    title: "Summarize public files",
    description:
      "Inspect the selected workspace in read-only mode and summarize the public-safe files. Focus on README, docs, configuration examples, and source structure. Do not read auth files, .env files, databases, logs, raw prompts, or secrets. Do not edit files."
  },
  {
    id: "inspect-structure",
    label: "Inspect repository structure",
    title: "Inspect repository structure",
    description:
      "Inspect the selected workspace in read-only mode and explain its folder structure, main entry points, build/test commands, and likely ownership boundaries. Do not include full local paths. Do not read secrets, raw logs, or auth files. Do not edit files."
  },
  {
    id: "find-docs-gaps",
    label: "Find documentation gaps",
    title: "Find documentation gaps",
    description:
      "Review the selected workspace in read-only mode and identify missing or unclear public documentation. Suggest safe improvements for setup, usage, testing, and security notes. Do not expose private local paths, secrets, raw prompts, logs, or account data. Do not edit files."
  },
  {
    id: "security-review",
    label: "Run read-only security review",
    title: "Run read-only security review",
    description:
      "Perform a read-only security review of the selected workspace. Look for risky public files, accidental secret patterns, unsafe scripts, overbroad permissions, and publishing risks. Report findings with file names only when safe. Do not read auth files, databases, raw logs, or private prompt content. Do not edit files."
  }
];

function modeInterval(mode: SystemModeName | undefined, fullMs: number, balancedMs: number): number | false {
  if (mode === "token_saver") return false;
  if (mode === "balanced") return balancedMs;
  return fullMs;
}

function useDashboardData(options: { pauseHeavyDashboard?: boolean } = {}) {
  const systemMode = useQuery({ queryKey: ["system-mode"], queryFn: () => apiGet<SystemMode>("/api/system-mode"), refetchInterval: 60000 });
  const mode = systemMode.data?.mode ?? "full";
  const heavyDashboardEnabled = !(options.pauseHeavyDashboard && mode === "token_saver");
  const health = useQuery({ queryKey: ["health"], queryFn: () => apiGet<Health>("/api/health"), refetchInterval: mode === "balanced" ? 60000 : 30000 });
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => apiGet<Summary>("/api/summary"), refetchInterval: mode === "balanced" ? 60000 : 30000 });
  const usage = useQuery({ queryKey: ["usage-limits"], queryFn: () => apiGet<UsageLimits>("/api/usage/limits"), refetchInterval: mode === "balanced" ? 60000 : 30000 });
  const taskTokenUsage = useQuery({ queryKey: ["task-token-usage"], queryFn: () => apiGet<TaskTokenUsage>("/api/tasks/token-usage?days=30"), refetchInterval: mode === "balanced" ? 60000 : 30000 });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => apiGet<{ items: Session[] }>("/api/sessions?limit=200"), refetchInterval: modeInterval(mode, 30000, 120000), enabled: heavyDashboardEnabled });
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => apiGet<{ items: ToolStat[] }>("/api/tools"), refetchInterval: modeInterval(mode, 30000, 120000), enabled: heavyDashboardEnabled });
  const skills = useQuery({ queryKey: ["skills"], queryFn: () => apiGet<{ items: Skill[] }>("/api/skills"), refetchInterval: modeInterval(mode, 60000, 180000), enabled: heavyDashboardEnabled || !options.pauseHeavyDashboard });
  const posture = useQuery({ queryKey: ["posture"], queryFn: () => apiGet<{ findings: Finding[] }>("/api/security-posture"), refetchInterval: modeInterval(mode, 60000, 180000), enabled: heavyDashboardEnabled });
  const context = useQuery({ queryKey: ["context"], queryFn: () => apiGet<{ findings: Finding[]; skills: number; automations: number; repo_agents_files: number; config_present: boolean }>("/api/context-health"), refetchInterval: modeInterval(mode, 60000, 180000), enabled: heavyDashboardEnabled });
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => apiGet<{ items: Task[] }>("/api/tasks"), refetchInterval: mode === "balanced" ? 30000 : 15000 });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: () => apiGet<{ items: Schedule[] }>("/api/schedules"), refetchInterval: mode === "balanced" ? 60000 : 30000 });
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: () => apiGet<{ items: Workspace[] }>("/api/workspaces"), refetchInterval: 60000 });
  return { systemMode, health, summary, usage, taskTokenUsage, sessions, tools, skills, posture, context, tasks, schedules, workspaces };
}

function Layout() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-line bg-ink/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-control border border-focus/40 bg-focus/10">
              <Terminal className="h-5 w-5 text-focus" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-white">Codex Control Center</div>
              <div className="break-words text-xs text-muted">Local observability. Approval-gated control.</div>
            </div>
          </div>
          <nav className="flex w-full flex-wrap items-center gap-2 text-sm sm:w-auto sm:justify-end">
            <Link to="/" className="rounded-control px-2 py-2 text-muted hover:bg-panel2 hover:text-white sm:px-3" activeProps={{ className: "rounded-control bg-panel2 px-2 py-2 text-white sm:px-3" }}>
              Dashboard
            </Link>
            <Link to="/tasks" className="rounded-control px-2 py-2 text-muted hover:bg-panel2 hover:text-white sm:px-3" activeProps={{ className: "rounded-control bg-panel2 px-2 py-2 text-white sm:px-3" }}>
              Tasks
            </Link>
            <Link to="/results" className="rounded-control px-2 py-2 text-muted hover:bg-panel2 hover:text-white sm:px-3" activeProps={{ className: "rounded-control bg-panel2 px-2 py-2 text-white sm:px-3" }}>
              Results
            </Link>
            <Link to="/skills" className="rounded-control px-2 py-2 text-muted hover:bg-panel2 hover:text-white sm:px-3" activeProps={{ className: "rounded-control bg-panel2 px-2 py-2 text-white sm:px-3" }}>
              Skills
            </Link>
            <Link to="/guide" className="rounded-control px-2 py-2 text-muted hover:bg-panel2 hover:text-white sm:px-3" activeProps={{ className: "rounded-control bg-panel2 px-2 py-2 text-white sm:px-3" }}>
              Guide
            </Link>
            <Link to="/publish" className="rounded-control px-2 py-2 text-muted hover:bg-panel2 hover:text-white sm:px-3" activeProps={{ className: "rounded-control bg-panel2 px-2 py-2 text-white sm:px-3" }}>
              Publish
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 py-5">
        <Outlet />
      </main>
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className="rounded-control border border-line bg-panel p-4">
      <div className="mb-3 flex items-center justify-between text-muted">
        <span className="text-xs">{label}</span>
        {icon}
      </div>
      <div className="text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}

function FindingList({ items }: { items: Finding[] }) {
  if (!items.length) return <EmptyState label="No findings yet." />;
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={`${item.level}-${item.title}`} className="rounded-control border border-line bg-panel2 p-3">
          <div className="mb-1 flex items-center gap-2">
            <Pill tone={findingTone(item.level)}>{item.level}</Pill>
            <div className="text-sm font-medium text-white">{item.title}</div>
          </div>
          <div className="text-sm text-muted">{item.detail}</div>
        </div>
      ))}
    </div>
  );
}

function findingTone(level: string): string {
  if (level === "ok") return "ok";
  if (level === "warn") return "warn";
  if (level === "bad") return "bad";
  return "focus";
}

function taskStatusTone(status: string): string {
  if (status === "done") return "ok";
  if (status === "failed") return "bad";
  if (status === "running" || status === "pending") return "focus";
  if (status === "cancelled") return "neutral";
  return "warn";
}

function publishStatusTone(status: string): string {
  if (status === "ready" || status === "ok" || status === "READY") return "ok";
  if (status === "blocked" || status === "block" || status === "BLOCK") return "bad";
  return "warn";
}

function publishStatusLabel(status: string): string {
  if (status === "ready") return "Ready";
  if (status === "needs_review") return "Needs review";
  if (status === "blocked") return "Blocked";
  if (status === "ok") return "OK";
  if (status === "block") return "Block";
  if (status === "review") return "Review";
  return status;
}

function resultCategoryTone(category: ResultCategory): string {
  if (category === "security") return "bad";
  if (category === "audit" || category === "cleanup") return "warn";
  if (category === "docs" || category === "structure") return "focus";
  return "neutral";
}

function resultCategoryLabel(category: ResultCategoryFilter): string {
  return RESULT_CATEGORIES.find((item) => item.id === category)?.label ?? "General";
}

function inferResultCategory(task: Task): ResultCategory {
  const text = `${task.title} ${task.description} ${task.output_summary ?? ""} ${task.failure_reason ?? ""}`.toLowerCase();
  if (/(full safe|audit|readiness|vault health|health report|score)/.test(text)) return "audit";
  if (/(security|secret|secrets|token|auth|\.env|vulnerability|privacy|publish|public-safety|safety)/.test(text)) return "security";
  if (/(readme|documentation|docs|guide|setup|install|usage|tutorial)/.test(text)) return "docs";
  if (/(structure|folder|repository layout|entry point|entry-point|build command|test command|architecture)/.test(text)) return "structure";
  if (/(cleanup|clean up|generated|ignore|\.gitignore|delete|archive|tidy|node_modules|dist)/.test(text)) return "cleanup";
  return "general";
}

function taskTokenText(task: Task): string {
  return task.total_tokens === null || task.total_tokens === undefined ? "unknown tokens" : `${compactNumber(task.total_tokens)} tokens`;
}

function resultNextActions(task: Task, category: ResultCategory): string[] {
  if (task.status === "failed") {
    return [
      "Open details and read the safe failure reason.",
      "Rerun once if the failure looks transient.",
      "Keep the rerun read-only unless the fix needs edits."
    ];
  }
  if (task.status !== "done") {
    return [
      "Wait for the task to finish before acting on the result.",
      "Cancel only if the task is clearly stuck or no longer useful.",
      "Keep new follow-up tasks small and read-only."
    ];
  }
  if (category === "audit") {
    return [
      "Review README, .gitignore, AGENTS.md, and docs findings first.",
      "Open Vault Health Report for file-location details.",
      "Queue a docs gap or security review follow-up if needed."
    ];
  }
  if (category === "docs") {
    return [
      "Turn the safest documentation gaps into one focused task.",
      "Keep examples fake and avoid private local paths.",
      "Run a read-only public-safety review before publishing."
    ];
  }
  if (category === "security") {
    return [
      "Check risky filenames in Vault Health Report.",
      "Verify secret-like files are ignored and stay private.",
      "Use workspace-write only for an explicit cleanup task."
    ];
  }
  if (category === "structure") {
    return [
      "Use the structure notes to pick the smallest next task.",
      "Add or improve AGENTS.md if repeated guidance is needed.",
      "Run docs gap review if setup or ownership is unclear."
    ];
  }
  if (category === "cleanup") {
    return [
      "Review generated folders and ignore-rule suggestions.",
      "Do not delete files from the dashboard without a focused edit task.",
      "Run the public-safety scan again after cleanup."
    ];
  }
  return [
    "Review the safe summary and decide if a follow-up is needed.",
    "Prefer one small read-only follow-up task at a time.",
    "Use Results filters to compare similar runs."
  ];
}

function safeResultCopyText(task: Task, category: ResultCategory): string {
  return [
    "Codex Control Center result summary",
    "",
    `Task: ${task.title}`,
    `Category: ${resultCategoryLabel(category)}`,
    `Status: ${task.status}`,
    `Workspace: ${task.cwd_label}`,
    `Sandbox: ${task.sandbox}`,
    `Completed: ${formatShortTime(task.completed_at ?? task.updated_at)}`,
    `Duration: ${formatDuration(task.duration_ms)}`,
    `Tools: ${task.tool_count ?? 0}`,
    `Tokens: ${taskTokenText(task)}`,
    "",
    "Safe summary:",
    task.output_summary || "No safe summary was recorded.",
    task.failure_reason ? `\nFailure reason:\n${task.failure_reason}` : "",
    "",
    "Safety note: copied from dashboard metadata and safe summaries only. Task prompt details, raw logs, full paths, and secrets are excluded."
  ].filter(Boolean).join("\n");
}

function safeMarkdownReportText(task: Task, category: ResultCategory, nextActions: string[]): string {
  const summary = task.output_summary || "No safe summary was recorded.";
  const failure = task.failure_reason ? ["", "## Failure Reason", "", task.failure_reason] : [];
  return [
    "# Codex Control Center Safe Result Report",
    "",
    "## Task",
    "",
    `- Title: ${task.title}`,
    `- Category: ${resultCategoryLabel(category)}`,
    `- Status: ${task.status}`,
    `- Workspace: ${task.cwd_label}`,
    `- Sandbox: ${task.sandbox}`,
    `- Completed: ${formatShortTime(task.completed_at ?? task.updated_at)}`,
    `- Duration: ${formatDuration(task.duration_ms)}`,
    `- Tools: ${task.tool_count ?? 0}`,
    `- Events: ${task.event_count ?? 0}`,
    `- Tokens: ${taskTokenText(task)}`,
    "",
    "## Safe Summary",
    "",
    summary,
    ...failure,
    "",
    "## Suggested Next Actions",
    "",
    ...(nextActions.length ? nextActions.map((action, index) => `${index + 1}. ${action}`) : ["No next actions were generated."]),
    "",
    "## Safety Note",
    "",
    "This report is copied from dashboard metadata and safe summaries only. It excludes task prompt details, raw logs, raw session IDs, full local paths, secrets, and private local data."
  ].join("\n");
}

async function writeClipboardText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const textArea = document.createElement("textarea");
      textArea.value = text;
      textArea.setAttribute("readonly", "true");
      textArea.style.position = "fixed";
      textArea.style.left = "-9999px";
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      const copied = document.execCommand("copy");
      document.body.removeChild(textArea);
      return copied;
    } catch {
      return false;
    }
  }
}

function followUpTaskPayload(task: Task, kind: FollowUpKind): {
  title: string;
  description: string;
  sandbox: "read-only";
  workspace_id?: number;
} {
  const template = FOLLOW_UP_TASKS[kind];
  return {
    title: template.title,
    description: template.description,
    sandbox: "read-only",
    workspace_id: task.workspace_id ?? undefined
  };
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `${Math.round(value)}%`;
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "n/a";
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return `${minutes}m ${remaining}s`;
}

function formatShortTime(value: string | null | undefined): string {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function localDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function sessionDate(session: Session): Date {
  const date = new Date(session.updated_at);
  return Number.isNaN(date.getTime()) ? new Date(0) : date;
}

function startOfLocalWeek(date: Date): Date {
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const mondayOffset = (start.getDay() + 6) % 7;
  start.setDate(start.getDate() - mondayOffset);
  return start;
}

function sessionGroupKey(session: Session, mode: SessionGroupMode): string {
  const date = sessionDate(session);
  if (mode === "year") return `${date.getFullYear()}`;
  if (mode === "month") return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  if (mode === "week") return localDateKey(startOfLocalWeek(date));
  return localDateKey(date);
}

function sessionGroupLabel(date: Date, mode: SessionGroupMode): string {
  if (mode === "year") return `${date.getFullYear()}`;
  if (mode === "month") return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  if (mode === "week") return `Week of ${startOfLocalWeek(date).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;

  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (localDateKey(date) === localDateKey(today)) return "Today";
  if (localDateKey(date) === localDateKey(yesterday)) return "Yesterday";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function groupSessionsByDate(sessions: Session[], mode: SessionGroupMode): SessionGroup[] {
  const groups = new Map<string, SessionGroup>();
  for (const session of sessions) {
    const date = sessionDate(session);
    const key = sessionGroupKey(session, mode);
    const existing = groups.get(key);
    if (existing) {
      existing.sessions.push(session);
    } else {
      groups.set(key, { key, label: sessionGroupLabel(date, mode), sessions: [session] });
    }
  }
  return Array.from(groups.values());
}

function formatReset(epochSeconds: number | null | undefined, mode: "time" | "date"): string {
  if (!epochSeconds) return "n/a";
  const date = new Date(epochSeconds * 1000);
  if (mode === "date") {
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function formatResetCountdown(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "reset unknown";
  const remainingSeconds = Math.ceil((epochSeconds * 1000 - Date.now()) / 1000);
  if (remainingSeconds <= 0) return "reset due";
  const days = Math.floor(remainingSeconds / 86400);
  const hours = Math.floor((remainingSeconds % 86400) / 3600);
  const minutes = Math.floor((remainingSeconds % 3600) / 60);
  if (days > 0) return `resets in ${days}d ${hours}h`;
  if (hours > 0) return `resets in ${hours}h ${minutes}m`;
  if (minutes > 0) return `resets in ${minutes}m`;
  return "resets in <1m";
}

function formatObservedAge(ageSeconds: number | null | undefined): string {
  if (ageSeconds === null || ageSeconds === undefined) return "freshness unknown";
  if (ageSeconds < 60) return "observed just now";
  const minutes = Math.floor(ageSeconds / 60);
  if (minutes < 60) return `observed ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours < 24) return `observed ${hours}h ${remainingMinutes}m ago`;
  const days = Math.floor(hours / 24);
  return `observed ${days}d ago`;
}

function usageWindowLabel(minutes: number | null | undefined, fallback: string): string {
  if (!minutes) return fallback;
  if (minutes >= 10080) return "Weekly";
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

function usageTone(remaining: number | null | undefined): string {
  if (remaining === null || remaining === undefined) return "neutral";
  if (remaining < 10) return "bad";
  if (remaining < 20) return "warn";
  return "ok";
}

function usageBarColor(tone: string): string {
  if (tone === "bad") return "bg-bad";
  if (tone === "warn") return "bg-warn";
  if (tone === "ok") return "bg-good";
  return "bg-focus";
}

function formatUsageBurnRate(rate: UsageBurnRate): string {
  if (!rate.available) return "Need more local history";
  if (rate.percent_spent <= 0) return `No spend over ${rate.hours}h`;
  return `${formatPercent(rate.percent_spent)} used over ${rate.hours}h (${rate.percent_per_hour}%/h)`;
}

function usageFreshnessTone(value: string): string {
  if (value === "fresh") return "ok";
  if (value === "old") return "warn";
  if (value === "very_stale") return "bad";
  return "neutral";
}

function usageAdviceTone(value: string): string {
  if (value === "normal") return "ok";
  if (value === "small_tasks") return "warn";
  return "bad";
}

function usageAdviceLabel(value: string): string {
  if (value === "normal") return "Good for normal tasks";
  if (value === "small_tasks") return "Use smaller tasks";
  return "Wait for reset";
}

function trendDirectionLabel(value: string): string {
  if (value === "falling") return "usage falling";
  if (value === "recovering") return "usage recovering";
  if (value === "stable") return "usage stable";
  return "trend unknown";
}

function trendDirectionTone(value: string): string {
  if (value === "falling") return "warn";
  if (value === "recovering") return "ok";
  if (value === "stable") return "focus";
  return "neutral";
}

function MiniBarChart({
  points,
  maxValue = 100,
  heightClass = "h-14"
}: {
  points: Array<{ key: string; value: number; tone?: string; title: string }>;
  maxValue?: number;
  heightClass?: string;
}) {
  if (points.length === 0) return null;
  const safeMax = Math.max(maxValue, 1);
  return (
    <div className={`${heightClass} w-full max-w-full overflow-hidden rounded-control bg-ink/60 p-1`}>
      <div
        className="grid h-full w-full max-w-full items-end gap-0.5 overflow-hidden"
        style={{ gridTemplateColumns: `repeat(${points.length}, minmax(0, 1fr))` }}
      >
        {points.map((point) => {
          const boundedValue = Math.max(0, Math.min(safeMax, point.value));
          const heightPercent = (boundedValue / safeMax) * 100;
          return (
            <div
              key={point.key}
              className={`min-w-0 rounded-t ${usageBarColor(point.tone ?? "focus")}`}
              style={{ height: `${heightPercent}%`, minHeight: "8px" }}
              title={point.title}
            />
          );
        })}
      </div>
    </div>
  );
}

function readinessTone(score: number | null | undefined): string {
  if (score === null || score === undefined) return "neutral";
  if (score < 60) return "bad";
  if (score < 80) return "warn";
  return "ok";
}

function ReadinessScoreCard({
  score,
  isLoading,
  isError,
  workspaces,
  selectedWorkspaceId,
  onWorkspaceChange
}: {
  score: HealthScore | undefined;
  isLoading: boolean;
  isError: boolean;
  workspaces: Workspace[];
  selectedWorkspaceId: string;
  onWorkspaceChange: (value: string) => void;
}) {
  const findings = score?.findings ?? [];
  const topFindings = [...findings].sort((a, b) => {
    const weight: Record<string, number> = { bad: 0, warn: 1, info: 2, ok: 3 };
    return (weight[a.level] ?? 4) - (weight[b.level] ?? 4);
  }).slice(0, 4);
  const tone = readinessTone(score?.overall_score);
  return (
    <Panel
      title="Readiness Score"
      action={workspaces.length > 1 ? (
        <select
          className="max-w-36 rounded-control border border-line bg-panel2 px-2 py-1 text-xs text-white outline-none focus:border-focus"
          value={selectedWorkspaceId}
          onChange={(event) => onWorkspaceChange(event.target.value)}
        >
          {workspaces.map((workspace) => (
            <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
          ))}
        </select>
      ) : undefined}
    >
      {isLoading ? <EmptyState label="Loading readiness score..." /> : isError || !score ? <EmptyState label="Readiness score unavailable." /> : (
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-4xl font-semibold text-white">{score.overall_score}</div>
              <div className="text-xs text-muted">Scores are metadata-only and local.</div>
            </div>
            <Pill tone={tone}>{tone}</Pill>
          </div>
          <div className="h-2 rounded bg-ink">
            <div className={`h-2 rounded ${usageBarColor(tone)}`} style={{ width: `${Math.max(0, Math.min(100, score.overall_score))}%` }} />
          </div>
          <div className="grid grid-cols-2 gap-2 text-center text-sm">
            <div className="rounded-control bg-panel2 p-2"><div className="text-lg text-white">{score.system_score}</div><div className="text-xs text-muted">system</div></div>
            <div className="rounded-control bg-panel2 p-2"><div className="text-lg text-white">{score.workspace_score}</div><div className="text-xs text-muted">vault</div></div>
          </div>
          <div className="rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
            <div className="truncate font-medium text-white">{score.workspace.name}</div>
            <div className="mono truncate">{score.workspace.path_label}</div>
          </div>
          <div className="space-y-2">
            {topFindings.map((finding) => (
              <div key={`${finding.level}-${finding.title}`} className="rounded-control border border-line bg-panel2 p-2 text-xs">
                <div className="mb-1 flex items-center gap-2">
                  <Pill tone={findingTone(finding.level)}>{finding.level}</Pill>
                  <span className="font-medium text-white">{finding.title}</span>
                </div>
                <div className="text-muted">{finding.detail}</div>
              </div>
            ))}
          </div>
          <a
            className="inline-flex items-center justify-center gap-2 rounded-control border border-focus bg-focus px-3 py-2 text-sm font-semibold text-ink shadow-sm hover:bg-focus/90"
            href={`/health-report?workspace_id=${encodeURIComponent(selectedWorkspaceId || String(score.workspace.id))}`}
          >
            <ShieldCheck className="h-4 w-4" />
            View full report
          </a>
        </div>
      )}
    </Panel>
  );
}

function UsageRemainingCard({ usage, onSync, isSyncing }: { usage: UsageLimits | undefined; onSync: () => void; isSyncing: boolean }) {
  const action = (
    <div className="flex items-center gap-2">
      {usage?.available ? (usage.stale ? <Pill tone="warn">stale</Pill> : <Pill tone="ok">local</Pill>) : null}
      <button
        className="rounded-control border border-line p-2 text-muted hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
        onClick={onSync}
        disabled={isSyncing}
        title="Sync usage from local sessions"
        aria-label="Sync usage from local sessions"
      >
        <RefreshCw className={`h-4 w-4 ${isSyncing ? "animate-spin" : ""}`} />
      </button>
    </div>
  );
  const limit = usage?.limit;
  if (!usage || !usage.available || !limit) {
    return (
      <Panel title="Usage Remaining" action={action}>
        <EmptyState label="No local Codex usage-limit metadata found yet. Run a Codex task, then sync." />
      </Panel>
    );
  }
  const primaryRemaining = limit.primary_remaining_percent ?? 0;
  const secondaryRemaining = limit.secondary_remaining_percent ?? 0;
  const primaryTone = usageTone(limit.primary_remaining_percent);
  const secondaryTone = usageTone(limit.secondary_remaining_percent);
  const lowTone = primaryTone === "bad" || secondaryTone === "bad" ? "bad" : primaryTone === "warn" || secondaryTone === "warn" ? "warn" : null;
  const insights = usage.insights;
  const lastLimitHit = insights.limit_hits[0];
  const trendPoints = insights.trend_points;
  return (
    <Panel title="Usage Remaining" action={action}>
      <div className="space-y-3">
        <div className="rounded-control border border-line bg-panel2 p-3">
          <div className="mb-2 flex flex-wrap items-start justify-between gap-2 text-sm">
            <div className="min-w-0">
              <div className="font-medium text-white">{usageWindowLabel(limit.primary_window_minutes, "Primary")}</div>
              <div className="break-words text-xs text-muted">{formatResetCountdown(limit.primary_resets_at)} - {formatReset(limit.primary_resets_at, "time")}</div>
            </div>
            <Pill tone={primaryTone}>{formatPercent(limit.primary_remaining_percent)}</Pill>
          </div>
          <div className="h-2 rounded bg-ink">
            <div className={`h-2 rounded ${usageBarColor(primaryTone)}`} style={{ width: `${Math.max(0, Math.min(100, primaryRemaining))}%` }} />
          </div>
        </div>
        <div className="rounded-control border border-line bg-panel2 p-3">
          <div className="mb-2 flex flex-wrap items-start justify-between gap-2 text-sm">
            <div className="min-w-0">
              <div className="font-medium text-white">{usageWindowLabel(limit.secondary_window_minutes, "Weekly")}</div>
              <div className="break-words text-xs text-muted">{formatResetCountdown(limit.secondary_resets_at)} - {formatReset(limit.secondary_resets_at, "date")}</div>
            </div>
            <Pill tone={secondaryTone}>{formatPercent(limit.secondary_remaining_percent)}</Pill>
          </div>
          <div className="h-2 rounded bg-ink">
            <div className={`h-2 rounded ${usageBarColor(secondaryTone)}`} style={{ width: `${Math.max(0, Math.min(100, secondaryRemaining))}%` }} />
          </div>
        </div>
        {lowTone && (
          <div className={`rounded-control border p-3 text-xs ${lowTone === "bad" ? "border-bad/40 bg-bad/10 text-bad" : "border-warn/40 bg-warn/10 text-warn"}`}>
            Usage remaining is low. Prefer smaller read-only tasks until the relevant window resets.
          </div>
        )}
        <div className="grid gap-2 md:grid-cols-2">
          <div className="rounded-control border border-line bg-panel2 p-3 text-xs">
            <div className="mb-1 font-medium text-white">Primary burn rate</div>
            <div className="break-words text-muted">{formatUsageBurnRate(insights.burn_rate.primary)}</div>
          </div>
          <div className="rounded-control border border-line bg-panel2 p-3 text-xs">
            <div className="mb-1 font-medium text-white">Weekly burn rate</div>
            <div className="break-words text-muted">{formatUsageBurnRate(insights.burn_rate.secondary)}</div>
          </div>
        </div>
        <div className="rounded-control border border-line bg-panel2 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-medium text-white">30-day trend</span>
            <Pill tone={trendDirectionTone(insights.trend_direction)}>{trendDirectionLabel(insights.trend_direction)}</Pill>
          </div>
          {trendPoints.length === 0 ? (
            <EmptyState label="Need more local usage observations for a trend." />
          ) : (
            <MiniBarChart
              points={trendPoints.map((point) => {
                const value = point.primary_remaining_percent ?? point.secondary_remaining_percent ?? 0;
                return {
                  key: point.date,
                  value,
                  tone: usageTone(value),
                  title: `${point.date}: ${formatPercent(point.primary_remaining_percent ?? point.secondary_remaining_percent)}`
                };
              })}
            />
          )}
        </div>
        <div className="grid gap-2 xl:grid-cols-2">
          <div className="rounded-control border border-line bg-panel2 p-3 text-xs">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-white">Freshness quality</span>
              <Pill tone={usageFreshnessTone(insights.freshness_quality)}>{insights.freshness_quality.replace("_", " ")}</Pill>
            </div>
            <div className="break-words text-muted">{insights.observation_count} local observations in the last 30 days.</div>
          </div>
          <div className="rounded-control border border-line bg-panel2 p-3 text-xs">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-white">Task advice</span>
              <Pill tone={usageAdviceTone(insights.task_advice)}>{usageAdviceLabel(insights.task_advice)}</Pill>
            </div>
            <div className="break-words text-muted">Based only on local remaining percent and metadata freshness.</div>
          </div>
        </div>
        <div className="rounded-control border border-line bg-panel2 p-3 text-xs">
          <div className="mb-1 font-medium text-white">Last limit hit</div>
          {lastLimitHit ? (
            <div className="text-muted">
              {lastLimitHit.rate_limit_reached_type} observed {formatShortTime(lastLimitHit.observed_at)} from local metadata.
            </div>
          ) : (
            <div className="text-muted">No local limit-hit event observed in the last 30 days.</div>
          )}
        </div>
        <div className="space-y-1 rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
          <div className="flex items-center justify-between gap-2">
            <span>{limit.plan_type || "unknown plan"}</span>
            <span>{formatObservedAge(usage.age_seconds)}</span>
          </div>
          {usage.stale && <div className="text-warn">Local usage metadata is over 1 hour old. Run a Codex task and sync to refresh it.</div>}
          <div>Best-effort local metadata. Codex app remains the source of truth.</div>
        </div>
      </div>
    </Panel>
  );
}

function SystemModeCard({ mode, onChange, isChanging }: { mode: SystemMode | undefined; onChange: (mode: SystemModeName) => void; isChanging: boolean }) {
  const activeMode = mode?.mode ?? "full";
  return (
    <Panel title="System Mode">
      <div className="space-y-3">
        <div className="rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
          Observe Mode does not call OpenAI or spend Codex tokens. Token Saver blocks dashboard-launched Codex work and pauses heavier dashboard refreshes.
        </div>
        <div className="grid gap-2">
          {(mode?.presets ?? [
            { id: "full" as SystemModeName, label: "Full", description: "All dashboard features and current refresh cadence." },
            { id: "balanced" as SystemModeName, label: "Balanced", description: "All features available with slower noncritical polling." },
            { id: "token_saver" as SystemModeName, label: "Token Saver", description: "Blocks dashboard task launches and pauses heavier dashboard refreshes." }
          ]).map((preset) => (
            <button
              key={preset.id}
              className={`rounded-control border p-3 text-left ${activeMode === preset.id ? "border-focus bg-focus/10" : "border-line bg-panel2 hover:border-focus/60"} disabled:cursor-not-allowed disabled:opacity-60`}
              disabled={isChanging}
              onClick={() => onChange(preset.id)}
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="font-medium text-white">{preset.label}</span>
                {activeMode === preset.id && <Pill tone={preset.id === "token_saver" ? "warn" : "focus"}>active</Pill>}
              </div>
              <div className="text-xs text-muted">{preset.description}</div>
            </button>
          ))}
        </div>
      </div>
    </Panel>
  );
}

function ControlCenterTokensCard({ usage }: { usage: TaskTokenUsage | undefined }) {
  if (!usage) {
    return (
      <Panel title="Control Center Tokens">
        <EmptyState label="Loading dashboard task token usage..." />
      </Panel>
    );
  }
  const latest = usage.latest_task;
  const maxTrendTokens = Math.max(...usage.trend_points.map((item) => item.total_tokens), 1);
  return (
    <Panel title="Control Center Tokens">
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 text-center text-sm">
          <div className="rounded-control bg-panel2 p-3">
            <div className="text-xl text-white">{compactNumber(usage.today.total_tokens)}</div>
            <div className="text-xs text-muted">today</div>
          </div>
          <div className="rounded-control bg-panel2 p-3">
            <div className="text-xl text-white">{compactNumber(usage.totals.total_tokens)}</div>
            <div className="text-xs text-muted">{usage.days} days</div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-center text-xs">
          <div className="rounded-control border border-line bg-panel2 p-2">
            <div className="text-lg text-white">{compactNumber(usage.totals.launched_tasks)}</div>
            <div className="text-muted">launched tasks</div>
          </div>
          <div className="rounded-control border border-line bg-panel2 p-2">
            <div className="text-lg text-warn">{compactNumber(usage.totals.unknown_task_count)}</div>
            <div className="text-muted">unknown</div>
          </div>
        </div>
        <div className="rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
          <div className="mb-1 font-medium text-white">Latest launched task</div>
          {latest ? (
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <span className="min-w-0 truncate">Task #{latest.id} - {latest.status}</span>
              <span className="mono text-white">{latest.total_tokens === null ? "unknown" : compactNumber(latest.total_tokens)}</span>
            </div>
          ) : (
            <div>No dashboard-launched tasks yet.</div>
          )}
        </div>
        <div className="rounded-control border border-line bg-panel2 p-3">
          <div className="mb-2 text-xs font-medium text-white">Task token trend</div>
          {usage.trend_points.length === 0 ? (
            <EmptyState label="No dashboard task token trend yet." />
          ) : (
            <MiniBarChart
              heightClass="h-12"
              maxValue={maxTrendTokens}
              points={usage.trend_points.map((point) => ({
                key: point.date,
                value: point.total_tokens,
                tone: "focus",
                title: `${point.date}: ${compactNumber(point.total_tokens)} tokens`
              }))}
            />
          )}
        </div>
        <div className="rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
          Dashboard-launched tasks only. This does not include all local Codex sessions or hidden quota totals.
        </div>
      </div>
    </Panel>
  );
}

function DashboardPage() {
  const data = useDashboardData({ pauseHeavyDashboard: true });
  const queryClient = useQueryClient();
  const [scoreWorkspaceId, setScoreWorkspaceId] = useState("");
  const [sessionGroupMode, setSessionGroupMode] = useState<SessionGroupMode>("week");
  const [openSessionGroups, setOpenSessionGroups] = useState<Record<string, boolean>>({});
  const mode = data.systemMode.data?.mode ?? "full";
  const tokenSaverActive = mode === "token_saver";
  const sync = useMutation({
    mutationFn: () => apiPost("/api/sync"),
    onSuccess: () => {
      ["usage-limits", "health", "summary", "sessions", "health-score", "tools", "skills", "context", "posture", "task-token-usage"].forEach((key) => {
        queryClient.invalidateQueries({ queryKey: [key] });
      });
    }
  });
  const updateMode = useMutation({
    mutationFn: (nextMode: SystemModeName) => apiPost<SystemMode>("/api/system-mode", { mode: nextMode }),
    onSuccess: () => {
      ["system-mode", "sessions", "health-score", "tools", "skills", "context", "posture", "tasks", "schedules"].forEach((key) => {
        queryClient.invalidateQueries({ queryKey: [key] });
      });
    }
  });
  const health = data.health.data;
  const summary = data.summary.data?.today;
  const sessions = data.sessions.data?.items ?? [];
  const tools = data.tools.data?.items ?? [];
  const workspaceItems = data.workspaces.data?.items ?? [];
  const defaultScoreWorkspace = workspaceItems.find((workspace) => workspace.is_default) ?? workspaceItems[0];
  const selectedScoreWorkspaceId = scoreWorkspaceId || (defaultScoreWorkspace ? String(defaultScoreWorkspace.id) : "");
  const healthScore = useQuery({
    queryKey: ["health-score", selectedScoreWorkspaceId || "default"],
    queryFn: () => apiGet<HealthScore>(selectedScoreWorkspaceId ? `/api/health-score?workspace_id=${encodeURIComponent(selectedScoreWorkspaceId)}` : "/api/health-score"),
    refetchInterval: mode === "balanced" ? 180000 : 60000,
    enabled: !tokenSaverActive
  });
  const sessionGroups = groupSessionsByDate(sessions, sessionGroupMode);
  const sessionGroupModes: SessionGroupMode[] = ["day", "week", "month", "year"];

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-4">
        <Metric label="Today sessions" value={compactNumber(summary?.sessions)} icon={<Activity className="h-4 w-4" />} />
        <Metric label="Today tokens" value={compactNumber(summary?.total_tokens)} icon={<Workflow className="h-4 w-4" />} />
        <Metric label="Tool calls" value={compactNumber(summary?.tools)} icon={<ListChecks className="h-4 w-4" />} />
        <Metric label="Recent sessions" value={compactNumber(summary?.recent_sessions)} icon={<Clock className="h-4 w-4" />} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2 xl:grid-cols-[minmax(260px,0.85fr)_minmax(320px,1fr)_minmax(440px,1.35fr)]">
        <SystemModeCard mode={data.systemMode.data} onChange={(nextMode) => updateMode.mutate(nextMode)} isChanging={updateMode.isPending} />

        <ControlCenterTokensCard usage={data.taskTokenUsage.data} />

        <div className="min-w-0 lg:col-span-2 xl:col-span-1">
          <UsageRemainingCard usage={data.usage.data} onSync={() => sync.mutate()} isSyncing={sync.isPending} />
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2 xl:grid-cols-4">
        <div className="min-w-0">
          {tokenSaverActive ? (
            <Panel title="Readiness Score">
              <EmptyState label="Paused by Token Saver. Switch to Balanced or Full to refresh this metadata panel." />
            </Panel>
          ) : (
            <ReadinessScoreCard
              score={healthScore.data}
              isLoading={healthScore.isLoading}
              isError={healthScore.isError}
              workspaces={workspaceItems}
              selectedWorkspaceId={selectedScoreWorkspaceId}
              onWorkspaceChange={setScoreWorkspaceId}
            />
          )}
        </div>

        <Panel
          title="System Health"
          action={
            <button
              className="rounded-control border border-line p-2 text-muted hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => sync.mutate()}
              disabled={sync.isPending}
              title="Sync all local metadata"
              aria-label="Sync all local metadata"
            >
              <RefreshCw className={`h-4 w-4 ${sync.isPending ? "animate-spin" : ""}`} />
            </button>
          }
        >
          {health ? (
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between"><span className="text-muted">Mode</span><Pill tone="focus">{health.mode}</Pill></div>
              <div className="flex items-center justify-between"><span className="text-muted">Codex</span><span className="mono text-white">{health.codex_version ?? "missing"}</span></div>
              <div className="flex items-center justify-between gap-3"><span className="text-muted">Control</span><Pill tone={health.control_mode_available ? "ok" : "warn"}>{health.control_mode_available ? "available" : "unavailable"}</Pill></div>
              <div className="flex items-center justify-between gap-3"><span className="text-muted">Reason</span><span className="max-w-44 truncate text-right text-white" title={health.control_mode_reason}>{health.control_mode_reason}</span></div>
              <div className="flex items-center justify-between gap-3"><span className="text-muted">Login</span><span className="max-w-44 truncate text-right text-white" title={health.codex_login_status}>{health.codex_login_status}</span></div>
              <div className="flex items-center justify-between"><span className="text-muted">Last sync</span><span className="mono text-white">{formatShortTime(health.last_sync?.created_at)}</span></div>
              <div className="flex items-center justify-between"><span className="text-muted">Session files</span><span className="mono text-white">{health.session_files_scanned}</span></div>
              <div className="flex items-center justify-between"><span className="text-muted">OTel</span><Pill tone={health.otel.status === "receiving" ? "ok" : health.otel.status === "configured" ? "focus" : "neutral"}>{health.otel.status}</Pill></div>
              <div className="flex items-center justify-between gap-3"><span className="text-muted">DB</span><span className="max-w-44 truncate text-right text-white" title={health.db_label}>{health.db_label}</span></div>
              <div className="flex items-center justify-between"><span className="text-muted">API key required</span><Pill tone={health.api_key_required ? "warn" : "ok"}>{String(health.api_key_required)}</Pill></div>
              <div className="flex items-center justify-between"><span className="text-muted">auth.json read</span><Pill tone={health.auth_json_read ? "bad" : "ok"}>{String(health.auth_json_read)}</Pill></div>
            </div>
          ) : <EmptyState label="Loading health..." />}
        </Panel>

        <Panel title="Security Posture">
          {tokenSaverActive ? <EmptyState label="Paused by Token Saver." /> : <FindingList items={data.posture.data?.findings ?? []} />}
        </Panel>

        <Panel title="Context Health">
          {tokenSaverActive ? (
            <EmptyState label="Paused by Token Saver." />
          ) : (
            <>
              <div className="mb-4 grid grid-cols-3 gap-2 text-center text-sm">
                <div className="rounded-control bg-panel2 p-3"><div className="text-lg text-white">{data.context.data?.skills ?? 0}</div><div className="text-xs text-muted">skills</div></div>
                <div className="rounded-control bg-panel2 p-3"><div className="text-lg text-white">{data.context.data?.automations ?? 0}</div><div className="text-xs text-muted">autos</div></div>
                <div className="rounded-control bg-panel2 p-3"><div className="text-lg text-white">{data.context.data?.repo_agents_files ?? 0}</div><div className="text-xs text-muted">AGENTS</div></div>
              </div>
              <FindingList items={data.context.data?.findings ?? []} />
            </>
          )}
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel
          title="Recent Sessions"
          action={
            <div className="flex max-w-full flex-wrap rounded-control border border-line bg-panel2 p-0.5">
              {sessionGroupModes.map((mode) => (
                <button
                  key={mode}
                  className={`rounded px-2 py-1 text-xs capitalize ${sessionGroupMode === mode ? "bg-focus text-ink" : "text-muted hover:text-white"}`}
                  onClick={() => {
                    setSessionGroupMode(mode);
                    setOpenSessionGroups({});
                  }}
                >
                  {mode}
                </button>
              ))}
            </div>
          }
        >
          <div className="space-y-3">
            {tokenSaverActive ? <EmptyState label="Paused by Token Saver." /> : sessions.length === 0 ? <EmptyState label="No Codex sessions found yet." /> : sessionGroups.map((group, index) => {
              const isOpen = openSessionGroups[group.key] ?? index === 0;
              return (
                <div key={group.key} className="rounded-control border border-line bg-panel2">
                  <button
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm"
                    onClick={() => setOpenSessionGroups((current) => ({ ...current, [group.key]: !isOpen }))}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      {isOpen ? <ChevronUp className="h-4 w-4 shrink-0 text-muted" /> : <ChevronDown className="h-4 w-4 shrink-0 text-muted" />}
                      <span className="truncate font-medium text-white">{group.label}</span>
                    </div>
                    <Pill tone={index === 0 ? "focus" : "neutral"}>{group.sessions.length} sessions</Pill>
                  </button>
                  {isOpen && (
                    <div className="space-y-2 border-t border-line p-3">
                      {group.sessions.map((session) => (
                        <div key={session.session_id} className="grid gap-3 rounded-control border border-line bg-ink p-3 text-sm sm:grid-cols-[1fr_auto]">
                          <div className="min-w-0">
                            <div className="truncate font-medium text-white">{session.project_label}</div>
                            <div className="truncate text-xs text-muted">{session.model}</div>
                          </div>
                          <div className="flex flex-col items-start gap-2 sm:items-end">
                            <div className="flex flex-wrap gap-2 sm:justify-end">
                              <Pill tone={session.status === "recent" ? "ok" : "neutral"}>{session.status}</Pill>
                              <Pill tone="neutral">{compactNumber(session.total_tokens)} tok</Pill>
                              <Pill tone="neutral">{session.tool_count ?? 0} tools</Pill>
                            </div>
                            <span className="mono text-xs text-muted">{formatShortTime(session.updated_at)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel title="Top Tools">
          <div className="space-y-2">
            {tokenSaverActive ? <EmptyState label="Paused by Token Saver." /> : tools.length === 0 ? <EmptyState label="No tool metadata parsed yet." /> : tools.slice(0, 12).map((tool) => (
              <div key={tool.tool_name} className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-control border border-line bg-panel2 p-3 text-sm">
                <span className="mono min-w-0 truncate text-white">{tool.tool_name}</span>
                <div className="flex flex-wrap items-center gap-2">
                  <Pill tone="focus">{tool.calls} calls</Pill>
                  {tool.failures > 0 && <Pill tone="warn">{tool.failures} fail</Pill>}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

const REPORT_LEVELS: Array<Finding["level"]> = ["bad", "warn", "info", "ok"];
type ReportFilter = "all" | "bad" | "warn" | "info" | "secret-like" | "log-like" | "database-like" | "raw-session-like" | "generated-folder";

const REPORT_FILTERS: Array<{ id: ReportFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "bad", label: "Bad" },
  { id: "warn", label: "Warn" },
  { id: "info", label: "Info" },
  { id: "secret-like", label: "Secret-like" },
  { id: "log-like", label: "Logs" },
  { id: "database-like", label: "Database" },
  { id: "raw-session-like", label: "Raw sessions" },
  { id: "generated-folder", label: "Generated" }
];

type ReviewStatus = "needs_action" | "reviewed" | "accepted_risk" | "ignore_for_now";
type ReviewFilter = "all" | ReviewStatus;
type ReportPresetId = "publishing-review" | "secrets-cleanup" | "generated-cleanup" | "logs-databases";
type HealthScanMode = "standard" | "deep";
type PublicationStatus = "not_ready" | "needs_review" | "public_safe_candidate";

const REVIEW_STATUS_OPTIONS: Array<{ id: ReviewStatus; label: string }> = [
  { id: "needs_action", label: "Needs action" },
  { id: "reviewed", label: "Reviewed" },
  { id: "accepted_risk", label: "Accepted risk" },
  { id: "ignore_for_now", label: "Ignore for now" }
];

const REPORT_PRESETS: Array<{ id: ReportPresetId; label: string; description: string }> = [
  { id: "publishing-review", label: "Publishing review", description: "Unprotected publish blockers that still need review." },
  { id: "secrets-cleanup", label: "Secrets cleanup", description: "Secret-like files such as .env and auth.json." },
  { id: "generated-cleanup", label: "Generated cleanup", description: "Generated folders that should usually stay ignored." },
  { id: "logs-databases", label: "Logs and databases", description: "Logs, databases, and raw session-like files." }
];

function reviewTone(status: string): string {
  if (status === "reviewed") return "ok";
  if (status === "accepted_risk") return "warn";
  if (status === "ignore_for_now") return "neutral";
  return "bad";
}

function reviewLabel(status: string): string {
  return REVIEW_STATUS_OPTIONS.find((option) => option.id === status)?.label ?? "Needs action";
}

function isPublishBlocker(match: { level: string; category: string }): boolean {
  return match.level === "bad" || ["database-like", "log-like", "raw-session-like"].includes(match.category);
}

function reportRecommendedAction(category: string): string {
  if (category === "secret-like") return "Keep private, verify it is ignored, and never publish unless replaced with a safe example file.";
  if (category === "database-like") return "Keep out of public commits unless intentionally sanitized and documented.";
  if (category === "log-like") return "Delete before publishing or keep ignored; logs can contain private traces.";
  if (category === "raw-session-like") return "Keep private; raw session files may include prompts, outputs, or local traces.";
  if (category === "generated-folder") return "Usually safe to ignore and rebuild from source or dependency install commands.";
  return "Review before publishing.";
}

function reportCategoryLabel(category: string): string {
  if (category === "secret-like") return "Secret-like";
  if (category === "database-like") return "Database";
  if (category === "log-like") return "Logs";
  if (category === "raw-session-like") return "Raw sessions";
  if (category === "generated-folder") return "Generated";
  return category;
}

function reportCategoryCounts(matches: HealthReportMatch[]): Record<string, number> {
  return matches.reduce<Record<string, number>>((counts, match) => {
    counts[match.category] = (counts[match.category] ?? 0) + 1;
    return counts;
  }, {});
}

function formatCategoryCounts(matches: HealthReportMatch[]): string {
  const counts = reportCategoryCounts(matches);
  const parts = Object.entries(counts)
    .sort(([left], [right]) => reportCategoryLabel(left).localeCompare(reportCategoryLabel(right)))
    .map(([category, count]) => `${reportCategoryLabel(category)}: ${count}`);
  return parts.length > 0 ? parts.join(", ") : "No matched risky categories";
}

function publicationMetrics(report: HealthReport): {
  status: PublicationStatus;
  label: string;
  detail: string;
  tone: string;
  publishBlockers: HealthReportMatch[];
  unresolvedBlockers: number;
  unprotectedRisky: number;
  unknownRisky: number;
  reviewProgress: string;
} {
  const review = report.scan.review_summary;
  const publishBlockers = report.matches.filter(isPublishBlocker);
  const unresolvedBlockers = publishBlockers.filter((match) => match.review.status === "needs_action").length;
  const unprotectedRisky = publishBlockers.filter((match) => match.ignore_coverage.status !== "protected").length;
  const unknownRisky = publishBlockers.filter((match) => match.ignore_coverage.status === "unknown").length;
  const reviewedCount = review.reviewed + review.accepted_risk + review.ignore_for_now;
  const reviewProgress = `${reviewedCount}/${review.total}`;

  if (unresolvedBlockers > 0 || unprotectedRisky > 0) {
    return {
      status: "not_ready",
      label: "Not ready",
      detail: "Resolve or explicitly review publish blockers and make sure risky files are ignored before sharing publicly.",
      tone: "bad",
      publishBlockers,
      unresolvedBlockers,
      unprotectedRisky,
      unknownRisky,
      reviewProgress
    };
  }
  if (review.needs_action > 0 || report.scan.truncated) {
    return {
      status: "needs_review",
      label: "Needs review",
      detail: "No obvious unprotected blockers are visible, but review items or sampled-scan limits still need a human pass.",
      tone: "warn",
      publishBlockers,
      unresolvedBlockers,
      unprotectedRisky,
      unknownRisky,
      reviewProgress
    };
  }
  return {
    status: "public_safe_candidate",
    label: "Public-safe candidate",
    detail: "Metadata-only checks show no unresolved publish blockers. Do a final human review before publishing.",
    tone: "ok",
    publishBlockers,
    unresolvedBlockers,
    unprotectedRisky,
    unknownRisky,
    reviewProgress
  };
}

function publicSafeSummary(report: HealthReport): string {
  const metrics = publicationMetrics(report);
  const coverage = report.scan.gitignore_coverage;
  const review = report.scan.review_summary;
  return [
    "Codex Control Center public-safety summary",
    "",
    `Workspace: ${report.workspace.name} (${report.workspace.path_label})`,
    `Status: ${metrics.label}`,
    `Scores: overall ${report.overall_score}, system ${report.system_score}, vault ${report.workspace_score}`,
    `Scan: ${report.scan.scan_mode}, ${report.scan.entries_scanned}/${report.scan.max_entries} entries, max depth ${report.scan.max_depth}, ${report.scan.truncated ? "sample limited" : "complete sample"}`,
    `Matched categories: ${formatCategoryCounts(report.matches)}`,
    `Publish blockers: ${metrics.publishBlockers.length}; unresolved blockers: ${metrics.unresolvedBlockers}; unprotected or unknown risky matches: ${metrics.unprotectedRisky}`,
    `Review progress: ${metrics.reviewProgress}; needs action ${review.needs_action}; reviewed ${review.reviewed}; accepted risk ${review.accepted_risk}; ignored for now ${review.ignore_for_now}`,
    `.gitignore coverage: protected ${coverage.protected}; not ignored ${coverage.not_ignored}; unknown ${coverage.unknown}; readable .gitignore files ${coverage.ignore_files_read}`,
    "",
    "Safety note: this summary uses metadata-only local checks. Full local paths, file contents, secrets, prompts, outputs, raw logs, databases, and raw sessions are excluded."
  ].join("\n");
}

function githubReadmeNote(report: HealthReport): string {
  const metrics = publicationMetrics(report);
  return [
    "## Local Safety Review",
    "",
    `This project was checked with Codex Control Center using metadata-only local scans. Current status: ${metrics.label}.`,
    "",
    "The review does not include full local paths, secrets, file contents, prompts, outputs, logs, databases, or raw session files. Run your own final human review before publishing or reusing this package."
  ].join("\n");
}

function cleanupChecklist(report: HealthReport): string {
  const metrics = publicationMetrics(report);
  const coverage = report.scan.gitignore_coverage;
  return [
    "Public cleanup checklist",
    "",
    `- Resolve or review publish blockers: ${metrics.unresolvedBlockers}`,
    `- Add ignore coverage for risky matches marked not ignored or unknown: ${metrics.unprotectedRisky}`,
    `- Re-check unknown .gitignore coverage: ${metrics.unknownRisky}`,
    `- Review remaining needs-action items: ${report.scan.review_summary.needs_action}`,
    `- Confirm generated/dependency folders are ignored or documented: ${report.matches.filter((match) => match.category === "generated-folder").length}`,
    `- Re-run ${report.scan.scan_mode === "deep" ? "deep" : "standard"} metadata scan after cleanup`,
    `- Confirm coverage totals before publishing: protected ${coverage.protected}, not ignored ${coverage.not_ignored}, unknown ${coverage.unknown}`,
    "- Do not publish .env files, auth files, raw logs, local databases, raw sessions, prompts, outputs, or private local paths",
    "- Run the repository public-safety scan before any commit or push"
  ].join("\n");
}

function coverageTone(status: string): string {
  if (status === "protected") return "ok";
  if (status === "not_ignored") return "bad";
  return "warn";
}

function coverageLabel(status: string): string {
  if (status === "protected") return "protected";
  if (status === "not_ignored") return "not ignored";
  return "unknown";
}

function reportIgnoreRules(matches: Array<{ category: string; name: string; kind: string }>): string[] {
  const rules = new Set<string>();
  for (const match of matches) {
    if (match.category === "secret-like") {
      if (match.name === "auth.json") rules.add("auth.json");
      if (match.name.startsWith(".env")) {
        rules.add(".env");
        rules.add(".env.*");
      }
    }
    if (match.category === "database-like") {
      rules.add("*.db");
      rules.add("*.sqlite");
      rules.add("*.sqlite3");
      rules.add("*-wal");
      rules.add("*-shm");
    }
    if (match.category === "log-like") {
      rules.add("*.log");
      rules.add("logs/");
    }
    if (match.category === "raw-session-like") {
      rules.add("*.jsonl");
      rules.add("sessions/");
    }
    if (match.category === "generated-folder") {
      if (match.kind === "folder") {
        rules.add(`${match.name}/`);
      }
    }
  }
  return Array.from(rules).sort((a, b) => a.localeCompare(b));
}

function safeMarkdownReport(report: HealthReport, matches: HealthReportMatch[]): string {
  const review = report.scan.review_summary;
  const coverage = report.scan.gitignore_coverage;
  const lines = [
    `# Vault Health Report`,
    "",
    `Workspace: ${report.workspace.name} (${report.workspace.path_label})`,
    `Generated: ${formatShortTime(report.generated_at)}`,
    "",
    `## Scores`,
    "",
    `- Overall: ${report.overall_score}`,
    `- System: ${report.system_score}`,
    `- Vault: ${report.workspace_score}`,
    "",
    `## Gitignore Coverage`,
    "",
    `- Protected: ${coverage.protected}`,
    `- Not ignored: ${coverage.not_ignored}`,
    `- Unknown: ${coverage.unknown}`,
    `- Readable .gitignore files: ${coverage.ignore_files_read}`,
    "",
    `## Review Progress`,
    "",
    `- Total: ${review.total}`,
    `- Needs action: ${review.needs_action}`,
    `- Reviewed: ${review.reviewed}`,
    `- Accepted risk: ${review.accepted_risk}`,
    `- Ignore for now: ${review.ignore_for_now}`,
    "",
    `## Visible Findings`,
    ""
  ];

  if (matches.length === 0) {
    lines.push("No visible matched locations for the current filters.");
  } else {
    for (const match of matches) {
      lines.push(
        `- [${match.level}] ${reportCategoryLabel(match.category)}: ${match.relative_path || match.name}`,
        `  - Coverage: ${coverageLabel(match.ignore_coverage.status)}`,
        `  - Review: ${reviewLabel(match.review.status)}`,
        `  - Action: ${reportRecommendedAction(match.category)}`
      );
    }
  }

  lines.push("", "Full local paths, secrets, file contents, prompts, outputs, logs, and raw session data are not included.");
  return lines.join("\n");
}

function HealthReportPage() {
  const queryClient = useQueryClient();
  const initialWorkspaceId = new URLSearchParams(window.location.search).get("workspace_id") ?? "";
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(initialWorkspaceId);
  const [revealedPaths, setRevealedPaths] = useState<HealthReportPaths | null>(null);
  const [copiedPathId, setCopiedPathId] = useState<string | null>(null);
  const [reportFilter, setReportFilter] = useState<ReportFilter>("all");
  const [reportSearch, setReportSearch] = useState("");
  const [publishBlockersOnly, setPublishBlockersOnly] = useState(false);
  const [unprotectedOnly, setUnprotectedOnly] = useState(false);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [showExport, setShowExport] = useState(false);
  const [activePreset, setActivePreset] = useState<ReportPresetId | null>(null);
  const [selectedReviewKeys, setSelectedReviewKeys] = useState<Record<string, boolean>>({});
  const [scanMode, setScanMode] = useState<HealthScanMode>("standard");
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: () => apiGet<{ items: Workspace[] }>("/api/workspaces"), refetchInterval: 60000 });
  const workspaceItems = workspaces.data?.items ?? [];
  const defaultWorkspace = workspaceItems.find((workspace) => workspace.is_default) ?? workspaceItems[0];
  const effectiveWorkspaceId = selectedWorkspaceId || (defaultWorkspace ? String(defaultWorkspace.id) : "");
  const reportQueryPath = effectiveWorkspaceId
    ? `/api/health-score/report?workspace_id=${encodeURIComponent(effectiveWorkspaceId)}&scan_mode=${scanMode}`
    : `/api/health-score/report?scan_mode=${scanMode}`;
  const revealQueryPath = effectiveWorkspaceId
    ? `/api/health-score/report/paths?workspace_id=${encodeURIComponent(effectiveWorkspaceId)}&scan_mode=${scanMode}`
    : `/api/health-score/report/paths?scan_mode=${scanMode}`;
  const report = useQuery({
    queryKey: ["health-score-report", effectiveWorkspaceId || "default", scanMode],
    queryFn: () => apiGet<HealthReport>(reportQueryPath),
    refetchInterval: 60000
  });
  const revealPaths = useMutation({
    mutationFn: () => apiGet<HealthReportPaths>(revealQueryPath),
    onSuccess: (data) => setRevealedPaths(data)
  });
  const saveReview = useMutation({
    mutationFn: ({ review_key, status }: { review_key: string; status: ReviewStatus }) => apiPost("/api/health-score/reviews", {
      workspace_id: effectiveWorkspaceId ? Number(effectiveWorkspaceId) : undefined,
      review_key,
      status,
      scan_mode: scanMode
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["health-score-report"] });
    }
  });
  const saveBulkReview = useMutation({
    mutationFn: ({ review_keys, status }: { review_keys: string[]; status: ReviewStatus }) => apiPost("/api/health-score/reviews/bulk", {
      workspace_id: effectiveWorkspaceId ? Number(effectiveWorkspaceId) : undefined,
      review_keys,
      status,
      scan_mode: scanMode
    }),
    onSuccess: () => {
      setSelectedReviewKeys({});
      queryClient.invalidateQueries({ queryKey: ["health-score-report"] });
    }
  });
  const pathById = new Map((revealedPaths?.matches ?? []).map((item) => [item.id, item.full_path]));

  function changeWorkspace(value: string) {
    setSelectedWorkspaceId(value);
    setRevealedPaths(null);
    setSelectedReviewKeys({});
    queryClient.invalidateQueries({ queryKey: ["health-score-report"] });
    window.history.replaceState(null, "", `/health-report?workspace_id=${encodeURIComponent(value)}`);
  }

  function changeScanMode(value: HealthScanMode) {
    setScanMode(value);
    setRevealedPaths(null);
    setSelectedReviewKeys({});
    queryClient.invalidateQueries({ queryKey: ["health-score-report"] });
  }

  function applyReportPreset(presetId: ReportPresetId) {
    setActivePreset(presetId);
    setReportSearch("");
    setSelectedReviewKeys({});
    if (presetId === "publishing-review") {
      setReportFilter("all");
      setPublishBlockersOnly(true);
      setUnprotectedOnly(true);
      setReviewFilter("needs_action");
    }
    if (presetId === "secrets-cleanup") {
      setReportFilter("secret-like");
      setPublishBlockersOnly(false);
      setUnprotectedOnly(false);
      setReviewFilter("all");
    }
    if (presetId === "generated-cleanup") {
      setReportFilter("generated-folder");
      setPublishBlockersOnly(false);
      setUnprotectedOnly(false);
      setReviewFilter("all");
    }
    if (presetId === "logs-databases") {
      setReportFilter("all");
      setPublishBlockersOnly(false);
      setUnprotectedOnly(false);
      setReviewFilter("all");
    }
  }

  function clearPreset() {
    setActivePreset(null);
  }

  async function copyPath(id: string, path: string) {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPathId(id);
      window.setTimeout(() => setCopiedPathId(null), 1400);
    } catch {
      setCopiedPathId(null);
    }
  }

  const reportData = report.data;
  const tone = readinessTone(reportData?.overall_score);
  const publication = reportData ? publicationMetrics(reportData) : null;
  const searchTerm = reportSearch.trim().toLowerCase();
  const filteredMatches = (reportData?.matches ?? []).filter((match) => {
    if (activePreset === "logs-databases" && !["log-like", "database-like", "raw-session-like"].includes(match.category)) return false;
    if (publishBlockersOnly && !isPublishBlocker(match)) return false;
    if (unprotectedOnly && match.ignore_coverage.status === "protected") return false;
    if (reviewFilter !== "all" && match.review.status !== reviewFilter) return false;
    if (reportFilter !== "all" && !([match.level, match.category] as string[]).includes(reportFilter)) return false;
    if (!searchTerm) return true;
    return [match.relative_path, match.name, match.category, match.reason, match.ignore_coverage.status, match.review.status].some((value) => value.toLowerCase().includes(searchTerm));
  });
  const filteredFindings = (reportData?.findings ?? []).filter((finding) => {
    if (reportFilter !== "all" && !["bad", "warn", "info"].includes(reportFilter)) return false;
    if (reportFilter !== "all" && finding.level !== reportFilter) return false;
    if (!searchTerm) return true;
    return [finding.title, finding.detail].some((value) => value.toLowerCase().includes(searchTerm));
  });
  const ignoreRules = reportIgnoreRules(filteredMatches);
  const markdownReport = reportData ? safeMarkdownReport(reportData, filteredMatches) : "";
  const secretMatches = reportData?.matches.filter((match) => match.category === "secret-like") ?? [];
  const secretProtected = secretMatches.filter((match) => match.ignore_coverage.status === "protected").length;
  const secretNeedsCoverage = secretMatches.filter((match) => match.ignore_coverage.status !== "protected").length;
  const selectedKeys = Object.entries(selectedReviewKeys).filter(([, selected]) => selected).map(([key]) => key);
  const visibleKeys = filteredMatches.map((match) => match.review_key);
  const selectedVisibleCount = visibleKeys.filter((key) => selectedReviewKeys[key]).length;

  function setSelection(keys: string[]) {
    setSelectedReviewKeys(Object.fromEntries(keys.map((key) => [key, true])));
  }

  function toggleSelection(key: string, selected: boolean) {
    setSelectedReviewKeys((current) => ({ ...current, [key]: selected }));
  }

  function bulkReview(status: ReviewStatus) {
    if (selectedKeys.length === 0) return;
    saveBulkReview.mutate({ review_keys: selectedKeys, status });
  }

  return (
    <div className="space-y-5">
      <Panel
        title="Vault Health Report"
        action={workspaceItems.length > 1 ? (
          <select
            className="max-w-48 rounded-control border border-line bg-panel2 px-2 py-1 text-xs text-white outline-none focus:border-focus"
            value={effectiveWorkspaceId}
            onChange={(event) => changeWorkspace(event.target.value)}
          >
            {workspaceItems.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
            ))}
          </select>
        ) : undefined}
      >
        {report.isLoading ? <EmptyState label="Loading vault health report..." /> : report.isError || !reportData ? <EmptyState label="Vault health report unavailable." /> : (
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-5">
              <div className="rounded-control border border-line bg-panel2 p-3">
                <div className="text-2xl font-semibold text-white">{reportData.overall_score}</div>
                <div className="text-xs text-muted">overall</div>
              </div>
              <div className="rounded-control border border-line bg-panel2 p-3">
                <div className="text-2xl font-semibold text-white">{reportData.workspace_score}</div>
                <div className="text-xs text-muted">vault</div>
              </div>
              <div className="rounded-control border border-line bg-panel2 p-3">
                <div className="text-2xl font-semibold text-white">{reportData.scan.entries_scanned}</div>
                <div className="text-xs text-muted">entries scanned</div>
              </div>
              <div className="rounded-control border border-line bg-panel2 p-3">
                <div className="text-2xl font-semibold text-white">{reportData.scan.matched_locations}</div>
                <div className="text-xs text-muted">matched locations</div>
              </div>
              <div className="rounded-control border border-line bg-panel2 p-3">
                <Pill tone={tone}>{tone}</Pill>
                <div className="mt-2 text-xs text-muted">{reportData.scan.truncated ? "sample limited" : "scan complete"}</div>
              </div>
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3 text-sm">
              <div className="mb-1 font-medium text-white">{reportData.workspace.name}</div>
              <div className="mono truncate text-xs text-muted">{reportData.workspace.path_label}</div>
              <div className="mt-2 text-xs text-muted">
                Safe report uses filenames, folder names, relative paths, and file types only. Full local paths are hidden until you reveal them.
              </div>
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">Metadata Scan Depth</div>
                  <div className="text-xs text-muted">
                    Standard stays fast. Deep scan expands the local metadata sample for this workspace only.
                  </div>
                </div>
                <Pill tone={reportData.scan.scan_mode === "deep" ? "focus" : "neutral"}>{reportData.scan.scan_mode}</Pill>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <button
                  className={`rounded-control border px-3 py-2 text-sm ${scanMode === "standard" ? "border-focus bg-focus text-ink" : "border-line text-muted hover:text-white"}`}
                  onClick={() => changeScanMode("standard")}
                >
                  Standard scan
                </button>
                <button
                  className={`rounded-control border px-3 py-2 text-sm ${scanMode === "deep" ? "border-focus bg-focus text-ink" : "border-line text-muted hover:text-white"}`}
                  onClick={() => changeScanMode("deep")}
                >
                  Run deeper metadata scan
                </button>
              </div>
              <div className="mt-3 text-xs text-muted">
                Deep scan increases max depth to {scanMode === "deep" ? reportData.scan.max_depth : "5"} and entry sampling to {scanMode === "deep" ? reportData.scan.max_entries : "5000"}. It still does not read file contents, prompts, outputs, or secrets.
              </div>
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">Gitignore Coverage</div>
                  <div className="text-xs text-muted">
                    Read-only check from {reportData.scan.gitignore_coverage.ignore_files_read} readable .gitignore file{reportData.scan.gitignore_coverage.ignore_files_read === 1 ? "" : "s"}.
                  </div>
                </div>
                {reportData.scan.gitignore_coverage.ignore_files_unreadable > 0 && <Pill tone="warn">{reportData.scan.gitignore_coverage.ignore_files_unreadable} unreadable</Pill>}
              </div>
              <div className="grid gap-2 text-center text-sm md:grid-cols-4">
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-good">{reportData.scan.gitignore_coverage.protected}</div><div className="text-xs text-muted">protected</div></div>
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-bad">{reportData.scan.gitignore_coverage.not_ignored}</div><div className="text-xs text-muted">not ignored</div></div>
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-warn">{reportData.scan.gitignore_coverage.unknown}</div><div className="text-xs text-muted">unknown</div></div>
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-white">{secretMatches.length}</div><div className="text-xs text-muted">secret-like</div></div>
              </div>
              <div className="mt-3 rounded-control border border-line bg-ink p-2 text-xs text-muted">
                Secret-like files: {secretProtected} protected, {secretNeedsCoverage} need ignore coverage.
              </div>
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">Review Checklist</div>
                  <div className="text-xs text-muted">Local-only status tracking for each matched report location.</div>
                </div>
                <Pill tone={reportData.scan.review_summary.needs_action === 0 ? "ok" : "bad"}>{reportData.scan.review_summary.needs_action} need review</Pill>
              </div>
              <div className="grid gap-2 text-center text-sm md:grid-cols-5">
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-white">{reportData.scan.review_summary.total}</div><div className="text-xs text-muted">total</div></div>
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-bad">{reportData.scan.review_summary.needs_action}</div><div className="text-xs text-muted">needs action</div></div>
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-good">{reportData.scan.review_summary.reviewed}</div><div className="text-xs text-muted">reviewed</div></div>
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-warn">{reportData.scan.review_summary.accepted_risk}</div><div className="text-xs text-muted">accepted risk</div></div>
                <div className="rounded-control bg-ink p-3"><div className="text-xl text-muted">{reportData.scan.review_summary.ignore_for_now}</div><div className="text-xs text-muted">ignore for now</div></div>
              </div>
            </div>
            {publication && (
              <div className="rounded-control border border-focus/40 bg-focus/5 p-3">
                <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-white">Public Safety Pack</div>
                    <div className="text-xs text-muted">Copy safe aggregate notes for publishing prep. No full paths, file contents, prompts, outputs, or secrets.</div>
                  </div>
                  <Pill tone={publication.tone}>{publication.label}</Pill>
                </div>
                <div className="mb-3 rounded-control border border-line bg-ink p-3 text-sm text-muted">
                  <span className="font-medium text-white">{publication.label}: </span>
                  {publication.detail}
                </div>
                <div className="grid gap-2 text-center text-sm md:grid-cols-5">
                  <div className="rounded-control bg-ink p-3"><div className="text-xl text-white">{reportData.overall_score}</div><div className="text-xs text-muted">readiness</div></div>
                  <div className="rounded-control bg-ink p-3"><div className="text-xl text-bad">{publication.unresolvedBlockers}</div><div className="text-xs text-muted">unresolved blockers</div></div>
                  <div className="rounded-control bg-ink p-3"><div className="text-xl text-warn">{publication.unprotectedRisky}</div><div className="text-xs text-muted">unprotected/unknown</div></div>
                  <div className="rounded-control bg-ink p-3"><div className="text-xl text-white">{publication.reviewProgress}</div><div className="text-xs text-muted">review progress</div></div>
                  <div className="rounded-control bg-ink p-3"><div className="text-xl text-good">{reportData.scan.gitignore_coverage.protected}</div><div className="text-xs text-muted">ignored</div></div>
                </div>
                <div className="mt-3 grid gap-2 md:grid-cols-3">
                  <button className="inline-flex items-center justify-center gap-1 rounded-control border border-line px-3 py-2 text-xs text-muted hover:text-white" onClick={() => copyPath("public-summary", publicSafeSummary(reportData))}>
                    <Copy className="h-3.5 w-3.5" /> {copiedPathId === "public-summary" ? "Copied" : "Copy public-safe summary"}
                  </button>
                  <button className="inline-flex items-center justify-center gap-1 rounded-control border border-line px-3 py-2 text-xs text-muted hover:text-white" onClick={() => copyPath("readme-note", githubReadmeNote(reportData))}>
                    <Copy className="h-3.5 w-3.5" /> {copiedPathId === "readme-note" ? "Copied" : "Copy GitHub README note"}
                  </button>
                  <button className="inline-flex items-center justify-center gap-1 rounded-control border border-line px-3 py-2 text-xs text-muted hover:text-white" onClick={() => copyPath("cleanup-checklist", cleanupChecklist(reportData))}>
                    <Copy className="h-3.5 w-3.5" /> {copiedPathId === "cleanup-checklist" ? "Copied" : "Copy cleanup checklist"}
                  </button>
                </div>
              </div>
            )}
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">Report Presets</div>
                  <div className="text-xs text-muted">Quick filter sets for common review passes.</div>
                </div>
                {activePreset && (
                  <button className="rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={clearPreset}>
                    Clear preset
                  </button>
                )}
              </div>
              <div className="grid gap-2 md:grid-cols-4">
                {REPORT_PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    className={`rounded-control border p-3 text-left ${activePreset === preset.id ? "border-focus bg-focus/10" : "border-line bg-ink hover:border-focus/60"}`}
                    onClick={() => applyReportPreset(preset.id)}
                  >
                    <div className="text-sm font-medium text-white">{preset.label}</div>
                    <div className="mt-1 text-xs text-muted">{preset.description}</div>
                  </button>
                ))}
              </div>
            </div>
            {revealedPaths ? (
              <div className="rounded-control border border-bad/30 bg-bad/10 p-3 text-sm">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <div className="font-medium text-bad">Full local paths revealed</div>
                    <div className="mono mt-1 break-all text-xs text-white">{revealedPaths.workspace.root_path}</div>
                  </div>
                  <button className="inline-flex items-center gap-1 rounded-control border border-bad/40 px-2 py-1 text-xs text-bad" onClick={() => copyPath("root", revealedPaths.workspace.root_path)}>
                    <Copy className="h-3.5 w-3.5" /> {copiedPathId === "root" ? "Copied" : "Copy root"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-line bg-panel2 p-3 text-sm">
                <div className="text-muted">Full folder paths are local-private. Reveal only when you need exact locations.</div>
                <button
                  className="inline-flex items-center gap-2 rounded-control border border-bad/40 px-3 py-2 text-sm text-bad hover:bg-bad/10 disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => revealPaths.mutate()}
                  disabled={revealPaths.isPending}
                >
                  <Eye className="h-4 w-4" /> {revealPaths.isPending ? "Revealing..." : "Reveal full local paths"}
                </button>
                {revealPaths.isError && <div className="basis-full text-xs text-bad">Full paths unavailable. Check local control access and try again.</div>}
              </div>
            )}
            <div className="space-y-3 rounded-control border border-line bg-panel2 p-3">
              <div className="flex flex-wrap gap-2">
                {REPORT_FILTERS.map((filter) => (
                  <button
                    key={filter.id}
                    className={`rounded-control border px-3 py-1.5 text-xs ${reportFilter === filter.id ? "border-focus bg-focus text-ink" : "border-line text-muted hover:text-white"}`}
                    onClick={() => {
                      clearPreset();
                      setReportFilter(filter.id);
                    }}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
                <input
                  className="rounded-control border border-line bg-ink px-3 py-2 text-sm text-white outline-none focus:border-focus"
                  placeholder="Search safe relative paths, names, or categories"
                  value={reportSearch}
                  onChange={(event) => {
                    clearPreset();
                    setReportSearch(event.target.value);
                  }}
                />
                <label className="flex items-center gap-2 rounded-control border border-line bg-ink px-3 py-2 text-sm text-muted">
                  <input type="checkbox" checked={publishBlockersOnly} onChange={(event) => {
                    clearPreset();
                    setPublishBlockersOnly(event.target.checked);
                  }} />
                  Show only publish blockers
                </label>
              </div>
              <label className="flex items-center gap-2 rounded-control border border-line bg-ink px-3 py-2 text-sm text-muted">
                <input type="checkbox" checked={unprotectedOnly} onChange={(event) => {
                  clearPreset();
                  setUnprotectedOnly(event.target.checked);
                }} />
                Show unprotected only
              </label>
              <div className="grid gap-2 md:grid-cols-5">
                <button
                  className={`rounded-control border px-3 py-2 text-xs ${reviewFilter === "all" ? "border-focus bg-focus text-ink" : "border-line text-muted hover:text-white"}`}
                  onClick={() => {
                    clearPreset();
                    setReviewFilter("all");
                  }}
                >
                  All review states
                </button>
                {REVIEW_STATUS_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    className={`rounded-control border px-3 py-2 text-xs ${reviewFilter === option.id ? "border-focus bg-focus text-ink" : "border-line text-muted hover:text-white"}`}
                    onClick={() => {
                      clearPreset();
                      setReviewFilter(option.id);
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div className="text-xs text-muted">
                Showing {filteredMatches.length} of {reportData.matches.length} matched locations. Aggregate findings are shown for level filters only.
              </div>
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">Bulk Review Actions</div>
                  <div className="text-xs text-muted">{selectedKeys.length} selected, {selectedVisibleCount} visible selected.</div>
                </div>
                <button className="rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => setSelectedReviewKeys({})}>
                  Clear selection
                </button>
              </div>
              <div className="mb-3 flex flex-wrap gap-2">
                <button className="rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => setSelection(visibleKeys)}>
                  Select visible
                </button>
                <button className="rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => setSelection(filteredMatches.filter((match) => match.ignore_coverage.status !== "protected").map((match) => match.review_key))}>
                  Select unprotected
                </button>
                <button className="rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => setSelection(filteredMatches.filter((match) => match.category === "secret-like").map((match) => match.review_key))}>
                  Select secret-like
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-control border border-good/40 px-2 py-1 text-xs text-good disabled:cursor-not-allowed disabled:opacity-50" disabled={selectedKeys.length === 0 || saveBulkReview.isPending} onClick={() => bulkReview("reviewed")}>
                  Mark selected reviewed
                </button>
                <button className="rounded-control border border-warn/40 px-2 py-1 text-xs text-warn disabled:cursor-not-allowed disabled:opacity-50" disabled={selectedKeys.length === 0 || saveBulkReview.isPending} onClick={() => bulkReview("accepted_risk")}>
                  Mark selected accepted risk
                </button>
                <button className="rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={selectedKeys.length === 0 || saveBulkReview.isPending} onClick={() => bulkReview("ignore_for_now")}>
                  Mark selected ignore for now
                </button>
                <button className="rounded-control border border-bad/40 px-2 py-1 text-xs text-bad disabled:cursor-not-allowed disabled:opacity-50" disabled={selectedKeys.length === 0 || saveBulkReview.isPending} onClick={() => bulkReview("needs_action")}>
                  Reset selected to needs action
                </button>
              </div>
              {saveBulkReview.isError && <div className="mt-3 rounded-control border border-bad/30 bg-bad/10 p-2 text-xs text-bad">Bulk review update failed. Refresh the report and try again.</div>}
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">.gitignore suggestions</div>
                  <div className="text-xs text-muted">Read-only suggestions from the currently visible report matches. Review before adding them yourself.</div>
                </div>
                {ignoreRules.length > 0 && (
                  <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => copyPath("ignore-rules", ignoreRules.join("\n"))}>
                    <Copy className="h-3.5 w-3.5" /> {copiedPathId === "ignore-rules" ? "Copied" : "Copy rules"}
                  </button>
                )}
              </div>
              {ignoreRules.length === 0 ? (
                <EmptyState label="No ignore suggestions for the current filters." />
              ) : (
                <pre className="mono max-h-48 overflow-auto rounded-control border border-line bg-ink p-3 text-xs text-white">{ignoreRules.join("\n")}</pre>
              )}
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">Safe Markdown Export</div>
                  <div className="text-xs text-muted">Public-safe export from the current filters. Full local paths and file contents are excluded.</div>
                </div>
                <div className="flex gap-2">
                  <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => setShowExport(!showExport)}>
                    <Eye className="h-3.5 w-3.5" /> {showExport ? "Hide" : "Preview"}
                  </button>
                  <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => copyPath("safe-export", markdownReport)}>
                    <Copy className="h-3.5 w-3.5" /> {copiedPathId === "safe-export" ? "Copied" : "Copy Markdown"}
                  </button>
                </div>
              </div>
              {showExport ? (
                <pre className="mono max-h-80 overflow-auto rounded-control border border-line bg-ink p-3 text-xs text-white">{markdownReport}</pre>
              ) : (
                <EmptyState label="Preview the public-safe Markdown before copying it." />
              )}
            </div>
          </div>
        )}
      </Panel>

      {reportData && (
        <div className="grid gap-5 lg:grid-cols-2">
          {REPORT_LEVELS.map((level) => {
            const findings = filteredFindings.filter((finding) => finding.level === level);
            const matches = filteredMatches.filter((match) => match.level === level);
            return (
              <Panel key={level} title={`${level.toUpperCase()} Findings`} action={<Pill tone={findingTone(level)}>{findings.length + matches.length}</Pill>}>
                {findings.length === 0 && matches.length === 0 ? <EmptyState label={`No ${level} report items.`} /> : (
                  <div className="space-y-3">
                    {findings.map((finding) => (
                      <div key={`${finding.level}-${finding.title}`} className="rounded-control border border-line bg-panel2 p-3">
                        <div className="mb-1 flex items-center gap-2">
                          <Pill tone={findingTone(finding.level)}>{finding.level}</Pill>
                          <div className="text-sm font-medium text-white">{finding.title}</div>
                        </div>
                        <div className="text-sm text-muted">{finding.detail}</div>
                      </div>
                    ))}
                    {matches.map((match) => {
                      const fullPath = pathById.get(match.id);
                      const isSelected = Boolean(selectedReviewKeys[match.review_key]);
                      return (
                        <div key={match.id} className={`rounded-control border bg-panel2 p-3 ${isSelected ? "border-focus" : "border-line"}`}>
                          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <Pill tone={findingTone(match.level)}>{reportCategoryLabel(match.category)}</Pill>
                              <Pill>{match.kind}</Pill>
                              <Pill tone={coverageTone(match.ignore_coverage.status)}>{coverageLabel(match.ignore_coverage.status)}</Pill>
                              <Pill tone={reviewTone(match.review.status)}>{reviewLabel(match.review.status)}</Pill>
                              <span className="text-xs text-muted">depth {match.depth}</span>
                            </div>
                            <label className="flex items-center gap-2 text-xs text-muted">
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={(event) => toggleSelection(match.review_key, event.target.checked)}
                              />
                              Select
                            </label>
                          </div>
                          <div className="mono break-all text-sm text-white">{match.relative_path || match.name}</div>
                          <div className="mt-1 text-sm text-muted">{match.reason}</div>
                          <div className="mt-3 rounded-control border border-line bg-ink p-2 text-xs text-muted">
                            <span className="font-medium text-white">Gitignore coverage: </span>
                            {match.ignore_coverage.detail}
                            {match.ignore_coverage.source_label && <span className="mono ml-1 text-white">({match.ignore_coverage.source_label})</span>}
                          </div>
                          <div className="mt-3 rounded-control border border-line bg-ink p-2 text-xs text-muted">
                            <span className="font-medium text-white">Recommended action: </span>
                            {reportRecommendedAction(match.category)}
                          </div>
                          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-control border border-line bg-ink p-2 text-xs text-muted">
                            <span className="font-medium text-white">Review status</span>
                            <select
                              className="rounded-control border border-line bg-panel2 px-2 py-1 text-xs text-white outline-none focus:border-focus disabled:opacity-60"
                              value={match.review.status}
                              disabled={saveReview.isPending}
                              onChange={(event) => saveReview.mutate({ review_key: match.review_key, status: event.target.value as ReviewStatus })}
                            >
                              {REVIEW_STATUS_OPTIONS.map((option) => (
                                <option key={option.id} value={option.id}>{option.label}</option>
                              ))}
                            </select>
                          </div>
                          {fullPath && (
                            <div className="mt-3 space-y-2">
                              <div className="mono break-all rounded-control border border-line bg-ink p-2 text-xs text-white">{fullPath}</div>
                              <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => copyPath(match.id, fullPath)}>
                                <Copy className="h-3.5 w-3.5" /> {copiedPathId === match.id ? "Copied" : "Copy path"}
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}

function TasksPage() {
  const { tasks, schedules, health, workspaces, systemMode } = useDashboardData();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [sandbox, setSandbox] = useState("read-only");
  const [showWorkspaceWriteConfirm, setShowWorkspaceWriteConfirm] = useState(false);
  const [workspaceId, setWorkspaceId] = useState("");
  const [openTaskId, setOpenTaskId] = useState<number | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");
  const [scheduleName, setScheduleName] = useState("");
  const [scheduleCron, setScheduleCron] = useState("@daily");
  const [scheduleTaskTitle, setScheduleTaskTitle] = useState("");
  const [scheduleTaskDescription, setScheduleTaskDescription] = useState("");
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [scheduleWorkspaceId, setScheduleWorkspaceId] = useState("");
  const [browserToken, setBrowserToken] = useState("");
  const browserRoots = useQuery({
    queryKey: ["workspace-browser-roots"],
    queryFn: () => apiGet<{ items: WorkspaceBrowserItem[] }>("/api/workspace-browser/roots")
  });
  const currentBrowserToken = browserToken || browserRoots.data?.items[0]?.token || "";
  const browserFolder = useQuery({
    queryKey: ["workspace-browser-folder", currentBrowserToken],
    queryFn: () => apiGet<WorkspaceBrowserFolder>(`/api/workspace-browser/folders?token=${encodeURIComponent(currentBrowserToken)}`),
    enabled: Boolean(currentBrowserToken)
  });
  const workspaceItems = workspaces.data?.items ?? [];
  const tokenSaverActive = systemMode.data?.mode === "token_saver";
  const defaultWorkspace = workspaceItems.find((workspace) => workspace.is_default) ?? workspaceItems[0];
  const selectedWorkspaceId = workspaceId || (defaultWorkspace ? String(defaultWorkspace.id) : "");
  const selectedScheduleWorkspaceId = scheduleWorkspaceId || (defaultWorkspace ? String(defaultWorkspace.id) : "");
  const workspaceById = new Map(workspaceItems.map((workspace) => [workspace.id, workspace]));
  const workspaceLabel = (id: number | null | undefined) => {
    const workspace = id ? workspaceById.get(id) : defaultWorkspace;
    return workspace ? `${workspace.name} - ${workspace.path_label}` : "workspace removed";
  };
  const createWorkspace = useMutation({
    mutationFn: (selection: { path?: string; browser_token?: string }) => apiPost<{ workspace: Workspace }>("/api/workspaces", { name: workspaceName, ...selection }),
    onSuccess: () => {
      setWorkspaceName("");
      setWorkspacePath("");
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    }
  });
  const browseFromPath = useMutation({
    mutationFn: () => apiPost<{ root: WorkspaceBrowserItem }>("/api/workspace-browser/roots", { path: workspacePath, name: workspaceName || undefined }),
    onSuccess: (data) => {
      setBrowserToken(data.root.token);
      setWorkspacePath("");
    }
  });
  const deleteWorkspace = useMutation({
    mutationFn: (id: number) => apiDelete(`/api/workspaces/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    }
  });
  const createTask = useMutation({
    mutationFn: () => apiPost("/api/tasks", {
      title,
      description,
      sandbox,
      workspace_id: selectedWorkspaceId ? Number(selectedWorkspaceId) : undefined
    }),
    onSuccess: () => {
      setTitle("");
      setDescription("");
      setSandbox("read-only");
      setShowWorkspaceWriteConfirm(false);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });
  const approve = useMutation({
    mutationFn: (id: number) => apiPost(`/api/tasks/${id}/approve`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] })
  });
  const cancel = useMutation({
    mutationFn: (id: number) => apiPost(`/api/tasks/${id}/cancel`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] })
  });
  const rerun = useMutation({
    mutationFn: (id: number) => apiPost(`/api/tasks/${id}/rerun`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] })
  });
  const archive = useMutation({
    mutationFn: (id: number) => apiPost(`/api/tasks/${id}/archive`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] })
  });
  const createSchedule = useMutation({
    mutationFn: () => apiPost("/api/schedules", {
      name: scheduleName,
      cron_expression: scheduleCron,
      task_title: scheduleTaskTitle,
      task_description: scheduleTaskDescription,
      enabled: scheduleEnabled,
      workspace_id: selectedScheduleWorkspaceId ? Number(selectedScheduleWorkspaceId) : undefined
    }),
    onSuccess: () => {
      setScheduleName("");
      setScheduleCron("@daily");
      setScheduleTaskTitle("");
      setScheduleTaskDescription("");
      setScheduleEnabled(true);
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    }
  });
  const materializeDue = useMutation({
    mutationFn: () => apiPost("/api/schedules/materialize-due"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });
  const toggleSchedule = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => apiPost(`/api/schedules/${id}/toggle`, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] })
  });
  const deleteSchedule = useMutation({
    mutationFn: (id: number) => apiPost(`/api/schedules/${id}/delete`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] })
  });
  const taskItems = tasks.data?.items ?? [];
  const browserRootsItems = browserRoots.data?.items ?? [];
  const browserChildren = browserFolder.data?.children ?? [];
  const browserBreadcrumbs = browserFolder.data?.breadcrumbs ?? [];
  const browserCurrent = browserFolder.data?.current;

  function browserIcon(kind: WorkspaceBrowserItem["kind"]) {
    if (kind === "drive") return <HardDrive className="h-4 w-4 text-muted" />;
    if (kind === "home") return <FolderOpen className="h-4 w-4 text-muted" />;
    return <Folder className="h-4 w-4 text-muted" />;
  }

  function submitWorkspace(event: FormEvent) {
    event.preventDefault();
    createWorkspace.mutate({ path: workspacePath });
  }

  function saveBrowserWorkspace() {
    if (!currentBrowserToken) return;
    createWorkspace.mutate({ browser_token: currentBrowserToken });
  }

  function applyTaskTemplate(template: SafeTaskTemplate) {
    setTitle(template.title);
    setDescription(template.description);
    setSandbox("read-only");
    setShowWorkspaceWriteConfirm(false);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    createTask.mutate();
  }

  function submitSchedule(event: FormEvent) {
    event.preventDefault();
    createSchedule.mutate();
  }

  return (
    <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,460px)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-5">
        {tokenSaverActive && (
          <Panel title="Token Saver Active">
            <div className="rounded-control border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
              Dashboard task launching and due-schedule materialization are paused. You can still queue drafts, manage workspaces, and inspect local metadata.
            </div>
          </Panel>
        )}
        <Panel title="Workspaces">
          <div className="space-y-3">
            <input className="w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Workspace name" value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} />
            <div className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-2 text-xs font-medium text-muted">Explore folders</div>
              <div className="mb-3 flex flex-wrap gap-2">
                {browserRootsItems.map((root) => (
                  <button key={root.token} type="button" className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => setBrowserToken(root.token)}>
                    {browserIcon(root.kind)} {root.label}
                  </button>
                ))}
              </div>
              {browserRoots.isLoading ? <EmptyState label="Loading folder roots..." /> : null}
              {browserRoots.isError || browserFolder.isError ? <div className="mb-3 rounded-control border border-bad/30 bg-bad/10 p-2 text-xs text-bad">Folder browser could not load this location.</div> : null}
              {browserCurrent && (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                    {browserBreadcrumbs.map((crumb, index) => (
                      <button key={`${crumb.token}-${index}`} type="button" className="rounded-control border border-line px-2 py-1 hover:text-white" onClick={() => setBrowserToken(crumb.token)}>
                        {crumb.label}
                      </button>
                    ))}
                  </div>
                  <button type="button" className="inline-flex w-full items-center justify-center gap-2 rounded-control bg-focus px-3 py-2 text-sm font-semibold text-ink disabled:opacity-50" disabled={!workspaceName || !currentBrowserToken || createWorkspace.isPending} onClick={saveBrowserWorkspace}>
                    <Save className="h-4 w-4" /> Select this folder
                  </button>
                  <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                    {browserFolder.isLoading ? <EmptyState label="Loading folders..." /> : browserChildren.length === 0 ? <EmptyState label="No visible child folders." /> : browserChildren.map((child) => (
                      <button key={child.token} type="button" className="flex w-full min-w-0 items-center gap-2 rounded-control border border-line bg-ink px-3 py-2 text-left text-sm text-muted hover:text-white" onClick={() => setBrowserToken(child.token)}>
                        {browserIcon(child.kind)}
                        <span className="min-w-0 truncate">{child.label}</span>
                      </button>
                    ))}
                  </div>
                  {browserFolder.data?.truncated && <div className="text-xs text-warn">Showing the first folders only. Narrow by entering a child folder.</div>}
                </div>
              )}
            </div>
            <details className="rounded-control border border-line bg-panel2 p-3">
              <summary className="cursor-pointer text-xs font-medium text-muted">Advanced paste path</summary>
              <form className="mt-3 space-y-3" onSubmit={submitWorkspace}>
                <input className="w-full rounded-control border border-line bg-ink px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Absolute folder path" value={workspacePath} onChange={(event) => setWorkspacePath(event.target.value)} />
                <button type="button" className="inline-flex w-full items-center justify-center gap-2 rounded-control border border-line px-3 py-2 text-sm font-semibold text-muted hover:text-white disabled:opacity-50" disabled={!workspacePath || browseFromPath.isPending} onClick={() => browseFromPath.mutate()}>
                  <FolderOpen className="h-4 w-4" /> Browse from pasted path
                </button>
                <button className="inline-flex w-full items-center justify-center gap-2 rounded-control border border-focus/40 px-3 py-2 text-sm font-semibold text-focus disabled:opacity-50" disabled={!workspaceName || !workspacePath || createWorkspace.isPending}>
                  <Save className="h-4 w-4" /> Save pasted path
                </button>
              </form>
            </details>
            {createWorkspace.isError && <div className="rounded-control border border-bad/30 bg-bad/10 p-2 text-xs text-bad">{String(createWorkspace.error.message)}</div>}
            {browseFromPath.isError && <div className="rounded-control border border-bad/30 bg-bad/10 p-2 text-xs text-bad">{String(browseFromPath.error.message)}</div>}
            {deleteWorkspace.isError && <div className="rounded-control border border-bad/30 bg-bad/10 p-2 text-xs text-bad">{String(deleteWorkspace.error.message)}</div>}
          </div>
          <div className="mt-4 space-y-2">
            {workspaceItems.length === 0 ? <EmptyState label="Loading workspaces..." /> : workspaceItems.map((workspace) => (
              <div key={workspace.id} className="flex items-center justify-between gap-3 rounded-control border border-line bg-panel2 p-3 text-sm">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Folder className="h-4 w-4 text-muted" />
                    <span className="truncate font-medium text-white">{workspace.name}</span>
                    {workspace.is_default ? <Pill tone="focus">default</Pill> : null}
                  </div>
                  <div className="mono mt-1 truncate text-xs text-muted">{workspace.path_label}</div>
                </div>
                {!workspace.is_default && (
                  <button className="rounded-control border border-line p-2 text-muted hover:text-white disabled:opacity-50" onClick={() => deleteWorkspace.mutate(workspace.id)} disabled={deleteWorkspace.isPending} title="Remove workspace">
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Safe Starter Tasks">
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              {SAFE_TASK_TEMPLATES.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  className="inline-flex min-h-12 items-center gap-2 rounded-control border border-line bg-panel2 px-3 py-2 text-left text-sm font-medium text-white hover:border-focus/50 hover:bg-focus/10"
                  onClick={() => applyTaskTemplate(template)}
                >
                  <ListChecks className="h-4 w-4 shrink-0 text-focus" />
                  <span>{template.label}</span>
                </button>
              ))}
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
              Choose a starter task or write your own. A safe task says the goal, expected output, and boundaries. Do not paste secrets, private paths, tokens, raw logs, or prompt history. Start read-only; use workspace-write only when edits are truly needed.
            </div>
          </div>
        </Panel>

        <Panel title="Queue Task">
          <form className="space-y-3" onSubmit={submit}>
            <div className="rounded-control border border-good/30 bg-good/10 p-3 text-xs text-muted">
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-white">Default launch safety</span>
                <Pill tone="ok">read-only first</Pill>
              </div>
              <div className="break-words">Queued tasks stay waiting for approval. workspace-write requires a separate confirmation.</div>
            </div>
            <label className="grid gap-1 text-xs text-muted">
              <span>Title</span>
              <input className="w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Task title" value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs text-muted">
              <span>Details</span>
              <textarea className="min-h-32 w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Task details. Do not paste secrets or private paths." value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs text-muted">
              <span>Workspace</span>
              <select className="w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" value={selectedWorkspaceId} onChange={(event) => setWorkspaceId(event.target.value)} disabled={!workspaceItems.length}>
                {workspaceItems.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>{workspace.name} - {workspace.path_label}</option>
                ))}
              </select>
            </label>
            <div className={`rounded-control border p-3 ${sandbox === "workspace-write" ? "border-bad/50 bg-bad/10" : "border-good/30 bg-good/10"}`}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-sm font-medium text-white">Sandbox</div>
                <Pill tone={sandbox === "workspace-write" ? "bad" : "ok"}>{sandbox}</Pill>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  className={`inline-flex items-center justify-center gap-2 rounded-control border px-3 py-2 text-sm font-semibold ${sandbox === "read-only" ? "border-good/50 bg-good/20 text-good" : "border-line text-muted hover:text-white"}`}
                  onClick={() => {
                    setSandbox("read-only");
                    setShowWorkspaceWriteConfirm(false);
                  }}
                >
                  <ShieldCheck className="h-4 w-4" /> Read-only
                </button>
                <button
                  type="button"
                  className={`inline-flex items-center justify-center gap-2 rounded-control border px-3 py-2 text-sm font-semibold ${sandbox === "workspace-write" ? "border-bad bg-bad text-white" : "border-bad/50 text-bad hover:bg-bad/10"}`}
                  onClick={() => setShowWorkspaceWriteConfirm(true)}
                >
                  <AlertTriangle className="h-4 w-4" /> Workspace-write
                </button>
              </div>
              {showWorkspaceWriteConfirm && sandbox !== "workspace-write" && (
                <div className="mt-3 rounded-control border border-bad/40 bg-ink p-3 text-xs text-muted">
                  <div className="mb-2 font-semibold text-bad">Are you sure?</div>
                  <div className="mb-3">workspace-write can modify files in {workspaceLabel(selectedWorkspaceId ? Number(selectedWorkspaceId) : undefined)}.</div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="rounded-control border border-line px-3 py-1.5 text-muted hover:text-white" onClick={() => setShowWorkspaceWriteConfirm(false)}>
                      Keep read-only
                    </button>
                    <button
                      type="button"
                      className="rounded-control border border-bad bg-bad px-3 py-1.5 font-semibold text-white"
                      onClick={() => {
                        setSandbox("workspace-write");
                        setShowWorkspaceWriteConfirm(false);
                      }}
                    >
                      Yes, allow workspace-write
                    </button>
                  </div>
                </div>
              )}
              {sandbox === "workspace-write" && (
                <div className="mt-3 rounded-control border border-bad/40 bg-ink p-3 text-xs text-bad">
                  workspace-write is armed for the selected workspace. Switch back to read-only unless this task must edit files.
                </div>
              )}
            </div>
            <button className="inline-flex w-full items-center justify-center gap-2 rounded-control bg-focus px-3 py-2 text-sm font-semibold text-ink disabled:opacity-50" disabled={!title || !description || !selectedWorkspaceId || createTask.isPending}>
              <Play className="h-4 w-4" /> Queue for approval
            </button>
            <div className="rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
              Control Mode: {health.data?.control_mode_available ? "available" : "unavailable"}. Tasks remain awaiting approval until launched.
              {!health.data?.control_mode_available && health.data?.control_mode_reason && <div className="mt-1 text-warn">{health.data.control_mode_reason}</div>}
            </div>
          </form>
        </Panel>

        <Panel title="Create Schedule">
          <form className="space-y-3" onSubmit={submitSchedule}>
            <input className="w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Schedule name" value={scheduleName} onChange={(event) => setScheduleName(event.target.value)} />
            <input className="w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="@daily or 0 9 * * 1-5" value={scheduleCron} onChange={(event) => setScheduleCron(event.target.value)} />
            <input className="w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Task title" value={scheduleTaskTitle} onChange={(event) => setScheduleTaskTitle(event.target.value)} />
            <textarea className="min-h-28 w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Task details. Do not paste secrets or private paths." value={scheduleTaskDescription} onChange={(event) => setScheduleTaskDescription(event.target.value)} />
            <select className="w-full rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" value={selectedScheduleWorkspaceId} onChange={(event) => setScheduleWorkspaceId(event.target.value)} disabled={!workspaceItems.length}>
              {workspaceItems.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>{workspace.name} - {workspace.path_label}</option>
              ))}
            </select>
            <label className="flex items-center gap-2 rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-muted">
              <input type="checkbox" checked={scheduleEnabled} onChange={(event) => setScheduleEnabled(event.target.checked)} />
              Enabled
            </label>
            <button className="inline-flex w-full items-center justify-center gap-2 rounded-control bg-focus px-3 py-2 text-sm font-semibold text-ink disabled:opacity-50" disabled={!scheduleName || !scheduleCron || !scheduleTaskTitle || !scheduleTaskDescription || !selectedScheduleWorkspaceId || createSchedule.isPending}>
              <Clock className="h-4 w-4" /> Save schedule
            </button>
          </form>
        </Panel>
      </div>

      <div className="min-w-0 space-y-5">
        <Panel title="Task Board">
          <div className="space-y-2">
            {taskItems.length === 0 ? <EmptyState label="No tasks queued." /> : taskItems.map((task) => (
              <div key={task.id} className="min-w-0 rounded-control border border-line bg-panel2 p-3">
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="break-words font-medium text-white">{task.title}</div>
                    <div className="break-words text-xs text-muted">{task.cwd_label} - {task.sandbox}</div>
                  </div>
                  <Pill tone={taskStatusTone(task.status)}>{task.status}</Pill>
                </div>
                <p className="mb-3 line-clamp-2 break-words text-sm text-muted">{task.description}</p>
                <div className="mb-3 flex flex-wrap gap-2 text-xs">
                  <Pill tone="neutral">duration {formatDuration(task.duration_ms)}</Pill>
                  <Pill tone="neutral">{task.event_count ?? 0} events</Pill>
                  <Pill tone="neutral">{task.tool_count ?? 0} tools</Pill>
                  {task.exit_code !== null && task.exit_code !== undefined && <Pill tone={task.exit_code === 0 ? "ok" : "bad"}>exit {task.exit_code}</Pill>}
                </div>
                {task.output_summary && <div className="mb-3 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-control bg-ink p-2 text-xs text-muted">{task.output_summary}</div>}
                {task.failure_reason && <div className="mb-3 rounded-control border border-bad/30 bg-bad/10 p-2 text-xs text-bad">{task.failure_reason}</div>}
                {openTaskId === task.id && (
                  <div className="mb-3 grid gap-2 rounded-control border border-line bg-ink p-3 text-xs text-muted md:grid-cols-2">
                    <div><span className="text-muted">Created</span><div className="mono text-white">{formatShortTime(task.created_at)}</div></div>
                    <div><span className="text-muted">Updated</span><div className="mono text-white">{formatShortTime(task.updated_at)}</div></div>
                    <div><span className="text-muted">Started</span><div className="mono text-white">{formatShortTime(task.started_at)}</div></div>
                    <div><span className="text-muted">Completed</span><div className="mono text-white">{formatShortTime(task.completed_at)}</div></div>
                    <div><span className="text-muted">Approved</span><div className="mono text-white">{formatShortTime(task.approved_at)}</div></div>
                    <div><span className="text-muted">Scheduled</span><div className="mono text-white">{formatShortTime(task.scheduled_for)}</div></div>
                    <div className="md:col-span-2"><span className="text-muted">Thread</span><div className="mono truncate text-white">{task.thread_id ?? "n/a"}</div></div>
                    {task.error_message && <div className="md:col-span-2"><span className="text-muted">Safe error</span><div className="text-white">{task.error_message}</div></div>}
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => setOpenTaskId(openTaskId === task.id ? null : task.id)}>
                    {openTaskId === task.id ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />} Details
                  </button>
                  {task.status === "awaiting_approval" && (
                    <button
                      className="inline-flex items-center gap-1 rounded-control border border-good/40 px-2 py-1 text-xs text-good disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => approve.mutate(task.id)}
                      disabled={tokenSaverActive || approve.isPending}
                      title={tokenSaverActive ? "Token Saver is active; task launching is paused" : "Approve task"}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" /> {tokenSaverActive ? "Paused" : "Approve"}
                    </button>
                  )}
                  {task.status === "running" && (
                    <button className="inline-flex items-center gap-1 rounded-control border border-bad/40 px-2 py-1 text-xs text-bad" onClick={() => cancel.mutate(task.id)}>
                      <Square className="h-3.5 w-3.5" /> Cancel
                    </button>
                  )}
                  {task.status === "failed" && (
                    <button className="inline-flex items-center gap-1 rounded-control border border-focus/40 px-2 py-1 text-xs text-focus" onClick={() => rerun.mutate(task.id)}>
                      <RefreshCw className="h-3.5 w-3.5" /> Rerun
                    </button>
                  )}
                  {task.status !== "running" && (
                    <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => archive.mutate(task.id)}>
                      <Archive className="h-3.5 w-3.5" /> Archive
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel
          title="Schedules"
          action={
            <button
              className="inline-flex items-center gap-2 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => materializeDue.mutate()}
              disabled={materializeDue.isPending || tokenSaverActive}
              title={tokenSaverActive ? "Token Saver is active; schedule materialization is paused" : "Materialize due schedules"}
            >
              <RefreshCw className="h-3.5 w-3.5" /> Materialize due
            </button>
          }
        >
          {(schedules.data?.items ?? []).length === 0 ? <EmptyState label="No schedules yet." /> : (
            <div className="space-y-2">
              {(schedules.data?.items ?? []).map((schedule) => (
                <div key={schedule.id} className="rounded-control border border-line bg-panel2 p-3 text-sm">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-medium text-white">{schedule.name}</div>
                      <div className="mono text-xs text-muted">{schedule.cron_expression}</div>
                    </div>
                    <Pill tone={schedule.enabled ? "ok" : "neutral"}>{schedule.enabled ? "enabled" : "off"}</Pill>
                  </div>
                  <div className="grid gap-2 text-xs text-muted md:grid-cols-5">
                    <div><span>Next</span><div className="mono text-white">{formatShortTime(schedule.next_run_at)}</div></div>
                    <div><span>Last</span><div className="mono text-white">{formatShortTime(schedule.last_run_at)}</div></div>
                    <div><span>Queued</span><div className="mono text-white">{schedule.materialized_count ?? 0}</div></div>
                    <div><span>Task</span><div className="truncate text-white">{schedule.task_title}</div></div>
                    <div><span>Workspace</span><div className="truncate text-white">{workspaceLabel(schedule.workspace_id)}</div></div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => toggleSchedule.mutate({ id: schedule.id, enabled: !schedule.enabled })}>
                      {schedule.enabled ? <Square className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />} {schedule.enabled ? "Disable" : "Enable"}
                    </button>
                    <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={() => deleteSchedule.mutate(schedule.id)}>
                      <Archive className="h-3.5 w-3.5" /> Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function ResultCard({
  task,
  open,
  copied,
  followUpPending,
  createdFollowUpKind,
  onToggle,
  onCopy,
  onCreateFollowUp,
  featured = false
}: {
  task: Task;
  open: boolean;
  copied: boolean;
  followUpPending: boolean;
  createdFollowUpKind: FollowUpKind | null;
  onToggle: () => void;
  onCopy: () => void;
  onCreateFollowUp: (kind: FollowUpKind) => void;
  featured?: boolean;
}) {
  const category = inferResultCategory(task);
  const followUpKinds: FollowUpKind[] = category === "docs"
    ? ["docs", "structure", "security", "cleanup"]
    : category === "security"
      ? ["security", "cleanup", "docs", "structure"]
      : category === "cleanup"
        ? ["cleanup", "security", "docs", "structure"]
        : category === "structure"
          ? ["structure", "docs", "security", "cleanup"]
          : ["docs", "security", "cleanup", "structure"];
  return (
    <div className={`rounded-control border border-line bg-panel2 p-3 ${featured ? "space-y-4" : ""}`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium text-white">{task.title}</div>
          <div className="break-words text-xs text-muted">{task.cwd_label} - {task.sandbox} - {formatShortTime(task.completed_at ?? task.updated_at)}</div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Pill tone={resultCategoryTone(category)}>{resultCategoryLabel(category)}</Pill>
          {task.archived ? <Pill tone="neutral">archived</Pill> : null}
          <Pill tone={taskStatusTone(task.status)}>{task.status}</Pill>
        </div>
      </div>

      <div className="mb-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-control border border-line bg-ink p-2"><span className="text-muted">Duration</span><div className="mono text-white">{formatDuration(task.duration_ms)}</div></div>
        <div className="rounded-control border border-line bg-ink p-2"><span className="text-muted">Tools</span><div className="mono text-white">{task.tool_count ?? 0}</div></div>
        <div className="rounded-control border border-line bg-ink p-2"><span className="text-muted">Events</span><div className="mono text-white">{task.event_count ?? 0}</div></div>
        <div className="rounded-control border border-line bg-ink p-2"><span className="text-muted">Tokens</span><div className="mono text-white">{taskTokenText(task)}</div></div>
      </div>

      {task.output_summary ? (
        <div className={`${featured ? "max-h-96" : "max-h-40"} mb-3 overflow-auto whitespace-pre-wrap rounded-control bg-ink p-3 text-sm text-muted`}>
          {task.output_summary}
        </div>
      ) : (
        <div className="mb-3 rounded-control border border-dashed border-line p-3 text-sm text-muted">No safe summary recorded yet.</div>
      )}
      {task.failure_reason && <div className="mb-3 rounded-control border border-bad/30 bg-bad/10 p-3 text-xs text-bad">{task.failure_reason}</div>}

      {open && (
        <div className="mb-3 grid gap-2 rounded-control border border-line bg-ink p-3 text-xs text-muted md:grid-cols-3">
          <div><span>Created</span><div className="mono text-white">{formatShortTime(task.created_at)}</div></div>
          <div><span>Started</span><div className="mono text-white">{formatShortTime(task.started_at)}</div></div>
          <div><span>Completed</span><div className="mono text-white">{formatShortTime(task.completed_at)}</div></div>
          <div><span>Scheduled</span><div className="mono text-white">{formatShortTime(task.scheduled_for)}</div></div>
          <div><span>Approved</span><div className="mono text-white">{formatShortTime(task.approved_at)}</div></div>
          <div><span>Updated</span><div className="mono text-white">{formatShortTime(task.updated_at)}</div></div>
          <div><span>Exit</span><div className="mono text-white">{task.exit_code ?? "n/a"}</div></div>
          <div><span>Input</span><div className="mono text-white">{task.input_tokens === null ? "unknown" : compactNumber(task.input_tokens)}</div></div>
          <div><span>Output</span><div className="mono text-white">{task.output_tokens === null ? "unknown" : compactNumber(task.output_tokens)}</div></div>
          <div className="md:col-span-3"><span>Thread</span><div className="mono truncate text-white">{task.thread_id ?? "n/a"}</div></div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <a className="inline-flex items-center gap-1 rounded-control border border-focus/40 px-2 py-1 text-xs text-focus hover:bg-focus/10" href={`/results/${encodeURIComponent(String(task.id))}`}>
          <Eye className="h-3.5 w-3.5" /> View detail
        </a>
        <button className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" onClick={onToggle}>
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />} Details
        </button>
        <button className="inline-flex items-center gap-1 rounded-control border border-focus/40 px-2 py-1 text-xs text-focus hover:bg-focus/10" onClick={onCopy}>
          <Copy className="h-3.5 w-3.5" /> {copied ? "Copied" : "Copy safe summary"}
        </button>
        {(category === "audit" || category === "security" || category === "cleanup") && (
          <a className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white" href={`/health-report${task.workspace_id ? `?workspace_id=${encodeURIComponent(String(task.workspace_id))}` : ""}`}>
            <ShieldCheck className="h-3.5 w-3.5" /> Vault report
          </a>
        )}
      </div>

      <div className="mt-3 rounded-control border border-line bg-ink p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs font-medium text-white">Create read-only follow-up</div>
          <Pill tone="ok">awaiting approval</Pill>
        </div>
        <div className="flex flex-wrap gap-2">
          {followUpKinds.map((kind) => (
            <button
              key={kind}
              className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:border-focus/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              disabled={followUpPending}
              onClick={() => onCreateFollowUp(kind)}
              title={`${FOLLOW_UP_TASKS[kind].label}. Queues a safe read-only task using the same workspace.`}
            >
              <ListChecks className="h-3.5 w-3.5" />
              {FOLLOW_UP_TASKS[kind].label}
            </button>
          ))}
        </div>
        {createdFollowUpKind && (
          <div className="mt-2 rounded-control border border-good/30 bg-good/10 p-2 text-xs text-good">
            {FOLLOW_UP_TASKS[createdFollowUpKind].label} queued for approval on the Tasks page.
          </div>
        )}
      </div>
    </div>
  );
}

function ResultsPage() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<ResultCategoryFilter>("all");
  const [includeArchived, setIncludeArchived] = useState(true);
  const [openTaskId, setOpenTaskId] = useState<number | null>(null);
  const [copiedTaskId, setCopiedTaskId] = useState<number | null>(null);
  const [createdFollowUp, setCreatedFollowUp] = useState<{ sourceTaskId: number; kind: FollowUpKind; taskId: number } | null>(null);
  const queryParams = new URLSearchParams({
    status,
    query,
    include_archived: String(includeArchived),
    limit: "200"
  });
  const history = useQuery({
    queryKey: ["task-history", status, query, includeArchived],
    queryFn: () => apiGet<{ items: Task[]; stats: TaskHistoryStats }>(`/api/tasks/history?${queryParams.toString()}`),
    refetchInterval: 30000
  });
  const items = history.data?.items ?? [];
  const stats = history.data?.stats;
  const categoryCounts = items.reduce<Record<ResultCategoryFilter, number>>((counts, task) => {
    const inferred = inferResultCategory(task);
    counts.all += 1;
    counts[inferred] += 1;
    return counts;
  }, { all: 0, audit: 0, docs: 0, security: 0, structure: 0, cleanup: 0, general: 0 });
  const filteredItems = category === "all" ? items : items.filter((task) => inferResultCategory(task) === category);
  const currentResult = filteredItems[0] ?? null;
  const currentCategory = currentResult ? inferResultCategory(currentResult) : "general";
  const nextActions = currentResult ? resultNextActions(currentResult, currentCategory) : [];
  const createFollowUp = useMutation({
    mutationFn: ({ task, kind }: { task: Task; kind: FollowUpKind }) => apiPost<{ ok: boolean; task_id: number; status: string }>("/api/tasks", followUpTaskPayload(task, kind)),
    onSuccess: (data, variables) => {
      setCreatedFollowUp({ sourceTaskId: variables.task.id, kind: variables.kind, taskId: data.task_id });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["task-history"] });
    }
  });

  async function copyResult(task: Task) {
    const inferred = inferResultCategory(task);
    if (await writeClipboardText(safeResultCopyText(task, inferred))) {
      setCopiedTaskId(task.id);
      window.setTimeout(() => setCopiedTaskId(null), 1400);
    } else {
      setCopiedTaskId(null);
    }
  }

  function createResultFollowUp(task: Task, kind: FollowUpKind) {
    createFollowUp.mutate({ task, kind });
  }

  return (
    <div className="space-y-5">
      <Panel title="Results Filters">
        <div className="grid gap-3 lg:grid-cols-[180px_1fr_auto]">
          <select className="rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="all">all statuses</option>
            <option value="done">done</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
            <option value="awaiting_approval">awaiting approval</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
          </select>
          <input className="rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-white outline-none focus:border-focus" placeholder="Search titles and safe summaries" value={query} onChange={(event) => setQuery(event.target.value)} />
          <label className="flex items-center gap-2 rounded-control border border-line bg-panel2 px-3 py-2 text-sm text-muted">
            <input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />
            Include archived
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {RESULT_CATEGORIES.map((item) => (
            <button
              key={item.id}
              className={`inline-flex items-center gap-2 rounded-control border px-3 py-1.5 text-xs ${category === item.id ? "border-focus bg-focus/10 text-focus" : "border-line text-muted hover:text-white"}`}
              title={item.description}
              onClick={() => setCategory(item.id)}
            >
              {item.label}
              <span className="mono">{categoryCounts[item.id]}</span>
            </button>
          ))}
        </div>
        {createFollowUp.isError && (
          <div className="mt-3 rounded-control border border-bad/30 bg-bad/10 p-3 text-xs text-bad">
            Follow-up could not be queued: {String(createFollowUp.error.message)}
          </div>
        )}
        {createdFollowUp && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-control border border-good/30 bg-good/10 p-3 text-xs text-good">
            <span>{FOLLOW_UP_TASKS[createdFollowUp.kind].label} queued as task #{createdFollowUp.taskId}. It is awaiting approval.</span>
            <Link to="/tasks" className="inline-flex items-center gap-1 rounded-control border border-good/40 px-2 py-1 font-semibold text-good hover:bg-good/10">
              <Play className="h-3.5 w-3.5" /> Open Tasks
            </Link>
          </div>
        )}
      </Panel>

      <div className="grid gap-4 md:grid-cols-6">
        <Metric label="Total" value={compactNumber(stats?.total)} icon={<ListChecks className="h-4 w-4" />} />
        <Metric label="Shown" value={compactNumber(filteredItems.length)} icon={<Eye className="h-4 w-4" />} />
        <Metric label="Done" value={compactNumber(stats?.done)} icon={<CheckCircle2 className="h-4 w-4" />} />
        <Metric label="Failed" value={compactNumber(stats?.failed)} icon={<AlertTriangle className="h-4 w-4" />} />
        <Metric label="Avg duration" value={formatDuration(stats?.avg_duration_ms)} icon={<Clock className="h-4 w-4" />} />
        <Metric label="Tools" value={compactNumber(stats?.total_tools)} icon={<Workflow className="h-4 w-4" />} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
        <Panel title="Current Result Review">
          {history.isLoading ? <EmptyState label="Loading latest result..." /> : !currentResult ? <EmptyState label="No result matches the current filters." /> : (
            <ResultCard
              task={currentResult}
              open={openTaskId === currentResult.id}
              copied={copiedTaskId === currentResult.id}
              followUpPending={createFollowUp.isPending}
              createdFollowUpKind={createdFollowUp?.sourceTaskId === currentResult.id ? createdFollowUp.kind : null}
              onToggle={() => setOpenTaskId(openTaskId === currentResult.id ? null : currentResult.id)}
              onCopy={() => copyResult(currentResult)}
              onCreateFollowUp={(kind) => createResultFollowUp(currentResult, kind)}
              featured
            />
          )}
        </Panel>

        <Panel title="What Should I Do Next?">
          {!currentResult ? <EmptyState label="Pick a result category or run a task to get guidance." /> : (
            <div className="space-y-3">
              <div className="rounded-control border border-line bg-panel2 p-3 text-xs text-muted">
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-white">Based on current result</span>
                  <Pill tone={resultCategoryTone(currentCategory)}>{resultCategoryLabel(currentCategory)}</Pill>
                </div>
                Guidance is local and rule-based. It does not call OpenAI.
              </div>
              <div className="space-y-2">
                {nextActions.map((action, index) => (
                  <div key={action} className="flex gap-2 rounded-control border border-line bg-panel2 p-3 text-sm text-muted">
                    <span className="mono text-focus">{index + 1}</span>
                    <span>{action}</span>
                  </div>
                ))}
              </div>
              <Link to="/tasks" className="inline-flex w-full items-center justify-center gap-2 rounded-control border border-focus/40 px-3 py-2 text-sm font-semibold text-focus hover:bg-focus/10">
                <Play className="h-4 w-4" /> Queue follow-up task
              </Link>
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Run History">
        <div className="space-y-3">
          {history.isLoading ? <EmptyState label="Loading results..." /> : filteredItems.length === 0 ? <EmptyState label="No matching task results." /> : filteredItems.map((task) => (
            <ResultCard
              key={task.id}
              task={task}
              open={openTaskId === task.id}
              copied={copiedTaskId === task.id}
              followUpPending={createFollowUp.isPending}
              createdFollowUpKind={createdFollowUp?.sourceTaskId === task.id ? createdFollowUp.kind : null}
              onToggle={() => setOpenTaskId(openTaskId === task.id ? null : task.id)}
              onCopy={() => copyResult(task)}
              onCreateFollowUp={(kind) => createResultFollowUp(task, kind)}
            />
          ))}
        </div>
      </Panel>
    </div>
  );
}

function SkillsPage() {
  const { skills } = useDashboardData();
  const [revealedPaths, setRevealedPaths] = useState<Record<number, string>>({});
  const [revealingId, setRevealingId] = useState<number | null>(null);
  const [revealErrorId, setRevealErrorId] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const items = skills.data?.items ?? [];
  const revealPath = useMutation({
    mutationFn: (id: number) => apiGet<SkillPath>(`/api/skills/${id}/path`),
    onMutate: (id: number) => {
      setRevealingId(id);
      setRevealErrorId(null);
    },
    onSuccess: (data) => {
      setRevealedPaths((current) => ({ ...current, [data.id]: data.path }));
    },
    onError: (_error, id) => {
      setRevealErrorId(id);
    },
    onSettled: () => {
      setRevealingId(null);
    }
  });
  const grouped = items.reduce<Record<string, Skill[]>>((acc, item) => {
    acc[item.scope] = acc[item.scope] || [];
    acc[item.scope].push(item);
    return acc;
  }, {});

  async function copyPath(id: number, path: string) {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedId(id);
      window.setTimeout(() => setCopiedId(null), 1400);
    } catch {
      setCopiedId(null);
    }
  }

  return (
    <div className="space-y-5">
      <Panel title="Skills And Plugins">
        {items.length === 0 ? <EmptyState label="No skills discovered." /> : (
          <div className="space-y-5">
            {Object.entries(grouped).map(([scope, group]) => (
              <div key={scope}>
                <div className="mb-2 flex items-center gap-2">
                  <Pill tone="focus">{scope}</Pill>
                  <span className="text-xs text-muted">{group.length} skills</span>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  {group.map((skill) => (
                    <div key={skill.id} className="rounded-control border border-line bg-panel2 p-3">
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <div className="truncate font-medium text-white">{skill.name}</div>
                        {skill.plugin_name && <Pill>{skill.plugin_name}</Pill>}
                      </div>
                      <div className="line-clamp-2 text-sm text-muted">{skill.description || "No description."}</div>
                      <div className="mono mt-2 truncate text-xs text-muted">{skill.path_label}</div>
                      {revealedPaths[skill.id] ? (
                        <div className="mt-3 space-y-2">
                          <div className="mono overflow-x-auto rounded-control border border-line bg-ink p-2 text-xs text-white">
                            {revealedPaths[skill.id]}
                          </div>
                          <button
                            className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white"
                            onClick={() => copyPath(skill.id, revealedPaths[skill.id])}
                          >
                            <Copy className="h-3.5 w-3.5" />
                            {copiedId === skill.id ? "Copied" : "Copy path"}
                          </button>
                        </div>
                      ) : (
                        <div className="mt-3">
                          <button
                            className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-xs text-muted hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={revealingId === skill.id}
                            onClick={() => revealPath.mutate(skill.id)}
                          >
                            <Eye className="h-3.5 w-3.5" />
                            {revealingId === skill.id ? "Revealing..." : "Reveal path"}
                          </button>
                          {revealErrorId === skill.id && (
                            <div className="mt-2 rounded-control border border-bad/30 bg-bad/10 p-2 text-xs text-bad">
                              Path unavailable. Run sync and try again.
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
      <Panel title="Privacy Boundary">
        <div className="grid gap-3 text-sm md:grid-cols-3">
          <div className="rounded-control border border-line bg-panel2 p-3"><KeyRound className="mb-2 h-4 w-4 text-good" />No API key is required for observation.</div>
          <div className="rounded-control border border-line bg-panel2 p-3"><ShieldCheck className="mb-2 h-4 w-4 text-good" />The dashboard does not read Codex auth token files.</div>
          <div className="rounded-control border border-line bg-panel2 p-3"><AlertTriangle className="mb-2 h-4 w-4 text-warn" />Do not paste secrets into queued tasks.</div>
        </div>
      </Panel>
    </div>
  );
}

function ResultDetailPage() {
  const queryClient = useQueryClient();
  const params = useParams({ from: "/results/$taskId" });
  const taskId = Number(params.taskId);
  const [copied, setCopied] = useState(false);
  const [exportedMarkdown, setExportedMarkdown] = useState(false);
  const [createdFollowUp, setCreatedFollowUp] = useState<{ kind: FollowUpKind; taskId: number } | null>(null);
  const detail = useQuery({
    queryKey: ["task-detail", taskId],
    queryFn: () => apiGet<{ task: Task }>(`/api/tasks/${encodeURIComponent(String(taskId))}`),
    enabled: Number.isFinite(taskId) && taskId > 0,
    refetchInterval: 30000
  });
  const task = detail.data?.task;
  const category = task ? inferResultCategory(task) : "general";
  const nextActions = task ? resultNextActions(task, category) : [];
  const createFollowUp = useMutation({
    mutationFn: ({ task, kind }: { task: Task; kind: FollowUpKind }) => apiPost<{ ok: boolean; task_id: number; status: string }>("/api/tasks", followUpTaskPayload(task, kind)),
    onSuccess: (data, variables) => {
      setCreatedFollowUp({ kind: variables.kind, taskId: data.task_id });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["task-history"] });
    }
  });

  async function copyDetailResult(currentTask: Task) {
    if (await writeClipboardText(safeResultCopyText(currentTask, inferResultCategory(currentTask)))) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } else {
      setCopied(false);
    }
  }

  async function exportMarkdown(currentTask: Task) {
    const currentCategory = inferResultCategory(currentTask);
    if (await writeClipboardText(safeMarkdownReportText(currentTask, currentCategory, resultNextActions(currentTask, currentCategory)))) {
      setExportedMarkdown(true);
      window.setTimeout(() => setExportedMarkdown(false), 1600);
    } else {
      setExportedMarkdown(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white">Result Detail</div>
          <div className="text-xs text-muted">Focused safe review for one dashboard-launched task.</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/results" className="inline-flex items-center gap-2 rounded-control border border-line px-3 py-2 text-sm font-semibold text-muted hover:text-white">
            <ChevronDown className="h-4 w-4 rotate-90" /> Back to Results
          </Link>
          <Link to="/tasks" className="inline-flex items-center gap-2 rounded-control border border-focus/40 px-3 py-2 text-sm font-semibold text-focus hover:bg-focus/10">
            <Play className="h-4 w-4" /> Open Tasks
          </Link>
          {task && (
            <button className="inline-flex items-center gap-2 rounded-control bg-focus px-3 py-2 text-sm font-semibold text-ink" onClick={() => exportMarkdown(task)}>
              <Copy className="h-4 w-4" /> {exportedMarkdown ? "Markdown copied" : "Export Markdown"}
            </button>
          )}
        </div>
      </div>

      {detail.isLoading ? <Panel title="Result"><EmptyState label="Loading task result..." /></Panel> : detail.isError || !task ? <Panel title="Result"><EmptyState label="Task result unavailable." /></Panel> : (
        <>
          <div className="grid gap-4 md:grid-cols-6">
            <Metric label="Status" value={task.status} icon={<CheckCircle2 className="h-4 w-4" />} />
            <Metric label="Category" value={resultCategoryLabel(category)} icon={<ListChecks className="h-4 w-4" />} />
            <Metric label="Duration" value={formatDuration(task.duration_ms)} icon={<Clock className="h-4 w-4" />} />
            <Metric label="Tools" value={compactNumber(task.tool_count)} icon={<Workflow className="h-4 w-4" />} />
            <Metric label="Events" value={compactNumber(task.event_count)} icon={<Activity className="h-4 w-4" />} />
            <Metric label="Tokens" value={taskTokenText(task)} icon={<Terminal className="h-4 w-4" />} />
          </div>

          {createFollowUp.isError && (
            <div className="rounded-control border border-bad/30 bg-bad/10 p-3 text-xs text-bad">
              Follow-up could not be queued: {String(createFollowUp.error.message)}
            </div>
          )}
          {createdFollowUp && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-good/30 bg-good/10 p-3 text-xs text-good">
              <span>{FOLLOW_UP_TASKS[createdFollowUp.kind].label} queued as task #{createdFollowUp.taskId}. It is awaiting approval.</span>
              <Link to="/tasks" className="inline-flex items-center gap-1 rounded-control border border-good/40 px-2 py-1 font-semibold text-good hover:bg-good/10">
                <Play className="h-3.5 w-3.5" /> Open Tasks
              </Link>
            </div>
          )}
          {exportedMarkdown && (
            <div className="rounded-control border border-good/30 bg-good/10 p-3 text-xs text-good">
              Safe Markdown report copied to clipboard.
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
            <Panel title="Safe Result Reader">
              <ResultCard
                task={task}
                open
                copied={copied}
                followUpPending={createFollowUp.isPending}
                createdFollowUpKind={createdFollowUp?.kind ?? null}
                onToggle={() => undefined}
                onCopy={() => copyDetailResult(task)}
                onCreateFollowUp={(kind) => createFollowUp.mutate({ task, kind })}
                featured
              />
            </Panel>

            <div className="space-y-5">
              <Panel title="Review Context">
                <div className="space-y-3 text-sm">
                  <div className="rounded-control border border-line bg-panel2 p-3">
                    <div className="mb-1 text-xs text-muted">Workspace</div>
                    <div className="break-words text-white">{task.cwd_label}</div>
                  </div>
                  <div className="rounded-control border border-line bg-panel2 p-3">
                    <div className="mb-1 text-xs text-muted">Sandbox</div>
                    <Pill tone={task.sandbox === "read-only" ? "ok" : "bad"}>{task.sandbox}</Pill>
                  </div>
                  <div className="rounded-control border border-line bg-panel2 p-3">
                    <div className="mb-1 text-xs text-muted">Completed</div>
                    <div className="mono text-white">{formatShortTime(task.completed_at ?? task.updated_at)}</div>
                  </div>
                  {(category === "audit" || category === "security" || category === "cleanup") && (
                    <a className="inline-flex w-full items-center justify-center gap-2 rounded-control border border-line px-3 py-2 text-sm font-semibold text-muted hover:text-white" href={`/health-report${task.workspace_id ? `?workspace_id=${encodeURIComponent(String(task.workspace_id))}` : ""}`}>
                      <ShieldCheck className="h-4 w-4" /> Open Vault Report
                    </a>
                  )}
                </div>
              </Panel>

              <Panel title="Next Actions">
                <div className="space-y-2">
                  {nextActions.map((action, index) => (
                    <div key={action} className="flex gap-2 rounded-control border border-line bg-panel2 p-3 text-sm text-muted">
                      <span className="mono text-focus">{index + 1}</span>
                      <span>{action}</span>
                    </div>
                  ))}
                </div>
              </Panel>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function PublishReadinessPage() {
  const readiness = useQuery({
    queryKey: ["publish-readiness"],
    queryFn: () => apiGet<PublishReadiness>("/api/publish-readiness"),
    refetchInterval: false
  });
  const data = readiness.data;
  const statusTone = publishStatusTone(data?.status ?? "review");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white">Publish Readiness</div>
          <div className="text-xs text-muted">Local-only checklist before any GitHub commit or push.</div>
        </div>
        <button
          className="inline-flex items-center gap-2 rounded-control border border-line px-3 py-2 text-sm font-semibold text-muted hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => readiness.refetch()}
          disabled={readiness.isFetching}
          title="Re-run local publish readiness checks"
        >
          <RefreshCw className={`h-4 w-4 ${readiness.isFetching ? "animate-spin" : ""}`} />
          Refresh check
        </button>
      </div>

      <div className="rounded-control border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
        This page does not publish, commit, stage, push, upload, or contact GitHub. It only reads local package metadata and safety-check results.
      </div>

      {readiness.isLoading ? <Panel title="Readiness"><EmptyState label="Running local publish readiness checks..." /></Panel> : readiness.isError || !data ? <Panel title="Readiness"><EmptyState label="Publish readiness unavailable." /></Panel> : (
        <>
          <div className="grid gap-5 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.2fr)]">
            <Panel title="Package Verdict">
              <div className="space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-4xl font-semibold text-white">{publishStatusLabel(data.status)}</div>
                    <div className="mt-1 text-xs text-muted">Generated {formatShortTime(data.generated_at)}</div>
                  </div>
                  <Pill tone={statusTone}>{publishStatusLabel(data.status)}</Pill>
                </div>
                <div className="rounded-control border border-line bg-panel2 p-3 text-sm">
                  <div className="mb-1 font-medium text-white">{data.package.name}</div>
                  <div className="mono truncate text-xs text-muted">{data.package.path_label}</div>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center text-sm">
                  <div className="rounded-control bg-panel2 p-3"><div className="text-xl text-good">{data.summary.ok}</div><div className="text-xs text-muted">ok</div></div>
                  <div className="rounded-control bg-panel2 p-3"><div className="text-xl text-warn">{data.summary.review}</div><div className="text-xs text-muted">review</div></div>
                  <div className="rounded-control bg-panel2 p-3"><div className="text-xl text-bad">{data.summary.block}</div><div className="text-xs text-muted">block</div></div>
                </div>
              </div>
            </Panel>

            <Panel title="Local Evidence">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-control border border-line bg-panel2 p-3">
                  <div className="mb-1 text-xs text-muted">Safety scan</div>
                  <Pill tone={publishStatusTone(data.safety_scan.status)}>{data.safety_scan.status}</Pill>
                  <div className="mt-2 text-xs text-muted">{data.safety_scan.finding_count} findings</div>
                </div>
                <div className="rounded-control border border-line bg-panel2 p-3">
                  <div className="mb-1 text-xs text-muted">Git review</div>
                  <Pill tone={data.git.available && data.git.changed === 0 ? "ok" : "warn"}>{data.git.available ? `${data.git.changed} changed` : "unavailable"}</Pill>
                  <div className="mt-2 text-xs text-muted">{data.git.staged} staged, {data.git.untracked} untracked</div>
                </div>
                <div className="rounded-control border border-line bg-panel2 p-3">
                  <div className="mb-1 text-xs text-muted">Publish action</div>
                  <Pill tone={data.does_not_publish ? "ok" : "bad"}>{data.does_not_publish ? "disabled" : "unsafe"}</Pill>
                  <div className="mt-2 text-xs text-muted">Manual approval required.</div>
                </div>
              </div>
            </Panel>
          </div>

          <Panel title="Checklist">
            <div className="grid gap-3 md:grid-cols-2">
              {data.checks.map((check) => (
                <div key={check.id} className="rounded-control border border-line bg-panel2 p-3">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="font-medium text-white">{check.label}</div>
                    <Pill tone={publishStatusTone(check.status)}>{publishStatusLabel(check.status)}</Pill>
                  </div>
                  <div className="text-sm text-muted">{check.detail}</div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Manual Next Steps">
              <div className="space-y-2">
                {data.next_steps.map((step, index) => (
                  <div key={step} className="flex gap-2 rounded-control border border-line bg-panel2 p-3 text-sm text-muted">
                    <span className="mono text-focus">{index + 1}</span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Recommended Commands">
              <pre className="mono overflow-auto rounded-control border border-line bg-ink p-3 text-xs text-white">{[
                "python -m pytest",
                "cd ui",
                "npm run build",
                "cd ..",
                "python scripts/public_safety_scan.py .",
                "git status --short",
                "git diff"
              ].join("\n")}</pre>
              <div className="mt-3 text-xs text-muted">Review outputs manually. Stage named files only after review.</div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

function GuidePage() {
  const steps = [
    {
      title: "Choose a workspace",
      detail: "Register the folder you want Codex to inspect. The UI shows safe labels, while the real path stays local in SQLite."
    },
    {
      title: "Start read-only",
      detail: "Pick a Safe Starter Task or write a small goal. Read-only is the default and should be used for audits, summaries, and reviews."
    },
    {
      title: "Approve deliberately",
      detail: "Queued tasks do nothing until you approve them. Approval launches local `codex exec --json` and may use Codex usage."
    },
    {
      title: "Review results",
      detail: "Use the Results page to read safe summaries, copy public-safe notes, check tools/tokens, and choose the next small task."
    }
  ];
  const safetyRules = [
    "Do not paste secrets, tokens, raw logs, private prompts, or full local paths into task details.",
    "Use workspace-write only for a focused edit task in a folder you are comfortable modifying.",
    "Use Vault Health Report for file-location details instead of asking tasks to expose full paths.",
    "Treat Usage Remaining as best-effort local metadata; the Codex app remains the source of truth."
  ];
  return (
    <div className="space-y-5">
      <Panel title="How To Use This Safely">
        <div className="grid gap-3 md:grid-cols-4">
          {steps.map((step, index) => (
            <div key={step.title} className="rounded-control border border-line bg-panel2 p-3">
              <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-control border border-focus/40 bg-focus/10 text-sm font-semibold text-focus">{index + 1}</div>
              <div className="mb-1 font-medium text-white">{step.title}</div>
              <div className="text-sm text-muted">{step.detail}</div>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Safe Defaults">
          <div className="space-y-3 text-sm">
            <div className="rounded-control border border-good/30 bg-good/10 p-3 text-good">
              Observe Mode does not call OpenAI and does not spend Codex tokens.
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3 text-muted">
              Dashboard-launched tasks stay approval-gated, default to read-only, and hide raw output by metadata-only policy.
            </div>
            <div className="rounded-control border border-line bg-panel2 p-3 text-muted">
              Token Saver blocks dashboard task launches and due schedule materialization when you want to avoid accidental usage.
            </div>
          </div>
        </Panel>

        <Panel title="Safety Checklist">
          <div className="space-y-2">
            {safetyRules.map((rule) => (
              <div key={rule} className="flex gap-2 rounded-control border border-line bg-panel2 p-3 text-sm text-muted">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-good" />
                <span>{rule}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Good First Tasks">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-control border border-line bg-panel2 p-3">
            <ListChecks className="mb-2 h-4 w-4 text-focus" />
            <div className="mb-1 font-medium text-white">Full safe audit</div>
            <div className="text-sm text-muted">Best first pass for a vault or project folder. It stays read-only and gives broad next steps.</div>
          </div>
          <div className="rounded-control border border-line bg-panel2 p-3">
            <ShieldCheck className="mb-2 h-4 w-4 text-good" />
            <div className="mb-1 font-medium text-white">Read-only security review</div>
            <div className="text-sm text-muted">Useful before publishing or sharing. Pair it with the Vault Health Report.</div>
          </div>
          <div className="rounded-control border border-line bg-panel2 p-3">
            <Workflow className="mb-2 h-4 w-4 text-focus" />
            <div className="mb-1 font-medium text-white">Documentation gaps</div>
            <div className="text-sm text-muted">Good after an audit, especially if README, setup, or usage notes are unclear.</div>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to="/tasks" className="inline-flex items-center gap-2 rounded-control bg-focus px-3 py-2 text-sm font-semibold text-ink">
            <Play className="h-4 w-4" /> Open Tasks
          </Link>
          <Link to="/results" className="inline-flex items-center gap-2 rounded-control border border-line px-3 py-2 text-sm font-semibold text-muted hover:text-white">
            <ListChecks className="h-4 w-4" /> Review Results
          </Link>
        </div>
      </Panel>
    </div>
  );
}

const rootRoute = createRootRoute({ component: Layout });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: DashboardPage });
const healthReportRoute = createRoute({ getParentRoute: () => rootRoute, path: "/health-report", component: HealthReportPage });
const tasksRoute = createRoute({ getParentRoute: () => rootRoute, path: "/tasks", component: TasksPage });
const resultsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/results", component: ResultsPage });
const resultDetailRoute = createRoute({ getParentRoute: () => rootRoute, path: "/results/$taskId", component: ResultDetailPage });
const skillsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/skills", component: SkillsPage });
const guideRoute = createRoute({ getParentRoute: () => rootRoute, path: "/guide", component: GuidePage });
const publishRoute = createRoute({ getParentRoute: () => rootRoute, path: "/publish", component: PublishReadinessPage });
const routeTree = rootRoute.addChildren([indexRoute, healthReportRoute, tasksRoute, resultsRoute, resultDetailRoute, skillsRoute, guideRoute, publishRoute]);
const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
