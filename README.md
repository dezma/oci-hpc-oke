# OCI OKE RDMA Quickstart

A Resource Manager-first quickstart for operating **CPU RDMA workloads on OCI Kubernetes Engine (OKE)**.

The stack provisions a private enhanced OKE cluster, an OCI Compute Cluster, managed bare-metal CPU RDMA workers, the native OKE Node Feature Discovery and NVIDIA Network Operator add-ons, OCI Bastion, and a private operator VM. The operator VM automatically installs and starts the **OKE RDMA Control Center**.

The supported pod networking model is intentionally narrow:

```text
OCI Compute Cluster
        |
        v
OKE managed CPU RDMA nodes
        |
        v
NVIDIA Network Operator + SR-IOV Network Operator
        |
        v
RDMA-capable SR-IOV VFs
        |
        v
unprivileged pods with hostNetwork=false
```

MacVLAN, IPvlan and generic host-device alternatives are not included. `SriovNetwork`, NVIDIA IPAM and the generated network attachment are treated as required SR-IOV/VF plumbing.

## What v1.2.0 improves

This release incorporates the operational lessons from a real first deployment:

- installs the OCI CLI in a dedicated bootstrap virtual environment and calls it by absolute path;
- sets an explicit cloud-init/systemd `PATH`;
- uses valid `oci os object get` syntax and reports bootstrap failures accurately;
- waits a bounded one-hour window for exact-instance dynamic-group/IAM convergence;
- installs Certificate Manager before NVIDIA Network Operator;
- resolves exact live OKE add-on version spellings, including leading `v` prefixes;
- configures the operator host firewall to allow TCP/8000 only from the Bastion private endpoint;
- creates shell helpers for the UI token, kubeconfig and health diagnostics;
- provides a **Managed nodes** page that queries Kubernetes, OCI Compute, OCI Instance Agent plugin state, and `SriovNetworkNodeState` without requiring SSH;
- blocks VF creation when nodes disagree on MTU, required OCI RDMA plugins are unhealthy, or the detected PF resembles a VCN/control-plane NIC rather than the RDMA fabric;
- optionally provisions a break-glass worker SSH key and the narrowly scoped operator-to-worker TCP/22 NSG rule; this is disabled by default;
- keeps the browser/API command boundary allowlisted—there is no arbitrary shell or manifest endpoint.

## Architecture and ownership boundary

```text
OCI Resource Manager
        |
        +-- VCN / private subnets / NSGs
        +-- enhanced OKE
        +-- OCI Compute Cluster
        +-- managed CPU RDMA node pool
        +-- NFD, Certificate Manager, NVIDIA Network Operator
        +-- private operator VM + OCI Bastion
        +-- IAM and immutable operator payload
                  |
                  v
          OKE RDMA Control Center
                  |
                  +-- query managed-node health
                  +-- discover/validate the RDMA PF and MTU
                  +-- configure SriovNetworkNodePolicy
                  +-- wait for VF reconciliation
                  +-- configure NVIDIA IPAM + SriovNetwork
                  +-- run finite cross-node ib_write_bw
```

| Resource Manager owns | Control Center owns |
| --- | --- |
| compartment, region, AD | live node and Oracle Cloud Agent diagnostics |
| VCN, private subnets and NSGs | PF/MTU discovery and selection |
| enhanced OKE | VF count and resource name |
| Compute Cluster | `SriovNetworkNodePolicy` |
| managed CPU RDMA node pool | VF reconciliation monitoring |
| Ubuntu HPC custom image | NVIDIA IPAM pool and `SriovNetwork` |
| OKE add-ons | cross-node RDMA validation |
| operator VM, Bastion and IAM | activity history and downloadable diagnostics |

A successful Terraform Apply means **infrastructure ready**. It does not mean RDMA traffic has been verified.

## Ubuntu OKE bootstrap values are derived

The Resource Manager form asks for:

- full OKE Kubernetes patch, for example `v1.36.4`;
- Ubuntu release: `ubuntu-noble` or `ubuntu-jammy`;
- the approved Ubuntu HPC custom-image OCID.

Terraform derives:

```text
Kubernetes minor
Ubuntu OKE repository URL
compatible oci-oke-node-all-* package
```

