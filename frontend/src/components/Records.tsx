// 数学表述、求解代码与数据视图的结构化渲染,移植自原 visuals.js 的同名逻辑。
import { useState } from "react";
import type { DataPreview } from "../types";
import { assumptionStatusNames, format, parameterValue, senseOperators, status } from "../ui";
import { isBareFormula, MathTex } from "../math";
import { tokenizeLines, type Token } from "../highlight";

interface Term {
  coefficient: number;
  variable_id: string;
}

export function Table({
  rows,
  fields,
}: {
  rows: unknown[];
  fields: [string, (row: any) => string][];
}) {
  return (
    <table className="visual-table">
      <thead>
        <tr>
          {fields.map(([label]) => (
            <th key={label}>{label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {fields.map(([, getter]) => (
              <td key={getter.name || ""}>{getter(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Card({
  title,
  subtitle,
  className = "model-card",
  children,
}: {
  title: string;
  subtitle?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <section className={className}>
      <h3>{title}</h3>
      {subtitle ? <p className="hint">{subtitle}</p> : null}
      {children}
    </section>
  );
}

export function EmptyView({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-view">
      <div className="empty-icon">◇</div>
      <h3>{title}</h3>
      <p className="hint">{text}</p>
    </div>
  );
}

function Expression({
  value,
  names,
  active,
  onSetActive,
}: {
  value: { terms?: Term[]; constant?: number };
  names: Record<string, string>;
  active?: string;
  onSetActive: (id: string) => void;
}) {
  const terms = value?.terms || [];
  return (
    <div className="math-expression">
      {value?.constant || !terms.length ? <span>{format(value?.constant || 0)}</span> : null}
      {terms.map((term, index) => (
        <span key={term.variable_id + index}>
          <span className="math-operator">
            {term.coefficient < 0 ? " − " : index || value?.constant ? " + " : ""}
          </span>
          {Math.abs(term.coefficient) !== 1 ? (
            <span className="coefficient">{format(Math.abs(term.coefficient))} </span>
          ) : null}
          <button
            type="button"
            className={"math-variable" + (term.variable_id === active ? " highlight" : "")}
            data-variable={term.variable_id}
            onClick={() => onSetActive(term.variable_id)}
          >
            {names[term.variable_id] || term.variable_id}
          </button>
        </span>
      ))}
    </div>
  );
}

function RequirementLinks({
  ids,
  requirements,
}: {
  ids?: string[];
  requirements: { id: string; text: string }[];
}) {
  if (!ids?.length) return null;
  return (
    <div className="requirement-sources">
      <span className="source-caption">来源需求</span>
      {ids.map((id) => (
        <details key={id} className="requirement-link">
          <summary className="source-tag">{id}</summary>
          <p className="requirement-text">
            {requirements.find((item) => item.id === id)?.text || "原问题未声明此需求。"}
          </p>
        </details>
      ))}
    </div>
  );
}

function ModelNotes({
  metadata,
  ir,
  relations,
  requirements,
}: {
  metadata: any;
  ir: any;
  relations: { label: string; ids: string[] }[];
  requirements: { id: string; text: string }[];
}) {
  const assumptions: any[] = metadata?.assumptions || ir?.assumptions || [];
  const initiallyOpen = Boolean(assumptions.length || metadata?.warnings?.length);
  return (
    <>
      <details
        className="model-card model-notes"
        ref={(el) => {
          if (el && initiallyOpen) el.open = true;
        }}
      >
        <summary>
          模型声明 · {assumptions.length} 条假设 / {metadata?.warnings?.length || 0} 条警告
        </summary>
        <h4>模型假设</h4>
        {assumptions.length ? (
          <Table
            rows={assumptions}
            fields={[
              ["假设", (item) => item?.text || parameterValue(item)],
              ["状态", (item) => assumptionStatusNames[item?.status] || "未记录确认状态"],
              ["来源", (item) => item?.origin || "未记录来源"],
            ]}
          />
        ) : (
          <p className="hint">该版本未记录模型假设。</p>
        )}
        <h4>模型警告</h4>
        {metadata?.warnings?.length ? (
          metadata.warnings.map((warning: unknown, index: number) => (
            <p className="model-warning" key={index}>
              {warning === "public_reflection_exhausted"
                ? "公开检查的修正已达到次数上限。"
                : parameterValue(warning)}
            </p>
          ))
        ) : (
          <p className="hint">该版本未记录模型警告。</p>
        )}
      </details>
      <Coverage metadata={metadata} relations={relations} requirements={requirements} />
    </>
  );
}

function Coverage({
  metadata,
  relations,
  requirements,
}: {
  metadata: any;
  relations: { label: string; ids: string[] }[];
  requirements: { id: string; text: string }[];
}) {
  const ids = [
    ...new Set([
      ...requirements.map((item) => item.id),
      ...relations.flatMap((item) => item.ids),
    ]),
  ];
  if (!ids.length && !metadata?.requirement_traces?.length) return null;
  return (
    <details className="model-card model-coverage">
      <summary>需求关联 · {ids.length} 条规则</summary>
      <p className="hint">这是方法声明的关联，独立检查见求解结果。</p>
      {ids.length ? (
        <Table
          rows={ids}
          fields={[
            ["需求", (id) => id],
            [
              "原始规则",
              (id) =>
                requirements.find((item) => item.id === id)?.text || "原问题未声明此需求。",
            ],
            [
              "模型条目",
              (id) =>
                relations
                  .filter((item) => item.ids.includes(id))
                  .map((item) => item.label)
                  .join(" · ") || "未记录关联",
            ],
          ]}
        />
      ) : (
        <p className="hint">原问题未提供结构化需求 ID，可依据原描述核对模型。</p>
      )}
      {metadata?.requirement_traces?.length ? (
        <details className="recorded-traces">
          <summary>方法保存的其他需求映射</summary>
          {metadata.requirement_traces.map((trace: unknown, index: number) => (
            <p className="requirement-text" key={index}>
              {parameterValue(trace)}
            </p>
          ))}
        </details>
      ) : null}
    </details>
  );
}

function HighlightedCode({ code }: { code: string }) {
  const lines = tokenizeLines(code);
  return (
    <div className="code-lines">
      {lines.map((tokens, index) => (
        <div className="code-line" key={index}>
          <span className="line-number">{index + 1}</span>
          <code>
            {tokens.map((token: Token, position: number) => (
              <span className={"tok-" + token.type} key={position}>
                {token.text}
              </span>
            ))}
            {!tokens.length ? " " : null}
          </code>
        </div>
      ))}
    </div>
  );
}

function CodeView({ value }: { value: any }) {
  const [copied, setCopied] = useState("");
  const source = typeof value === "string" ? value : value?.source;
  if (!source)
    return (
      <EmptyView title="求解实现正在生成" text="生成完成后会在这里展示可读代码。" />
    );
  const linesRef = { current: null as HTMLDivElement | null };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(source);
      setCopied("已复制");
    } catch {
      const node = linesRef.current;
      if (node) {
        const range = document.createRange();
        range.selectNodeContents(node);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
      }
      setCopied("代码已选中");
    }
  };
  return (
    <>
      <div className="code-toolbar">
        <span className="pill">Python · 求解实现</span>
        <button className="secondary" onClick={copy}>
          {copied || "复制代码"}
        </button>
      </div>
      <div ref={(el) => (linesRef.current = el)}>
        <HighlightedCode code={source} />
      </div>
    </>
  );
}

const entries = (items: any): any[] =>
  Array.isArray(items)
    ? items
    : Object.entries(items || {}).map(([id, item]) => ({ id, ...(item as object) }));

export function FormulationView({ value, contents }: { value: any; contents: Record<string, any> }) {
  const [active, setActive] = useState<string>();
  const records = Object.entries(contents || {});
  const document = value?.formulation_ref
    ? records.find(([, item]) => item?.formulation_id === value.formulation_ref.artifact_id)?.[1]
    : value;
  const metadata = Object.hasOwn(value || {}, "formulation_ref")
    ? value
    : records
        .filter(
          ([, item]) =>
            document?.formulation_id && item?.formulation_ref?.artifact_id === document.formulation_id,
        )
        .sort(
          ([left], [right]) =>
            Number(right.endsWith("/artifact.json")) - Number(left.endsWith("/artifact.json")),
        )[0]?.[1];
  const requirements = contents?.["public-problem.json"]?.requirements || [];
  const source = document?.representation || {};
  const representation = source.state || source;
  const ir =
    (!Object.hasOwn(value || {}, "formulation_ref") || Boolean(value.formulation_ref)) &&
    !source.state &&
    (document?.objective?.expression
      ? document
      : records.find(
          ([name, data]) => /model-ir|structured-ir|supplied-ir/.test(name) && data?.objective?.expression,
        )?.[1]);
  const names = Object.fromEntries(
    (ir?.variables || []).map((item: any) => [item.id, item.name || item.id]),
  );
  const variables = ir?.variables || entries(representation.variables);
  const objective = representation.objective;
  if (!objective && !variables.length && !representation.constraints) {
    if (source.state) {
      const parameters = entries(representation.parameters);
      return (
        <Card title="问题与参数" subtitle="此时尚未形成完整的数学表述。">
          <p className="problem-text">{representation.description || ""}</p>
          {parameters.length ? (
            <Table
              rows={parameters}
              fields={[
                ["参数", (r) => r.id],
                ["定义", (r) => r.definition || r.description || "—"],
              ]}
            />
          ) : null}
        </Card>
      );
    }
    return (
      <>
        <EmptyView
          title="这一步没有独立的数学表述"
          text="可以继续查看求解代码和方法过程。不同方法会提供不同形式的建模产物。"
        />
        {metadata ? <ModelNotes metadata={metadata} ir={null} relations={[]} requirements={requirements} /> : null}
      </>
    );
  }
  const relations: { label: string; ids: string[] }[] = [];
  const sense = objective?.sense || ir?.objective?.sense;
  const goalIds = ir?.objective?.requirement_ids ?? objective?.requirement_ids ?? [];
  relations.push({ label: "目标函数", ids: goalIds });
  const restrictions = ir?.constraints || representation.constraints || [];
  return (
    <>
      <section className="model-card objective-card">
        <h3>优化目标</h3>
        <p className="hint">
          {isBareFormula(objective?.description) && (objective?.expression_text || objective?.formulation)
            ? "目标函数"
            : objective?.description || "模型要达到的目标"}
        </p>
        <span className="pill">
          {sense === "min" ? "最小化 MIN" : sense === "max" ? "最大化 MAX" : "目标函数"}
        </span>
        {ir?.objective?.expression ? (
          <Expression value={ir.objective.expression} names={names} active={active} onSetActive={setActive} />
        ) : objective?.expression_text || objective?.formulation || isBareFormula(objective?.description) ? (
          <div className="math-expression">
            <MathTex
              text={
                objective?.expression_text ||
                objective?.formulation ||
                (isBareFormula(objective?.description) ? objective.description : "")
              }
              display
            />
          </div>
        ) : (
          <p className="hint">数学目标表达式尚未形成。</p>
        )}
        <RequirementLinks ids={goalIds} requirements={requirements} />
      </section>
      {variables.length || !source.state ? (
        <section className="model-card variables-card">
          <h3>决策变量</h3>
            {variables.map((item: any) => {
            const domain =
              ({
                integer: "整数 ℤ",
                real: "实数 ℝ",
                continuous: "连续变量 ℝ",
                binary: "0 / 1",
              } as Record<string, string>)[item.domain || item.type] ||
              item.domain ||
              item.type ||
              "方法未声明域";
            relations.push({ label: "变量 " + (item.name || item.id), ids: item.requirement_ids || [] });
            return (
              <div key={item.id || item.name}>
                <button
                  type="button"
                  className={"variable-card" + ((item.id || item.name) === active ? " highlight" : "")}
                  data-variable={item.id || item.name}
                  onClick={() => setActive(item.id || item.name)}
                >
                  <strong className="variable-symbol">{item.name || item.id}</strong>
                  <span>{item.description || item.definition || ""}</span>
                  <span className="pill muted">
                    {domain}
                    {item.lower_bound != null ? " · ≥ " + format(item.lower_bound) : ""}
                    {item.upper_bound != null ? " · ≤ " + format(item.upper_bound) : ""}
                  </span>
                </button>
                <RequirementLinks ids={item.requirement_ids} requirements={requirements} />
              </div>
            );
          })}
        </section>
      ) : null}
      {representation.constraints || ir?.constraints || !source.state ? (
        <section className="model-card constraints-card">
          <h3>约束条件</h3>
            {restrictions.map((item: any, index: number) => {
            relations.push({
              label: "约束 " + (item.id || index + 1),
              ids: item.requirement_ids || [],
            });
            return (
              <div className="constraint-row" key={item.id || index}>
                <span className="constraint-number">{String(index + 1).padStart(2, "0")}</span>
                <div className="constraint-content">
                  <strong>
                    {/* description 被方法写成裸公式时只保留编号标题,公式由下方数学行渲染,避免显示两遍 */}
                    {isBareFormula(item.description) && (item.expression_text || item.formulation)
                      ? item.id || "约束 " + (index + 1)
                      : item.description || item.id || "约束 " + (index + 1)}
                  </strong>
                  {item.expression ? (
                    <div className="math-expression">
                      <Expression value={item.expression} names={names} active={active} onSetActive={setActive} />
                      <span className="math-bound">
                        {" "}
                        {senseOperators[item.sense] || item.sense || ""} {format(item.rhs)}
                      </span>
                    </div>
                  ) : (
                    <div className="math-expression">
                      <MathTex
                        text={
                          item.expression_text ||
                          item.formulation ||
                          (isBareFormula(item.description) ? item.description : "")
                        }
                      />
                    </div>
                  )}
                  <RequirementLinks ids={item.requirement_ids} requirements={requirements} />
                </div>
              </div>
            );
          })}
          {!restrictions.length ? <p className="hint">当前表述没有列出约束。</p> : null}
        </section>
      ) : null}
      {(representation.sets || []).length ? (
        <Card title="集合与索引">
          {(representation.sets || []).map((item: any) => (
            <div className="set-row" key={item.id}>
              <code>{item.id}</code>
              <span>{item.description || ""}</span>
              <span className="set-elements">{(item.elements || []).join(" · ")}</span>
            </div>
          ))}
        </Card>
      ) : null}
      {entries(representation.parameters).length ? (
        <Card title="参数与数据">
          <Table
            rows={entries(representation.parameters)}
            fields={[
              ["参数", (r) => r.id],
              ["含义", (r) => r.description || r.definition || "—"],
              [
                "值或来源",
                (r) =>
                  r.value !== undefined
                    ? parameterValue(r.value)
                    : r.source
                      ? r.source.data_id +
                        " · " +
                        (r.source.column || r.source.columns?.join(", ") || "数据绑定")
                      : "未提供",
              ],
            ]}
          />
        </Card>
      ) : null}
      {!source.state ? (
        <ModelNotes metadata={metadata} ir={ir} relations={relations} requirements={requirements} />
      ) : null}
    </>
  );
}

function DataView({ contents, dataPreviews }: { contents: Record<string, any>; dataPreviews: Record<string, DataPreview> }) {
  const problem = contents["public-problem.json"];
  if (!problem) return <EmptyView title="问题与数据正在准备" text="问题读取完成后会在这里展示。" />;
  return (
    <>
      <Card title="你的问题">
        <p className="problem-text">{problem.description}</p>
      </Card>
      {(
        [
          ["输入规则", problem.requirements],
          ["输入假设", problem.assumptions],
        ] as [string, any[]][]
      ).map(([title, rows]) =>
        rows?.length ? (
          <Card title={title} key={title}>
            <Table
              rows={rows}
              fields={[
                ["标识", (item) => item.id],
                ["内容", (item) => item.text],
                ["状态", (item) => assumptionStatusNames[item.status] || "问题规则"],
              ]}
            />
          </Card>
        ) : null,
      )}
      {(problem.data_refs || []).map((ref: any) => {
        const preview = dataPreviews[ref.data_id];
        const view = preview?.metadata;
        return (
          <section className="model-card" key={ref.data_id}>
            <h3>{ref.data_id}</h3>
            <p className="hint">{ref.format.toUpperCase() + " · 原始数据绑定"}</p>
            <div className="data-view-meta">
              <span className="pill">
                {view?.complete
                  ? "完整模型数据视图"
                  : view?.kind === "summary"
                    ? "仅结构摘要"
                    : view
                      ? "部分模型数据视图"
                      : "尚无模型数据视图"}
              </span>
              {view?.total_rows !== null && view?.total_rows !== undefined ? (
                <span className="pill">原始 {format(view.total_rows)} 行 · 视图 {format(view.rows)} 行</span>
              ) : null}
            </div>
            {preview ? (
              <>
                <Table
                  rows={preview.rows}
                  fields={preview.columns.map((column, index) => [
                    column,
                    (row: string[]) => row[index],
                  ])}
                />
                <p className="hint">
                  {preview.display_truncated
                    ? `页面显示 ${preview.rows.length} / ${preview.total_items} 行或字段，最多16列，长文本显示前256字符。完整已保存视图随公共导出提供。`
                    : "显示已保存视图的全部内容。"}
                </p>
              </>
            ) : (
              <p className="hint">原始数据已绑定；模型数据视图尚未保存。</p>
            )}
            <details className="data-provenance">
              <summary>数据版本与来源</summary>
              <Table
                rows={[
                  ["原始数据 SHA-256", ref.sha256 || "未提供"],
                  ["模型视图 SHA-256", view?.sha256 || "未提供"],
                  ["模型视图字节", view ? format(view.size_bytes) : "未提供"],
                ]}
                fields={[
                  ["项目", (row) => row[0]],
                  ["值", (row) => row[1]],
                ]}
              />
            </details>
          </section>
        );
      })}
      {!problem.data_refs?.length ? (
        <p className="hint">此问题没有附加数据文件，建模输入来自问题描述与明确规则。</p>
      ) : null}
    </>
  );
}

export function Records({
  value,
  tab,
  contents,
  dataPreviews = {},
}: {
  value: any;
  tab: string;
  contents: Record<string, any>;
  dataPreviews?: Record<string, DataPreview>;
}) {
  if (tab === "formulation") return <FormulationView value={value} contents={contents} />;
  if (tab === "code") return <CodeView value={value} />;
  if (tab === "data") return <DataView contents={contents} dataPreviews={dataPreviews} />;
  if (Array.isArray(value))
    return (
      <Card title="运行记录">
        <Table
          rows={value.slice(-30)}
          fields={[
            ["顺序", (r) => String(r.sequence_no ?? "—")],
            ["事件", (r) => r.kind || "记录"],
            ["状态", (r) => statusOf(r)],
          ]}
        />
      </Card>
    );
  return <EmptyView title="此阶段暂无内容" text="完成的公开产物会出现在这里。" />;
}

function statusOf(r: any) {
  return status(r.status || r.method_event?.status);
}
