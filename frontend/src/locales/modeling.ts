import { locale } from "@/i18n";

// Protocol labels are translated only for display; payloads and node identities remain unchanged.
const fields: Record<string, string> = {
  Sets: "集合", Parameters: "参数", Variables: "变量", Objective: "目标函数", Constraints: "约束",
  "Decision variables": "决策变量", "Equality constraints": "等式约束", "Inequality constraints": "不等式约束",
  Formulation: "数学模型", "Mathematical Formulation": "数学模型", Objectives: "目标函数",
  "Objective and constraints": "目标函数与约束", Ambiguities: "歧义", "Assumptions and Conventions": "假设与约定",
  Code: "代码", "Data schema": "数据结构", Expert: "专家",
  Accepted: "已接受", "Ambiguities relevant": "歧义与题意相关", "Ambiguity resolutions": "歧义处理",
  Attempts: "尝试次数", Belongs: "类别匹配", Blamed: "问题归因", Classes: "问题类别",
  "Code executable": "代码可执行", "Code execution count": "代码执行次数",
  "Code validation count": "代码检查次数", "Code validation feedback": "代码检查反馈",
  "Code validation passed": "代码检查通过", Comment: "说明", Comparisons: "比较结果",
  Components: "模型组件", "Constraint candidate": "约束候选", Corrections: "修正意见",
  "Debug round": "调试轮次", "Decision variable candidate": "决策变量候选", "Error attribution": "错误归因",
  Executed: "已执行", "Execution feedback": "执行反馈", Executions: "执行次数", Expansion: "搜索展开",
  "Facts faithful": "事实忠于题意", Feedback: "反馈", "Fixed code": "修正代码",
  "Formulation revision action": "模型修正动作", "Formulation validation count": "模型检查次数",
  "Formulation validation feedback": "模型检查反馈", "Formulation validation passed": "模型检查通过",
  Inspections: "检查记录", Node: "节点", "Objective candidate": "目标函数候选",
  "Parameter index candidate": "参数与索引候选", Path: "路径", Reconstructed: "回译内容",
  Reflection: "反思", Repairs: "修正次数", Reply: "回复", "Resolutions consistent": "歧义处理一致",
  Review: "复核", Rollout: "模拟搜索", Rounds: "轮次", "Selected formulation expert": "选定建模专家",
  "Semantic ambiguities": "语义歧义", "Semantic facts": "语义事实", "Semantic rounds": "语义检查轮次",
  "Semantic validation count": "语义检查次数", "Semantic validation feedback": "语义检查反馈",
  "Solution path": "求解路径", Stage: "阶段", "Thought template": "推理模板", Trial: "试验轮次",
  Tries: "尝试次数", Turns: "对话轮次", Verdict: "判断结果",
};
const canonicalFields = new Map(Object.entries(fields).map(([name, translation]) => [name.toLowerCase(), { name, translation }]));

const inlineFields: Record<string, string> = {
  var_type: "变量类型", domain: "取值域", shape: "形状", unit: "单位",
  description: "描述", value: "值", expr: "表达式", type: "类型",
};
const fieldValues: Record<string, Record<string, string>> = {
  var_type: { real: "实数", int: "整数", bool: "二元" },
  shape: { scalar: "标量" },
  type: { min: "最小化", max: "最大化", satisfy: "满足约束", real: "实数", int: "整数", bool: "二元" },
};

/** Applied to model prose nodes only, never to code, formulas or the saved source. */
export function modelFieldText(source: string): string {
  if (locale !== "zh") return source;
  return source.replace(/(^|[\s;；,，:：])(var_type|domain|shape|unit|description|value|expr|type)(\s*[:：]\s*)(?:(real|int|bool|scalar|min|max|satisfy)\b)?/g,
    (_, prefix: string, key: string, separator: string, value: string | undefined) => {
      const choices = fieldValues[key];
      const translated = value && choices && Object.hasOwn(choices, value) ? choices[value] : value ?? "";
      return prefix + inlineFields[key] + separator + translated;
    });
}

const experts: Record<string, string> = {
  "Terminology Interpreter": "术语解释专家", "Parameter Extractor": "参数提取专家",
  "Modeling Expert": "建模专家", "Programming Example Provider": "编程示例专家",
  "Programming Expert": "编程专家", "Modeling Knowledge Supplement Expert": "建模知识补充专家",
  "Code Reviewer": "代码审查专家",
};

