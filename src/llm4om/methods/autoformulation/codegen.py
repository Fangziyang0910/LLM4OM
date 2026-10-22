"""Code for a formalization dict, per code language: upstream utils_exec.create_code_str, made pluggable.

Upstream writes one gurobipy script per tree node and runs it with `python3`: parameters, variables, then the
objective expression (objective step), the equality constraints (equality step), or the whole model and
`gpy_model.optimize()` (inequality step). The gurobipy output here is that text; the Pyomo, OR-Tools pywraplp and
PuLP outputs are its equivalents. Partial steps become check scripts; the complete model becomes
`build_model(data)` for the solver. The model keeps upstream's name `gpy_model` in every dialect.
"""

from llm4om.methods.autoformulation.upstream.utils_general import (
    check_none_key_value,
    extract_loop_variables,
    extract_range_dv,
    extract_variable_name,
    extract_vtype_dv,
    get_borders_constraints,
    get_param_code_str,
    get_var_name,
    remove_brackets_content,
    separate_constraint_from_for,
)

# Each header is "imports\n\nmodel set-up"; model_code keeps the imports at module level.
HEADERS = {
    "gurobipy": 'from gurobipy import Model, GRB\n\n# Initialize the model\ngpy_model = Model("Production Planning")\n',
    "pyomo": ('import pyomo.environ as pyo\nfrom pyomo.environ import *\n\n# Initialize the model\n'
              'gpy_model = pyo.ConcreteModel("Production Planning")\ngpy_model.constraints = pyo.ConstraintList()\n'),
    "pywraplp": ('from ortools.linear_solver import pywraplp\n\n# Initialize the model\n'
                'gpy_model = pywraplp.Solver.CreateSolver("SCIP")\n\n'
                'def _new_var(vtype, name):\n'
                '    vtype = str(vtype).lower()\n'
                '    if "bin" in vtype or "bool" in vtype:\n'
                '        return gpy_model.BoolVar(name)\n'
                '    if "int" in vtype:\n'
                '        return gpy_model.IntVar(0, gpy_model.infinity(), name)\n'
                '    return gpy_model.NumVar(0, gpy_model.infinity(), name)\n'),
    "pulp": ('import pulp\n\n# Initialize the model\n'
             'gpy_model = pulp.LpProblem("Production Planning", pulp.LpMinimize)\n\n'
             'def _new_var(vtype, name):\n'
             '    vtype = str(vtype).lower()\n'
             '    category = "Binary" if "bin" in vtype or "bool" in vtype else "Integer" if "int" in vtype else "Continuous"\n'
             '    return pulp.LpVariable(name, lowBound=0, cat=category)\n'),
}


def _new_var(language: str, var_name: str, vtype: str, index: str | None, name: str) -> str:
    """One new variable; Pyomo variables come from a sparse indexed Var so border constraints can add indices."""
    if language == "gurobipy":
        return f"gpy_model.addVar(vtype={vtype}, name={name})"
    if language in ("pywraplp", "pulp"):
        return f"_new_var({vtype!r}, {name})"
    return f"_{var_name}_var[{index}]" if index is not None else f"_{var_name}_var"


def var_code(language: str, var_name: str, vtype: str, space_index: list[str]) -> str:
    """utils_exec.get_var_code_str."""
    if language != "pyomo":
        declare = ""
    elif space_index:
        declare = f"_{var_name}_var = pyo.Var(pyo.Any, dense=False, domain={vtype})\ngpy_model.add_component('{var_name}', _{var_name}_var)\n"
    else:
        declare = f"_{var_name}_var = pyo.Var(domain={vtype})\ngpy_model.add_component('{var_name}', _{var_name}_var)\n"
    if len(space_index) == 0:
        return declare + f"{var_name} = {_new_var(language, var_name, vtype, None, repr(var_name))}"
    if len(space_index) == 1:
        new = _new_var(language, var_name, vtype, "i", f"f'{var_name}[{{i}}]'")
        return declare + f"{var_name} = {{i: {new} for i in {space_index[0]}}}"
    new = _new_var(language, var_name, vtype, "i, j", f"f'{var_name}[{{i}},{{j}}]'")
    return declare + f"{var_name} = {{(i, j): {new} for i in {space_index[0]} for j in {space_index[1]}}}"


def dv_code(language: str, form: dict) -> str:
    """utils_exec.get_dv_code_str."""
    lines = ""
    for this_var, description in form["decision_variables"].items():
        var_name, _ = get_var_name(this_var)
        lines += var_code(language, var_name, extract_vtype_dv(description), extract_range_dv(description)) + "\n"
    return lines


def clean_python_expression(expression: str) -> str:
    """utils_exec.clean_python_expression: drop leading blank and comment lines."""
    lines = [line for line in expression.lstrip().splitlines() if line.strip() and not line.strip().startswith("#")]
    return "\n".join(lines)


