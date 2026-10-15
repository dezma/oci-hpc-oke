# Managed-node diagnostics

The Control Center can query the managed RDMA nodes directly without SSH. It uses read-only Kubernetes and OCI APIs and correlates each Kubernetes node with its OCI instance.

## What the UI queries

For every node labelled `oci-rdma=true`:

```text
Kubernetes
  Ready condition
  InternalIP
  OS image / kernel / kubelet
  allocatable nvidia.com/<resource>

SriovNetworkNodeState
  syncStatus
  PF name
  driver / vendor
  MTU
  PCI address
  VF capability
  link admin state/speed when reported

OCI Compute
  instance OCID
  display name
  shape
  lifecycle state
  availability domain

OCI Instance Agent
  Compute HPC RDMA Authentication status
  Compute HPC RDMA Auto-Configuration status
```

The resulting report can be downloaded as JSON from **Managed nodes**.

## What the API cannot prove

The APIs do not expose every host-level signal. In particular, a plugin can report `RUNNING` while a per-interface authentication session or RDMA link is unhealthy.

A common unhealthy pattern is:

```text
required OCI plugins: RUNNING
SriovNetworkNodeState PF on node A: MTU 4220
same PF on node B: MTU 1500
```

The Control Center blocks VF creation in this case. Do not force the MTU or create VFs to mask the problem.

## Break-glass host inspection

The UI displays a command such as:

```bash
kubectl debug node/<node-name> \
  -it \
  --image=docker.io/library/ubuntu:24.04 \
  --profile=sysadmin \
  -- chroot /host bash
```

The fully qualified image name avoids CRI-O short-name enforcement failures.

This is a privileged diagnostic pod. The web service does not execute it.

Useful host commands:

```bash
hostname
rdma link show
ibdev2netdev 2>/dev/null || true
ip -d link show <pf>
ip addr show <pf>
cat /sys/class/net/<pf>/carrier
cat /sys/class/net/<pf>/mtu
ps -leaf | grep -E 'oci-rdma-authentication|oci-hpc-configure|wpa_supplicant' | grep -v grep
```

For a healthy `BM.Optimized3.36` RDMA path in the tested environment, the key pattern was:

```text
mlx5_2/1 state ACTIVE physical_state LINK_UP
ens800f0np0 LOWER_UP
MTU 4220
per-interface wpa_supplicant for ens800f0np0
```

Do not encode that interface/device name as a universal shape invariant; use it only to compare sibling nodes in one homogeneous node pool.

## Remediation order

1. Query **Managed nodes** again to rule out stale state.
2. Confirm both required OCI RDMA plugins are `RUNNING`.
3. Compare the same PF across all workers.
4. Use the generated break-glass command only if host inspection is required.
5. Do not manually force MTU, WPA or VF settings.
6. If one sibling node remains `NO-CARRIER`/disabled while the others are healthy, recycle only that managed node through the OKE node-pool lifecycle or open an OCI support case.
7. Return to the Control Center and rerun discovery before creating VFs.

## Optional worker SSH

The stack can install a worker public key and allow TCP/22 from the operator NSG. It is disabled by default and should not be needed for normal operation. Keep private keys on the administrator workstation and use agent forwarding rather than copying a private key onto the operator VM.
