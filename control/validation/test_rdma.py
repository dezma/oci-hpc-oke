#!/usr/bin/env python3
"""Finite cross-node RoCE validation for the two Control Center pods."""
from __future__ import annotations

import argparse
import json
import subprocess
import time

GID_DISCOVERY = r'''
import ipaddress, json, pathlib, subprocess
rows=json.loads(subprocess.check_output(['ip','-j','-4','addr','show','dev','net1']))
ips=[a['local'] for row in rows for a in row.get('addr_info',[]) if a.get('family')=='inet']
if len(ips)!=1: raise SystemExit('expected exactly one IPv4 address on net1')
ip=ipaddress.IPv4Address(ips[0]); matches=[]
for dev in pathlib.Path('/sys/class/infiniband').glob('*'):
 for port in (dev/'ports').glob('*'):
  for gid in (port/'gids').glob('*'):
   try:
    ndev=(port/'gid_attrs/ndevs'/gid.name).read_text().strip()
    typ=(port/'gid_attrs/types'/gid.name).read_text().strip().lower()
    val=ipaddress.IPv6Address(gid.read_text().strip())
    if ndev=='net1' and typ.endswith('v2') and val.ipv4_mapped==ip:
     matches.append({'device':dev.name,'port':int(port.name),'gid':int(gid.name),'ip':str(ip)})
   except (OSError,ValueError): pass
if len(matches)!=1: raise SystemExit('expected one RoCE v2 GID for net1; found '+str(matches))
print(json.dumps(matches[0]))
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--namespace", required=True)
    args = ap.parse_args()
    base = ["kubectl", "-n", args.namespace]

    def run(tail, timeout=45, check=True):
        p = subprocess.run(base + tail, text=True, capture_output=True, timeout=timeout)
        if check and p.returncode:
            raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "kubectl failed")
        return p

    def exec_in(pod, tail, **kw):
        return run(["exec", pod, "-c", "rdma", "--", *tail], **kw)

    report = {"status": "failed", "namespace": args.namespace, "cross_node": False, "checks": []}
    server_proc = None
    try:
        records = {}
        for pod in ("rdma-server", "rdma-client"):
            records[pod] = json.loads(run(["get", "pod", pod, "-o", "json"]).stdout)
            if records[pod].get("spec", {}).get("hostNetwork"):
                raise RuntimeError(f"{pod} unexpectedly uses hostNetwork")
            if any(c.get("securityContext", {}).get("privileged") for c in records[pod]["spec"]["containers"]):
                raise RuntimeError(f"{pod} unexpectedly has a privileged container")
        nodes = [records[p]["spec"]["nodeName"] for p in records]
        if len(set(nodes)) != 2:
            raise RuntimeError("validation pods are not on two different nodes")
        report["nodes"] = nodes
        report["cross_node"] = True

        endpoints = {p: json.loads(exec_in(p, ["python3", "-c", GID_DISCOVERY]).stdout) for p in records}
        report["endpoints"] = endpoints
        server = endpoints["rdma-server"]
        client = endpoints["rdma-client"]

        route = json.loads(exec_in("rdma-client", ["ip", "-j", "route", "get", server["ip"]]).stdout)
        if not route or route[0].get("dev") != "net1":
            raise RuntimeError("peer route does not use net1")

        ping = exec_in("rdma-client", ["ping", "-I", "net1", "-c", "3", "-W", "2", server["ip"]], check=False)
        neigh = json.loads(exec_in("rdma-client", ["ip", "-j", "neigh", "show", "to", server["ip"], "dev", "net1"]).stdout)
        if not neigh or any(set(n.get("state", [])) & {"FAILED", "INCOMPLETE"} for n in neigh):
            raise RuntimeError("neighbor resolution is incomplete or failed on net1")
        report["checks"].append({"name": "neighbor", "passed": True})
        report["checks"].append({"name": "icmp", "passed": ping.returncode == 0, "note": "ICMP can be filtered independently of RDMA."})

        def perf(ep):
            return [
                "timeout", "-k", "5s", "90s", "ib_write_bw", "-R", "-F", "--report_gbits",
                "-d", ep["device"], "-i", str(ep["port"]), "-x", str(ep["gid"]),
                "-p", "18515", "-D", "10", "-s", "65536",
            ]

        server_proc = subprocess.Popen(base + ["exec", "rdma-server", "-c", "rdma", "--", *perf(server)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(2)
        if server_proc.poll() is not None:
            out = server_proc.stdout.read() if server_proc.stdout else ""
            raise RuntimeError("ib_write_bw server exited early: " + out[-1500:])
        client_run = exec_in("rdma-client", [*perf(client), server["ip"]], timeout=110, check=False)
        server_out, _ = server_proc.communicate(timeout=100)
        if client_run.returncode or server_proc.returncode:
            raise RuntimeError("ib_write_bw failed: " + (client_run.stdout + client_run.stderr + server_out)[-2500:])

        report["status"] = "passed"
        report["checks"].append({"name": "ib_write_bw", "passed": True})
        report["client_output_tail"] = client_run.stdout[-3000:]
        print(json.dumps(report))
        return 0
    except Exception as exc:
        report["error"] = str(exc)
        print(json.dumps(report))
        return 1
    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
