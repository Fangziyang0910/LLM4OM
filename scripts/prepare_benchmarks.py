"""Bundle OPT-Agent's existing public benchmark inputs; no runtime imports or downloads."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def write(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    path.write_bytes(raw)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True, help='Local OPT-Agent repository')
    source = parser.parse_args().source_root.resolve()
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', 'benchmark', 'experiments/manager'],
        cwd=source, check=True, stdout=subprocess.DEVNULL)
    version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    sys.path.insert(0, str(source))
    from experiments.manager import (ComplexORManager, IndustryORManager, MamoManager, NL4COPManager,
        NL4LPManager, NL4OptManager, OptiBenchManager, OptmathManager)

    output = Path(__file__).resolve().parents[1] / 'src/llm4om/benchmark_sources'
    output.mkdir(exist_ok=True)
    catalog = []
    for title, description, manager, license in (
        ('NL4Opt', '自然语言线性优化问题。', NL4OptManager(), 'MIT'),
        ('NL4LP', '已整理为完整题面的线性优化问题。', NL4LPManager(), '来源项目未标注'),
        ('MAMO Easy', '基础优化建模问题。', MamoManager(difficulty='easy'), 'CC-BY-SA-4.0'),
        ('MAMO Complex', '复杂优化建模问题。', MamoManager(difficulty='complex'), 'CC-BY-SA-4.0'),
        ('IndustryOR', '来自业务场景的运筹优化问题。', IndustryORManager(), '来源项目未标注'),
        ('ComplexOR', '复杂业务场景的优化问题。', ComplexORManager(), '来源项目未标注'),
        ('OptiBench', '多种类型的优化问题。', OptiBenchManager(), '来源项目未标注'),
        ('OptMATH', '较长题面的优化建模问题。', OptmathManager(), '来源项目未标注'),
        ('NL4COP', '组合优化问题及其具体实例。', NL4COPManager(), '来源项目未标注'),
    ):
        dataset = title.lower().replace(' ', '_')
        cases = [{'case_id': dataset + ':' + manager.get_id(i), 'sample_id': manager.get_id(i),
            'subset': title, 'description': manager.get_input(i), 'data': []}
            for i in range(manager.get_total_count())]
        assert cases and all(case['description'].strip() for case in cases)
        assert len({case['case_id'] for case in cases}) == len(cases)
        raw = write(output / (dataset + '.json'), {'cases': cases})
        paths = sorted(manager.dataset_path.glob('*.json')) if manager.dataset_path.is_dir() else [manager.dataset_path]
        catalog.append({'task_id': hashlib.sha256(('builtin:' + dataset).encode()).hexdigest()[:32],
            'dataset_id': dataset, 'title': title, 'description': description, 'source_version': version,
            'source_url': f'https://github.com/Fangziyang0910/OPT-Agent/tree/{version}/benchmark',
            'license': license, 'N_cases': len(cases), 'cases_file': dataset + '.json',
            'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw),
            'sources': [{'path': str(path.relative_to(source)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in paths]})
    attribution_files = json.loads((output / 'catalog.json').read_text())['attribution_files']
    attribution_files.pop('NLP4LP-SOURCE_CARD.md', None)
    write(output / 'catalog.json', {'schema_version': '0.1.0', 'benchmarks': catalog, 'attribution_files': attribution_files})
    print(json.dumps({item['title']: item['N_cases'] for item in catalog}))


if __name__ == '__main__':
    main()
