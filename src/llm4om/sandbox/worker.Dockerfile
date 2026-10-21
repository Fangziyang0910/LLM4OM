# Sandbox for generated model code. llm4om mounts worker.py read-only at run time,
# so this image only needs Python and the solver packages.
FROM python:3.12-slim
# Match the HiGHS ABI bundled with OR-Tools 9.15 (google/or-tools#5246).
RUN python -m pip install --no-cache-dir Pyomo==6.10.1 highspy==1.12.0 ortools==9.15.6755 cpmpy==1.1.0 gurobipy==13.0.3 \
    numpy==2.3.4 pandas==2.3.3 sympy==1.14.0 z3-solver==5.1.0.0
USER 65532:65532
WORKDIR /tmp
