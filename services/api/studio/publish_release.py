"""发版工具：把桌面安装包上传到 S3 并登记 ``releases`` 表。

只维护 Win x64 + Mac arm64。安装包字节进 S3 ``releases/<version>/<filename>``，
表里存元数据 + 当前指针（``is_latest`` 每平台至多一行）。发新版 = 上传 + 插一行
（``--latest`` 时把旧的 latest 翻掉、本行置上，同一事务）；回滚 = ``promote`` 把
旧版本重新置为 latest（无需重传）。

不直接调用——用 ``scripts/publish-release.sh <env-file> <subcommand> [args]`` 包装，
它负责把本命令跑在 compose 网络里并把 ``--file`` 挂进容器：

    scripts/publish-release.sh .env.release list
    scripts/publish-release.sh .env.release publish \\
        --version 0.1.0 --platform win --file ~/builds/Laborster-Setup-0.1.0.exe --latest
    scripts/publish-release.sh .env.release promote --version 0.0.9 --platform win
"""

import argparse
import hashlib
import os
import sys
from uuid import uuid4

from studio.db import SessionLocal, utc_now
from studio.models import Release
from studio.s3 import S3_BUCKET, _s3_client

PLATFORMS = ("win", "mac")
_CHUNK = 1024 * 1024


def _sha256_and_size(path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _clear_latest(db, platform: str) -> None:
    db.query(Release).filter(
        Release.platform == platform, Release.is_latest.is_(True)
    ).update({"is_latest": False}, synchronize_session=False)


def cmd_publish(args) -> int:
    if not os.path.isfile(args.file):
        print(f"文件不存在: {args.file}", file=sys.stderr)
        return 2
    filename = os.path.basename(args.file)
    sha256, size = _sha256_and_size(args.file)
    s3_key = f"releases/{args.version}/{filename}"

    db = SessionLocal()
    try:
        if db.query(Release).filter_by(version=args.version, platform=args.platform).first():
            print(
                f"已存在 {args.version} ({args.platform})——版本不可覆盖。"
                f"提升版本号，或用 promote 切换 latest。",
                file=sys.stderr,
            )
            return 1

        # 先上传字节，成功后再登记，避免 DB 有行而 S3 没文件。
        _s3_client.upload_file(args.file, S3_BUCKET, s3_key)

        now = utc_now()
        if args.latest:
            _clear_latest(db, args.platform)
        db.add(Release(
            id=f"rel_{uuid4().hex}",
            version=args.version,
            platform=args.platform,
            s3_key=s3_key,
            filename=filename,
            sha256=sha256,
            size_bytes=size,
            notes=args.notes,
            is_latest=bool(args.latest),
            created_at=now,
            published_at=now,
        ))
        db.commit()
    finally:
        db.close()

    print(
        f"已发布 {args.version} ({args.platform})  latest={bool(args.latest)}  "
        f"{size/1e6:.1f}MB  sha256={sha256[:12]}…  s3://{S3_BUCKET}/{s3_key}"
    )
    return 0


def cmd_promote(args) -> int:
    db = SessionLocal()
    try:
        rel = db.query(Release).filter_by(version=args.version, platform=args.platform).first()
        if not rel:
            print(f"没有 {args.version} ({args.platform})，先 publish。", file=sys.stderr)
            return 1
        if rel.is_latest:
            print(f"{args.version} ({args.platform}) 已经是 latest。")
            return 0
        _clear_latest(db, args.platform)
        rel.is_latest = True
        db.commit()
    finally:
        db.close()
    print(f"已将 {args.version} ({args.platform}) 设为 latest。")
    return 0


def cmd_list(args) -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(Release)
            .order_by(Release.platform.asc(), Release.published_at.desc())
            .all()
        )
    finally:
        db.close()
    if not rows:
        print("（暂无任何发布版本，下载端点会返回 404）")
        return 0
    print(f"{'latest':<7}{'平台':<6}{'版本':<12}{'大小':>10}  发布时间            文件")
    for r in rows:
        print(
            f"{'  *' if r.is_latest else '':<7}{r.platform:<6}{r.version:<12}"
            f"{r.size_bytes/1e6:>8.1f}MB  {r.published_at:%Y-%m-%d %H:%M}  {r.filename}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="studio.publish_release")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("publish", help="上传安装包并登记一个新版本")
    p.add_argument("--version", required=True, help="版本号，如 0.1.0")
    p.add_argument("--platform", required=True, choices=PLATFORMS)
    p.add_argument("--file", required=True, help="容器内安装包路径")
    p.add_argument("--notes", default=None, help="发布说明（可选）")
    p.add_argument("--latest", action="store_true", help="设为该平台当前最新")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("promote", help="把已有版本切为 latest（回滚/前滚开关）")
    p.add_argument("--version", required=True)
    p.add_argument("--platform", required=True, choices=PLATFORMS)
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("list", help="列出所有版本")
    p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
