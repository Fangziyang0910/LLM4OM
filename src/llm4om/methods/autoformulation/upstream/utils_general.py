# llm4om: unused upstream helpers and overwritten definitions removed; active algorithms are unchanged.
import ast
import re


def check_none_key_value(d):
    return d.get(None) is None and None in d

def transform_keys(data):
    # llm4om: preserve exact key types (e.g. '2024', '01', 'inf') without in-place mutation or float coercion.
    return {key: dict(value) if isinstance(value, dict) else value for key, value in data.items()}

def get_param_code_str(formalization_dict, apply_ast = False):
    if apply_ast:
        param_dict = ast.literal_eval(formalization_dict['parameters'])
    else:
        param_dict = formalization_dict['parameters']
    param_dict = transform_keys(param_dict)
    prompt = ""
    for param, value in param_dict.items():
        # llm4om: repr preserves quotes, backslashes and line breaks in generated Python literals.
        prompt += f'{param} = {value!r}\n'
    return prompt


def extract_vtype_dv(input_dict):
    # Use regex to find the text between < and >
    return input_dict['type']

def get_var_name(this_var):
    right_index = -1
    if this_var[right_index] == ']':
        left_index = this_var[:right_index].rfind("[")
        return this_var[:left_index], True
    else:
        return this_var, False

def extract_iteration_spec(comp_str):
    """Return `(targets, iterables)` for an iteration_space expression."""
    if comp_str is None:
        return [], []
    text = str(comp_str).strip()
    if not text:
        return [], []
    if text.startswith("for "):
        text = "0 " + text
    comp_ast = None
    for candidate in (text, f"[{text}]"):
        try:
            comp_ast = ast.parse(candidate, mode='eval')
            break
        except SyntaxError:
            continue
    if comp_ast is None:
        return [], []
    body = comp_ast.body
    if isinstance(body, (ast.ListComp, ast.GeneratorExp)):
        targets = [ast.unparse(gen.target) for gen in body.generators]
        iterables = [ast.unparse(gen.iter) for gen in body.generators]
        return targets, iterables
    if isinstance(body, (ast.Tuple, ast.List)):
        return [], [ast.unparse(element) for element in body.elts]
    if isinstance(body, ast.Name):
        return [], [ast.unparse(body)]
    return [], []


def extract_range_iterables(comp_str):
    if comp_str is None:
        return ''
    _, iterables = extract_iteration_spec(comp_str)
    return iterables


def extract_range_dv(input_dict):
    #def extract_iterables(comp_str):
    comp_str = input_dict['iteration_space']
    if comp_str is None:
        return ''

    matches = extract_range_iterables(comp_str)
    return matches

def extract_variable_name(equation):
    # Match everything before the first opening bracket
    match = re.match(r"^\s*([a-zA-Z_]\w*)\[", equation)
    if match:
        return match.group(1)
    return None

def remove_brackets_content(input_string):
    # Use regex to remove the brackets and their content
    result = re.sub(r"\[.*?\]", "", input_string)
    return result.strip()  # Remove any extra spaces


def separate_constraint_from_for(input_string):
    # Remove leading/trailing whitespace
    input_string = input_string.strip()
    stack = []
    for_loop_starts = []
    for i, char in enumerate(input_string):
        if char == '(':
            stack.append(i)
        elif char == ')':
            if stack:
                stack.pop()
        elif not stack and char.isspace() and re.match(r'\s+for\s+', input_string[i:]):
            for_loop_starts.append(i)
    if for_loop_starts:
        main_expr = input_string[:for_loop_starts[0]].strip()
        for_loop = input_string[for_loop_starts[0]:].strip()
    else:
        main_expr = input_string
        for_loop = ""
    return main_expr, for_loop


def extract_loop_variables(loop_string):
    if not loop_string or not str(loop_string).strip():
        return []
    text = str(loop_string).strip()
    candidate = f"[0 {text}]" if text.startswith("for ") else f"[{text}]"
    try:
        parsed = ast.parse(candidate, mode="eval").body
        if isinstance(parsed, (ast.ListComp, ast.GeneratorExp)):
            names = []
            for gen in parsed.generators:
                for node in ast.walk(gen.target):
                    if isinstance(node, ast.Name):
                        names.append(node.id)
            if names:
                return names
    except SyntaxError:
        pass
    # Fallback regex preserving order across multiple clauses
    variables = re.findall(r'for\s+\(([^)]+)\)\s+in|for\s+([a-zA-Z_]\w*(?:\s*,\s*[a-zA-Z_]\w*)*)\s+in', text)
    flattened_results = []
    for group in variables:
        raw = group[0] or group[1]
        flattened_results.extend(item.strip() for item in raw.split(',') if item.strip())
    return flattened_results


