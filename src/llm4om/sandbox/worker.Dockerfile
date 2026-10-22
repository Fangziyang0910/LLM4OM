# Sandbox for generated model code: Python, the solver packages and worker.py.
# Build context: this directory (llm4om build-worker, or compose.yaml).
FROM python:3.12-slim
# Match the HiGHS ABI bundled with OR-Tools 9.15 (google/or-tools#5246).
# Generated code has no network and no use for pip; removing it also drops pip's own advisories from the image.
# PuLP 3.3 bundles the CBC binary. CVXPY 1.9 needs highspy 1.14, so CVXPY stays at 1.8.
RUN python -m pip install --no-cache-dir Pyomo==6.10.1 highspy==1.12.0 ortools==9.15.6755 cpmpy==1.1.0 gurobipy==13.0.3 \
    PuLP==3.3.2 cvxpy==1.8.2 clarabel==0.11.1 scipy==1.18.1 osqp==1.1.3 scs==3.3.1 \
    pyscipopt==6.3.0 casadi==3.8.1 coptpy==8.0.7 Mosek==11.2.6 \
    numpy==2.3.4 pandas==2.3.3 sympy==1.14.0 z3-solver==5.1.0.0 \
    && python -m pip uninstall -y pip
# Baked in rather than mounted: when llm4om itself runs in a container, mounts would resolve on the Docker host.
COPY worker.py /opt/llm4om/worker.py
USER 65532:65532
WORKDIR /tmp