from an explicit compatibility map. The custom HPC image is a pasteable OCID field—not a platform-image selector—and Terraform validates image/shape/AD launch compatibility. That validation cannot prove OFED or RDMA-driver readiness.

Oracle compatibility matrix:

https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengCompatibilitymatrix_topic.htm

Ubuntu managed-node bootstrap guidance:

https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengcreatingubuntubasedworkernodes.htm

## Build the Resource Manager package

A production build vendors the pinned Python wheels used by the private operator:

```bash
./provisioning/build-orm.sh
```

Output:

```text
dist/oci-oke-rdma-quickstart-orm.zip
```

For development only, where the operator VM may install pinned dependencies over its NAT path:

```bash
OKE_RDMA_SKIP_VENDOR=1 ./provisioning/build-orm.sh
```

Output:

```text
dist/oci-oke-rdma-quickstart-orm-dev.zip
```

Do not publish the development package as a production release artifact.

## Provision through Resource Manager

Upload the release ZIP to OCI Resource Manager and review the Plan before Apply.

Primary inputs:

```text
compartment / region / availability domain
OKE patch version
Ubuntu release
Ubuntu HPC custom-image OCID
CPU RDMA shape and node count
Bastion client CIDR
```

Optional break-glass access:

```text
Enable worker SSH from operator: false by default
Worker SSH public key: required only when enabled
```

The private key remains on the administrator workstation. Normal Control Center operation does not require worker SSH.

### Add-on order

The stack installs add-ons in this order:

```text
managed RDMA nodes
        ↓
Node Feature Discovery
        ↓
Certificate Manager
        ↓
NVIDIA Network Operator
        ↓
SR-IOV Network Operator components
```

NVIDIA Network Operator receives the exact live version string returned by OKE. The Resource Manager form uses the user-friendly prefix-free spelling.

## Open the private Control Center

After Apply:

1. Run `operator_ui_bastion_session_create_command` using a public key whose private key is on your workstation.
2. Copy the SSH command returned by OCI Bastion.
3. Run the tunnel **on your workstation**, mapping local port `18000` to the operator target port `8000`.
4. Open:

```text
http://127.0.0.1:18000
```

5. Connect to the operator with the generated managed-SSH session and retrieve the token:

```bash
sudo cat /etc/oke-rdma-control/admin.token
```

The UI port is protected twice:

```text
operator NSG: Bastion private endpoint /32 -> TCP/8000
operator firewalld: same Bastion private endpoint /32 -> TCP/8000
```

Do not expose TCP/8000 directly to the internet.

### Operator shell helpers

New operator shells receive:

```bash
export KUBECONFIG=/etc/oke-rdma-control/kube/config
```

Useful commands:

```bash
oke-rdma-doctor
sudo cat /var/lib/oke-rdma-control/bootstrap-status.json
sudo cat /etc/oke-rdma-control/admin.token
curl http://127.0.0.1:8000/health/ready
kubectl get nodes -l oci-rdma=true -o wide
```

## Use the Control Center

### 1. Query managed nodes

Open **Managed nodes** and select **Query nodes**.

The API performs read-only queries and correlates:

- Kubernetes Ready state, InternalIP, OS/kernel and kubelet version;
- OCI instance OCID, shape and lifecycle state;
- OCI Instance Agent runtime state for:
  - `Compute HPC RDMA Authentication`;
  - `Compute HPC RDMA Auto-Configuration`;
- `SriovNetworkNodeState` sync state and interface inventory;
- allocatable `nvidia.com/<resource>` capacity.

The UI provides a downloadable JSON report and a fully qualified `kubectl debug` command for break-glass inspection. The web service never executes that privileged host command.

### 2. Discover the RDMA PF

Open **SR-IOV & VFs** and select **Discover hardware**.

The discovery logic is deliberately conservative because a BM node can expose several MLX5 PFs, including a VCN/control-plane PF. A normal UI candidate must:

- exist on every selected RDMA worker;
- be Mellanox/MLX5-backed;
- report one consistent MTU across workers;
- use the OCI CPU-RDMA fabric MTU range (normally `4220`, not `1500` or `9000`);
- have the highest common VF capability among the MLX5 PFs;
- not report a down/disabled administrative state when the CRD exposes it.

