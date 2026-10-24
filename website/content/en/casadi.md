CasADi uses symbolic expressions and native plugins for optimization. A common path is Opti with Ipopt for smooth continuous nonlinear models.

## Supported interfaces

The platform supports Opti NLP, Opti Conic and native problem dictionaries for `nlpsol`, `qpsol` and `conic`. Opti returns a model; low-level APIs also need problem structure, numerical arguments, optional plugin and options. Variables follow native ordering.

## Select it in the platform

Choose CasADi, commonly with the Ipopt default. Use smooth expressions and meaningful bounds and initial guesses from the problem. Integer domains require a compatible plugin such as Bonmin; Ipopt is not an integer solver.

The platform discovers plugins and checks loading through native CasADi facilities. A loadable plugin does not validate a commercial license. Plugin-specific parameters still follow the native API.

## Maximization and statuses

For maximization through CasADi's minimization interface, minimize the negative objective and return `objective_sign: -1` so the platform restores the original value:

```python
return {"model": model, "objective_sign": -1}
```

For nonconvex problems, Ipopt generally provides local conclusions. `locally_optimal` is not a global certificate, and local infeasibility does not prove the entire problem infeasible. The result page preserves these meanings.

## Official references

See the [CasADi documentation](https://web.casadi.org/docs/) and [plugin API](https://web.casadi.org/python-api/). If a global conclusion is required, select a suitable global solving approach and check the plugin's actual capabilities in the deployment.
