import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { format, pretty, shortMethod } from "../ui";
import { Connectivity } from "./Connectivity";
import type { BenchmarkInput, Bootstrap, JobRecord, Notice, PublicProblem, RunConfig, UploadItem } from "../types";

const problemExamples: Record<string, string> = {
  production:
    "一家工厂生产产品 A 和 B。每件 A 的利润为 3，每件 B 的利润为 2。每件 A 消耗 2 单位原料和 1 单位工时；每件 B 消耗 1 单位原料和 2 单位工时。原料和工时的可用容量均为 8。决定两种产品的生产数量，数量必须是非负整数，使总利润最大。",
  projects:
    "有甲、乙、丙三个项目，费用分别为 4、3、5 万元，收益分别为 7、5、9 万元。总预算为 8 万元。每个项目只能选择或不选择，最多执行一次。决定选择哪些项目，使总收益最大，并且不超过预算。",
  diet: "两种食物 A、B 每份价格分别为 2、3 元，每份蛋白质分别为 3、4 克，每份膳食纤维分别为 2、1 克。每日至少需要 12 克蛋白质和 8 克膳食纤维。份数可以是非负小数。决定两种食物的份数，使总费用最小。",
};

function parseConfig(raw: string): RunConfig {
  const value: RunConfig = JSON.parse(raw);
  const object = (item: unknown) => item !== null && typeof item === "object" && !Array.isArray(item);
  if (!object(value) || !object(value.llm) || !object(value.llm.config) ||
      typeof value.llm.model !== "string" || typeof value.llm.provider_plugin_id !== "string" ||
      !object(value.budget) || !["method", "model_backend", "solver", "executor", "store"].every(key =>
        object(value[key]) && typeof (value[key] as { plugin_id?: unknown }).plugin_id === "string") ||
      !["max_llm_attempts", "max_total_tokens", "max_candidates", "max_repairs", "max_solver_calls", "wall_time_s", "max_concurrency"].every(key =>
        typeof value.budget[key] === "number" && Number.isFinite(value.budget[key])))
    throw new Error("请提供完整的运行配置、模型和有效的预算数值。");
  return value;
}

