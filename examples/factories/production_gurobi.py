"""Hand-authored native gurobipy fixture; public CSV data, no self-reported solution."""

import csv
import io
import gurobipy as gp
from llm4om.backends import ModelHandle


def build_model(data):
    products = list(csv.DictReader(io.StringIO(data["products"].decode("utf-8"))))
    capacities = list(csv.DictReader(io.StringIO(data["capacities"].decode("utf-8"))))
    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 0)
    env.setParam("LogFile", "")
    env.start()
    model = gp.Model(env=env)
    qty = {row["product_id"]: model.addVar(lb=0, vtype=gp.GRB.INTEGER, name="qty_" + row["product_id"])
           for row in products}
    model.setObjective(gp.quicksum(float(row["profit"]) * qty[row["product_id"]] for row in products), gp.GRB.MAXIMIZE)
    for capacity in capacities:
        model.addConstr(gp.quicksum(float(row[capacity["resource_id"]]) * qty[row["product_id"]]
                                   for row in products) <= float(capacity["capacity"]))
    return ModelHandle(model, {"qty_" + key: var for key, var in qty.items()})
