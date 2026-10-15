"""Built-in workbench defaults, kept outside modeling and compatibility logic."""

from copy import deepcopy
from typing import Any

from llm4om.contracts import RunError

STANDARD_BUDGET = {"max_llm_attempts": 4, "max_total_tokens": 100000, "max_solver_calls": 4,
                   "max_repairs": 2, "max_checks": 4, "wall_time_s": 180}
NATIVE_BUDGET = {"max_llm_attempts": 30, "max_total_tokens": 300000, "max_solver_calls": 12,
                 "max_repairs": 3, "max_checks": 4, "wall_time_s": 1800}


def llm_presets() -> list[dict[str, str]]:
    return [{'id': identifier, 'label': label, 'provider_plugin_id': 'llm4om.providers.openai_compatible', 'base_url': url}
        for identifier, label, url in (
            ('openai', 'OpenAI', 'https://api.openai.com/v1'),
            ('google', 'Google Gemini', 'https://generativelanguage.googleapis.com/v1beta/openai'),
            ('kimi', 'Kimi', 'https://api.moonshot.cn/v1'),
            ('glm', 'GLM（智谱）', 'https://open.bigmodel.cn/api/paas/v4'),
            ('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1'),
            ('bailian', '阿里云百炼（北京）', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
            ('deepseek', 'DeepSeek', 'https://api.deepseek.com/v1'),
            ('openai_compatible', 'OpenAI 兼容（自定义地址）', ''),
        )] + [{'id': 'anthropic', 'label': 'Anthropic', 'provider_plugin_id': 'llm4om.providers.anthropic',
            'base_url': 'https://api.anthropic.com/v1'}]


def validate_llm_preset(config: dict[str, Any], preset_id: str | None) -> None:
    if preset_id is None:
        return
    preset = next((item for item in llm_presets() if item['id'] == preset_id), None)
    selected = config['llm']
    url = selected['config'].get('base_url')
    if (preset is None or selected['provider_plugin_id'] != preset['provider_plugin_id']
            or preset['base_url'] and (not isinstance(url, str) or url.rstrip('/') != preset['base_url'])):
        raise RunError('invalid_config', 'web', 'Preset LLM endpoints are fixed; select OpenAI compatible for a custom URL.')


def method_presets() -> dict[str, dict[str, Any]]:
    grounded = {"config": {"formulation_mode": "five_element", "output_mode": "lp_ir"},
        "model_backend": {"plugin_id": "llm4om.model_backends.pyomo_factory"},
        "solver": {"plugin_id": "llm4om.solvers.highs"},
        "compiler": {"plugin_id": "llm4om.compilers.lp_ir_to_pyomo"}, "budget": STANDARD_BUDGET}
    prompt = {"model_backend": {"plugin_id": "llm4om.model_backends.pyomo_factory"},
              "solver": {"plugin_id": "llm4om.solvers.highs"}, "budget": NATIVE_BUDGET}
    return deepcopy({
        "llm4om.methods.direct": {**grounded,
            "explanation": "一次模型调用联合生成数学表述与求解实现，再构建并求解候选模型。"},
        "llm4om.methods.feedback_repair": {**grounded,
            "explanation": "遇到缺失或含糊的规则时可以先向你提问。生成候选模型后，依据公开执行反馈修正，并保存候选与选择关系。"},
        "llm4om.methods.optimus_inline": {**prompt, "config": {"rag_mode": None}, "hidden": True,
            "explanation": "依次理解目标与约束、形成数学表述、编写代码，并根据执行反馈调试。适合直接输入问题。"},
        "llm4om.methods.optimus": {**prompt, "config": {"rag_mode": None},
            "explanation": "直接输入自然语言问题，依次理解目标与约束、形成数学表述、编写代码，并根据执行反馈调试。"},
        "llm4om.methods.or_llm_agent": {**prompt, "config": {"max_debug_attempts": 2},
            "explanation": "先由数学建模代理形成表述，再按所选后端和求解器生成代码，依据实际执行错误进行调试。"},
        "llm4om.methods.optitree": {**prompt, "config": {"max_debug_attempts": 2},
            "explanation": "在固定的官方问题类型树中逐层检索建模思路，再针对你的问题形成表述与代码，并执行调试。"},
        "llm4om.methods.autoformulation": {**grounded, "config": {"rollouts": 2, "branching": 2, "exploration": 1.4},
            "budget": {**NATIVE_BUDGET, "max_llm_attempts": 40, "max_checks": 2, "max_solver_calls": 2},
            "explanation": "用 MCTS 搜索参数、变量、目标、等式与不等式约束的表述；用独立自评、求解反馈和 SMT 等价剪枝引导选择。"},
        "llm4om.methods.coe": {**prompt,
            "config": {"max_collaborate_nums": 1, "enable_reflection": True, "max_trials": 2, "seed": 0},
            "explanation": "由协调者选择专家，进行建模讨论、代码生成与审查。页面展示实际参与的角色。",
            "requirements": "多轮专家讨论，使用所选求解器。"},
    })