export function ProblemEditor({ bootstrap, notice, onSubmitted, benchmarkInput }: {
  bootstrap: Bootstrap; notice: Notice; onSubmitted: (job: JobRecord) => Promise<void>;
  benchmarkInput?: BenchmarkInput | null;
}) {
  const [config, setConfig] = useState<RunConfig>(bootstrap.config);
  const [configDraft, setConfigDraft] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [compatNote, setCompatNote] = useState("");
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [description, setDescription] = useState("");
  const [problemJson, setProblemJson] = useState("");
  const [doctorResult, setDoctorResult] = useState<unknown>(null);
  const [checkConnectivity, setCheckConnectivity] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [doctorBusy, setDoctorBusy] = useState(false);
  useEffect(() => {
    if (!benchmarkInput) return;
    setDescription(benchmarkInput.problem.description);
    setProblemJson(JSON.stringify(benchmarkInput.problem, null, 2));
    setUploads(benchmarkInput.data.map((item) => ({ ...item })));
    setDoctorResult(null);
    document.getElementById("description")?.focus();
  }, [benchmarkInput]);
  const plugins = bootstrap.plugins;
  const presets = bootstrap.method_presets;
  const methodManifest = plugins.find(
    (p) => p.manifest.plugin_id === config.method?.plugin_id,
  )?.manifest;
  const backendManifest = plugins.find(
    (p) => p.manifest.plugin_id === config.model_backend?.plugin_id,
  )?.manifest;
  const compatibleSolvers = methodManifest?.capabilities.solvers?.filter((id: string) => {
    const solver = plugins.find((p) => p.manifest.plugin_id === id)?.manifest;
    return (
        !backendManifest?.capabilities.handle_profile ||
        !solver?.capabilities.handle_profiles ||
        solver.capabilities.handle_profiles.includes(backendManifest.capabilities.handle_profile)
      );
    });

    const selectOptions = useMemo(() => {
      const build = (kind: string, selected: string | undefined, allowed?: string[]) => {
        const options: { value: string; label: string; disabled?: boolean }[] = plugins
          .filter(
            (p) =>
              p.manifest.kind === kind &&
              !(kind === "llm_provider" && p.manifest.capabilities.provider_profile !== "http_text/0.1.0") &&
              !(kind === "method" && presets[p.manifest.plugin_id]?.hidden) &&
              !p.manifest.capabilities.human_assisted &&
              (!allowed || allowed.includes(p.manifest.plugin_id)),
          )
          .map((p) => ({
            value: p.manifest.plugin_id,
            label:
              kind === "method"
                ? shortMethod(p.manifest.plugin_id)
                : kind === "solver_backend"
                  ? p.manifest.plugin_id === "llm4om.solvers.ortools" ? p.manifest.display_name : p.manifest.plugin_id.split(".").at(-1)!.toUpperCase()
                  : p.manifest.display_name,
          }));
        if (selected && !options.some((option) => option.value === selected))
          options.push({ value: selected, label: "当前配置不可用 · " + selected, disabled: true });
        return options;
      };
      return {
        method: build("method", config.method?.plugin_id),
        provider: build("llm_provider", config.llm?.provider_plugin_id),
        backend: build("model_backend", config.model_backend?.plugin_id),
        solver: build("solver_backend", config.solver?.plugin_id, compatibleSolvers),
      };
    }, [plugins, presets, config.method?.plugin_id, config.llm?.provider_plugin_id, config.model_backend?.plugin_id, config.solver?.plugin_id, compatibleSolvers]);

    const solverSelectionDisabled = Boolean(
      selectOptions.solver.find((option) => option.value === config.solver?.plugin_id)?.disabled,
    );

    const chooseMethod = (method: string) => {
      const preset = presets[method];
      const next = structuredClone(config);
      next.method = { plugin_id: method, config: preset?.config || {} };
      if (preset) {
        next.model_backend = { ...next.model_backend, ...preset.model_backend };
        next.solver = { ...next.solver, ...preset.solver };
        next.budget = { ...next.budget, ...preset.budget };
        if (preset.compiler) next.compiler = preset.compiler;
        else delete next.compiler;
      }
      setConfig(next);
      setCompatNote(preset ? "已按该方法声明的能力切换:建模后端 " + preset.model_backend.plugin_id.split(".").at(-1) +
        " · 求解器 " + preset.solver.plugin_id.split(".").at(-1)?.toUpperCase() + "。可在下方手动调整。" : "");
    };
    const submitRun = async () => {
      try {
        setSubmitting(true);
        const next = config;
        const payload: { description: string; config: RunConfig; data: unknown[]; problem?: PublicProblem } = {
          description,
          config: next,
          data: uploads.map(({ data_id, format, base64, schema }) => ({
            data_id,
            format,
            base64,
            ...(schema ? { schema } : {}),
          })),
        };
        if (problemJson.trim()) {
          const problem: PublicProblem = JSON.parse(problemJson);
          problem.description = description;
          payload.problem = problem;
        }
        const job = await api<JobRecord>("/api/jobs", payload, apiKey || undefined);
        notice("运行已提交。");
        await onSubmitted(job);
      } catch (error) {
        notice((error as Error).message, true);
      } finally {
        setSubmitting(false);
      }
    };

    const runDoctor = async () => {
      try {
        setDoctorBusy(true);
        setDoctorResult(null);
        notice("正在检查实际环境与兼容路径…");
        const result = await api<{ connectivity_checks: { status: string } }>("/api/doctor", {
          config,
          check_connectivity: checkConnectivity,
        }, apiKey || undefined);
        setDoctorResult(result);
        notice(
          result.connectivity_checks.status === "failed"
            ? "配置检查通过，模型接口检查未通过。"
            : "配置检查完成。",
          result.connectivity_checks.status === "failed",
        );
      } catch (error) {
        notice((error as Error).message, true);
      } finally {
        setDoctorBusy(false);
      }
    };

    return (
            <section id="editor" className="editor-grid">
              <div className="panel problem-panel">
                <div className="panel-title">
                  <h2>描述问题</h2>
                  <label className="file-button">
                    导入问题
                    <input
                      id="problem-file"
                      type="file"
                      accept=".json"
                      onChange={async (event) => {
                        const file = event.target.files?.[0];
                        if (!file) return;
                        try {
                          const problem = JSON.parse(await file.text());
                          setProblemJson(pretty(problem));
                          setDescription(problem.description);
                          notice("问题规格已导入。请同时添加其中引用的公开数据。");
                        } catch (error) {
                          notice((error as Error).message, true);
                        }
                      }}
                    />
                  </label>
                </div>
                <label htmlFor="description">用自然语言描述你的目标、决策和限制</label>
                <textarea
                  id="description"
                  rows={9}
                  placeholder={
                    "例如：我想制定工厂的生产计划。在原料和工时有限的情况下，决定每种产品的生产数量，让总利润最大。"
                  }
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
                <div className="example-chips">
                  <span>从示例开始</span>
                  {Object.entries(problemExamples).map(([key, text]) => (
                    <span key={key}>
                      <button
                        type="button"
                        className="example-chip"
                        data-example={key}
                        id={key === "production" ? "load-example" : undefined}
                        onClick={() => {
                          setDescription(text);
                          setProblemJson("");
                          setUploads([]);
                        }}
                      >
                        {{ production: "生产计划", projects: "项目选择", diet: "配餐优化" }[key]}
                      </button>
                    </span>
                  ))}
                </div>
                <div className="upload-line">
                  <label className="file-button">
                    ＋ 添加 CSV / JSON
                    <input
                      id="data-files"
                      type="file"
                      accept=".csv,.json"
                      disabled={false}
                      multiple
                      onChange={async (event) => {
                        const files = Array.from(event.target.files || []);
                        for (const file of files) {
                          if (file.size > 8 * 1024 * 1024) {
                            notice("单个文件不能超过 8 MiB。", true);
                            continue;
                          }
                          const bytes = new Uint8Array(await file.arrayBuffer());
                          let binary = "";
                          for (let start = 0; start < bytes.length; start += 16384)
                            binary += String.fromCharCode(...bytes.subarray(start, start + 16384));
                          const upload: UploadItem = {
                            name: file.name,
                            size: file.size,
                            data_id: file.name.replace(/\.[^.]+$/, ""),
                            format: file.name.toLowerCase().endsWith(".csv") ? "csv" : "json",
                            base64: btoa(binary),
                          };
                          setUploads((prior) => [...prior, upload]);
                          try {
                          const preview = await api<NonNullable<UploadItem["preview"]>>("/api/data-preview", {
                              format: upload.format,
                              base64: upload.base64,
                            });
                            upload.preview = preview;
                          } catch (error) {
                            upload.previewError = "文件预览未完成：" + (error as Error).message;
                          }
                          setUploads((prior) => [...prior]);
                        }
                        event.target.value = "";
                      }}
                    />
                  </label>
                </div>
                <div id="uploads">
                  {uploads.map((upload, index) => (
                    <div className="upload-card" key={upload.name + index}>
                      <div className="upload-meta">
                        <input
                          aria-label="公开数据 ID"
                          value={upload.data_id}
                          onChange={(event) =>
                            setUploads((prior) =>
                              prior.map((item, i) =>
                                i === index ? { ...item, data_id: event.target.value } : item,
                              ),
                            )
                          }
                        />
                        <span>{`${upload.name} · ${upload.size} bytes`}</span>
                        <button
                          onClick={() => setUploads((prior) => prior.filter((_, i) => i !== index))}
                        >
                          移除
                        </button>
                      </div>
                      {upload.preview ? (
                        <>
                          <UploadPreview preview={upload.preview} />
                          <p className="hint">
                            {upload.preview.display_truncated
                              ? `显示 ${upload.preview.rows.length} / ${upload.preview.total_items} 行或字段，最多16列；长文本只显示前256字符。完整文件会用于提交。`
                              : `共 ${upload.preview.total_items} 行或字段。预览保留原始值，不改变提交的数据。`}
                          </p>
                        </>
                      ) : (
                        <p className="hint">{upload.previewError || "正在读取文件预览…"}</p>
                      )}
                      <details>
                        <summary>
                          {upload.format === "csv"
                            ? "高级：列类型与唯一键（CSV 默认保留原始字符串）"
                            : "高级：数据 schema"}
                        </summary>
                        <textarea
                          rows={6}
                          aria-label="公开数据 schema"
                          defaultValue={upload.schema ? pretty(upload.schema) : ""}
                          onChange={(event) => {
                            try {
                              const schema = event.target.value.trim()
                                ? JSON.parse(event.target.value)
                                : undefined;
                              setUploads((prior) =>
                                prior.map((item, i) => (i === index ? { ...item, schema } : item)),
                              );
                            } catch (error) {
                              notice((error as Error).message, true);
                            }
                          }}
                        />
                      </details>
                    </div>
                  ))}
                </div>
                <details>
                  <summary>高级：直接编辑问题 JSON</summary>
                  <textarea
                    id="problem-json"
                    rows={12}
                    aria-label="完整公开问题规格"
                    placeholder="可导入或编辑 ProblemSpec；留空时根据上述描述创建。"
                    value={problemJson}
                    onChange={(event) => setProblemJson(event.target.value)}
                  />
                </details>
              </div>
              <div className="panel settings-panel">
                <h2>建模设置</h2>
                <div className="field-grid">
                  <label>
                    建模方法
                    <select
                      id="method"
                      value={config.method?.plugin_id || ""}
                      onChange={(event) => chooseMethod(event.target.value)}
                    >
                      {selectOptions.method.map((option) => (
                        <option key={option.value} value={option.value} disabled={option.disabled}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    LLM 接口类型
                    <select
                      id="provider"
                      value={config.llm?.provider_plugin_id || ""}
                      onChange={(event) => {
                        const defaults: Record<string, string> = {
                          "llm4om.providers.openai_compatible": "https://api.openai.com/v1",
                          "llm4om.providers.anthropic": "https://api.anthropic.com/v1",
                        };
                        const provider = event.target.value;
                        const baseUrl = config.llm.config.base_url;
                        const next = {
                          ...config,
                          llm: { ...config.llm, provider_plugin_id: provider, config: {
                            ...config.llm.config,
                            ...(defaults[provider] && (!baseUrl || Object.values(defaults).includes(baseUrl))
                              ? { base_url: defaults[provider] } : {}),
                          } },
                        };
                        setConfig(next);
                      }}
                    >
                      {selectOptions.provider.map((option) => (
                        <option key={option.value} value={option.value} disabled={option.disabled}>
                          {{ "llm4om.providers.openai_compatible": "OpenAI 兼容协议",
                            "llm4om.providers.anthropic": "Anthropic 协议" }[option.value] || option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wide">
                    模型名称
                    <input
                      id="model"
                      placeholder="填写服务提供的模型 ID"
                      value={config.llm.model}
                      onChange={(event) => setConfig(prior => ({ ...prior, llm: { ...prior.llm, model: event.target.value } }))}
                    />
                  </label>
                  <label className="wide">
                    API 地址（Base URL）
                    <input id="llm-base-url" type="url" value={config.llm.config.base_url || ""}
                      placeholder="https://你的服务地址/v1"
                      disabled={!config.llm.config.credential_env}
                      onChange={(event) => setConfig(prior => ({ ...prior, llm: { ...prior.llm,
                        config: { ...prior.llm.config, base_url: event.target.value } } }))} />
                  </label>
                  <label className="wide">
                    API Key
                    <input id="llm-api-key" type="password" autoComplete="off" spellCheck={false}
                      value={apiKey} disabled={!config.llm.config.credential_env} maxLength={4096}
                      placeholder="留空使用本机默认服务的密钥；更换服务时请填写"
                      onChange={(event) => setApiKey(event.target.value.trim())} />
                    <span className="hint">密钥只用于当前本机服务会话，不写入运行记录。</span>
                  </label>
                  <label className="advanced-field">
                    建模后端
                    <select
                      id="backend"
                      value={config.model_backend?.plugin_id || ""}
                      onChange={(event) => {
                        const next = {
                          ...config,
                          model_backend: { ...config.model_backend, plugin_id: event.target.value },
                        };
                        setConfig(next);
                      }}
                    >
                      {selectOptions.backend.map((option) => (
                        <option key={option.value} value={option.value} disabled={option.disabled}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    求解器
                    <select
                      id="solver"
                      value={config.solver?.plugin_id || ""}
                      onChange={(event) => {
                        const next = { ...config, solver: { ...config.solver, plugin_id: event.target.value } };
                        setConfig(next);
                      }}
                    >
                      {selectOptions.solver.map((option) => (
                        <option key={option.value} value={option.value} disabled={option.disabled}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wide advanced-field">
                    Provider URL
                    <input
                      id="base-url"
                      type="url"
                      value={config.llm.config.base_url || ""}
                      onChange={(event) => setConfig(prior => ({ ...prior, llm: { ...prior.llm, config: { ...prior.llm.config, base_url: event.target.value } } }))}
                    />
                  </label>
                </div>
                <div id="method-explainer" className="method-explainer method-explainer-card">
                  <p>{presets[config.method.plugin_id]?.explanation ||
                    "按所选方法的实际流程建模，保存公开步骤和输出。"}</p>
                  {presets[config.method.plugin_id]?.requirements ? (
                    <p className="hint">{presets[config.method.plugin_id]?.requirements}</p>
                  ) : null}
                  {compatNote ? <p className="compat-note">{compatNote}</p> : null}
                  {solverSelectionDisabled ? (
                    <p className="compat-note warning">
                      当前求解器与所选方法或建模后端不兼容;请选择可用求解器后再提交。
                    </p>
                  ) : null}
                </div>
                <div id="budget-summary" className="budget-visual" aria-live="polite">
                  <span className="pill">模型请求 ≤{config.budget?.max_llm_attempts ?? "—"}</span>
                  <span className="pill">Token ≤{format(config.budget?.max_total_tokens)}</span>
                  <span className="pill">时间 ≤{format(config.budget?.wall_time_s)} 秒</span>
                  <span className="pill">求解 ≤{config.budget?.max_solver_calls ?? "—"}</span>
                  {(presets[config.method.plugin_id]?.budget.max_llm_attempts || 0) > 4 ? (
                    <p className="hint">此方法真实请求与费用显著更高。</p>
                  ) : null}
                </div>
                <details className="advanced-controls">
                  <summary>高级设置</summary>
                  <div className="field-grid">
                    <label>
                      模型请求次数
                      <input
                        id="attempt-budget"
                        type="number"
                        min="1"
                        value={Number.isNaN(config.budget.max_llm_attempts) ? "" : config.budget.max_llm_attempts}
                        onChange={(event) => setConfig(prior => ({ ...prior, budget: { ...prior.budget, max_llm_attempts: event.target.value === "" ? NaN : Number(event.target.value) } }))}
                      />
                    </label>
                    <label>
                      总 Token
                      <input
                        id="token-budget"
                        type="number"
                        min="1"
                        value={Number.isNaN(config.budget.max_total_tokens) ? "" : config.budget.max_total_tokens}
                        onChange={(event) => setConfig(prior => ({ ...prior, budget: { ...prior.budget, max_total_tokens: event.target.value === "" ? NaN : Number(event.target.value) } }))}
                      />
                    </label>
                    <label>
                      时间（秒）
                      <input
                        id="wall-budget"
                        type="number"
                        min="0.1"
                        step="any"
                        value={Number.isNaN(config.budget.wall_time_s) ? "" : config.budget.wall_time_s}
                        onChange={(event) => setConfig(prior => ({ ...prior, budget: { ...prior.budget, wall_time_s: event.target.value === "" ? NaN : Number(event.target.value) } }))}
                      />
                    </label>
                    <label>
                      求解次数
                      <input
                        id="solver-budget"
                        type="number"
                        min="0"
                        value={Number.isNaN(config.budget.max_solver_calls) ? "" : config.budget.max_solver_calls}
                        onChange={(event) => setConfig(prior => ({ ...prior, budget: { ...prior.budget, max_solver_calls: event.target.value === "" ? NaN : Number(event.target.value) } }))}
                      />
                    </label>
                  </div>
                  <textarea
                    id="config-json"
                    rows={15}
                    aria-label="完整 RunConfig"
                    value={configDraft ?? pretty(config)}
                    onChange={(event) => setConfigDraft(event.target.value)}
                  />
                  {configDraft !== null ? <p className="hint">JSON草稿尚未应用。表单仍使用当前配置。</p> : null}
                  <button
                    id="apply-config"
                    className="secondary"
                    onClick={() => {
                      try {
                        const next = parseConfig(configDraft ?? pretty(config));
                        setConfig(next);
                        setConfigDraft(null);
                        notice("完整配置已应用。");
                      } catch (error) {
                        notice((error as Error).message, true);
                      }
                    }}
                  >
                    应用完整配置
                  </button>
                </details>
                <label className="connectivity-option">
                  <input
                    id="check-connectivity"
                    type="checkbox"
                    checked={checkConnectivity}
                    onChange={(event) => setCheckConnectivity(event.target.checked)}
                  />
                  检查配置时联网测试模型接口
                </label>
                <div className="actions">
                  <button id="doctor" className="secondary" disabled={doctorBusy} onClick={runDoctor}>
                    检查配置
                  </button>
                  <button id="submit" className="primary" disabled={submitting || solverSelectionDisabled} onClick={submitRun}>
                    开始建模 →
                  </button>
                </div>
                <div id="doctor-result" className="doctor-result" hidden={!doctorResult}>
                  {doctorResult ? <Connectivity report={doctorResult} /> : null}
                </div>
              </div>
            </section>
  );
}

function UploadPreview({ preview }: { preview: NonNullable<UploadItem["preview"]> }) {
  return (
    <div className="table-scroll upload-preview">
      <table className="visual-table">
        <thead>
          <tr>
            {preview.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cIndex) => (
                <td key={cIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
