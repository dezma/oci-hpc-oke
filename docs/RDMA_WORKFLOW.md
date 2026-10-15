# RDMA workflow

## Stage 0 — Resource Manager infrastructure

Resource Manager creates:

```text
private VCN and NSGs
enhanced OKE
OCI Compute Cluster
managed CPU RDMA node pool
NFD
Certificate Manager
NVIDIA Network Operator
private operator VM and Bastion
```

This stage is `INFRA_READY`, not `RDMA_VERIFIED`.

## Stage 1 — Managed-node health

The Control Center queries Kubernetes, OCI Compute, OCI Instance Agent and `SriovNetworkNodeState`.

VF creation is blocked when:

- fewer than two selected nodes are Ready;
- a required OCI RDMA plugin is not `RUNNING`;
- `SriovNetworkNodeState` is missing;
- no safe common RDMA PF exists.

## Stage 2 — PF discovery

A candidate must exist on every worker, be MLX5/Mellanox-backed, use a consistent OCI RDMA fabric MTU and have RDMA-class VF capacity. MLX5 VCN interfaces remain visible but are not approved by the normal UI.

A cross-node MTU mismatch is a node-health problem, not a configuration field to override.

## Stage 3 — Save runtime settings

The operator saves PF, MTU, VFs per node, resource name, NVIDIA IPAM pool and optional immutable validation image. Saving is non-mutating.

## Stage 4 — VF policy

Before Apply, the backend:

1. re-runs node/plugin diagnostics;
2. re-runs PF discovery;
3. verifies live MTU and VF capability;
4. identifies the CRD's `pfName`/`pfNames` schema;
5. performs a server-side dry-run;
6. requires typed approval.

## Stage 5 — Reconciliation gate

Every node must report:

```text
SriovNetworkNodeState.status.syncStatus = Succeeded
```

and advertise the expected:

```text
nvidia.com/<resource>
```

capacity.

## Stage 6 — VF network

The Control Center creates the workload namespace, NVIDIA IPAM `IPPool` and `SriovNetwork`, then waits for the generated network attachment.

## Stage 7 — Cross-node validation

Two anti-affined pods each request one VF and run without host networking or privileged mode. The verifier discovers the pod's real RDMA device and RoCE-v2 GID, checks the route/neighbor state and runs finite `ib_write_bw`.
