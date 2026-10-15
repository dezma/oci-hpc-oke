# Architecture

## Provisioning plane

OCI Resource Manager is the sole infrastructure state owner. It creates the VCN, private subnets/NSGs, Bastion, operator VM, enhanced OKE cluster, OCI Compute Cluster, managed RDMA node pool, OKE add-ons, operator identity and private application artifact bucket.

The Control Center does not run Terraform Apply or Destroy against its own stack.

## Runtime plane

The private operator VM hosts:

```text
FastAPI API
single durable worker
SQLite job/event state
OCI CLI and kubectl
private OKE kubeconfig using instance-principal auth
responsive Control Center UI
```

The UI is reached only through OCI Bastion port forwarding.

## Managed-node diagnostics plane

The read-only node query combines:

```text
Kubernetes node API
SriovNetworkNodeState
OCI Compute instance API
OCI Instance Agent plugin API
```

It does not use SSH or execute privileged host commands. A generated break-glass `kubectl debug` command is shown to the human operator when host-level evidence is necessary.

## RDMA data plane

```text
OCI RDMA PF
  -> SriovNetworkNodePolicy
  -> SR-IOV VF
  -> nvidia.com/<resource>
  -> SriovNetwork + NVIDIA IPAM
  -> pod net1
  -> VF-backed mlx5 device / RoCE v2
```

The normal workload boundary remains:

```text
hostNetwork=false
hostPID=false
hostIPC=false
privileged=false
automountServiceAccountToken=false
```

## Durable job model

Mutating actions are enqueued in SQLite and claimed by a separate worker using a lease. Browser refreshes do not rerun node-changing operations. The current model is intentionally single-operator/single-instance; multi-replica production requires a managed DB and queue.
