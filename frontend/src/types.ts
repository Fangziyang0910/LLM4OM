// 公开运行数据的外形。字段按需声明,未知阶段如实缺失;不做任何补造。

export interface ArtifactRef {
  artifact_id?: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
  namespace: string;
  relative_path: string;
  schema_version?: string;
}

export interface JobRecord {
  job_id: string;
  created_at: number;
  status: string;
  run_id: string | null;
  description: string;
  method: string;
  model: string;
  error?: { code: string; message: string } | null;
  assisted?: boolean;
  [key: string]: unknown;
}

export interface RunVersion {
  run_id: string;
  status: string;
  parent_run_id: string | null;
  operation: string | null;
  assisted: boolean;
  saved_at: number;
}

export interface RunEvent {
  sequence_no: number;
  kind: string;
  method_event?: MethodStep & { artifact_ref?: ArtifactRef; stage?: string };
  [key: string]: unknown;
}

export interface MethodStep {
  type?: string;
  step_id: string;
  label: string;
  actor: string;
  phase: "formulation" | "code" | "solve" | "coordination";
  status: "running" | "completed" | "failed";
  timestamp?: number;
  artifact_ref?: ArtifactRef;
}

export interface Snapshot {
  job: JobRecord;
  bundle: RunBundle | null;
  events: RunEvent[];
  artifacts: ArtifactRef[];
  contents: Record<string, any>;
  versions: RunVersion[];
  latest_run_id: string | null;
  historical: boolean;
  data_previews: Record<string, DataPreview>;
}

export interface RunBundle {
  status: string;
  assisted?: boolean;
  error?: { code: string; message: string } | null;
  final_candidate_id?: string;
  stages?: Record<string, { status: string; reason: string | null }>;
  model_artifact_ref?: ArtifactRef | null;
  solve_result_ref?: ArtifactRef | null;
  execution_result_ref?: ArtifactRef | null;
  clarification_request_ref?: ArtifactRef | null;
  public_projections?: Record<string, ArtifactRef>;
  artifacts?: ArtifactRef[];
}

export interface DataPreview {
  columns: string[];
  rows: string[][];
  total_items: number;
  display_truncated: boolean;
  metadata: { complete?: boolean; kind?: string; rows?: number; total_rows?: number | null; sha256?: string; size_bytes?: number };
}

export interface PluginManifest {
  manifest: {
    kind: string;
    plugin_id: string;
    display_name: string;
    capabilities: Record<string, any>;
  };
}

export interface ExperimentRecord {
  experiment_id: string;
  created_at: number;
  status: string;
  task_count: number;
  configuration_count: number;
  repeats: number;
  error?: unknown;
}

export type RunConfig = Record<string, any>;

export interface UploadItem {
  name: string;
  size: number;
  data_id: string;
  format: "csv" | "json";
  base64: string;
  schema?: unknown;
  preview?: { columns: string[]; rows: string[][]; total_items: number; display_truncated: boolean };
  previewError?: string;
}
