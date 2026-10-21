# llm4om: unused upstream helpers and overwritten definitions removed; active algorithms are unchanged.
import re

from .utils_general import (
    extract_range_dv,
    get_borders_constraints,
    get_param_code_str,
    get_prompt_cte_constraints,
    get_var_name,
    separate_constraint_from_for,
)

# llm4om: the scripts below are generated here and run in the sandbox by the method, which also runs
# the pairwise filtering (upstream execute_python_code, filter_functionally_equivalent, compar_two_dicts
# and get_equivalence_function are removed). sympy and z3 are imported only by the generated scripts.

# Example usage


### Differences in parameters


def get_dv_sym_str(var_name, space_index = []):
    if len(space_index) == 0:
        return f"{var_name} = sp.symbols('{var_name}')"
    elif len(space_index) == 1:
        return f"{var_name} = {{i: sp.symbols( ('{var_name}_' + str(i)).replace(' ', '_') ) for i in {space_index[0]}}}"
    elif len(space_index) == 2:
        return f"{var_name} = {{(i,j): sp.symbols(  ('{var_name}_' + str(i) + '_' +  str(j)).replace(' ', '_') ) for i in {space_index[0]} for j in {space_index[1]}}}"


def get_symbolic_par_dv(this_dict):

    output_string = "import sympy as sp\n\n"

    # Define symbolic variables for parameters
    output_string += "# Define symbolic variables\n"

    output_string += get_param_code_str(this_dict)

    # Define decision variables
    decision_variables = this_dict.get("decision_variables", {})
    output_string += "\n# Decision Variables\n"

    for var, description in decision_variables.items():
        space_index       = extract_range_dv(description)
        var_name, is_dict = get_var_name(var)
        this_code_str     = get_dv_sym_str(var_name, space_index)
        output_string    += f'{this_code_str}\n'
    return output_string


### Differences in objectives

def dict_to_obj_str(this_dict):

    # Start with an empty string
    output_string = get_symbolic_par_dv(this_dict)

    # Define the objective functions
    this_idx = 1
    for i, (obj_name, obj_expr) in enumerate(this_dict.items(), start=1):
        if obj_name.startswith('objective_'):
            output_string += f"# Define the objective function {this_idx}\n"
            if 'min' in obj_expr.keys():
                this_obj = obj_expr['min'].replace('\n', '')
            else:
                this_obj = obj_expr['max'].replace('\n', '')

            output_string += f"objective{this_idx} = {this_obj}\n\n"
            this_idx += 1

    # Simplify both objective functions
    output_string += "# Simplify both objective functions\n"
    output_string += "simplified_obj1 = sp.simplify(objective1)\n"
    output_string += "simplified_obj2 = sp.simplify(objective2)\n\n"

    # Check if they are equivalent
    output_string += "# Check if they are equivalent\n"
    output_string += "equivalence = sp.simplify(simplified_obj1 - simplified_obj2) == 0\n\n"
    output_string += 'print("Hypothesis are equivalent: ", equivalence)\n'

    return output_string

EQ_CNST_STRING = """
def are_constraints_equivalent(constraints1, constraints2):
    # Normalize each equation to have the form `Expr = 0`
    normalized_constraints1 = set(sp.simplify(cnst.lhs - cnst.rhs) for cnst in constraints1)
    normalized_constraints2 = set(sp.simplify(cnst.lhs - cnst.rhs) for cnst in constraints2)

    # Directly compare the two sets
    return normalized_constraints1 == normalized_constraints2

# Check if the constraints are equivalent
equivalence = are_constraints_equivalent(equality_constraints_1, equality_constraints_2)

if equivalence:
    print("Hypothesis are equivalent: True")
else:
    print("Hypothesis are equivalent: False")
"""


def dict_to_eq_const_str(this_dict):
    # Initialize the output string
    output_string = get_symbolic_par_dv(this_dict)

    for aux_const_dict in ["equality_constraints_1", "equality_constraints_2"]:
        borders_constraints  = get_borders_constraints(this_dict[aux_const_dict], check_is_constant = True,
                                                        parameter_list = list(this_dict['parameters'].keys())  )
        output_string       += get_prompt_cte_constraints(borders_constraints, this_dict, this_dict[aux_const_dict], var_type = 'simpy')

    for key in ["equality_constraints_1", "equality_constraints_2"]:
        constraints = this_dict.get(key, {})
        output_string += f"\n# {key.replace('_', ' ').capitalize()}\n"

        output_string += f'{key} = []\n'
        for cons_name, const_str in constraints.items():
            eq_const, for_loop = separate_constraint_from_for(const_str)
            output_string += f"{key} += [sp.Eq({eq_const.split('==')[0].strip()}, {eq_const.split('==')[1].strip()}) {for_loop}]\n"

    # Add the function to check for constraint equivalence
    output_string += EQ_CNST_STRING

    return output_string