def objective_code(language: str, form: dict, set_objective: bool = True) -> str:
    """utils_exec.get_obj_code_str, without `optimize()`: the platform solves the model."""
    sense = list(form["objective"].keys())[0]
    expression = clean_python_expression(form["objective"][sense]).replace("\n", "")
    code = f"objective = {expression}\n"
    if set_objective:
        if language == "gurobipy":
            code += f"gpy_model.setObjective(objective, GRB.{'MINIMIZE' if sense == 'min' else 'MAXIMIZE'})\n"
        elif language == "pywraplp":
            code += f"gpy_model.{'Minimize' if sense == 'min' else 'Maximize'}(objective)\n"
        elif language == "pulp":
            code += f"gpy_model.sense = pulp.{'LpMinimize' if sense == 'min' else 'LpMaximize'}\ngpy_model.setObjective(objective)\n"
        else:
            code += f"gpy_model.objective = pyo.Objective(expr=objective, sense=pyo.{'minimize' if sense == 'min' else 'maximize'})\n"
    return code


def _border_code(language: str, form: dict, const_dict: dict) -> str:
    """utils_general.get_prompt_cte_constraints: variables for border constraints outside a variable's space.

    llm4om: upstream exec()-ed the parameters and index spaces on the host to decide; the line checks membership.
    """
    borders = get_borders_constraints(const_dict, check_is_constant=True, parameter_list=list(form["parameters"].keys()))
    vtypes = {remove_brackets_content(name): extract_vtype_dv(value) for name, value in form["decision_variables"].items()}
    code = ""
    for const_name, indexes in borders:
        var_name = extract_variable_name(const_dict[const_name])
        _, for_loop = separate_constraint_from_for(const_dict[const_name])
        index = ", ".join(indexes)
        new = _new_var(language, var_name, vtypes[var_name], index, "f'%s[%s]'" % (var_name, ", ".join(f"{{{e}}}" for e in indexes)))
        guard = f"({index}) not in {var_name}"
        if for_loop:
            code += f"{var_name}.update({{({index}): {new} {for_loop} if {guard}}})\n"
        else:
            code += f"{var_name}.update({{({index}): {new}}} if {guard} else {{}})\n"
    return code + ("\n\n" if code else "")


def _all_constraints(language: str, const_dict: dict) -> str:
    """utils_exec.get_prompt_all_constraints."""
    code = ""
    for const_name, const_str in const_dict.items():
        main, for_loop = separate_constraint_from_for(const_str)
        if language in ("gurobipy", "pywraplp", "pulp"):
            add = {"gurobipy": "addConstr", "pywraplp": "Add", "pulp": "addConstraint"}[language]
            name = "name = " if language == "gurobipy" else ""
            if for_loop == "":
                code += f"all_const += [gpy_model.{add}({main}, {name}'{const_name}')] \n"
            else:
                index = ", ".join(f"{{{elem}}}" for elem in extract_loop_variables(for_loop))
                code += f"all_const += [gpy_model.{add}({main}, {name}f'{const_name}[{index}]')  {for_loop}] \n"
        else:
            code += f"all_const += [gpy_model.constraints.add({main}){(' ' + for_loop) if for_loop else ''}] \n"
    return code


def constraints_code(language: str, form: dict, step: str) -> str:
    """utils_exec.get_code_for_const_str."""
    const_dict = form[step]
    if check_none_key_value(const_dict):
        return ""
    code = _border_code(language, form, const_dict) if step == "equality_constraints" else ""
    return code + _all_constraints(language, const_dict)


def check_script(language: str, form: dict, step: str) -> str:
    """The script upstream runs to check a node of the objective or equality step (create_code_str)."""
    code = HEADERS[language] + "\n" + get_param_code_str(form) + "\n\n" + dv_code(language, form) + "\n\n"
    if step == "objective":
        return code + objective_code(language, form, set_objective=False) + "\n\n"
    return code + "all_const = [] \n\n" + constraints_code(language, form, "equality_constraints") + "\n\n"


def model_code(language: str, form: dict) -> str:
    """The complete model of a leaf as `build_model(data)`; upstream's script for the inequality step."""
    body = (HEADERS[language].split("\n\n", 1)[1] + "\n" + get_param_code_str(form) + "\n\n" + dv_code(language, form)
            + "\n\nall_const = [] \n\n" + constraints_code(language, form, "equality_constraints") + "\n\n"
            + constraints_code(language, form, "inequality_constraints") + "\n\n" + objective_code(language, form)
            + "return gpy_model\n")
    imports = HEADERS[language].split("\n\n", 1)[0]
    indented = "".join("    " + line if line.strip() else line for line in body.splitlines(True))
    return f"{imports}\n\n\ndef build_model(data):\n{indented}"
