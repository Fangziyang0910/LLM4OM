"""AutoFormulation node checks and complete models, using the shared native Python emitter."""

from llm4om.languages import CodeTarget
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
from llm4om.model_code import ModelCode


def _model(target: CodeTarget | str) -> ModelCode:
    return ModelCode(CodeTarget(target) if isinstance(target, str) else target, 'gpy_model')


def dv_code(target: CodeTarget | str, form: dict) -> str:
    model, lines = _model(target), []
    for name, description in form['decision_variables'].items():
        lines.append(model.variables(get_var_name(name)[0], extract_range_dv(description), extract_vtype_dv(description),
                     str(description.get('lower_bound', 0)), str(description.get('upper_bound')),
                     indices=extract_loop_variables(description['iteration_space'] or '') or None))
    return ''.join(lines)


def clean_python_expression(expression: str) -> str:
    """utils_exec.clean_python_expression: drop leading blank and comment lines."""
    lines = [line for line in expression.lstrip().splitlines() if line.strip() and not line.strip().startswith("#")]
    return "\n".join(lines)


def objective_code(target: CodeTarget | str, form: dict, set_objective: bool = True) -> str:
    sense, expression = next(iter(form['objective'].items()))
    code = 'objective = ' + clean_python_expression(expression).replace('\n', '') + '\n'
    return code + (_model(target).objective('objective', sense) + '\n' if set_objective else '')


def _border_code(target: CodeTarget | str, form: dict, const_dict: dict) -> str:
    """utils_general.get_prompt_cte_constraints: variables for border constraints outside a variable's space.

    llm4om: upstream exec()-ed the parameters and index spaces on the host to decide; the line checks membership.
    """
    borders = get_borders_constraints(const_dict, check_is_constant=True, parameter_list=list(form["parameters"].keys()))
    descriptions = {remove_brackets_content(name): value for name, value in form["decision_variables"].items()}
    code = ""
    for const_name, indexes in borders:
        var_name = extract_variable_name(const_dict[const_name])
        _, for_loop = separate_constraint_from_for(const_dict[const_name])
        index = ", ".join(indexes)
        description = descriptions[var_name]
        label = "f'%s[%s]'" % (var_name, ", ".join(f"{{{e}}}" for e in indexes))
        new = _model(target).new_var(extract_vtype_dv(description), label,
                                     str(description.get('lower_bound', 0)), str(description.get('upper_bound')))
        guard = f"({index}) not in {var_name}"
        if for_loop:
            code += f"{var_name}.update({{({index}): {new} {for_loop} if {guard}}})\n"
        else:
            code += f"{var_name}.update({{({index}): {new}}} if {guard} else {{}})\n"
    return code + ("\n\n" if code else "")


def _all_constraints(target: CodeTarget | str, const_dict: dict) -> str:
    code = ''
    model = _model(target)
    for name, expression in const_dict.items():
        main, loop = separate_constraint_from_for(expression)
        index = ', '.join('{' + item + '}' for item in extract_loop_variables(loop))
        label = f"f'{name}[{index}]'" if loop else repr(name)
        code += 'all_const += [' + model.constraint(main, label) + (' ' + loop if loop else '') + ']\n'
    return code


def constraints_code(target: CodeTarget | str, form: dict, step: str) -> str:
    """utils_exec.get_code_for_const_str."""
    const_dict = form[step]
    if check_none_key_value(const_dict):
        return ""
    code = _border_code(target, form, const_dict) if step == "equality_constraints" else ""
    return code + _all_constraints(target, const_dict)


def check_script(target: CodeTarget | str, form: dict, step: str) -> str:
    """Build, without solving, the partial model used by the original search's node checks."""
    model = _model(target)
    code = model.imports + '\n' + model.setup + '\n' + get_param_code_str(form) + '\n' + dv_code(target, form) + '\n'
    if step == 'objective':
        return code + objective_code(target, form, set_objective=False)
    return code + 'all_const = []\n' + constraints_code(target, form, 'equality_constraints')


def model_code(target: CodeTarget | str, form: dict) -> str:
    return _model(target).assemble([get_param_code_str(form), dv_code(target, form), 'all_const = []',
                                    constraints_code(target, form, 'equality_constraints'),
                                    constraints_code(target, form, 'inequality_constraints'), objective_code(target, form)])
