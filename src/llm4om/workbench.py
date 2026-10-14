"""Built-in workbench defaults, kept outside modeling and compatibility logic."""

from copy import deepcopy
from typing import Any

STANDARD_BUDGET = {"max_llm_attempts": 4, "max_total_tokens": 100000, "max_solver_calls": 4,
                   "max_repairs": 2, "max_candidates": 4, "wall_time_s": 180}
NATIVE_BUDGET = {"max_llm_attempts": 30, "max_total_tokens": 300000, "max_solver_calls": 12,
                 "max_repairs": 3, "max_candidates": 4, "wall_time_s": 1800}


def method_presets() -> dict[str, dict[str, Any]]:
    grounded = {"config": {"formulation_mode": "five_element", "output_mode": "lp_ir"},
        "model_backend": {"plugin_id": "llm4om.model_backends.pyomo_factory"},
        "solver": {"plugin_id": "llm4om.solvers.highs"},
        "compiler": {"plugin_id": "llm4om.compilers.lp_ir_to_pyomo"}, "budget": STANDARD_BUDGET}
    native = {"model_backend": {"plugin_id": "llm4om.model_backends.gurobipy"},
              "solver": {"plugin_id": "llm4om.solvers.gurobi"}, "budget": NATIVE_BUDGET}
    return deepcopy({
        "llm4om.methods.direct": {**grounded,
            "explanation": "一次模型调用联合生成数学表述与求解实现，再构建并求解候选模型。"},
        "llm4om.methods.feedback_repair": {**grounded,
            "explanation": "遇到缺失或含糊的规则时可以先向你提问。生成候选模型后，依据公开执行反馈修正，并保存候选与选择关系。"},
        "llm4om.methods.optimus_inline": {**native, "config": {"rag_mode": None},
            "explanation": "依次理解目标与约束、形成数学表述、编写代码，并根据执行反馈调试。适合直接输入问题。"},
        "llm4om.methods.optimus": {**native,
            "config": {"rag_mode": None, "params_data_id": "params", "labels_data_id": "labels"},
            "explanation": "使用公开参数和标签文件，分步形成数学表述与求解代码。需要 params 与 labels 数据。",
            "requirements": "需要上传 params 与 labels 两个数据文件(或自定义数据 ID);求解走 Gurobi。"},
        "llm4om.methods.coe": {**native,
            "config": {"max_collaborate_nums": 1, "enable_reflection": True, "max_trials": 2, "seed": 0},
            "explanation": "由协调者选择专家，进行建模讨论、代码生成与审查。页面展示实际参与的角色。",
            "requirements": "多轮专家讨论,求解走 Gurobi。"},
    })
