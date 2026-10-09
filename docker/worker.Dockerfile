FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

WORKDIR /opt/llm4om
COPY runtime-requirements.txt /opt/llm4om/runtime-requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r runtime-requirements.txt
COPY wheels/ /opt/llm4om/wheels/
RUN python -m pip install --no-deps --no-cache-dir /opt/llm4om/wheels/llm4om-*.whl
ENV PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
ENTRYPOINT ["python", "-I", "-m", "llm4om.worker"]