const roles: Record<string, readonly [string, string]> = {
  semantic_fact_extractor: ["语义事实提取", "Extract semantic facts"],
  ambiguity_resolver: ["处理语义歧义", "Resolve semantic ambiguities"],
  semantic_validator: ["检查语义", "Validate semantics"],
  parameter_index_expert: ["提取参数与索引", "Extract parameters and indices"],
  decision_variable_expert: ["定义决策变量", "Define decision variables"],
  objective_expert: ["建立目标函数", "Formulate the objective"],
  constraint_expert: ["建立约束", "Formulate constraints"],
  formulation_selector: ["选择数学模型", "Select a formulation"],
  formulation_validator: ["检查数学模型", "Validate the formulation"],
  revise_formulation: ["修正数学模型", "Revise the formulation"],
  code_validator: ["检查求解代码", "Validate solver code"],
  explain_result: ["解读求解结果", "Explain the result"],
  bind_generate: ["BIND 建模", "BIND modeling"],
  optimind_classify: ["OptiMind 问题分类", "OptiMind problem classification"],
  optimind_generate: ["OptiMind 建模与反思", "OptiMind modeling and reflection"],
  parameters: ["提取参数", "Extract parameters"], constraints: ["建立约束", "Formulate constraints"],
  constraints_redundancy: ["检查冗余约束", "Check redundant constraints"],
  objective: ["建立目标函数", "Formulate the objective"],
  objective_model: ["建立目标函数", "Formulate the objective"], objective_code: ["生成目标函数代码", "Generate objective code"],
  constraint_model: ["建立约束", "Formulate constraints"], constraint_code: ["生成约束代码", "Generate constraint code"],
  constraint_check: ["检查约束", "Check constraints"], constraint_feedback: ["修正约束", "Revise constraints"],
  math_model: ["数学建模", "Mathematical modeling"], compare: ["比较模型", "Compare models"],
  conductor: ["选择专家", "Select an expert"], inspector: ["检查代码", "Inspect code"],
  interpreter: ["解释问题", "Interpret the problem"], reasoner: ["问题推理", "Reason about the problem"],
  reducer: ["归约问题", "Reduce the problem"], group_decision_variables: ["分组决策变量", "Group decision variables"],
  sac_generate: ["生成分项代码", "Generate component code"], sac_objective: ["生成目标函数", "Generate the objective"],
  sac_backtranslate: ["约束回译", "Backtranslate constraints"], sac_compare: ["检查约束语义", "Check constraint semantics"],
  sac_repair: ["修正失败组件", "Repair failed components"], sac_revise_constraint: ["修正约束", "Revise constraints"],
  sac_debug: ["调试求解代码", "Debug solver code"],
};

const components: Record<string, readonly [string, string]> = {
  parameters: ["参数", "parameters"], variables: ["变量", "variables"],
  decision_variables: ["决策变量", "decision variables"], objective: ["目标函数", "objective"],
  constraints: ["约束", "constraints"], equality_constraints: ["等式约束", "equality constraints"],
  inequality_constraints: ["不等式约束", "inequality constraints"],
};

export function expertLabel(source: string): string {
  const backward = source.endsWith(" (backward)");
  const name = backward ? source.slice(0, -11) : source;
  return locale === "zh" && Object.hasOwn(experts, name) ? (backward ? "反向反思：" : "") + experts[name] : source;
}

export function modelLabel(source: string): string {
  const title = source.trim().replace(/[:：]$/, "");
  const field = canonicalFields.get(title.replace(/_/g, " ").toLowerCase());
  if (field) return locale === "zh" ? field.translation : field.name;
  return source;
}

export function methodRoleLabel(role: string): string | undefined {
  const expert = expertLabel(role);
  if (expert !== role || Object.hasOwn(experts, role.replace(/ \(backward\)$/, ""))) return expert;
  const part = role.slice(role.lastIndexOf(".") + 1);
  const component = Object.hasOwn(components, part) ? components[part] : undefined;
  const operation = role.startsWith("generate.") ? ["生成", "Generate "]
    : role.startsWith("rank.") ? ["排序", "Rank "] : null;
  if (operation && component) return operation[locale === "zh" ? 0 : 1] + component[locale === "zh" ? 0 : 1];
  const label = Object.hasOwn(roles, part) ? roles[part] : undefined;
  if (label) return label[locale === "zh" ? 0 : 1];
  const sac = /^(sac_check_|sac_)(.+)$/.exec(part);
  if (sac && Object.hasOwn(components, sac[2])) return (locale === "zh" ? "检查" : "Check ") + components[sac[2]][locale === "zh" ? 0 : 1];
  return undefined;
}
