"use strict";
const UI = (() => {
  const statusNames = {
    running: "进行中",
    queued: "排队中",
    completed: "已完成",
    failed: "未完成",
    cancelled: "已取消",
    artifact_ready: "模型已生成",
    needs_input: "需要补充信息",
    unresolved: "等待确认",
    available: "已生成",
    pending: "等待中",
    not_available: "未提供",
    optimal: "候选最优",
    infeasible: "候选不可行",
    unbounded: "候选无界",
    proposed: "已生成",
    executed: "已执行",
    invalid: "未通过检查",
    selected: "最终选择",
  };
  const methodNames = {
    "llm4om.methods.direct": "Direct · 直接建模",
    "llm4om.methods.optimus_inline": "OptiMUS · 分步建模",
    "llm4om.methods.optimus": "OptiMUS · 参数化输入",
    "llm4om.methods.coe": "CoE · 专家协作",
    "llm4om.methods.feedback_repair": "反馈修正",
    "llm4om.methods.assisted": "人工辅助修订",
  };
  const roles = {
    conductor: "选择参与专家",
    reducer: "汇总专家方案",
    public_evaluator: "生成公开检查输入",
    "Terminology Interpreter": "解释问题术语",
    "Parameter Extractor": "提取参数与决策",
    "Modeling Expert": "数学建模讨论",
    "Programming Example Provider": "构建代码示例",
    "Programming Expert": "生成求解代码",
    "Modeling Knowledge Supplement Expert": "补充建模方案",
    "Code Reviewer": "审查与修正代码",
  };
  const node = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const format = (value) =>
    typeof value === "number"
      ? value.toLocaleString("zh-CN", { maximumFractionDigits: 6 })
      : (value ?? "—");
  const status = (value) => statusNames[value] || value || "等待中";
  const shortMethod = (value) =>
    methodNames[value] || value?.split(".").at(-1) || "建模方法";
  const parameterValue = (value) =>
    Array.isArray(value)
      ? value.map(parameterValue).join(" · ")
      : value && typeof value === "object"
        ? Object.entries(value)
            .map(([key, item]) => key + " = " + parameterValue(item))
            .join("; ")
        : format(value);
  const artifactLabel = (name) =>
    ({
      "formulation.json": "数学表述",
      "structured-ir.json": "实例化模型",
      "formulation-snapshot.json": "表述来源",
      "model.py": "求解源码",
      "code-artifact.json": "代码来源",
      "candidate.json": "候选状态",
      "candidate-snapshot.json": "初始候选",
      "assessment.json": "公开检查",
      "candidate-selection.json": "最终选择",
      "formulation-changes.json": "表述变化",
      "repair-state.json": "修正过程",
      "evaluation.json": "独立评估",
      "public-problem.json": "原始问题与规则",
      "data-views.json": "模型数据视图",
      "dataset-manifest.json": "原始数据来源",
      "state_1_params.json": "问题与参数",
      "state_2_objective.json": "优化目标初稿",
      "state_3_constraints.json": "约束识别",
      "state_4_constraints_modeled.json": "约束数学表述",
      "state_5_objective_modeled.json": "完整数学表述",
      "state_6_code.json": "数学表述与代码片段",
    })[name.split("/").at(-1)] || name;
  function artifactKey(snapshot, reference) {
    if (reference?.namespace !== "run_public") return;
    const current = (
      snapshot.bundle
        ? Object.values(snapshot.bundle.public_projections || {})
        : snapshot.artifacts || []
    ).find((item) => item.relative_path === reference.relative_path);
    if (
      current?.namespace !== reference.namespace ||
      current?.sha256 !== reference.sha256 ||
      current?.size_bytes !== reference.size_bytes
    )
      return;
    return Object.keys(snapshot.contents || {})
      .sort((a, b) => b.length - a.length)
      .find(
        (name) =>
          reference.relative_path === name ||
          reference.relative_path.endsWith("/" + name),
      );
  }
  const mathText = (value) =>
    String(value || "")
      .replace(/\\leq\b/g, "≤")
      .replace(/\\geq\b/g, "≥")
      .replace(/\\cdot\b/g, "·")
      .replace(/\\times\b/g, "×")
      .replace(/\\sum\b/g, "∑")
      .replace(/\\forall\b/g, "∀")
      .replace(/\\in\b/g, "∈")
      .replace(/\\mathbb\{R\}/g, "ℝ")
      .replace(/\\mathbb\{Z\}/g, "ℤ")
      .replace(/^\$+|\$+$/g, "");
  function roleLabel(role) {
    if (roles[role]) return roles[role];
    if (/debug/.test(role)) return "检查与调试代码";
    if (/code/.test(role)) return "生成求解实现";
    if (/objective.*formulation/.test(role)) return "形成目标函数";
    if (/constraint.*formulation/.test(role)) return "形成约束表述";
    if (/objective/.test(role)) return "解析优化目标";
    if (/constraint/.test(role)) return "识别业务约束";
    return role;
  }
  function card(title, subtitle) {
    const el = node("section", "model-card");
    el.append(node("h3", "", title));
    if (subtitle) el.append(node("p", "hint", subtitle));
    return el;
  }
  function empty(container, title, text) {
    container.replaceChildren();
    const box = node("div", "empty-view");
    box.append(
      node("div", "empty-icon", "◇"),
      node("h3", "", title),
      node("p", "hint", text),
    );
    container.append(box);
  }
  function list(container, rows, fields) {
    const table = node("table", "visual-table"),
      head = node("tr");
    for (const [label] of fields) head.append(node("th", "", label));
    const thead = node("thead");
    thead.append(head);
    table.append(thead);
    const body = node("tbody");
    for (const row of rows) {
      const tr = node("tr");
      for (const [, getter] of fields) tr.append(node("td", "", getter(row)));
      body.append(tr);
    }
    table.append(body);
    container.append(table);
  }
  function expression(value, names, active) {
    const row = node("div", "math-expression");
    const terms = value?.terms || [];
    if (value?.constant || !terms.length)
      row.append(node("span", "", format(value?.constant || 0)));
    terms.forEach((term, index) => {
      const coefficient = term.coefficient;
      row.append(
        node(
          "span",
          "math-operator",
          coefficient < 0 ? " − " : index || value?.constant ? " + " : "",
        ),
      );
      if (Math.abs(coefficient) !== 1)
        row.append(
          node("span", "coefficient", format(Math.abs(coefficient)) + " "),
        );
      const variable = node(
        "button",
        "math-variable",
        names[term.variable_id] || term.variable_id,
      );
      variable.type = "button";
      variable.dataset.variable = term.variable_id;
      variable.classList.toggle("highlight", term.variable_id === active);
      variable.onclick = () =>
        document
          .querySelectorAll("[data-variable]")
          .forEach((el) =>
            el.classList.toggle(
              "highlight",
              el.dataset.variable === term.variable_id,
            ),
          );
      row.append(variable);
    });
    return row;
  }
  function requirementLinks(container, ids, requirements) {
    if (!ids?.length) return;
    const group = node("div", "requirement-sources");
    group.append(node("span", "source-caption", "来源需求"));
    for (const id of ids) {
      const link = node("details", "requirement-link");
      link.append(node("summary", "source-tag", id));
      link.append(
        node(
          "p",
          "requirement-text",
          requirements.find((item) => item.id === id)?.text ||
            "原问题未声明此需求。",
        ),
      );
      group.append(link);
    }
    container.append(group);
  }
  function modelNotes(container, metadata, ir, relations, requirements) {
    const assumptions = metadata?.assumptions || ir?.assumptions || [];
    const section = node("details", "model-card model-notes");
    section.open = Boolean(assumptions.length || metadata?.warnings?.length);
    section.append(
      node(
        "summary",
        "",
        "模型声明 · " +
          assumptions.length +
          " 条假设 / " +
          (metadata?.warnings?.length || 0) +
          " 条警告",
      ),
    );
    section.append(node("h4", "", "模型假设"));
    if (assumptions.length)
      list(section, assumptions, [
        ["假设", (item) => item?.text || parameterValue(item)],
        [
          "状态",
          (item) =>
            ({ explicit: "原文声明", proposed: "待确认", confirmed: "已确认" })[
              item?.status
            ] || "未记录确认状态",
        ],
        ["来源", (item) => item?.origin || "未记录来源"],
      ]);
    else section.append(node("p", "hint", "该版本未记录模型假设。"));
    section.append(node("h4", "", "模型警告"));
    if (metadata?.warnings?.length)
      for (const warning of metadata.warnings)
        section.append(
          node(
            "p",
            "model-warning",
            warning === "public_reflection_exhausted"
              ? "公开检查的修正已达到次数上限。"
              : parameterValue(warning),
          ),
        );
    else
      section.append(
        node("p", "hint", "该版本未记录模型警告；这不表示模型已通过全部检查。"),
      );
    container.append(section);
    const ids = new Set([
      ...requirements.map((item) => item.id),
      ...relations.flatMap((item) => item.ids),
    ]);
    if (!ids.size && !metadata?.requirement_traces?.length) return;
    const coverage = node("details", "model-card model-coverage");
    coverage.append(node("summary", "", "需求关联 · " + ids.size + " 条规则"));
    coverage.append(
      node("p", "hint", "这是方法声明的关联，独立检查见求解结果。"),
    );
    if (ids.size)
      list(
        coverage,
        [...ids],
        [
          ["需求", (id) => id],
          [
            "原始规则",
            (id) =>
              requirements.find((item) => item.id === id)?.text ||
              "原问题未声明此需求。",
          ],
          [
            "模型条目",
            (id) =>
              relations
                .filter((item) => item.ids.includes(id))
                .map((item) => item.label)
                .join(" · ") || "未记录关联",
          ],
        ],
      );
    else
      coverage.append(
        node("p", "hint", "原问题未提供结构化需求 ID，可依据原描述核对模型。"),
      );
    if (metadata?.requirement_traces?.length) {
      const traces = node("details", "recorded-traces");
      traces.append(node("summary", "", "方法保存的其他需求映射"));
      for (const trace of metadata.requirement_traces)
        traces.append(node("p", "requirement-text", parameterValue(trace)));
      coverage.append(traces);
    }
    container.append(coverage);
  }
  function formulation(container, value, contents) {
    container.replaceChildren();
    const records = Object.entries(contents || {});
    const document = value?.formulation_ref
      ? records.find(
          ([, item]) =>
            item?.formulation_id === value.formulation_ref.artifact_id,
        )?.[1]
      : value;
    const metadata = Object.hasOwn(value || {}, "formulation_ref")
      ? value
      : records
          .filter(
            ([, item]) =>
              document?.formulation_id &&
              item?.formulation_ref?.artifact_id === document.formulation_id,
          )
          .sort(
            ([left], [right]) =>
              Number(right.endsWith("/artifact.json")) -
              Number(left.endsWith("/artifact.json")),
          )[0]?.[1];
    const requirements = contents?.["public-problem.json"]?.requirements || [];
    const source = document?.representation || {};
    const representation = source.state || source;
    const ir =
      (!Object.hasOwn(value || {}, "formulation_ref") ||
        Boolean(value.formulation_ref)) &&
      !source.state &&
      (document?.objective?.expression
        ? document
        : records.find(
            ([name, data]) =>
              /model-ir|structured-ir|supplied-ir/.test(name) &&
              data?.objective?.expression,
          )?.[1]);
    const names = Object.fromEntries(
      (ir?.variables || []).map((item) => [item.id, item.name || item.id]),
    );
    const entries = (items) =>
      Array.isArray(items)
        ? items
        : Object.entries(items || {}).map(([id, item]) => ({ id, ...item }));
    const variables = ir?.variables || entries(representation.variables);
    const objective = representation.objective;
    if (!objective && !variables.length && !representation.constraints) {
      if (source.state) {
        const section = card("问题与参数", "此时尚未形成完整的数学表述。");
        section.append(
          node("p", "problem-text", representation.description || ""),
        );
        const parameters = entries(representation.parameters);
        if (parameters.length)
          list(section, parameters, [
            ["参数", (r) => r.id],
            ["定义", (r) => r.definition || r.description || "—"],
          ]);
        container.append(section);
        return;
      }
      empty(
        container,
        "这一步没有独立的数学表述",
        "可以继续查看求解代码和方法过程。不同方法会提供不同形式的建模产物。",
      );
      if (metadata) modelNotes(container, metadata, null, [], requirements);
      return;
    }
    const goal = card("优化目标", objective?.description || "模型要达到的目标");
    goal.classList.add("objective-card");
    const sense = objective?.sense || ir?.objective?.sense;
    goal.append(
      node(
        "span",
        "pill",
        sense === "min"
          ? "最小化 MIN"
          : sense === "max"
            ? "最大化 MAX"
            : "目标函数",
      ),
    );
    if (ir?.objective?.expression)
      goal.append(expression(ir.objective.expression, names));
    else if (objective?.expression_text || objective?.formulation)
      goal.append(
        node(
          "div",
          "math-expression",
          mathText(objective?.expression_text || objective?.formulation),
        ),
      );
    else goal.append(node("p", "hint", "数学目标表达式尚未形成。"));
    const goalIds =
      ir?.objective?.requirement_ids ?? objective?.requirement_ids ?? [];
    requirementLinks(goal, goalIds, requirements);
    const relations = [{ label: "目标函数", ids: goalIds }];
    container.append(goal);
    const vars = card(
      "决策变量",
      "点击变量或公式中的符号，查看它在模型中的关联。",
    );
    vars.classList.add("variables-card");
    for (const item of variables) {
      const row = node("button", "variable-card");
      row.type = "button";
      row.dataset.variable = item.id || item.name;
      row.append(
        node("strong", "variable-symbol", item.name || item.id),
        node("span", "", item.description || item.definition || ""),
      );
      const domain =
        {
          integer: "整数 ℤ",
          real: "实数 ℝ",
          continuous: "连续变量 ℝ",
          binary: "0 / 1",
        }[item.domain || item.type] ||
        item.domain ||
        item.type ||
        "方法未声明域";
      row.append(
        node(
          "span",
          "pill muted",
          domain +
            (item.lower_bound != null
              ? " · ≥ " + format(item.lower_bound)
              : "") +
            (item.upper_bound != null
              ? " · ≤ " + format(item.upper_bound)
              : ""),
        ),
      );
      row.onclick = () =>
        document
          .querySelectorAll("[data-variable]")
          .forEach((el) =>
            el.classList.toggle(
              "highlight",
              el.dataset.variable === row.dataset.variable,
            ),
          );
      vars.append(row);
      requirementLinks(vars, item.requirement_ids, requirements);
      relations.push({
        label: "变量 " + (item.name || item.id),
        ids: item.requirement_ids || [],
      });
    }
    if (variables.length || !source.state) container.append(vars);
    const constraints = card("约束条件", "保留模型实际提供的关系与边界。");
    constraints.classList.add("constraints-card");
    const restrictions = ir?.constraints || representation.constraints || [];
    restrictions.forEach((item, index) => {
      const row = node("div", "constraint-row");
      row.append(
        node("span", "constraint-number", String(index + 1).padStart(2, "0")),
      );
      const detail = node("div", "constraint-content");
      detail.append(
        node(
          "strong",
          "",
          item.description || item.id || "约束 " + (index + 1),
        ),
      );
      if (item.expression) {
        const formula = expression(item.expression, names);
        const operator =
          { le: "≤", ge: "≥", eq: "=" }[item.sense] || item.sense || "";
        formula.append(
          node("span", "math-bound", " " + operator + " " + format(item.rhs)),
        );
        detail.append(formula);
      } else
        detail.append(
          node(
            "div",
            "math-expression",
            mathText(item.expression_text || item.formulation || ""),
          ),
        );
      requirementLinks(detail, item.requirement_ids, requirements);
      relations.push({
        label: "约束 " + (item.id || index + 1),
        ids: item.requirement_ids || [],
      });
      row.append(detail);
      constraints.append(row);
    });
    if (!restrictions.length)
      constraints.append(node("p", "hint", "当前表述没有列出约束。"));
    if (representation.constraints || ir?.constraints || !source.state)
      container.append(constraints);
    if (source.state) {
      const fragments = [
        { description: "优化目标", code: objective?.code },
        ...(representation.constraints || []),
      ].filter((item) => typeof item.code === "string" && item.code);
      if (fragments.length) {
        const section = card(
          "已生成的代码片段",
          "这些是当前状态的代码片段。完整程序可在求解代码中查看。",
        );
        for (const fragment of fragments) {
          const block = node("div");
          block.append(node("h4", "", fragment.description || "代码片段"));
          const body = node("div");
          code(body, fragment.code);
          block.append(body);
          section.append(block);
        }
        container.append(section);
      }
    }
    const sets = representation.sets || [];
    if (sets.length) {
      const section = card("集合与索引");
      for (const item of sets) {
        const row = node("div", "set-row");
        row.append(
          node("code", "", item.id),
          node("span", "", item.description || ""),
          node("span", "set-elements", (item.elements || []).join(" · ")),
        );
        section.append(row);
      }
      container.append(section);
    }
    const parameters = entries(representation.parameters);
    if (parameters.length) {
      const section = card("参数与数据");
      list(section, parameters, [
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
                  (r.source.column ||
                    r.source.columns?.join(", ") ||
                    "数据绑定")
                : "未提供",
        ],
      ]);
      container.append(section);
    }
    if (!source.state)
      modelNotes(container, metadata, ir, relations, requirements);
  }
  function code(container, value) {
    container.replaceChildren();
    let source = typeof value === "string" ? value : value?.source;
    if (!source) {
      empty(
        container,
        "代码还在生成",
        "这里将显示可读的求解实现。构建信息可以在原始记录中查看。",
      );
      return;
    }
    const toolbar = node("div", "code-toolbar"),
      copy = node("button", "secondary", "复制代码");
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(source);
        copy.textContent = "已复制";
      } catch {
        const range = document.createRange();
        range.selectNodeContents(container.querySelector(".code-lines"));
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        copy.textContent = "代码已选中";
      }
    };
    toolbar.append(node("span", "pill", "Python · 求解实现"), copy);
    container.append(toolbar);
    const lines = node("div", "code-lines");
    source.split("\n").forEach((text, index) => {
      const line = node("div", "code-line");
      line.append(
        node("span", "line-number", index + 1),
        node("code", "", text || " "),
      );
      lines.append(line);
    });
    container.append(lines);
  }
  function records(container, value, tab, contents, dataPreviews = {}) {
    if (tab === "formulation") return formulation(container, value, contents);
    if (tab === "code") return code(container, value);
    container.replaceChildren();
    if (tab === "data") {
      const problem = contents["public-problem.json"];
      if (problem) {
        const section = card("你的问题");
        section.append(node("p", "problem-text", problem.description));
        container.append(section);
        for (const [title, rows] of [
          ["输入规则", problem.requirements],
          ["输入假设", problem.assumptions],
        ]) {
          if (rows?.length) {
            const section = card(title);
            list(section, rows, [
              ["标识", (item) => item.id],
              ["内容", (item) => item.text],
              [
                "状态",
                (item) =>
                  ({
                    explicit: "原文声明",
                    proposed: "待确认",
                    confirmed: "已确认",
                  })[item.status] || "问题规则",
              ],
            ]);
            container.append(section);
          }
        }
        for (const ref of problem.data_refs || []) {
          const preview = dataPreviews[ref.data_id],
            view = preview?.metadata;
          const file = card(
            ref.data_id,
            ref.format.toUpperCase() + " · 原始数据绑定",
          );
          const scope = node("div", "data-view-meta");
          scope.append(
            node(
              "span",
              "pill",
              view?.complete
                ? "完整模型数据视图"
                : view?.kind === "summary"
                  ? "仅结构摘要"
                  : view
                    ? "部分模型数据视图"
                    : "尚无模型数据视图",
            ),
          );
          if (view?.total_rows !== null && view?.total_rows !== undefined)
            scope.append(
              node(
                "span",
                "pill",
                `原始 ${format(view.total_rows)} 行 · 视图 ${format(view.rows)} 行`,
              ),
            );
          file.append(scope);
          if (preview) {
            list(
              file,
              preview.rows,
              preview.columns.map((column, index) => [
                column,
                (row) => row[index],
              ]),
            );
            file.append(
              node(
                "p",
                "hint",
                preview.display_truncated
                  ? `页面显示 ${preview.rows.length} / ${preview.total_items} 行或字段，最多16列，长文本显示前256字符。完整已保存视图随公共导出提供。`
                  : "显示已保存视图的全部内容。这里的页面预览不改变模型输入。",
              ),
            );
          } else
            file.append(
              node("p", "hint", "原始数据已绑定；模型数据视图尚未保存。"),
            );
          const provenance = node("details", "data-provenance");
          provenance.append(node("summary", "", "数据版本与来源"));
          list(
            provenance,
            [
              ["原始数据 SHA-256", ref.sha256 || "未提供"],
              ["模型视图 SHA-256", view?.sha256 || "未提供"],
              ["模型视图字节", view ? format(view.size_bytes) : "未提供"],
            ],
            [
              ["项目", (row) => row[0]],
              ["值", (row) => row[1]],
            ],
          );
          file.append(provenance);
          container.append(file);
        }
        if (!problem.data_refs?.length)
          container.append(
            node(
              "p",
              "hint",
              "此问题没有附加数据文件，建模输入来自问题描述与明确规则。",
            ),
          );
        return;
      }
    }
    if (Array.isArray(value)) {
      const section = card("运行记录");
      list(section, value.slice(-30), [
        ["顺序", (r) => r.sequence_no ?? "—"],
        ["事件", (r) => r.kind || "记录"],
        ["状态", (r) => status(r.status || r.method_event?.status)],
      ]);
      container.append(section);
      return;
    }
    empty(
      container,
      "详细记录已保存",
      "需要开发或研究时，可以展开下方原始记录。",
    );
  }
  function candidates(container, snapshot) {
    container.replaceChildren();
    const contents = snapshot?.contents || {};
    const get = (reference) => contents[artifactKey(snapshot, reference)];
    const selection = contents["candidate-selection.json"];
    const selectedId =
      snapshot?.bundle?.final_candidate_id || selection?.candidate_id;
    const records = new Map();
    for (const [name, item] of Object.entries(contents)) {
      if (
        !/^candidates\/[^/]+\/candidate(?:-snapshot)?\.json$/.test(name) ||
        !item?.candidate_id
      )
        continue;
      if (name.endsWith("/candidate.json") || !records.has(item.candidate_id))
        records.set(item.candidate_id, item);
    }
    if (!records.size) {
      empty(
        container,
        "候选方案正在形成",
        "方法保存候选后，可在这里查看模型、修正关系与实际求解结果。",
      );
      return;
    }
    if (selectedId) {
      const summary = card("最终选择 · 候选 " + selectedId);
      summary.classList.add("candidate-selection");
      summary.append(
        node("p", "", selection?.reason || "该方法未单独保存选择理由。"),
      );
      if (selection?.rule)
        summary.append(node("span", "hint", "选择规则：" + selection.rule));
      container.append(summary);
    }
    for (const candidate of [...records.values()].sort(
      (a, b) => a.sequence_no - b.sequence_no,
    )) {
      const assessment =
        contents[`candidates/${candidate.candidate_id}/assessment.json`];
      const model = get(candidate.artifact_ref);
      const codeArtifact = get(model?.code_ref);
      const solve = get(
        assessment?.solve_result_ref ||
          (candidate.candidate_id === selectedId
            ? snapshot.bundle?.solve_result_ref
            : null),
      );
      const section = card("候选 " + candidate.candidate_id);
      section.classList.add("candidate-card");
      section.dataset.candidateId = candidate.candidate_id;
      section.classList.toggle(
        "final-candidate",
        candidate.candidate_id === selectedId,
      );
      const tags = node("div", "result-tags");
      tags.append(node("span", "pill", status(candidate.status)));
      if (candidate.parent_ids?.length)
        tags.append(
          node(
            "span",
            "pill muted",
            "修正自 " + candidate.parent_ids.join("、"),
          ),
        );
      section.append(
        tags,
        node("p", "candidate-reason", candidate.change_reason || "初始候选"),
      );
      const stages = node("div", "candidate-stages");
      for (const [phase, title] of [
        ["formulation", "数学表述"],
        ["code", "求解实现"],
        ["solve", "求解"],
      ]) {
        const state =
          assessment?.stages?.[phase] ||
          (phase === "solve" && solve
            ? { status: "available" }
            : model?.stage_status?.[phase]);
        const item = node("div");
        item.append(
          node("span", "", title),
          node("strong", "", state ? status(state.status) : "未记录"),
        );
        stages.append(item);
      }
      section.append(stages);
      if (solve) {
        const result = node("div", "candidate-result");
        result.append(
          node("span", "", status(solve.termination)),
          node("strong", "", "候选目标 " + format(solve.objective_value)),
        );
        section.append(result);
      }
      for (const diagnostic of assessment?.diagnostics || [])
        section.append(
          node(
            "p",
            "candidate-diagnostic",
            diagnostic.message || diagnostic.code,
          ),
        );
      const changes = get(assessment?.formulation_changes_ref);
      if (changes) {
        const detail = node("details", "candidate-changes");
        detail.append(node("summary", "", "查看与上一候选的变化"));
        const names = {
          sets: "集合",
          parameters: "参数",
          variables: "变量",
          objective: "目标",
          constraints: "约束",
          assumptions: "假设",
          problem_type: "问题类型",
        };
        list(
          detail,
          [
            [
              "表述变化",
              (changes.changed_sections || [])
                .map((key) => names[key] || key)
                .join("、") || "未记录变化",
            ],
            [
              "IR变化",
              (changes.ir_changed_sections || [])
                .map((key) => names[key] || key)
                .join("、") || "未记录变化",
            ],
            [
              "增加约束",
              (changes.constraint_ids_added || []).join("、") || "无",
            ],
            [
              "删除约束",
              (changes.constraint_ids_removed || []).join("、") || "无",
            ],
            [
              "丢失需求关联",
              (changes.requirements_lost || []).join("、") || "无",
            ],
          ],
          [
            ["项目", (row) => row[0]],
            ["内容", (row) => row[1]],
          ],
        );
        detail.append(
          node(
            "p",
            "hint",
            changes.source_formulation_available
              ? "这是已声明输出的比较，不构成语义正确性证明。"
              : "上一候选没有可比较的完整表述；这里保留实际比较记录。",
          ),
        );
        section.append(detail);
      }
      const actions = node("div", "actions");
      for (const [label, tab, reference] of [
        ["查看数学模型", "formulation", model?.formulation_ref],
        ["查看求解代码", "code", codeArtifact?.representation_ref],
      ]) {
        const key = artifactKey(snapshot, reference);
        if (!key) continue;
        const button = node("button", "secondary", label);
        button.type = "button";
        button.onclick = () => {
          document.querySelector(`[data-tab="${tab}"]`).click();
          const choice = document.getElementById("artifact-choice");
          choice.value = key;
          choice.dispatchEvent(new Event("change"));
          document
            .getElementById("model-view")
            .scrollIntoView({ block: "start" });
        };
        actions.append(button);
      }
      section.append(actions);
      container.append(section);
    }
    container.append(
      node(
        "p",
        "hint",
        "各目标值属于各自的候选模型。候选之间可能改变目标或约束，不自动按目标值排名。",
      ),
    );
  }
  function connectivity(container, report) {
    container.hidden = false;
    container.replaceChildren();
    container.append(node("strong", "", "配置与兼容性检查通过"));
    const result = report.connectivity_checks;
    const labels = {
      reachable: "接口可达",
      failed: "检查未通过",
      not_supported: "不支持目录检查",
      not_checked: "未执行",
      not_applicable: "无需网络检查",
    };
    if (result.status === "not_requested") {
      container.append(
        node("p", "hint", "未请求网络检查。勾选上方选项后可读取模型目录。"),
      );
      return;
    }
    for (const item of result.checks || []) {
      const row = node("div", "connectivity-row");
      row.append(
        node(
          "span",
          "",
          (item.role === "default" ? "默认模型" : item.role) +
            " · " +
            (item.model || ""),
        ),
        node("strong", "", labels[item.status] || item.status),
      );
      if (item.model_listed != null)
        row.append(
          node(
            "small",
            "",
            item.model_listed ? "该页目录包含此模型" : "该页目录未列出此模型",
          ),
        );
      if (item.http_status)
        row.append(node("small", "", "HTTP " + item.http_status));
      container.append(row);
    }
    container.append(
      node(
        "p",
        "hint",
        "只读取目录，不发起文本生成。目录可能分页或使用别名；生成能力以实际运行结果为准。",
      ),
    );
  }
  function runtimeDetails(container, snapshot) {
    container.replaceChildren();
    const contents = snapshot?.contents || {};
    const ledger = contents["budget-ledger.json"] || {};
    const budget = contents["public-config.json"]?.budget || {};
    const shown = (value) => (value == null ? "未提供" : format(value));
    const usage = card(
      "资源使用",
      "累计资源来自保存的账本，可包含父版本消耗。",
    );
    usage.classList.add("runtime-card");
    const metrics = node("div", "runtime-metrics");
    for (const [label, key, limit] of [
      ["模型尝试", "llm_attempts", "max_llm_attempts"],
      ["外部模型请求", "external_llm_requests"],
      ["候选", "candidates", "max_candidates"],
      ["求解", "solver_calls", "max_solver_calls"],
    ]) {
      const box = node("div", "metric");
      box.append(
        node("span", "", label),
        node("strong", "", shown(ledger[key])),
      );
      if (budget[limit] != null)
        box.append(node("small", "", "总上限 " + format(budget[limit])));
      metrics.append(box);
    }
    usage.append(metrics);
    list(
      usage,
      [
        [
          "总Token",
          ledger.total_tokens == null ? "未知" : format(ledger.total_tokens),
        ],
        ["已知Token", shown(ledger.known_total_tokens ?? ledger.total_tokens)],
        ["未知用量预留", shown(ledger.reserved_tokens)],
        ["Token总上限", shown(budget.max_total_tokens)],
        ["修正轮数", shown(ledger.repairs)],
        ["新运行时间上限（秒）", shown(budget.wall_time_s)],
        ["费用", shown(ledger.cost)],
      ],
      [
        ["项目", (row) => row[0]],
        ["记录", (row) => row[1]],
      ],
    );
    container.append(usage);
    const solve =
      contents[artifactKey(snapshot, snapshot?.bundle?.solve_result_ref)];
    const execution =
      contents[artifactKey(snapshot, snapshot?.bundle?.execution_result_ref)];
    if (solve || execution) {
      const section = card(
        "最终候选的求解与执行",
        "耗时与资源按记录来源分别呈现；Gap保留求解器报告原值。",
      );
      section.classList.add("runtime-card");
      list(
        section,
        [
          ["求解器", solve?.solver_id || "未提供"],
          ["终止状态", solve ? status(solve.termination) : "未提供"],
          ["原始状态", solve?.raw_status || "未提供"],
          [
            "候选模型可行解",
            solve ? (solve.has_primal_solution ? "有" : "无") : "未提供",
          ],
          ["目标值", shown(solve?.objective_value)],
          ["Best bound", shown(solve?.best_bound)],
          ["报告Gap", shown(solve?.reported_gap)],
          ["求解耗时（秒）", shown(solve?.solve_time_s)],
          ["执行耗时（秒）", shown(execution?.wall_time_s)],
          ["CPU时间（秒）", shown(execution?.resources?.cpu_time_s)],
          [
            "峰值内存（MiB）",
            execution?.resources?.peak_memory_bytes == null
              ? "未提供"
              : format(execution.resources.peak_memory_bytes / 1048576),
          ],
        ],
        [
          ["项目", (row) => row[0]],
          ["记录", (row) => row[1]],
        ],
      );
      container.append(section);
    }
    const attempts = new Map();
    for (const [name, trace] of Object.entries(contents).sort(
      ([a], [b]) =>
        Number(b === "llm-trace.json") - Number(a === "llm-trace.json"),
    )) {
      if (!/(?:^|\/)llm-trace\.json$/.test(name)) continue;
      (trace.attempts || []).forEach((item, index) => {
        const key = item.attempt_id || name + "#" + index;
        if (!attempts.has(key))
          attempts.set(key, {
            ...item,
            source: name.startsWith("parent/")
              ? "父版本 " + name.split("/")[1].slice(0, 8)
              : "当前版本",
          });
      });
    }
    if (attempts.size) {
      const section = card(
        "已保存的模型调用",
        "每次尝试分别记录，可包含父版本。未知Token和费用不记为零。",
      );
      section.classList.add("runtime-card");
      list(
        section,
        [...attempts.values()],
        [
          ["来源", (item) => item.source],
          ["角色", (item) => roleLabel(item.role || "模型调用")],
          ["模型", (item) => item.model || item.requested_model || "未提供"],
          [
            "状态",
            (item) =>
              ({ success: "成功", response_unknown: "响应未确认" })[
                item.status
              ] || status(item.status),
          ],
          [
            "耗时（秒）",
            (item) =>
              item.start != null && item.end != null
                ? format(item.end - item.start)
                : "未提供",
          ],
          [
            "Token",
            (item) =>
              item.usage?.total_tokens == null
                ? "未知"
                : format(item.usage.total_tokens),
          ],
          ["预留", (item) => shown(item.reservation)],
        ],
      );
      container.append(section);
    }
    const events = snapshot?.events || [];
    if (events.length) {
      const section = node("details", "model-card runtime-card");
      section.append(node("summary", "", "查看最近运行事件"));
      list(section, events.slice(-30), [
        ["顺序", (item) => item.sequence_no],
        ["事件", (item) => item.kind],
        ["状态", (item) => status(item.status || item.method_event?.status)],
      ]);
      container.append(section);
    }
  }
  function timeline(snapshot) {
    const container = document.getElementById("method-timeline");
    if (!container) return;
    const events = snapshot.events || [],
      job = snapshot.job;
    const items = new Map();
    for (const event of events) {
      const step = event.method_event;
      if (step?.type === "modeling_step") {
        const prior = items.get(step.step_id);
        items.set(step.step_id, {
          ...prior,
          ...step,
          sequence: prior?.sequence || event.sequence_no,
          start: prior?.start || step.timestamp,
          end: step.status === "completed" ? step.timestamp : undefined,
        });
      }
      if (step?.artifact_ref?.namespace === "run_public") {
        const name = artifactKey(snapshot, step.artifact_ref);
        if (name) {
          items.set("artifact-" + event.sequence_no, {
            sequence: event.sequence_no,
            label: artifactLabel(name),
            phase: step.stage || "formulation",
            status: "completed",
            actor: "已保存的公开产物",
            artifact: name,
          });
        }
      }
    }
    if (!events.some((event) => event.method_event?.type === "modeling_step")) {
      const calls =
        snapshot.contents?.["method/calls.json"]?.calls ||
        snapshot.contents?.["method/source-calls.json"]?.calls ||
        [];
      calls.forEach((call, index) =>
        items.set("call-" + index, {
          label: roleLabel(call.role),
          actor: call.role,
          phase: /conductor|reducer/.test(call.role)
            ? "coordination"
            : /code|Programming|Reviewer/.test(call.role)
              ? "code"
              : "formulation",
          status: "completed",
        }),
      );
      for (const event of events) {
        const labels = {
          run_started: "读取问题与数据",
          formulation_saved: "数学表述已生成",
          code_saved: "求解实现已保存",
          solver_started: "调用求解器",
          solver_finished: "求解完成",
          code_output_saved: "原生代码已生成",
          method_execution_finished: "执行候选代码",
        };
        if (labels[event.kind])
          items.set("event-" + event.sequence_no, {
            label: labels[event.kind],
            status:
              event.kind.endsWith("started") && job.status === "running"
                ? "running"
                : "completed",
            phase: event.kind.startsWith("solver")
              ? "solve"
              : event.kind.startsWith("code") ||
                  event.kind.startsWith("method_execution")
                ? "code"
                : "formulation",
          });
      }
    } else
      for (const event of events) {
        if (
          [
            "code_saved",
            "solver_started",
            "solver_finished",
            "method_execution_finished",
          ].includes(event.kind)
        )
          items.set("core-" + event.sequence_no, {
            sequence: event.sequence_no,
            label: {
              code_saved: "生成的代码已保存",
              solver_started: "调用求解器",
              solver_finished: "求解结果已保存",
              method_execution_finished: "执行候选代码",
            }[event.kind],
            status:
              event.kind === "solver_started" &&
              !events.some((e) => e.kind === "solver_finished") &&
              job.status === "running"
                ? "running"
                : "completed",
            phase: event.kind.startsWith("solver") ? "solve" : "code",
          });
      }
    container.replaceChildren();
    if (!items.size)
      container.append(
        node(
          "p",
          "hint",
          job.status === "queued" ? "正在等待执行…" : "正在读取问题与检查配置…",
        ),
      );
    for (const [id, item] of Array.from(items).sort(
      (a, b) => (a[1].sequence || 0) - (b[1].sequence || 0),
    )) {
      const row = node("button", "timeline-step " + item.status);
      row.type = "button";
      if (item.artifact) row.dataset.artifact = item.artifact;
      if (
        item.status === "running" &&
        ["failed", "cancelled"].includes(job.status)
      )
        row.className = "timeline-step failed";
      const marker = node(
        "span",
        "step-marker",
        item.status === "completed"
          ? "✓"
          : row.classList.contains("failed")
            ? "!"
            : "",
      );
      const content = node("div", "step-content");
      content.append(node("strong", "", roleLabel(item.label)));
      const phase =
        {
          formulation: "Formulation · 数学表述",
          code: "Code · 求解实现",
          solve: "Solve · 求解",
          coordination: "方法协调",
        }[item.phase] || item.phase;
      content.append(
        node(
          "span",
          "",
          phase +
            (item.end && item.start
              ? " · " + format(item.end - item.start) + " s"
              : ""),
        ),
      );
      row.append(marker, content);
      row.onclick = () => {
        const tab =
          item.phase === "code"
            ? "code"
            : item.phase === "formulation"
              ? "formulation"
              : "diagnostics";
        document.querySelector('[data-tab="' + tab + '"]')?.click();
        if (item.artifact) {
          const choice = document.getElementById("artifact-choice");
          if (
            Array.from(choice.options).some(
              (option) => option.value === item.artifact,
            )
          ) {
            choice.value = item.artifact;
            choice.dispatchEvent(new Event("change"));
          }
        }
        row.classList.toggle("expanded");
        let detail = row.querySelector(".step-detail");
        if (detail) detail.remove();
        else
          content.append(
            node("small", "step-detail", item.actor || "应用流程"),
          );
        const output = document.getElementById("step-output");
        const comments = Object.entries(snapshot.contents || {}).flatMap(
          ([name, value]) =>
            Array.isArray(value?.comments)
              ? value.comments
                  .filter(
                    (comment) =>
                      Array.isArray(comment) &&
                      comment[0] === item.actor &&
                      typeof comment[1] === "string",
                  )
                  .map((comment) => ({ name, text: comment[1] }))
              : [],
        );
        output.hidden = !comments.length;
        output.replaceChildren();
        if (comments.length) {
          output.append(
            node("h3", "", roleLabel(item.actor) + " · 已保存的角色输出"),
          );
          comments.forEach((comment) => {
            const details = node("details"),
              summary = node("summary", "", comment.name.split("/").at(-1));
            details.append(summary, node("pre", "", comment.text));
            output.append(details);
          });
        }
      };
      container.append(row);
    }
    document.getElementById("process-state").textContent = status(job.status);
    document.getElementById("process-summary").textContent =
      shortMethod(
        snapshot.contents?.["public-config.json"]?.method?.plugin_id ||
          job.method,
      ) +
      " · " +
      (job.status === "running"
        ? "正在执行方法步骤"
        : "已保存 " + items.size + " 个过程记录");
  }
  function clarification(container, request, problem) {
    container.replaceChildren();
    container.dataset.requestId = request.request_id;
    const fields = request.questions.map((question, index) => {
      const group = node("fieldset", "clarification-question");
      group.append(node("legend", "", question.question));
      const input = node("textarea");
      input.rows = 3;
      input.maxLength = 4096;
      input.id = "clarification-answer-" + index;
      let choice = null;
      if (question.kind === "confirm_existing") {
        group.append(
          node("p", "existing-statement", "原声明：" + question.statement),
        );
        choice = node("select");
        choice.setAttribute("aria-label", question.question);
        for (const [value, label] of [
          ["", "请选择"],
          ["confirm", "确认原声明"],
          ["replace", "修改这项声明"],
        ]) {
          const option = node("option", "", label);
          option.value = value;
          choice.append(option);
        }
        group.append(choice);
        input.hidden = true;
        choice.onchange = () => {
          input.hidden = choice.value !== "replace";
          label.hidden = input.hidden;
          preview();
        };
      }
      const label = node(
        "label",
        "",
        question.kind === "confirm_existing"
          ? "修改后的完整声明"
          : "你的补充信息",
      );
      label.htmlFor = input.id;
      label.hidden = input.hidden;
      input.placeholder = "请直接描述规则、数值和单位。";
      group.append(label, input);
      container.append(group);
      input.oninput = () => preview();
      return { question, input, choice };
    });
    function submission() {
      const answers = fields.map(({ question, input, choice }) => {
        if (choice && !choice.value) throw new Error("请回答所有澄清问题。");
        const value = choice?.value === "confirm" ? true : input.value.trim();
        if (value !== true && (!value || value.length > 4096))
          throw new Error("请填写完整的补充或修订信息，最多4096个字符。");
        return { question_id: question.question_id, value };
      });
      const revise = answers.some((answer) => answer.value !== true);
      const response = {
        schema_version: "0.1.0",
        request_id: request.request_id,
        action: revise ? "revise" : "confirm",
        answers,
      };
      if (!revise) return { answers: response };
      const revised = structuredClone(problem);
      revised.revision =
        problem.revision + ".clarification-" + request.request_id.slice(0, 8);
      const changes = [];
      fields.forEach(({ question }, index) => {
        const answer = answers[index];
        if (answer.value === true) return;
        if (question.kind === "confirm_existing") {
          const source = revised[
            question.statement_ref.kind === "requirement"
              ? "requirements"
              : "assumptions"
          ].find((item) => item.id === question.statement_ref.id);
          if (!source)
            throw new Error("原声明不在当前公开问题中，无法提交修订。");
          source.text = answer.value;
          if (question.statement_ref.kind === "assumption") {
            source.status = "confirmed";
            source.origin = "user_clarification";
          }
          if ("source_span" in source) source.source_span = null;
          changes.push(
            "修订原声明（" + question.statement + "）：" + answer.value,
          );
        } else {
          revised.requirements.push({
            id: "CLARIFY-" + request.request_id.slice(0, 8) + "-" + (index + 1),
            text: answer.value,
            category: "other",
            source_span: null,
          });
          changes.push(question.question + "\n" + answer.value);
        }
      });
      revised.description +=
        "\n\n本次问题修订（以下规则替代有冲突的原声明）：\n" +
        changes.join("\n");
      return { answers: response, revised_problem: revised };
    }
    function preview() {
      try {
        const payload = submission();
        document.getElementById("clarification-preview").hidden =
          !payload.revised_problem;
        document.getElementById("clarification-description").textContent =
          payload.revised_problem?.description || "";
        document.getElementById("answer-submit").textContent =
          payload.revised_problem ? "确认修订并继续" : "确认声明并继续";
      } catch {
        document.getElementById("clarification-preview").hidden = true;
        document.getElementById("answer-submit").textContent = "提交回答并继续";
      }
    }
    preview();
    return submission;
  }
  function checks(container, evaluation) {
    const section = node("section", "result-checks");
    section.append(node("h3", "", "模型检查"));
    for (const [key, label] of [
      ["formulation_validation", "表述结构"],
      ["code_validation", "代码接口 / 构建"],
      ["independent_feasibility", "原问题可行性"],
      ["objective_match", "参考目标匹配"],
      ["semantic_validation", "业务语义证据"],
    ]) {
      const result = evaluation?.[key];
      const row = node("div", "check-row");
      row.append(
        node("span", "", label),
        node(
          "span",
          "pill " + (result?.status === "pass" ? "success" : "muted"),
          {
            pass: "通过",
            fail: "未通过",
            error: "检查异常",
            not_available: "未提供",
          }[result?.status] || "未提供",
        ),
      );
      if (result?.reason) row.title = result.reason;
      section.append(row);
    }
    container.append(section);
  }
  function failure(container, snapshot) {
    const error = snapshot?.job?.error || snapshot?.bundle?.error;
    if (!error) return false;
    const advice = {
      provider_timeout: [
        "模型服务响应超时",
        "检查模型服务状态与请求时限，再决定是否创建新运行。",
      ],
      provider_connection_error: [
        "暂时无法连接模型服务",
        "检查服务地址和连接。已保存的记录会保留。",
      ],
      auth_error: ["模型服务认证失败", "检查服务端配置的凭据。"],
      llm_output_truncated: [
        "模型输出未生成完整",
        "调整输出上限或简化问题后重新建模。",
      ],
      budget_exhausted: [
        "本次运行已达到预算上限",
        "查看实际消耗，调整预算后创建新的运行。",
      ],
      checkpoint_incompatible: [
        "保存记录与当前版本不兼容",
        "历史结果仍可查看。新的执行需要使用当前版本的配置。",
      ],
    };
    const connection = snapshot.contents?.["llm-trace.json"]?.attempts
      ?.filter(
        (item) => item.diagnostic === error.code && item.connection_diagnostic,
      )
      .at(-1);
    const diagnosis = {
      tls_interrupted: [
        "模型服务的 TLS 连接被中断",
        "检查服务或显式代理的连接路线。请求用量可能未知，原记录已保留。",
      ],
      tls_certificate: [
        "模型服务证书校验失败",
        "检查服务证书与本机可信证书配置，再创建新运行。",
      ],
      tls_error: ["模型服务的 TLS 连接失败", "检查服务和代理的 TLS 连接配置。"],
      dns_error: ["模型服务域名解析失败", "检查服务地址和使用路线的 DNS。"],
      connection_refused: [
        "模型服务连接被拒绝",
        "检查服务或代理是否正在监听配置的地址和端口。",
      ],
      connection_reset: [
        "模型服务连接被重置",
        "检查服务或显式代理的连接路线。请求用量可能未知。",
      ],
      timeout: advice.provider_timeout,
    };
    const [title, detail] = diagnosis[connection?.connection_diagnostic] ||
      advice[error.code] || [
        "这次建模未完成",
        "查看已保存的步骤和诊断，修改输入或配置后再执行。",
      ];
    const section = node("div", "failure-summary");
    section.append(
      node("span", "eyebrow", "RUN NEEDS ATTENTION"),
      node("h2", "", title),
      node("p", "hint", detail),
      node("code", "failure-code", error.code),
    );
    const button = node("button", "secondary", "查看运行详情");
    button.onclick = () =>
      document.querySelector('[data-tab="diagnostics"]').click();
    section.append(button);
    container.append(section);
    return true;
  }
  function decisionExplorer(container, ir, solution) {
    if (
      !ir?.objective?.expression ||
      !ir.variables?.length ||
      !ir.variables.every((item) =>
        Number.isFinite(solution?.variables?.[item.id]),
      )
    )
      return;
    const section = node("section", "model-card decision-explorer");
    section.append(node("h3", "", "目标与约束余量"));
    section.append(
      node(
        "p",
        "hint",
        "仅代入当前候选模型计算，不重新求解或修改已保存结果。约束余量为负表示超出该限制；等式显示左侧减右侧的偏差。",
      ),
    );
    const fields = node("div", "explorer-fields");
    const inputs = new Map();
    for (const item of ir.variables) {
      const label = node("label", "", item.name || item.id);
      const input = node("input");
      input.type = "number";
      input.step = item.domain === "continuous" ? "any" : "1";
      if (item.lower_bound != null) input.min = item.lower_bound;
      if (item.upper_bound != null) input.max = item.upper_bound;
      if (item.domain === "binary") {
        input.min = Math.max(item.lower_bound ?? 0, 0);
        input.max = Math.min(item.upper_bound ?? 1, 1);
      }
      input.value = solution.variables[item.id];
      input.dataset.decisionVariable = item.id;
      label.append(input);
      fields.append(label);
      inputs.set(item.id, input);
    }
    const reset = node("button", "secondary", "恢复求解结果");
    reset.type = "button";
    const output = node("div", "explorer-output");
    output.setAttribute("aria-live", "polite");
    const calculate = () => {
      output.replaceChildren();
      if (
        [...inputs.values()].some(
          (input) =>
            !input.validity.valid || !Number.isFinite(input.valueAsNumber),
        )
      ) {
        output.append(node("p", "hint", "请填写符合变量边界和类型的数值。"));
        return;
      }
      const value = (expression) =>
        expression.constant +
        expression.terms.reduce(
          (sum, term) =>
            sum + term.coefficient * inputs.get(term.variable_id).valueAsNumber,
          0,
        );
      const objective = node("div", "explorer-objective");
      objective.append(
        node(
          "span",
          "",
          ir.objective.sense === "max"
            ? "试算目标 · 最大化"
            : "试算目标 · 最小化",
        ),
        node("strong", "", format(value(ir.objective.expression))),
      );
      output.append(objective);
      for (const item of ir.constraints || []) {
        const activity = value(item.expression);
        const margin =
          item.sense === "le" ? item.rhs - activity : activity - item.rhs;
        const row = node("div", "explorer-constraint");
        row.classList.toggle("exceeded", item.sense !== "eq" && margin < 0);
        row.append(node("strong", "", item.name || item.id));
        row.append(
          node(
            "span",
            "",
            `${format(activity)} ${{ le: "≤", ge: "≥", eq: "=" }[item.sense]} ${format(item.rhs)}`,
          ),
        );
        row.append(
          node(
            "span",
            "constraint-margin",
            `${item.sense === "eq" ? "偏差" : "余量"} ${format(margin)}`,
          ),
        );
        if (item.sense === "le" && item.rhs > 0 && activity >= 0) {
          const meter = node("meter");
          meter.min = 0;
          meter.max = item.rhs;
          meter.value = activity;
          meter.setAttribute(
            "aria-label",
            `${item.name || item.id} ${format(activity)} / ${format(item.rhs)}`,
          );
          row.append(meter);
        }
        output.append(row);
      }
    };
    fields.oninput = calculate;
    reset.onclick = () => {
      for (const [id, input] of inputs) input.value = solution.variables[id];
      calculate();
    };
    const controls = node("details", "decision-controls");
    controls.append(
      node("summary", "", "调整决策值 · 交互试算"),
      fields,
      reset,
    );
    section.append(output, controls);
    container.append(section);
    calculate();
  }
  function decision(container, solve, solution, ledger, snapshot, solvedIR) {
    container.replaceChildren();
    const failed = failure(container, snapshot);
    if (!solve) {
      if (failed) return;
      const state = snapshot?.job?.status;
      if (["queued", "running", "needs_input"].includes(state)) {
        const step = activeStep(snapshot);
        const live = node("div", "live-modeling " + state);
        live.setAttribute("role", "status");
        live.setAttribute("aria-live", "polite");
        const symbol = node("div", "modeling-orbit", "∑");
        symbol.setAttribute("aria-hidden", "true");
        const copy = node("div", "modeling-copy");
        copy.append(
          node(
            "span",
            "eyebrow",
            shortMethod(
              snapshot.contents?.["public-config.json"]?.method?.plugin_id ||
                snapshot.job.method,
            ),
          ),
          node(
            "h2",
            "",
            state === "queued"
              ? "问题已提交，等待执行"
              : state === "needs_input"
                ? "等待你补充问题信息"
                : step
                  ? roleLabel(step.label)
                  : "正在准备建模",
          ),
          node(
            "p",
            "hint",
            state === "needs_input"
              ? "请完成下方问题，模型将依据你的回答继续。"
              : state === "queued"
                ? "开始执行后，这里会显示实际建模步骤。"
                : "正在执行所选方法。步骤与模型输出会自动更新。",
          ),
        );
        if (step && state === "running") {
          const detail = node("div", "modeling-detail");
          detail.append(
            node(
              "span",
              "pill",
              {
                formulation: "Formulation · 数学表述",
                code: "Code · 求解实现",
                solve: "Solve · 数值求解",
                coordination: "方法协作",
              }[step.phase],
            ),
            node("span", "hint", roleLabel(step.actor)),
          );
          copy.append(detail);
        }
        live.append(symbol, copy);
        container.append(live);
        return;
      }
      empty(
        container,
        "求解结果将在这里出现",
        "建模进行时，可在左侧查看实际步骤。",
      );
      return;
    }
    const hero = node("div", "decision-hero");
    const title = node("div");
    title.append(
      node("span", "eyebrow", "MODEL SOLUTION"),
      node(
        "h2",
        "",
        solve.has_primal_solution
          ? "候选模型求解完成"
          : status(solve.termination),
      ),
    );
    const objective = node("div", "objective-result");
    objective.append(
      node("span", "hint", "目标值"),
      node("strong", "", format(solve.objective_value)),
    );
    hero.append(title, objective);
    container.append(hero);
    const meta = node("div", "result-tags");
    if (snapshot?.bundle?.assisted)
      meta.append(node("span", "pill muted", "人工辅助结果"));
    meta.append(
      node("span", "pill success", status(solve.termination)),
      node("span", "pill muted", (solve.solver_id || "").split(".").at(-1)),
      node(
        "span",
        "pill muted",
        "Token " + format(ledger?.total_tokens ?? ledger?.known_total_tokens),
      ),
      node(
        "span",
        "pill muted",
        ledger?.cost == null ? "费用未提供" : "费用 " + format(ledger.cost),
      ),
    );
    container.append(meta);
    const values = Object.entries(solution?.variables || {});
    const variableNames = new Map(
      (solvedIR?.variables || []).map((item) => [
        item.id,
        item.name || item.id,
      ]),
    );
    if (values.length) {
      const bars = node("div", "decision-bars"),
        maximum = Math.max(...values.map(([, value]) => Math.abs(value)), 1);
      values.forEach(([name, value]) => {
        const row = node("button", "decision-row");
        row.type = "button";
        row.setAttribute("aria-pressed", "false");
        const label = node(
          "span",
          "decision-name",
          variableNames.get(name) || name,
        );
        if (variableNames.get(name) && variableNames.get(name) !== name)
          label.append(node("small", "decision-id", name));
        row.append(label);
        const track = node("div", "bar-track"),
          bar = node("span", "bar-fill");
        bar.style.width = (Math.abs(value) / maximum) * 100 + "%";
        bar.classList.toggle("negative", value < 0);
        track.append(bar);
        row.append(track, node("strong", "", format(value)));
        row.onclick = () => {
          row.classList.toggle("selected");
          row.setAttribute("aria-pressed", row.classList.contains("selected"));
        };
        bars.append(row);
      });
      container.append(bars);
      container.append(
        node(
          "p",
          "hint",
          "柱长表示决策值的绝对大小；点击可选中比较，准确值显示在右侧。",
        ),
      );
    }
    const expression = solvedIR?.objective?.expression;
    if (
      solve.has_primal_solution &&
      expression &&
      expression.terms.every((term) =>
        Number.isFinite(solution?.variables?.[term.variable_id]),
      )
    ) {
      const breakdown = node("section", "model-card objective-breakdown");
      breakdown.append(node("h3", "", "目标值如何构成"));
      const contributions = node("div", "contribution-grid");
      for (const term of expression.terms) {
        const quantity = solution.variables[term.variable_id];
        const item = node("div", "contribution-item");
        item.append(
          node(
            "span",
            "",
            variableNames.get(term.variable_id) || term.variable_id,
          ),
          node("strong", "", format(term.coefficient * quantity)),
          node(
            "small",
            "hint",
            `${format(term.coefficient)} × ${format(quantity)}`,
          ),
        );
        contributions.append(item);
      }
      if (expression.constant !== 0) {
        const constant = node("div", "contribution-item");
        constant.append(
          node("span", "", "常数项"),
          node("strong", "", format(expression.constant)),
        );
        contributions.append(constant);
      }
      breakdown.append(
        contributions,
        node("p", "hint", "各项来自已求解的目标函数；负数表示负贡献。"),
      );
      container.append(breakdown);
    }
    if (solve.has_primal_solution)
      decisionExplorer(container, solvedIR, solution);
    checks(container, snapshot?.contents?.["evaluation.json"]);
    container.append(
      node(
        "p",
        "evidence-note",
        "以上是当前候选模型的求解结果。原问题的独立验证以已保存的检查证据为准。",
      ),
    );
  }
  function activeStep(snapshot) {
    const current = new Map();
    let solver = null;
    for (const event of snapshot.events || []) {
      const step = event.method_event;
      if (step?.type === "modeling_step")
        current.set(step.step_id, { ...step, sequence: event.sequence_no });
      if (event.kind === "solver_started")
        solver = {
          phase: "solve",
          label: "正在求解候选模型",
          actor: "求解器",
          sequence: event.sequence_no,
          status: "running",
        };
      if (event.kind === "solver_finished") solver = null;
    }
    return [...current.values(), ...(solver ? [solver] : [])]
      .filter((step) => step.status === "running")
      .sort((a, b) => b.sequence - a.sequence)[0];
  }
  function revision(container, template, ledger) {
    container.replaceChildren();
    const fields = [];
    let readDraft = draft;
    const changeConstraints = (change) => {
      const value = draft(false);
      change(value.structured_ir.constraints);
      synchronizeFormulation(value);
      readDraft = revision(container, value, ledger);
    };
    function field(
      label,
      value,
      path,
      {
        multiline = false,
        number = false,
        nullable = false,
        choices,
        rows = 4,
      } = {},
    ) {
      const wrapper = node("label", "revision-field", label);
      const input = node(choices ? "select" : multiline ? "textarea" : "input");
      if (choices)
        for (const [key, label] of choices) {
          const option = node("option", "", label);
          option.value = key;
          input.append(option);
        }
      if (multiline) input.rows = rows;
      else if (number) {
        input.type = "number";
        if (path[0] === "budget") input.min = 0;
        input.step =
          path[0] === "budget" && path.at(-1) !== "wall_time_s" ? "1" : "any";
      }
      if (nullable) input.placeholder = "无界";
      input.value = value ?? "";
      wrapper.append(input);
      container.append(wrapper);
      fields.push({ input, path, number, nullable });
      input.oninput = () => draft(false);
      return input;
    }
    const hint =
      template.operation === "problem"
        ? "确认后将重新调用所选模型建模。原数据绑定不变，新版本继承已有消耗。"
        : "确认后使用编辑后的建模输出重新求解，不新增模型请求。原问题与数据保留。";
    container.append(node("p", "revision-summary", hint));
    if (template.operation === "problem") {
      field("新版本标识", template.problem.revision + ".edited-" + Date.now(), [
        "problem",
        "revision",
      ]);
      field(
        "完整问题描述",
        template.problem.description,
        ["problem", "description"],
        { multiline: true, rows: 7 },
      );
      for (const [group, label] of [
        ["requirements", "已有规则"],
        ["assumptions", "已有假设"],
      ]) {
        if (template.problem[group].length)
          container.append(node("h4", "", label));
        template.problem[group].forEach((item, index) =>
          field(item.id, item.text, ["problem", group, index, "text"], {
            multiline: true,
            rows: 2,
          }),
        );
      }
    } else if (template.operation === "code") {
      const input = field(
        "求解代码",
        template.code.source,
        ["code", "source"],
        { multiline: true, rows: 18 },
      );
      input.classList.add("source-editor");
      input.spellcheck = false;
    } else if (template.structured_ir) {
      container.append(
        node(
          "p",
          "hint",
          "编辑实际用于求解的线性模型。新版本的变量、目标与约束文本会按编辑后的IR更新。数值边界留空表示无界。",
        ),
      );
      const ir = template.structured_ir;
      const names = Object.fromEntries(
        ir.variables.map((item) => [item.id, item.name || item.id]),
      );
      const group = (title) => {
        const section = node("div", "revision-model-group");
        section.append(node("h4", "", title));
        const grid = node("div", "field-grid");
        section.append(grid);
        container.append(section);
        return grid;
      };
      const addField = (grid, label, value, path, options) => {
        field(label, value, path, options);
        grid.append(container.lastElementChild);
      };
      const linearFields = (grid, label, expression, path) => {
        addField(
          grid,
          label + " · 常数",
          expression.constant,
          [...path, "constant"],
          { number: true },
        );
        expression.terms.forEach((term, index) =>
          addField(
            grid,
            label + " · " + names[term.variable_id] + " 系数",
            term.coefficient,
            [...path, "terms", index, "coefficient"],
            { number: true },
          ),
        );
      };
      const objective = group("优化目标");
      addField(
        objective,
        "优化方向",
        ir.objective.sense,
        ["structured_ir", "objective", "sense"],
        {
          choices: [
            ["max", "最大化"],
            ["min", "最小化"],
          ],
        },
      );
      linearFields(objective, "目标", ir.objective.expression, [
        "structured_ir",
        "objective",
        "expression",
      ]);
      ir.variables.forEach((item, index) => {
        const grid = group("变量 · " + names[item.id]);
        const path = ["structured_ir", "variables", index];
        addField(grid, item.id + " · 类型", item.domain, [...path, "domain"], {
          choices: [
            ["continuous", "连续"],
            ["integer", "整数"],
            ["binary", "0 / 1"],
          ],
        });
        for (const [key, label] of [
          ["lower_bound", "下界"],
          ["upper_bound", "上界"],
        ])
          addField(grid, item.id + " · " + label, item[key], [...path, key], {
            number: true,
            nullable: true,
          });
      });
      ir.constraints.forEach((item, index) => {
        const grid = group("约束 · " + item.id);
        const remove = node("button", "secondary", "移除约束");
        remove.type = "button";
        remove.setAttribute("aria-label", "移除约束 " + item.id);
        remove.onclick = () =>
          changeConstraints((rows) => rows.splice(index, 1));
        grid.parentElement.firstElementChild.append(remove);
        const path = ["structured_ir", "constraints", index];
        linearFields(grid, item.id, item.expression, [...path, "expression"]);
        addField(grid, item.id + " · 关系", item.sense, [...path, "sense"], {
          choices: [
            ["le", "≤"],
            ["ge", "≥"],
            ["eq", "="],
          ],
        });
        addField(grid, item.id + " · 右侧值", item.rhs, [...path, "rhs"], {
          number: true,
        });
      });
      const add = node("button", "secondary", "＋ 添加约束");
      add.type = "button";
      add.onclick = () =>
        changeConstraints((rows) => {
          let index = 1;
          while (rows.some((item) => item.id === "C_USER_" + index)) index++;
          rows.push({
            id: "C_USER_" + index,
            expression: {
              constant: 0,
              terms: ir.variables.map((item) => ({
                variable_id: item.id,
                coefficient: 0,
              })),
            },
            sense: "le",
            rhs: 0,
            requirement_ids: [],
          });
        });
      container.append(
        add,
        node(
          "p",
          "hint",
          "新约束请填写变量系数、关系和右侧值。修改将保存为人工辅助的新版本。",
        ),
      );
    } else
      container.append(
        node(
          "p",
          "hint",
          "数学表述与严格IR通过下方完整文档编辑，应用后再提交。",
        ),
      );
    const reason = field("修改原因", template.reason, ["reason"], {
      multiline: true,
      rows: 2,
    });
    reason.maxLength = 4096;
    reason.placeholder = "说明你希望改变的行为或要修正的问题。";
    const consumed = ledger || {};
    container.append(
      node(
        "p",
        "hint",
        "已累计：模型请求 " +
          format(consumed.llm_attempts) +
          " 次 · 求解 " +
          format(consumed.solver_calls) +
          " 次 · 候选 " +
          format(consumed.candidates) +
          " 个 · 已知 Token " +
          format(consumed.known_total_tokens ?? consumed.total_tokens) +
          "。下方是包含这些消耗的总上限。",
      ),
    );
    const budgets = node("div", "field-grid revision-budget");
    container.append(budgets);
    for (const [key, label] of [
      ["max_llm_attempts", "模型请求总上限"],
      ["max_total_tokens", "Token 总上限"],
      ["max_solver_calls", "求解次数总上限"],
      ["max_candidates", "候选总上限"],
      ["wall_time_s", "新运行时间上限（秒）"],
    ]) {
      field(label, template.budget[key], ["budget", key], { number: true });
      budgets.append(container.lastElementChild);
    }
    function draft(validate) {
      const value = structuredClone(template);
      fields.forEach(({ input, path, number, nullable }) => {
        let target = value;
        for (const key of path.slice(0, -1)) target = target[key];
        target[path.at(-1)] = number
          ? nullable && input.value === ""
            ? null
            : input.valueAsNumber
          : input.value;
      });
      if (
        value.operation === "formulation" &&
        value.structured_ir &&
        JSON.stringify(value.structured_ir) !==
          JSON.stringify(template.structured_ir)
      ) {
        synchronizeFormulation(value);
      }
      if (validate) {
        if (
          fields.some(
            ({ input, number, nullable }) =>
              number &&
              (!input.validity.valid ||
                (input.value === ""
                  ? !nullable
                  : !Number.isFinite(input.valueAsNumber))),
          )
        )
          throw new Error("请填写有效的数值。只有变量边界可以留空。");
        if (!value.reason.trim()) throw new Error("请填写修改原因。");
        if (
          value.operation === "problem" &&
          (!value.problem.description.trim() ||
            !value.problem.revision.trim() ||
            value.problem.revision === template.problem.revision)
        )
          throw new Error("问题修订需要完整描述和新的版本标识。");
        if (value.operation === "code" && !value.code.source.trim())
          throw new Error("求解代码不能留空。");
        if (value.budget.max_candidates <= (consumed.candidates || 0))
          throw new Error("候选总上限需要覆盖已有候选和本次新增候选。");
      }
      document.getElementById("assisted-document").value = JSON.stringify(
        value,
        null,
        2,
      );
      return value;
    }
    function synchronizeFormulation(value) {
      const ir = value.structured_ir;
      ir.problem_type = ir.variables.every(
        (item) => item.domain === "continuous",
      )
        ? "lp"
        : "milp";
      if (value.formulation?.representation_kind !== "five_element") return;
      const text = (expression) =>
        [
          expression.constant,
          ...expression.terms.map(
            (term) => `${term.coefficient}*${term.variable_id}`,
          ),
        ].join(" + ");
      const representation = value.formulation.representation;
      representation.variables = ir.variables.map(
        ({ id, domain, lower_bound, upper_bound, requirement_ids }) => ({
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
      representation.constraints = ir.constraints.map((item) => ({
        id: item.id,
        expression_text: `${text(item.expression)} ${{ le: "<=", ge: ">=", eq: "=" }[item.sense]} ${item.rhs}`,
        requirement_ids: item.requirement_ids,
      }));
    }
    draft(false);
    return () => readDraft(true);
  }
  return {
    node,
    list,
    format,
    status,
    shortMethod,
    artifactLabel,
    artifactKey,
    activeStep,
    candidates,
    runtimeDetails,
    connectivity,
    records,
    timeline,
    decision,
    clarification,
    revision,
    empty,
  };
})();
