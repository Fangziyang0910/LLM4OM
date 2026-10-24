Built-in examples support a first walkthrough. Public benchmarks help you explore problem descriptions and select modeling cases for further inspection.

## Begin with a small example

The home page offers sample problems that you can load into the editor and run with your chosen method and solver environment. Start with the [production plan](../quickstart/) to check integer domains, two resource constraints and the objective before using your own data.

The product website's three interactive examples compute fixed small problems in the browser to explain the interaction. Runs in the full platform use your configured LLM and an actual solver.

## Public benchmark coverage

The example library contains 9 groups and 2,033 problem statements:

| Benchmark | Problems | Benchmark | Problems |
|---|---:|---|---:|
| NL4Opt | 205 | IndustryOR | 99 |
| NL4LP | 178 | ComplexOR | 18 |
| MAMO Easy | 642 | OptiBench | 403 |
| MAMO Complex | 210 | OptMATH | 128 |
| NL4COP | 150 | | |

Open Example library, read a problem and load it into the editor. The statements come from the OPT-Agent collection and do not include answers. See the [source and license notes](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/references/benchmark-sources.md).

## Use benchmarks for checks

Some problems exceed LP/MILP scope. Check the [method scope](../methods/) and [solver capabilities](../solvers/) first. Loading a problem does not provide a reference answer or automatic scoring. For evaluation, separately retain sources, reference solutions, run configurations and judgment criteria.
