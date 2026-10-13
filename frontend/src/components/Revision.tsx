// 人工修订:问题/代码/严格IR 三种编辑范围;字段规格、数值转换与校验同源。
import { format } from "../ui";

type Path = (string | number)[];

export interface FieldSpec {
  label: string;
  path: Path;
  kind: "text" | "textarea" | "number" | "select";
  choices?: [string, string][];
  rows?: number;
  nullable?: boolean;
  maxLength?: number;
  placeholder?: string;
  spellcheck?: boolean;
  className?: string;
}

const getPath = (source: any, path: Path): any => {
  let target = source;
  for (const key of path) target = target?.[key];
  return target;
};

const setPath = (target: any, path: Path, value: any) => {
  let cursor = target;
  for (const key of path.slice(0, -1)) cursor = cursor[key];
  cursor[path.at(-1) as string | number] = value;
};

const keyOf = (path: Path) => path.join(".");

export function synchronizeFormulation(value: any) {
  const ir = value.structured_ir;
  ir.problem_type = ir.variables.every((item: any) => item.domain === "continuous") ? "lp" : "milp";
  if (value.formulation?.representation_kind !== "five_element") return;
  const text = (expression: any) =>
    [expression.constant, ...expression.terms.map((term: any) => `${term.coefficient}*${term.variable_id}`)].join(
      " + ",
    );
  const representation = value.formulation.representation;
  representation.variables = ir.variables.map(
    ({ id, domain, lower_bound, upper_bound, requirement_ids }: any) => ({
      id,
      index_sets: [],
      domain,
      lower_bound,
      upper_bound,
      requirement_ids,
    }),
  );
  representation.objective = {
    sense: ir.objective.sense,
    expression_text: text(ir.objective.expression),
    requirement_ids: ir.objective.requirement_ids,
  };
  representation.constraints = ir.constraints.map((item: any) => ({
    id: item.id,
    expression_text: `${text(item.expression)} ${({ le: "<=", ge: ">=", eq: "=" } as Record<string, string>)[item.sense]} ${item.rhs}`,
    requirement_ids: item.requirement_ids,
  }));
}

// 与原表单一致的数值语义:数字字段空值仅在可空边界处为 null,其余为 NaN 并被校验阻止。
export function buildDoc(base: any, overrides: Record<string, string>, template: any): any {
  const value = structuredClone(base);
  for (const spec of fieldSpecs(base)) {
    const raw = overrides[keyOf(spec.path)];
    if (raw === undefined) continue;
    if (spec.kind === "number")
      setPath(value, spec.path, raw === "" ? (spec.nullable ? null : NaN) : Number(raw));
    else setPath(value, spec.path, raw);
  }
  if (
    value.operation === "formulation" &&
    value.structured_ir &&
    JSON.stringify(value.structured_ir) !== JSON.stringify(template?.structured_ir)
  )
    synchronizeFormulation(value);
  return value;
}

