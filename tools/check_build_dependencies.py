"""Refuse a release build when its Python environment violates requirements."""
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def requirement_lines(path, seen=None):
    seen = set() if seen is None else seen
    path = Path(path).resolve()
    if path in seen:
        return
    seen.add(path)
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if line.startswith('-r '):
            yield from requirement_lines(path.parent / line[3:].strip(), seen)
        elif line:
            yield line


def mismatches(lines, lookup=metadata.version):
    problems = []
    for line in lines:
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = lookup(requirement.name)
        except metadata.PackageNotFoundError:
            problems.append(f'{requirement.name}: missing; requires {requirement.specifier}')
            continue
        if installed not in requirement.specifier:
            problems.append(f'{requirement.name}: found {installed}; requires {requirement.specifier}')
    return problems


def main():
    problems = mismatches(requirement_lines(ROOT / 'requirements-dev.txt'))
    if problems:
        print('Build dependencies do not match requirements:\n' + '\n'.join(problems))
        return 1
    print('Build dependencies satisfy requirements')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