def split_by_inequality(expression):
    # Updated regex pattern that accounts for possible spaces between operators
    pattern = r'\s*(<=|>=|<\s*=|>\s*=|[<>!=]=?|==|=)\s*'
    # Use regex to split the expression
    split_parts = re.split(pattern, expression, maxsplit=1)
    # The operator will be at index 1, and the expressions on either side will be at index 0 and 2
    return split_parts[0].strip(), split_parts[2].strip()


def dict_to_ineq_const_str(this_dict):
    # Initialize the output string
    output_string = get_symbolic_par_dv(this_dict)

    # Define equality constraints
    for key in ["inequality_constraints_1", "inequality_constraints_2"]:
        constraints = this_dict.get(key, {})
        output_string += f"\n# {key.replace('_', ' ').capitalize()}\n"
        output_string += f'{key} = []\n'
        for cons_name, const_str in constraints.items():
            ineq_const, for_loop = separate_constraint_from_for(const_str)
            lhs, rhs = split_by_inequality(ineq_const)
            if '<=' in ineq_const or '< =' in ineq_const or '<' in ineq_const:
                output_string += f"{key} += [sp.Eq({lhs}, {rhs}) {for_loop}]\n"
            else:
                output_string += f"{key} += [sp.Eq({rhs}, {lhs}) {for_loop}]\n"

    # Add the function to check for constraint equivalence
    aux1 = EQ_CNST_STRING.replace("equality_constraints_1", "inequality_constraints_1")
    aux1 = aux1.replace("equality_constraints_2", "inequality_constraints_2")
    output_string += aux1

    return output_string

def extract_equivalence_value(input_string):
    # Define the pattern to match the string format without angle brackets
    pattern = r"Hypothesis are equivalent:\s*(True|False)"

    # Search for the pattern in the input string
    match = re.search(pattern, input_string)

    # If a match is found, return the boolean equivalent of the matched value
    if match:
        value = match.group(1)
        if value == 'True':
            return True
        elif value == 'False':
            return False

    # If no match is found or value is not 'True' or 'False', return False
    return False


def rename_keys(d, pre_str, post_str):
    return {k.replace(pre_str, post_str): v for k, v in d.items()}

def obtain_code_compar(dict1, dict2, step, is_symbolic = False):
    dict_aux, dict2_aux = rename_keys(dict1, step, step + '_1'), rename_keys(dict2, step, step + '_2')
    dict_aux.update(dict2_aux)
    if step == 'objective':
        code_str     = dict_to_obj_str(dict_aux)
    elif step == 'equality_constraints':
        if is_symbolic:
            code_str     = dict_to_eq_const_str(dict_aux)
        else:
            code_str     = dict_to_eq_const_str_smt(dict_aux)
    elif step == 'inequality_constraints':
        if is_symbolic:
            code_str     = dict_to_ineq_const_str(dict_aux)
        else:
            code_str     = dict_to_ineq_const_str_smt(dict_aux)
    return code_str


def get_most_common_dict_index(dict_list):
    from collections import defaultdict

    def make_hashable(o):
        if isinstance(o, (list, tuple)):
            return tuple(make_hashable(e) for e in o)
        elif isinstance(o, dict):
            return tuple(sorted((make_hashable(k), make_hashable(v)) for k, v in o.items()))
        else:
            return o

    hashable_dicts = []
    index_map = defaultdict(list)
    count_map = defaultdict(int)

    for index, d in enumerate(dict_list):
        # Convert the dictionary to a hashable representation
        hashable = make_hashable(d)
        hashable_dicts.append(hashable)
        count_map[hashable] += 1
        index_map[hashable].append(index)

    max_count = max(count_map.values())
    max_count_hashables = [h for h, c in count_map.items() if c == max_count]

    if max_count > 1:
        # There is at least one dictionary that repeats
        # Pick any one of the dictionaries that repeats the most
        # Return any one index of that dictionary
        selected_hashable = max_count_hashables[0]
        selected_index = index_map[selected_hashable][0]
        return selected_index
    else:
        # No repetitions, pick the dictionary with the highest number of elements
        max_elements = -1
        selected_index = -1
        for index, d in enumerate(dict_list):
            num_elements = len(d)
            if num_elements > max_elements:
                max_elements = num_elements
                selected_index = index
        return selected_index

def filter_parameters(objects):
    if not objects:
        return [], []
    dict_list = []
    for obj in objects:
        dict_list += [obj.form_dict_eval.get('parameters', {})]
    idx_selected = get_most_common_dict_index(dict_list)
    best_object  = objects[idx_selected]
    discarded_list = [obj for obj in objects if obj != best_object]
    return [best_object], discarded_list



