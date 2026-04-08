# retrieval-hub core library image.
#
# This image packages the core library only. It does not run a service. Peer
# components (retrieval-hub-mcp, retrieval-hub-ui, retrieval-hub-auth, etc.)
# will live in their own subdirectories with their own Containerfiles in
# future steps per docs/PLATFORM_COMPONENT_PATTERN.md.
#
# Build (on Mac, for OpenShift):
#   podman build --platform linux/amd64 -t retrieval-hub-core:latest \
#     -f Containerfile .

FROM registry.access.redhat.com/ubi9/python-311:latest

LABEL name="retrieval-hub-core" \
      summary="retrieval-hub core library (catalog data model, policy, schemas)" \
      io.k8s.description="Core library for retrieval-hub. Imported by peer components." \
      io.openshift.tags="retrieval-hub,catalog,python"

# UBI Python images already provide a non-root user (1001).
USER 1001

WORKDIR /opt/app-root/src

COPY --chown=1001:0 pyproject.toml README.md ./
COPY --chown=1001:0 src/ ./src/
COPY --chown=1001:0 alembic.ini ./
COPY --chown=1001:0 alembic/ ./alembic/

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

# No CMD: this image is consumed by peer components, not run as a service.
CMD ["python", "-c", "import retrieval_hub; print(retrieval_hub.__version__)"]
