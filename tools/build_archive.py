"""Архив для передачи клиенту: python -m tools.build_archive → dist/epidemic-bot.tar.gz

Внутри только то, что нужно для запуска через Docker Compose. Файл .env (токен!), база, тесты,
документация для разработчиков и локальные зависимости в архив не попадают.
"""
from __future__ import annotations

import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ["Dockerfile", "docker-compose.yml", ".dockerignore", ".env.example", "requirements.txt", "README.md",
           "epidemic", "tools", "media"]
OUT = ROOT / "dist" / "epidemic-bot.tar.gz"


def _keep(path: Path) -> bool:
    return "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo") and path.name != ".env"


def _normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mode = 0o755 if info.isdir() else 0o644
    return info


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    with tarfile.open(OUT, "w:gz") as tar:
        for name in INCLUDE:
            path = ROOT / name
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for file in files:
                if _keep(file):
                    tar.add(file, arcname=f"epidemic-bot/{file.relative_to(ROOT).as_posix()}", filter=_normalize)
    with tarfile.open(OUT) as tar:
        names = tar.getnames()
    if any(n.endswith("/.env") for n in names):
        raise SystemExit("В архив попал .env с токеном — архив не годится")
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size // 1024} КБ, файлов: {len(names)}")


if __name__ == "__main__":
    main()