EQ_CNST_STRING_SMT = """
def check_equivalence_smt(system1, system2, variables):
    # input two system of linear equations

    eq_flag = True
    s = Solver()
    
    s.push()
    # check that solution to both equations in system 1 is not a solution to either equation in system 2
    s.add(And(*[eq for eq in system1]))
    s.add(Or(*[Not(eq) for eq in system2]))
    # check satisfiability
    result = s.check()
    if result == sat:
        print("Hypothesis are equivalent: False")
        return
        eq_flag=False
    s.pop()

    s.push()
    # reverse check: solution to both equations in system 2 is not a solution to either of system 1
    s.add(And(*[eq for eq in system2]))
    s.add(Or(*[Not(eq) for eq in system1]))
    result = s.check()
    if result == sat:
        print("Hypothesis are equivalent: False")
        return
        eq_flag=False
    s.pop()

    if eq_flag:
        print("Hypothesis are equivalent: True")
        return
    return eq_flag

check_equivalence_smt(system1, system2, all_variables)
"""


def get_dv_smt_str(output_string, var_name, space_index = []):
    if len(space_index) == 0:
        output_string += f"{var_name} = Reals('{var_name}')[0]\n"
        output_string += f"all_variables += [{var_name}]\n"
    elif len(space_index) == 1:
        output_string += f"{var_name} = {{i: Reals( ('{var_name}_' + str(i)).replace(' ', '_') )[0] for i in {space_index[0]}}}\n"
        output_string += f"all_variables += [Reals( ('{var_name}_' + str(i)).replace(' ', '_') )[0] for i in {space_index[0]}]\n"
    elif len(space_index) == 2:
        output_string += f"{var_name} = {{(i,j): Reals(  ('{var_name}_' + str(i) + '_' +  str(j)).replace(' ', '_') )[0] for i in {space_index[0]} for j in {space_index[1]}}}\n"
        output_string += f"all_variables += [Reals(  ('{var_name}_' + str(i) + '_' +  str(j)).replace(' ', '_') )[0]  for i in {space_index[0]} for j in {space_index[1]}]\n"
    return output_string


def get_smt_par_dv(this_dict):

    output_string = "from z3 import Solver, Reals, And, Or, sat, Not\n\n"

    # Define symbolic variables for parameters
    output_string += "# Define symbolic variables\n"

    output_string += get_param_code_str(this_dict)

    # Define decision variables
    decision_variables = this_dict.get("decision_variables", {})
    output_string += "\n# Decision Variables\n"

    output_string += "all_variables = []\n"
    for var, description in decision_variables.items():
        space_index       = extract_range_dv(description)
        var_name, is_dict = get_var_name(var)
        output_string     = get_dv_smt_str(output_string, var_name, space_index)
        #output_string    += f'{this_code_str}\n'
    return output_string


def dict_to_eq_const_str_smt(this_dict):
    # Initialize the output string
    output_string = get_smt_par_dv(this_dict)

    for aux_const_dict in ["equality_constraints_1", "equality_constraints_2"]:
        borders_constraints  = get_borders_constraints(this_dict[aux_const_dict], check_is_constant = True,
                                                       parameter_list = list(this_dict['parameters'].keys()) )
        output_string       += get_prompt_cte_constraints(borders_constraints, this_dict, this_dict[aux_const_dict], var_type = 'smt')

    dict_name = {'equality_constraints_1': 'system1', 'equality_constraints_2': 'system2'}
    for key in ["equality_constraints_1", "equality_constraints_2"]:
        constraints = this_dict.get(key, {})
        output_string += f"\n# {key.replace('_', ' ').capitalize()}\n"

        output_string += f'{dict_name[key]} = []\n'
        for cons_name, const_str in constraints.items():
            #eq_const, for_loop = separate_constraint_from_for(const_str)
            output_string += f"{dict_name[key]} += [{const_str}]\n"

    # Add the function to check for constraint equivalence
    output_string += EQ_CNST_STRING_SMT
    return output_string


def dict_to_ineq_const_str_smt(this_dict):
    # Initialize the output string
    output_string = get_smt_par_dv(this_dict)

    dict_name = {'inequality_constraints_1': 'system1', 'inequality_constraints_2': 'system2'}
    for key in ["inequality_constraints_1", "inequality_constraints_2"]:
        constraints = this_dict.get(key, {})
        output_string += f"\n# {key.replace('_', ' ').capitalize()}\n"

        output_string += f'{dict_name[key]} = []\n'
        for cons_name, const_str in constraints.items():
            #eq_const, for_loop = separate_constraint_from_for(const_str)
            output_string += f"{dict_name[key]} += [{const_str}]\n"

    # Add the function to check for constraint equivalence
    output_string += EQ_CNST_STRING_SMT
    return output_string
