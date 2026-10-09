"""Hand-authored parameterized Pyomo fixture, not a real LLM response."""

import csv
import io
import pyomo.environ as pyo
from llm4om.backends import ModelHandle


def build_model(data):
    products = list(csv.DictReader(io.StringIO(data["products"].decode("utf-8"))))
    capacities = list(csv.DictReader(io.StringIO(data["capacities"].decode("utf-8"))))
    model = pyo.ConcreteModel()
    model.qty = pyo.Var([row["product_id"] for row in products], domain=pyo.NonNegativeIntegers)
    model.profit = pyo.Objective(
        expr=sum(float(row["profit"]) * model.qty[row["product_id"]] for row in products), sense=pyo.maximize)
    model.capacities = pyo.ConstraintList()
    for capacity in capacities:
        model.capacities.add(sum(float(row[capacity["resource_id"]]) * model.qty[row["product_id"]]
                                 for row in products) <= float(capacity["capacity"]))
    return ModelHandle(model, {"qty_" + row["product_id"]: model.qty[row["product_id"]] for row in products})
