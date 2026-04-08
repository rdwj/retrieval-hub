# OpenShift Pipelines and Tekton for AI workflows

OpenShift Pipelines, built on the upstream **Tekton** project, provides
Kubernetes-native continuous integration and continuous delivery for
workloads running on OpenShift. On OpenShift AI clusters, Tekton is
commonly used to automate data ingestion, model training, evaluation
runs, and deployment workflows.

## Why Tekton for AI pipelines

AI workflows look very different from traditional CI/CD: steps can take
hours, outputs are large artifacts (datasets, model weights, indexes),
and a single "run" may need to coordinate distributed compute across
many pods. Tekton handles these well because its primitives (`Task`,
`Pipeline`, `TaskRun`, `PipelineRun`) are built on Kubernetes resources,
so each step runs as a pod with full access to the cluster's compute,
storage, and networking.

Compared to Kubeflow Pipelines, Tekton is lighter weight and more
directly integrated with OpenShift's operator and console. Kubeflow
Pipelines is still supported on OpenShift AI for teams that want its
richer DAG-level features and its tighter coupling to notebook
workflows.

## Writing a Tekton PipelineRun

A Tekton `Pipeline` defines a DAG of `Task` steps; a `PipelineRun`
triggers an execution. For example, a simple ingestion pipeline for
retrieval-hub might look like:

```yaml
apiVersion: tekton.dev/v1
kind: Pipeline
metadata:
  name: rh-docs-ingest
spec:
  params:
    - name: source-slug
      type: string
  tasks:
    - name: fetch
      taskRef:
        name: fetch-docs
      params:
        - name: slug
          value: $(params.source-slug)
    - name: parse-and-chunk
      runAfter: [fetch]
      taskRef:
        name: parse-and-chunk
    - name: embed-and-write
      runAfter: [parse-and-chunk]
      taskRef:
        name: embed-and-write
    - name: register-source
      runAfter: [embed-and-write]
      taskRef:
        name: register-catalog-source
```

Each task runs as a separate pod with its own resource requests, its
own inputs, and its own outputs. Failed tasks can be retried
independently, and Tekton's operator surfaces execution state in the
OpenShift console.

## Triggering pipelines from events

Tekton Triggers listens for webhook events (GitHub push, Git commit,
container image update) and starts `PipelineRun`s automatically. This
is how production retrieval-hub deployments will trigger source
re-ingestion when an upstream documentation repository updates.
