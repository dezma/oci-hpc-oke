FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    perftest rdma-core ibverbs-utils libibverbs1 ibverbs-providers \
    iproute2 iputils-ping python3 ca-certificates coreutils \
    && rm -rf /var/lib/apt/lists/*
# User-space tools only; host RDMA drivers remain owned by the OKE worker image/operator.
CMD ["sleep", "infinity"]
