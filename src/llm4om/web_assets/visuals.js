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
      "state_1_params.json": "问题与参数",
      "state_2_objective.json": "优化目标初稿",
      "state_3_constraints.json": "约束识别",
      "state_4_constraints_modeled.json": "约束数学表述",
      "state_5_objective_modeled.json": "完整数学表述",
      "state_6_code.json": "数学表述与代码片段",
    })[name.split("/").at(-1)] || name;
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
  function formulation(container, value, contents) {
    container.replaceChildren();
    const source = value?.representation || {};
    const representation = source.state || source;
    const ir = Object.entries(contents || {}).find(
      ([name, data]) =>
        /model-ir|structured-ir|supplied-ir/.test(name) &&
        data?.objective?.expression,
    )?.[1];
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
    container.append(goal);
    const vars = card(
      "决策变量",
      "点击变量或公式中的符号，查看它在模型中的关联。",
    );
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
    }
    if (variables.length || !source.state) container.append(vars);
    const constraints = card("约束条件", "保留模型实际提供的关系与边界。");
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
      if (item.requirement_ids?.length)
        detail.append(
          node(
            "span",
            "source-tag",
            "来源需求 " + item.requirement_ids.join(" · "),
          ),
        );
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
  function records(container, value, tab, contents) {
    if (tab === "formulation") return formulation(container, value, contents);
    if (tab === "code") return code(container, value);
    container.replaceChildren();
    if (tab === "data") {
      const problem = contents["public-problem.json"];
      if (problem) {
        const section = card("你的问题");
        section.append(node("p", "problem-text", problem.description));
        container.append(section);
        for (const ref of problem.data_refs || []) {
          const file = card(
            ref.data_id,
            ref.format.toUpperCase() + " · 原始数据绑定",
          );
          file.append(node("p", "hint", "已保存，建模使用这一版本的数据。"));
          container.append(file);
        }
        return;
      }
    }
    if (tab === "candidates") {
      const candidates = Object.entries(contents)
        .filter(
          ([name, data]) =>
            /candidate-snapshot.json$/.test(name) && data?.candidate_id,
        )
        .map(([, data]) => data);
      const section = card(
        "候选方案",
        "展示实际保存的候选，保留修正和选择关系。",
      );
      list(section, candidates, [
        ["方案", (r) => r.candidate_id],
        ["状态", (r) => status(r.status)],
        ["原因", (r) => r.change_reason || "初始方案"],
      ]);
      container.append(section);
      return;
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
        const name = Object.keys(snapshot.contents || {})
          .filter((key) => step.artifact_ref.relative_path?.endsWith("/" + key))
          .sort((a, b) => b.length - a.length)[0];
        const current =
          snapshot.bundle?.public_projections?.[name] ||
          snapshot.artifacts?.find(
            (ref) => name && ref.relative_path?.endsWith("/" + name),
          );
        if (
          name &&
          current?.sha256 === step.artifact_ref.sha256 &&
          current.relative_path === step.artifact_ref.relative_path
        ) {
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
      shortMethod(job.method) +
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
    const [title, detail] = advice[error.code] || [
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
  function decision(container, solve, solution, ledger, snapshot) {
    container.replaceChildren();
    const failed = failure(container, snapshot);
    if (!solve) {
      if (failed) return;
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
    if (values.length) {
      const bars = node("div", "decision-bars"),
        maximum = Math.max(...values.map(([, value]) => Math.abs(value)), 1);
      values.forEach(([name, value]) => {
        const row = node("button", "decision-row");
        row.type = "button";
        row.append(node("span", "decision-name", name));
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
    checks(container, snapshot?.contents?.["evaluation.json"]);
    container.append(
      node(
        "p",
        "evidence-note",
        "以上是当前候选模型的求解结果。原问题的独立验证以已保存的检查证据为准。",
      ),
    );
  }
  function revision(container, template, ledger) {
    container.replaceChildren();
    const fields = [];
    function field(
      label,
      value,
      path,
      { multiline = false, number = false, rows = 4 } = {},
    ) {
      const wrapper = node("label", "revision-field", label);
      const input = node(multiline ? "textarea" : "input");
      if (multiline) input.rows = rows;
      else if (number) {
        input.type = "number";
        input.min = 0;
        input.step = path.at(-1) === "wall_time_s" ? "any" : "1";
      }
      input.value = value ?? "";
      wrapper.append(input);
      container.append(wrapper);
      fields.push({ input, path, number });
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
      fields.forEach(({ input, path, number }) => {
        let target = value;
        for (const key of path.slice(0, -1)) target = target[key];
        target[path.at(-1)] = number ? Number(input.value) : input.value;
      });
      if (validate) {
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
    draft(false);
    return () => draft(true);
  }
  return {
    node,
    format,
    status,
    shortMethod,
    artifactLabel,
    records,
    timeline,
    decision,
    clarification,
    revision,
    empty,
  };
})();
