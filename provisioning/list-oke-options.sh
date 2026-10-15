#!/usr/bin/env bash
set -euo pipefail
: "${OCI_REGION:?Set OCI_REGION}"
: "${COMPARTMENT_OCID:?Set COMPARTMENT_OCID}"

printf '%s\n' '--- OKE Kubernetes versions ---'
oci ce cluster-options get --cluster-option-id all --compartment-id "$COMPARTMENT_OCID" --region "$OCI_REGION" \
  --query 'data."kubernetes-versions"' --output table || true

if [[ -n "${KUBERNETES_VERSION:-}" ]]; then
  printf '%s\n' "--- Add-ons for $KUBERNETES_VERSION ---"
  oci ce addon-option list --kubernetes-version "$KUBERNETES_VERSION" --region "$OCI_REGION" --all \
    --query 'data[].{name:name,description:description,state:state}' --output table
fi

if [[ -n "${AVAILABILITY_DOMAIN:-}" ]]; then
  printf '%s\n' "--- Shapes in $AVAILABILITY_DOMAIN ---"
  oci compute shape list --compartment-id "$COMPARTMENT_OCID" --availability-domain "$AVAILABILITY_DOMAIN" --region "$OCI_REGION" --all \
    --query 'data[?contains(shape, `BM.`)].{shape:shape,ocpus:ocpus,memory:"memory-in-gbs"}' --output table
fi
