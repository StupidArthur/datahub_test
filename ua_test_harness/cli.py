"""ua_test_harness CLI。

旧子命令(保留,迁移期):os / mock / provision / all
新子命令(plan.md 5.1):
  catalog  export --output <path> [--package ua_test_harness.tests]
  run      --config <run-config.json>
            [--cases id1,id2] [--chapters ch1,ch2] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _creds(args) -> tuple[str, str, str, str]:
    base = args.base_url or os.environ.get("DATAHUB_BASE_URL", "")
    user = args.user or os.environ.get("DATAHUB_USER", "")
    pwd = os.environ.get("DATAHUB_PASSWORD", "")
    tenant = args.tenant or ""
    return base, user, pwd, tenant


def _pick_local_ip(ips: list[str]) -> str:
    for ip in ips:
        if ip.startswith("10."):
            return ip
    for ip in ips:
        if ip.startswith("172."):
            return ip
    return ips[0] if ips else ""


def cmd_os(args) -> int:
    from ua_test_harness.env.os_env import scan_ports, list_local_ips, check_connectivity
    print("== 端口 18960~18969 ==")
    for p in scan_ports():
        flag = f"占用 pid={p.pid}({p.process})" if p.in_use else "空闲"
        print(f"  {p.port}: {flag}")
    print("== 本地 IP ==")
    for ip in list_local_ips():
        print(f"  {ip}")
    if args.check_conn:
        base, user, pwd, tenant = _creds(args)
        if not pwd:
            print("== 连通性 ==\n  跳过(DATAHUB_PASSWORD 未设置)")
        else:
            ok, msg = check_connectivity(base, user, pwd, tenant)
            print(f"== 连通性 ==\n  ok={ok} {msg}")
    return 0


def cmd_mock(args) -> int:
    from ua_test_harness.env.mock_manager import MockManager, all_specs
    mgr = MockManager()
    specs = {s.key: s for s in all_specs()}
    if args.action == "list":
        for s in all_specs():
            print(f"  {s.key:12s} {s.name} port={s.port} nodes={s.node_count} status={mgr.status(s.key)}")
    elif args.action == "status":
        for s in all_specs():
            print(f"  {s.key}: {mgr.status(s.key)}")
    elif args.action == "start":
        spec = specs[args.key]
        rt = mgr.start(spec)
        print(f"started {spec.key} pid={rt.pid} endpoint={spec.endpoint} nodes={spec.node_count}")
    elif args.action == "stop":
        mgr.stop(args.key)
        print(f"stopped {args.key} status={mgr.status(args.key)}")
    return 0


def cmd_provision(args) -> int:
    import time
    from ua_test_harness.env.subject import parse_subject_url, login_subject
    from ua_test_harness.env.mock_manager import MockManager, all_specs
    from ua_test_harness.env.ds_provision import provision, tag_specs_from_mock

    base, user, pwd, tenant = _creds(args)
    if not pwd:
        print("DATAHUB_PASSWORD 未设置,无法登录")
        return 2
    sub = parse_subject_url(base)
    print(f"被测对象: base={sub.base_url} protocol={sub.protocol} tenant={sub.tenant_id!r}")
    api = login_subject(sub.base_url, user, pwd, tenant)
    print("登录 OK")

    mgr = MockManager()
    if args.mock_key == "performance":
        from ua_test_harness.env.mock_manager import build_performance
        spec = build_performance(args.poll_n, args.write_n, args.ratio)
    else:
        spec = {s.key: s for s in all_specs()}[args.mock_key]
    if mgr.status(spec.key) != "running":
        rt = mgr.start(spec)
        print(f"mock {spec.key} started pid={rt.pid} local_endpoint={spec.endpoint}")
        time.sleep(3)

    from ua_config_builder import endpoint_for
    from ua_test_harness.env.os_env import list_local_ips
    local_ip = args.local_ip or _pick_local_ip(list_local_ips())
    tpt_endpoint = endpoint_for(local_ip, spec.port)
    print(f"TPT 视角 endpoint: {tpt_endpoint} (local_ip={local_ip})")

    tag_specs = tag_specs_from_mock(spec, frequency=args.frequency)
    smoke_tag = next((s.name for s in tag_specs
                      if s.mocker_type == "Double" and s.writable), None)

    def confirm(count: int, names: list[str]) -> bool:
        print(f"  重名位号 {count} 个,前 10: {names}")
        if args.yes_delete:
            print("  --yes-delete -> 自动彻底删除")
            return True
        print("  不删(加 --yes-delete 可自动删);重名位号 add_tag 可能报错")
        return False

    r = provision(api, ds_name=args.ds_name, endpoint=tpt_endpoint,
                  tag_specs=tag_specs, confirm_delete=confirm,
                  smoke_tag=smoke_tag, frequency=args.frequency)
    print(f"ds_id={r.ds_id} reused={r.ds_reused} alive={r.ds_alive}")
    print(f"  added={len(r.tags_added)} skipped={len(r.tags_skipped_unsupported)} "
          f"failed={len(r.tags_failed)} deleted={len(r.tags_deleted)}")
    if r.tags_skipped_unsupported:
        print(f"  skipped(String/DateTime): {r.tags_skipped_unsupported[:5]}...")
    if r.tags_failed:
        print(f"  failed(前5): {r.tags_failed[:5]}")
    print(f"  smoke({smoke_tag}): {r.smoke}")

    if not args.keep:
        mgr.stop(spec.key)
        print(f"mock {spec.key} stopped")
    return 0


def cmd_all(args) -> int:
    cmd_os(args)
    print()
    args.action = "start"
    args.key = args.mock_key
    cmd_mock(args)
    print()
    cmd_provision(args)
    return 0


# ------- 新增子命令 --------------------------------------------------
def cmd_catalog(args) -> int:
    from ua_test_harness.catalog import export_catalog
    pkg = args.package or "ua_test_harness.tests"
    cat = export_catalog(args.output, package=pkg)
    n_cases = sum(len(ch["cases"]) for ch in cat["chapters"])
    print(f"catalog written: {args.output} chapters={len(cat['chapters'])} cases={n_cases}")
    return 0


def cmd_run(args) -> int:
    from ua_test_harness.catalog import discover, all_defs
    from ua_test_harness.config import RunConfig
    from ua_test_harness.runner import Runner

    discover(args.package)
    defs = list(all_defs())

    cli_explicit = False
    selected: list = []
    if args.cases:
        cli_explicit = True
        ids = {s.strip() for s in args.cases.split(",") if s.strip()}
        if not ids:
            print("--cases provided but parsed empty", file=sys.stderr)
            return 2
        selected = [d for d in defs if d.id in ids]
        if not selected:
            print(f"--cases matched no cases: {sorted(ids)}", file=sys.stderr)
            return 2
    elif args.chapters:
        cli_explicit = True
        chs = {s.strip() for s in args.chapters.split(",") if s.strip()}
        if not chs:
            print("--chapters provided but parsed empty", file=sys.stderr)
            return 2
        selected = [d for d in defs if d.chapter in chs]
        if not selected:
            print(f"--chapters matched no cases: {sorted(chs)}", file=sys.stderr)
            return 2

    if args.dry_run:
        if not selected:
            selected = list(defs)
        for d in selected:
            print(f"  planned: {d.id:18s} {d.title} [{d.kind}] file={d.file_path}:{d.lineno}")
        print(f"dry-run: {len(selected)} cases")
        return 0

    if not args.config:
        print("--config required for non dry-run mode", file=sys.stderr)
        return 2
    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"run-config not found: {cfg_path}", file=sys.stderr)
        return 2
    cfg = RunConfig.load(cfg_path)

    if not selected:
        cfg_ids = list(cfg.selected_case_ids or [])
        if cfg_ids:
            ids = set(cfg_ids)
            selected = [d for d in defs if d.id in ids]
            if not selected:
                print(
                    f"config selectedCaseIds matched no cases: {sorted(ids)}",
                    file=sys.stderr,
                )
                return 2
        elif cli_explicit:
            print("explicit selector matched nothing", file=sys.stderr)
            return 2
        else:
            selected = list(defs)

    runner = Runner(cfg, cases=selected)
    return runner.run()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ua_test_harness")
    p.add_argument("--base-url", default=None)
    p.add_argument("--user", default=None)
    p.add_argument("--tenant", default="")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("os", help="OS 环境检测")
    po.add_argument("--check-conn", action="store_true", help="顺带测连通性(需密码 env)")
    po.set_defaults(func=cmd_os)

    pm = sub.add_parser("mock", help="ua-server-mock 管理")
    pm.add_argument("action", choices=["list", "start", "stop", "status"])
    pm.add_argument("key", nargs="?", default="functional",
                    choices=["functional", "reconnect", "performance", "abnormal"])
    pm.set_defaults(func=cmd_mock)

    pp = sub.add_parser("provision", help="数据源组态(需登录)")
    pp.add_argument("--mock-key", default="functional",
                    choices=["functional", "reconnect", "performance", "abnormal"])
    pp.add_argument("--ds-name", default="ua_test_harness_functional")
    pp.add_argument("--frequency", type=int, default=10, help="采样周期(秒)")
    pp.add_argument("--keep", action="store_true", help="结束后保留 mock")
    pp.add_argument("--yes-delete", action="store_true", help="自动彻底删除重名位号(非交互)")
    pp.add_argument("--local-ip", default=None, help="TPT 连 mock 用的本机 IP(默认自动选 10.x)")
    pp.add_argument("--poll-n", type=int, default=10000, help="性能测试:轮询位号数")
    pp.add_argument("--write-n", type=int, default=1000, help="性能测试:可写位号数")
    pp.add_argument("--ratio", type=float, default=0.9, help="性能测试:可写中 Double 占比")
    pp.set_defaults(func=cmd_provision)

    pa = sub.add_parser("all", help="全链路")
    pa.add_argument("--mock-key", default="functional")
    pa.add_argument("--ds-name", default="ua_test_harness_functional")
    pa.add_argument("--frequency", type=int, default=10)
    pa.set_defaults(func=cmd_all)

    pc = sub.add_parser("catalog", help="导出 catalog.json")
    pc.add_argument("--output", required=True, help="输出文件路径")
    pc.add_argument("--package", default="ua_test_harness.tests", help="扫描包(默认 ua_test_harness.tests)")
    pc.set_defaults(func=cmd_catalog)

    pr = sub.add_parser("run", help="执行已配置 run-config 的用例")
    pr.add_argument("--config", default=None, help="run-config.json 路径(非 dry-run 必填)")
    pr.add_argument("--cases", default=None, help="逗号分隔 caseId(覆盖 config)")
    pr.add_argument("--chapters", default=None, help="逗号分隔 chapter(覆盖 config)")
    pr.add_argument("--package", default="ua_test_harness.tests", help="扫描包")
    pr.add_argument("--dry-run", action="store_true", help="只列出将执行的用例,不执行")
    pr.set_defaults(func=cmd_run)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()