# Native modeling libraries and backend plugins. Keep the common SDK layer reusable.
FROM python:3.12-slim AS core
RUN python -m pip install --no-cache-dir Pyomo==6.10.1 highspy==1.12.0 ortools==9.15.6755 cpmpy==1.1.0 gurobipy==13.0.3 \
    PuLP==3.3.2 cvxpy==1.8.2 clarabel==0.11.1 scipy==1.18.1 osqp==1.1.3 scs==3.3.1 \
    pyscipopt==6.3.0 casadi==3.8.1 coptpy==8.0.7 Mosek==11.2.6 \
    numpy==2.3.4 pandas==2.3.3 sympy==1.14.0 z3-solver==5.1.0.0 \
    && python -m pip uninstall -y pip

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc glpk-utils minizinc default-jre-headless build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=core /usr/local /usr/local
# GCS's published source installer otherwise clones the JSON repository's entire history.
ADD --checksum=sha256:0dbc5e40a01ff142e7e68c03e85247a4dcede2f592d12d3677dee3664d17975a \
    https://codeload.github.com/nlohmann/json/tar.gz/9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03 /tmp/gcs-json.tar.gz
RUN mkdir /tmp/gcs-json && tar -xzf /tmp/gcs-json.tar.gz --strip-components=1 -C /tmp/gcs-json \
    && python -m ensurepip \
    && python -m pip install --no-cache-dir \
    cvxopt==1.3.3 ecos==2.0.14 cylp==0.94.0 daqp==0.10.3 piqp==0.6.4 proxsuite==0.7.3 qoco==0.3.2 qpalm==1.3.0 \
    python-sat==1.9.dev17 pysdd==1.0.6 exact==2.2.1 pychoco==0.4.0 pumpkin-solver==0.5.0 pindakaas==0.6.1 \
    minizinc==0.10.0 cplex==22.2.0.1 xpress==9.9.1 swiglpk==5.0.13 docplex==2.32.264 \
    && CMAKE_BUILD_PARALLEL_LEVEL=2 python -m pip install --no-cache-dir gcspy==0.1.9 \
       --config-settings=cmake.define.FETCHCONTENT_SOURCE_DIR_JSON=/tmp/gcs-json \
    && python -m pip install --no-cache-dir --no-deps --target /opt/ortools-cvxpy ortools==9.14.6206 \
    && python -m pip uninstall -y pip \
    && rm -rf /tmp/gcs-json /tmp/gcs-json.tar.gz
COPY worker.py /opt/llm4om/worker.py
USER 65532:65532
WORKDIR /tmp
