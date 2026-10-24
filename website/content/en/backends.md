The backend list comes from native registries in the actual solver sandbox. First check model and interface compatibility, then dependencies, executables and licenses.

## Common engine families

| Engine | Typical use and conditions |
|---|---|
| HiGHS, CBC, GLPK | Their supported LP/MIP models through compatible libraries |
| SCIP | LP/MIP; native nonlinear constraints through PySCIPOpt |
| CP-SAT | Integer, Boolean, logical and discrete scheduling models |
| Gurobi, COPT | Native mathematical programming, subject to capabilities and licensing |
| Clarabel, SCS | Compatible continuous conic models |
| OSQP | Continuous convex quadratic programming with linear constraints |
| MOSEK | Compatible mathematical programming models; requires a license |
| Ipopt | Smooth continuous nonlinear optimization, usually with local conclusions |
| Bonmin | Compatible mixed-integer nonlinear plugins through interfaces such as CasADi |
| SAT, SMT, MiniZinc and others | Native CPMpy backends, subject to installation |

This table describes families. Use the platform's current list for exact IDs and availability reasons. One engine may have different library and interface identifiers.

## AUTO, installation and errors

AUTO follows native selection for the library and returned model. Explicit selection is preserved and not replaced after failure. An LP-only backend rejects integer models.

Restart the service after changing backend dependencies or licenses to refresh its cache. A registered name does not establish a complete executable installation, and successful plugin loading does not establish commercial-license validity. GPU or separately deployed runtimes need their own environment.

## Mount licenses

Gurobi uses `GRB_LICENSE_FILE`, MOSEK uses `MOSEKLM_LICENSE_FILE`, and COPT uses `COPT_LICENSE_DIR`. Corresponding absolute host and app paths let the sandbox mount required files read-only. For example:

```yaml
services:
  app:
    volumes:
      - /opt/gurobi/gurobi.lic:/opt/gurobi/gurobi.lic:ro
      - /opt/mosek/mosek.lic:/opt/mosek/mosek.lic:ro
```

Keep only mounts you actually use and set the corresponding `.env` variables. COPT mounts its individual `license.dat` and `license.key` files. The sandbox has no network, so this deployment path needs licenses suitable for offline, container and actual usage conditions.

## Official license references

See [Gurobi documentation](https://docs.gurobi.com/projects/optimizer/en/current/), [MOSEK client setup](https://docs.mosek.com/latest/licensing/client-setup.html) and [COPT installation and licensing](https://guide.coap.online/copt/en-doc/install.html). Do not commit license files or keys. The [original deployment guide](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/deployment.md) has full container configuration.
