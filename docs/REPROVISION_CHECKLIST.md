# Reprovision checklist

Use this checklist for a clean lab reprovision.

## Before destroying the old stack

- Export any useful Resource Manager Plan/Apply logs.
- Download Control Center node-diagnostics JSON and RDMA validation reports.
- Record the tested Ubuntu HPC image OCID and image build provenance.
- Confirm no workload results or local NVMe data need preservation.
- Destroy through the same Resource Manager stack/state owner.
- Verify the Compute Cluster, OKE cluster, node pool, Bastion, operator VM, artifact bucket, dynamic group and policies are deleted as expected.

## Image prerequisites

The Ubuntu HPC image should contain:

- cloud-init;
- Oracle Cloud Agent with automatic updates enabled;
- the compatible host kernel/RDMA/OFED stack;
- no stale OKE cluster identity;
- no embedded user credentials or kubeconfig;
- support for the selected bare-metal shape.

Resource Manager injects the matching Oracle Ubuntu OKE repository and `oci-oke-node-all-*` package, then runs `oke bootstrap`.

## Resource Manager inputs

- correct compartment and region;
- AD with CPU RDMA capacity;
- full supported OKE patch;
- matching Ubuntu release;
- approved custom-image OCID;
- CPU RDMA shape and at least two workers;
- workstation/VPN `/32` or narrow Bastion client CIDR;
- optional worker SSH disabled unless break-glass access is explicitly needed.

## Plan review

Confirm the Plan creates:

```text
VCN and private subnets
OCI Compute Cluster
enhanced OKE cluster
managed node pool with compute_cluster_id
NFD
Certificate Manager
NVIDIA Network Operator
private operator VM
OCI Bastion
scoped IAM and private artifact bucket
```

Confirm it does not expose the operator or OKE API publicly.

## First-boot checks

After Apply:

```bash
sudo cat /var/lib/oke-rdma-control/bootstrap-status.json
sudo systemctl status oke-rdma-control-api.service --no-pager -l
sudo systemctl status oke-rdma-control-worker.service --no-pager -l
curl http://127.0.0.1:8000/health/ready
```

The bootstrap now handles the OCI CLI path, valid Object Storage download syntax, IAM convergence, host firewall and shell kubeconfig automatically.

## Control Center checks

1. Create the Bastion UI session with the workstation public key.
2. Run the returned tunnel on the workstation using local port `18000`.
3. Open `http://127.0.0.1:18000`.
4. Retrieve the token with `sudo cat /etc/oke-rdma-control/admin.token`.
5. Run **Query nodes**.
6. Require all nodes Ready and both OCI RDMA plugins `RUNNING`.
7. Run **Discover hardware**.
8. Do not continue unless one healthy common RDMA PF is recommended with consistent fabric MTU.
9. Save settings, approve the VF policy, wait for reconciliation, then create the VF network.
10. Run finite cross-node validation using an immutable image digest.