export function fieldSpecs(base: any): FieldSpec[] {
  const specs: FieldSpec[] = [];
  const ir = base.structured_ir;
  if (base.operation === "problem") {
    specs.push({ label: "新版本标识", path: ["problem", "revision"], kind: "text" });
    specs.push({ label: "完整问题描述", path: ["problem", "description"], kind: "textarea", rows: 7 });
    for (const group of ["requirements", "assumptions"] as const)
      (base.problem[group] || []).forEach((item: any, index: number) =>
        specs.push({
          label: item.id,
          path: ["problem", group, index, "text"],
          kind: "textarea",
          rows: 2,
        }),
      );
  } else if (base.operation === "code") {
    specs.push({
      label: "求解代码",
      path: ["code", "source"],
      kind: "textarea",
      rows: 18,
      className: "source-editor",
      spellcheck: false,
    });
  } else if (ir) {
    const names = Object.fromEntries(ir.variables.map((item: any) => [item.id, item.name || item.id]));
    specs.push({
      label: "优化方向",
      path: ["structured_ir", "objective", "sense"],
      kind: "select",
      choices: [
        ["max", "最大化"],
        ["min", "最小化"],
      ],
    });
    specs.push({
      label: "目标 · 常数",
      path: ["structured_ir", "objective", "expression", "constant"],
      kind: "number",
    });
    ir.objective.expression.terms.forEach((term: any, index: number) =>
      specs.push({
        label: "目标 · " + names[term.variable_id] + " 系数",
        path: ["structured_ir", "objective", "expression", "terms", index, "coefficient"],
        kind: "number",
      }),
    );
    ir.variables.forEach((item: any, index: number) => {
      specs.push({
        label: item.id + " · 类型",
        path: ["structured_ir", "variables", index, "domain"],
        kind: "select",
        choices: [
          ["continuous", "连续"],
          ["integer", "整数"],
          ["binary", "0 / 1"],
        ],
      });
      for (const [key, text] of [
        ["lower_bound", "下界"],
        ["upper_bound", "上界"],
      ] as [string, string][])
        specs.push({
          label: item.id + " · " + text,
          path: ["structured_ir", "variables", index, key],
          kind: "number",
          nullable: true,
        });
    });
    ir.constraints.forEach((item: any, index: number) => {
      specs.push({
        label: item.id + " · 常数",
        path: ["structured_ir", "constraints", index, "expression", "constant"],
        kind: "number",
      });
      item.expression.terms.forEach((term: any, tIndex: number) =>
        specs.push({
          label: item.id + " · " + names[term.variable_id] + " 系数",
          path: ["structured_ir", "constraints", index, "expression", "terms", tIndex, "coefficient"],
          kind: "number",
        }),
      );
      specs.push({
        label: item.id + " · 关系",
        path: ["structured_ir", "constraints", index, "sense"],
        kind: "select",
        choices: [
          ["le", "≤"],
          ["ge", "≥"],
          ["eq", "="],
        ],
      });
      specs.push({
        label: item.id + " · 右侧值",
        path: ["structured_ir", "constraints", index, "rhs"],
        kind: "number",
      });
    });
  }
  specs.push({
    label: "修改原因",
    path: ["reason"],
    kind: "textarea",
    rows: 2,
    placeholder: "说明你希望改变的行为或要修正的问题。",
    maxLength: 4096,
  });
  for (const [key, label] of [
    ["max_llm_attempts", "模型请求总上限"],
    ["max_total_tokens", "Token 总上限"],
    ["max_solver_calls", "求解次数总上限"],
    ["max_candidates", "候选总上限"],
    ["wall_time_s", "新运行时间上限（秒）"],
  ] as [string, string][])
    specs.push({ label, path: ["budget", key], kind: "number" });
  return specs;
}

export function validateRevision(document: any, template: any, consumed: any): string | null {
  const invalid = (value: unknown) => value == null || typeof value !== "number" || !Number.isFinite(value);
  const walk = (node: any): unknown[] =>
    node == null
      ? []
      : Array.isArray(node)
        ? node.flatMap(walk)
        : typeof node === "object"
          ? Object.entries(node).flatMap(([key, item]) =>
              /constant|coefficient|rhs/.test(key) && key !== "constant_term" ? [item] : walk(item),
            )
          : [];
  if (walk(document.structured_ir).some(invalid))
    return "请填写有效的数值。只有变量边界可以留空。";
  if (["max_llm_attempts", "max_total_tokens", "max_solver_calls", "max_candidates", "wall_time_s"].some((key) =>
    invalid(document.budget[key]),
  ))
    return "请填写有效的数值。只有变量边界可以留空。";
  if (!document.reason.trim()) return "请填写修改原因。";
  if (
    document.operation === "problem" &&
    (!document.problem.description.trim() ||
      !document.problem.revision.trim() ||
      document.problem.revision === template.problem.revision)
  )
    return "问题修订需要完整描述和新的版本标识。";
  if (document.operation === "code" && !document.code.source.trim()) return "求解代码不能留空。";
  if (document.budget.max_candidates <= (consumed?.candidates || 0))
    return "候选总上限需要覆盖已有候选和本次新增候选。";
  return null;
}

