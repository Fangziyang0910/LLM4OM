# Native modeling libraries and backend plugins. Keep the common SDK layer reusable.
FROM python:3.12-slim AS core
RUN python -m pip install --no-cache-dir Pyomo==6.10.1 highspy==1.12.0 ortools==9.15.6755 gurobipy==13.0.3 \
    cvxpy==1.8.2 clarabel==0.11.1 scipy==1.18.1 osqp==1.1.3 scs==3.3.1 \
    pyscipopt==6.3.0 casadi==3.8.1 Mosek==11.2.6 \
    numpy==2.3.4 pandas==2.3.3 cma==4.6.0 pymoo==0.6.2 \
    && python -m pip uninstall -y pip

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc glpk-utils \
    && rm -rf /var/lib/apt/lists/*
COPY --from=core /usr/local /usr/local
RUN python -m ensurepip \
    && python -m pip install --no-cache-dir \
    cvxopt==1.3.3 ecos==2.0.14 daqp==0.10.3 piqp==0.6.4 proxsuite==0.7.3 qoco==0.3.2 qpalm==1.3.0 \
    cplex==22.2.0.1 xpress==9.9.1 swiglpk==5.0.13 docplex==2.32.264 \
    && python -m pip install --no-cache-dir --no-deps --target /opt/ortools-cvxpy ortools==9.14.6206 \
    && python -m pip uninstall -y pip
COPY --chmod=644 worker.py /opt/llm4om/worker.py
COPY autoco /opt/llm4om/autoco
RUN chmod -R a+rX /opt/llm4om
USER 65532:65532
WORKDIR /tmp