A `1500/4220` mismatch is treated as a node-health problem. The UI will not recommend another MLX5 port merely because it is present.

### 3. Save RDMA settings

Select and save:

```text
healthy RDMA PF
live MTU
VFs per node
nvidia.com/<resource-name>
NVIDIA IPAM IPv4 pool
immutable RDMA tools image digest (can be added later)
```

Saving settings does not modify Kubernetes or the workers.

### 4. Apply the VF policy

The action requires typing the exact environment name. Immediately before Apply, the backend re-queries node/plugin health and live PF capability, then performs a Kubernetes server-side dry-run.

The action is blocked when:

- a node is not Ready;
- a required OCI RDMA plugin is not `RUNNING`;
- no healthy common RDMA PF exists;
- MTUs disagree;
- the requested VF count exceeds the live minimum capability.

### 5. Wait for reconciliation

The workflow advances only after every selected node reports:

```text
SriovNetworkNodeState.status.syncStatus = Succeeded
```

and advertises the expected:

```text
nvidia.com/<resource-name>
```

capacity.

### 6. Create the VF network

The Control Center creates the workload namespace, NVIDIA IPAM `IPPool` and `SriovNetwork`, then waits for the generated `NetworkAttachmentDefinition`.

### 7. Validate RDMA

Configure a scanned, immutable image reference:

```text
fra.ocir.io/<namespace>/rdma-tools@sha256:<digest>
```

The finite two-pod profile verifies:

- different worker-node placement;
- one VF allocated to each pod;
- `hostNetwork: false` and `privileged: false`;
- route and neighbor state over `net1`;
- the actual VF-backed RDMA device and RoCE-v2 GID;
- a finite `ib_write_bw` server/client run.

ICMP failure alone is not treated as proof of RDMA failure.

## Node-health failure example

If one worker reports:

```text
Compute HPC RDMA plugins: RUNNING
RDMA PF on one node: MTU 4220
same PF on another: MTU 1500
```

then do not configure VFs. Use **Managed nodes** to export diagnostics, and use the displayed break-glass command only if host inspection is required. A per-interface authentication or fabric failure can leave the plugin process running while the RDMA link remains down. In that case, recycle only the unhealthy managed node rather than forcing MTU/VF configuration from the application.

See `docs/NODE_DIAGNOSTICS.md`.

## Security model

See `SECURITY.md` and `docs/THREAT_MODEL.md`.

Core boundary:

```text
administrator workstation
      |
      | time-limited OCI Bastion session
      v
private operator VM
      |
      | instance principal + private OKE endpoint
      v
OKE control plane
      |
      | reviewed SR-IOV/VF resources
      v
non-host-network, non-privileged RDMA workload pods
```

No OCI user API key, private key or kubeconfig is accepted in the browser.

## Validation

Run:

```bash
./provisioning/validate.sh
```

The local checks cover Python/API behavior, UI JavaScript syntax, shell syntax, YAML parsing and project-contract controls. Terraform provider validation also runs when Terraform has been initialized.

Live OCI creation, shape capacity, custom Ubuntu HPC image readiness, add-on reconciliation and actual RDMA traffic must still be validated in the target tenancy.

## Repository layout

```text
oci-oke-rdma-quickstart/
├── control/
│   ├── app/                  FastAPI API and durable worker
│   ├── validation/           finite cross-node RDMA verifier
│   └── web/                  responsive Control Center
├── docs/
│   ├── ARCHITECTURE.md
│   ├── NODE_DIAGNOSTICS.md
│   ├── RDMA_WORKFLOW.md
│   ├── REPROVISION_CHECKLIST.md
│   ├── SECURITY / threat and production guidance
│   └── SOURCES.md
├── provisioning/
├── terraform/
│   ├── operator/             managed-node and operator bootstrap templates
│   └── schema.yaml           Resource Manager UX
├── tests/
└── workloads/rdma-tools/
```

## Current limitations

- no public UI or enterprise SSO/RBAC;
- no automatic boot-volume replacement;
- no arbitrary host-shell execution from the UI;
- no automatic VF-policy deletion/migration;
- no automatic managed-node replacement;
- no fabricated capacity, cost or performance claims;
- release builds require a trusted environment with package-repository access to vendor Python wheels.