export function RevisionFields({
  base,
  overrides,
  onInput,
  onRemoveConstraint,
  onAddConstraint,
  ledger,
}: {
  base: any;
  overrides: Record<string, string>;
  onInput: (key: string, value: string) => void;
  onRemoveConstraint: (index: number) => void;
  onAddConstraint: () => void;
  ledger: any;
}) {
  const specs = fieldSpecs(base);
  const ir = base.structured_ir;
  const reason = specs.find((spec) => keyOf(spec.path) === "reason")!;
  const consumed = ledger || {};
  const render = (spec: FieldSpec) => {
    const key = keyOf(spec.path);
    const raw = overrides[key] ?? String(getPath(base, spec.path) ?? "");
    const common = { value: raw, onChange: (event: any) => onInput(key, event.target.value) };
    if (spec.kind === "textarea")
      return (
        <label className={"revision-field" + (spec.className ? " " + spec.className : "")} key={key}>
          {spec.label}
          <textarea
            rows={spec.rows}
            maxLength={spec.maxLength}
            placeholder={spec.placeholder}
            spellCheck={spec.spellcheck ?? true}
            {...common}
          />
        </label>
      );
    if (spec.kind === "number")
      return (
        <label className="revision-field" key={key}>
          {spec.label}
          <input type="number" min={0} step="any" placeholder={spec.nullable ? "无界" : undefined} {...common} />
        </label>
      );
    if (spec.kind === "select")
      return (
        <label className="revision-field" key={key}>
          {spec.label}
          <select {...common}>
            {spec.choices?.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      );
    return (
      <label className="revision-field" key={key}>
        {spec.label}
        <input {...common} />
      </label>
    );
  };
  const isBudget = (spec: FieldSpec) => spec.path[0] === "budget";
  return (
    <div id="revision-fields">
      <p className="revision-summary">
        {base.operation === "problem"
          ? "确认后将重新调用所选模型建模。原数据绑定不变，新版本继承已有消耗。"
          : "确认后使用编辑后的建模输出重新求解，不新增模型请求。原问题与数据保留。"}
      </p>
      {base.operation === "problem" ? (
        specs.filter((spec) => spec.path[0] === "problem" && !isBudget(spec) && spec !== reason).map(render)
      ) : base.operation === "code" ? (
        specs.filter((spec) => spec.path[0] === "code").map(render)
      ) : ir ? (
        <>
          <p className="hint">编辑实际用于求解的线性模型；数值边界留空表示无界。</p>
          <div className="revision-model-group">
            <h4>优化目标</h4>
            <div className="field-grid">
              {specs
                .filter((spec) => spec.path[0] === "structured_ir" && spec.path[1] === "objective")
                .map(render)}
            </div>
          </div>
          {ir.variables.map((item: any, index: number) => (
            <div className="revision-model-group" key={item.id}>
              <h4>{"变量 · " + (item.name || item.id)}</h4>
              <div className="field-grid">
                {specs
                  .filter(
                    (spec) =>
                      spec.path[0] === "structured_ir" &&
                      spec.path[1] === "variables" &&
                      spec.path[2] === index,
                  )
                  .map(render)}
              </div>
            </div>
          ))}
          {ir.constraints.map((item: any, index: number) => (
            <div className="revision-model-group" key={item.id}>
              <h4>
                {"约束 · " + item.id}
                <button
                  className="secondary"
                  type="button"
                  aria-label={"移除约束 " + item.id}
                  onClick={() => onRemoveConstraint(index)}
                >
                  移除约束
                </button>
              </h4>
              <div className="field-grid">
                {specs
                  .filter(
                    (spec) =>
                      spec.path[0] === "structured_ir" &&
                      spec.path[2] === "constraints" &&
                      spec.path[3] === index,
                  )
                  .map(render)}
              </div>
            </div>
          ))}
          <button className="secondary" type="button" onClick={onAddConstraint}>
            ＋ 添加约束
          </button>
          <p className="hint">修改保存为人工辅助新版本。</p>
        </>
      ) : null}
      {render(reason)}
      <p className="hint">
        {"已累计：模型请求 " +
          format(consumed.llm_attempts) +
          " 次 · 求解 " +
          format(consumed.solver_calls) +
          " 次 · 候选 " +
          format(consumed.candidates) +
          " 个 · 已知 Token " +
          format(consumed.known_total_tokens ?? consumed.total_tokens) +
          "。下方是包含这些消耗的总上限。"}
      </p>
      <div className="field-grid revision-budget">{specs.filter(isBudget).map(render)}</div>
    </div>
  );
}
