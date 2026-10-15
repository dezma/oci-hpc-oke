# Security policy and operating model

## Default posture

- private OKE Kubernetes API endpoint;
- private managed RDMA workers;
- private operator VM with no public IP;
- OCI Bastion as the human ingress path;
- operator NSG and host `firewalld` both restrict TCP/8000 to the Bastion private endpoint `/32`;
- operator instance principal instead of a user API-signing key;
- optional worker SSH disabled by default;
- live RDMA pods use `hostNetwork: false`, no host PID/IPC namespaces and `privileged: false`;
- immutable validation image digest;
- explicit server-side confirmation for mutating cluster actions;
- Network Operator/SR-IOV admission controllers enabled;
- SR-IOV config daemon constrained to Linux nodes labelled `oci-rdma=true`;
- VF operations gated on live managed-node diagnostics and reconciliation.

## Operator identity

The operator dynamic group receives cluster-scoped OKE access plus narrowly scoped read access to:

```text
Compute instances
OCI Instance Agent plugin status
one immutable Object Storage payload object
```

The read-only node-diagnostics endpoint uses those APIs and Kubernetes resources. It does not SSH to nodes or execute host commands.

## Credentials and sensitive state

Terraform generates a deployment-specific workspace token. It is:

- a sensitive Resource Manager/Terraform output;
- written root-owned to `/etc/oke-rdma-control/admin.token`;
- entered into the browser and retained only in JavaScript memory.

The browser never receives OCI API private keys, user auth tokens or kubeconfig content. Treat access to Resource Manager state and break-glass operator SSH as privileged.

For broad multi-user production, replace the bootstrap token with enterprise OIDC/SSO and per-user authorization/audit.

## Runtime command boundary

The API exposes an allowlist of business operations:

- environment and preflight;
- read-only managed-node diagnostics;
- read-only SR-IOV hardware discovery;
- validated RDMA settings persistence;
- reviewed VF-policy creation;
- reviewed VF-network creation;
- finite cross-node validation;
- validation-pod cleanup.

There is no generic command, SSH, node-shell or arbitrary-manifest endpoint. `kubectl` and `oci` are invoked using argument arrays assembled by code.

## Host and network diagnostics

The UI can display a generated, fully qualified `kubectl debug` command for a human administrator. It never executes that command. Such a debug pod is privileged and should be used only as an audited break-glass action.

Optional worker SSH:

- is disabled by default;
- requires an explicit public key at provisioning time;
- creates only an operator-NSG-to-worker-NSG TCP/22 ingress rule;
- does not copy a private key onto the operator VM;
- should be used with workstation-held keys and SSH agent forwarding.

## High-risk operations

Creating or removing `SriovNetworkNodePolicy` can drain, reconfigure or reboot nodes. The normal UI:

- requires the exact environment name before creation;
- revalidates Kubernetes readiness, OCI RDMA plugin state and PF/MTU/VF capability;
- performs a server-side dry-run;
- does not expose routine policy deletion/migration.

Infrastructure destroy and managed-node replacement remain Resource Manager/OKE administrator operations.

## Supply chain

- Production operator payloads vendor pinned wheels.
- The payload is uploaded to private Object Storage and SHA-256 verified by cloud-init.
- The bootstrap OCI CLI is installed into a dedicated venv and version-checked.
- RDMA validation images must use `repository@sha256:<digest>`.
- Host OFED/kernel drivers are never installed from a workload container.

## Remaining production gates

- enterprise OIDC/SSO and role-based authorization;
- actor-aware, tamper-resistant audit export;
- signed-image policy and registry scanning;
- formal penetration and WCAG testing;
- managed database/queue for multi-replica operation;
- reviewed node-replacement and VF-policy migration runbooks.
