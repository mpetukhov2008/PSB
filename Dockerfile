FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/psb
RUN useradd --uid 10001 --create-home assistant
COPY --chown=assistant:assistant psb ./psb
COPY --chown=assistant:assistant samples/psb-demo.json ./samples/psb-demo.json
COPY --chown=assistant:assistant solution.py ./solution.py
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"
CMD ["python", "-m", "psb.server", "--host", "0.0.0.0", "--port", "8080"]