def is_constant_constraint(equation: str, allowed_variables: list):
    # Step 1: Eliminate the for loop if it exists at the end of the string
    equation, _ = separate_constraint_from_for(equation)

    # Step 2: Split the equation into left and right parts by "=="
    if "==" not in equation:
        return False, None  # Not a valid equality
    left, right = map(str.strip, equation.split("==", 1))

    # Step 3: Check the right side (it should be a number or a single variable, with or without brackets)
    # Regex pattern for a number (integer or float)
    if re.match(r'^[-+]?\d*\.?\d+$', right):
        pass  # It's a number, proceed further
    else:
        # Check if the right part is a variable, with or without brackets
        # Match variables with brackets: variable_name[...]
        match_right_with_brackets = re.match(r'^([a-zA-Z_]\w*)\[(.*?)\]$', right)
        if match_right_with_brackets:
            variable_name_right = match_right_with_brackets.groups()[0]
        else:
            variable_name_right = right  # In case there are no brackets, it's the variable itself

        # Check if the variable name (without brackets) is in the allowed list
        if variable_name_right not in allowed_variables:
            return False, None  # Variable not in the allowed list

    # Step 4: Check the left side (it should be a variable with brackets and at least one index must be an integer)
    match_left = re.match(r'^([a-zA-Z_]\w*)\[(.*?)\]$', left)
    if not match_left:
        return False, None  # Left side must have brackets
    variable_name, index_content = match_left.groups()

    # Step 5: Check if at least one index is an integer
    indices = [idx.strip() for idx in index_content.split(',')]
    has_integer_index = any(re.match(r'^\d+$', idx) for idx in indices)
    if not has_integer_index:
        return False, None

    # If all conditions are satisfied, return True and the list of indices
    return True, indices


def get_borders_constraints(eq_const_dict, check_is_constant = False, parameter_list = []):
    all_borders_constraints = []
    for eq_const in eq_const_dict.keys():
        if check_is_constant:
            try:
                is_constant, indexes = is_constant_constraint(eq_const_dict[eq_const], parameter_list)
            except:
                raise  # llm4om: was pdb.set_trace(), which blocks a server thread
                print("A")
            if is_constant:
                all_borders_constraints += [(eq_const, indexes)]
    return all_borders_constraints


def get_prompt_cte_constraints(all_const_cte, formalization_dict, const_dict, var_type = 'gurobipy'):
    # llm4om: upstream exec()-ed the parameters and the index spaces on the host to add a variable only when a
    # border constraint uses an integer index outside the variable's space. The emitted line now checks membership
    # itself, so nothing generated runs on the host. The smt lines also take `[0]` of Reals() and close their
    # brackets; upstream's lines raised a SyntaxError, which made every such comparison "not equivalent".
    vtypes = {remove_brackets_content(name): extract_vtype_dv(value)
              for name, value in formalization_dict['decision_variables'].items()}
    prompt = ""
    for const_name, indexes in all_const_cte:
        var_name      = extract_variable_name(const_dict[const_name])
        if var_name not in vtypes:
            continue
        _, for_loop   = separate_constraint_from_for(const_dict[const_name])
        vtype         = vtypes[var_name]
        idx_str_1     = ', '.join(indexes)
        guard         = f"({idx_str_1}) not in {var_name}"
        if var_type == 'gurobipy':
            idx_str     = ', '.join(f'{{{elem}}}' for elem in indexes)
            new_var     = "gpy_model.addVar(vtype=%s, name = f'%s[%s]')" % (vtype, var_name, idx_str)
        elif var_type == 'simpy':
            idx_str     = '_'.join(f'{{{elem}}}' for elem in indexes)
            new_var     = "sp.symbols(f'%s_%s'.replace(' ', '_') )" % (var_name, idx_str)
        elif var_type == 'smt':
            idx_str     = '_'.join(f'{{{elem}}}' for elem in indexes)
            new_var     = "Reals(f'%s_%s'.replace(' ', '_') )[0]" % (var_name, idx_str)
        if for_loop:
            prompt += "%s.update({(%s): %s %s if %s})\n" % (var_name, idx_str_1, new_var, for_loop, guard)
        else:
            prompt += "%s.update({(%s): %s} if %s else {})\n" % (var_name, idx_str_1, new_var, guard)
        if var_type == 'smt':
            prompt += "all_variables += [%s[(%s)] %s]\n" % (var_name, idx_str_1, for_loop)
    if prompt:
        prompt += "\n\n"
    return prompt
