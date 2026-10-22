"""Render the README banner and architecture diagram as SVG files in docs/assets, in light and dark versions.

Static SVG instead of Mermaid: GitHub draws Mermaid in an iframe from another domain, which some networks block.
"""

from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "docs/assets"
FONT = "Inter, 'Segoe UI', 'PingFang SC', 'Noto Sans CJK SC', 'Microsoft YaHei', sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', Menlo, Consolas, monospace"
THEMES = {
    "light": dict(bg1="#ffffff", bg2="#f1efff", dot="#d9d5fb", text="#14112b", muted="#5b5876", card="#ffffff",
                  border="#e3e0f5", accent="#4f39f6", accent2="#8b5cf6", ok="#16a34a", okbg="#dcfce7", code="#312e81",
                  arrow="#a5a0d8", chip="#eef0ff"),
    "dark": dict(bg1="#0b0a16", bg2="#1a1636", dot="#2a2650", text="#f4f3ff", muted="#a8a5c8", card="#15132a",
                 border="#2e2a52", accent="#7c86ff", accent2="#a78bfa", ok="#4ade80", okbg="#14532d", code="#c7d2fe",
                 arrow="#4b4680", chip="#221f45"),
}


def defs(c: dict[str, str]) -> str:
    return f'''<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c['bg1']}"/><stop offset="1" stop-color="{c['bg2']}"/></linearGradient>
  <linearGradient id="brand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c['accent']}"/><stop offset="1" stop-color="{c['accent2']}"/></linearGradient>
  <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.2" fill="{c['dot']}"/></pattern>
  <radialGradient id="glow" cx="0.78" cy="0.5" r="0.5"><stop offset="0" stop-color="{c['accent']}" stop-opacity="0.16"/><stop offset="1" stop-color="{c['accent']}" stop-opacity="0"/></radialGradient>
  <filter id="shadow" x="-10%" y="-10%" width="120%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="{c['accent']}" flood-opacity="0.12"/></filter>
  <marker id="head" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M1 1l7 4-7 4" fill="none" stroke="{c['arrow']}" stroke-width="1.6" stroke-linecap="round"/></marker>
</defs>'''


def background(width: int, height: int) -> str:
    return "".join(f'<rect width="{width}" height="{height}" rx="24" fill="url(#{fill})"{extra}/>'
                   for fill, extra in (("bg", ""), ("dots", ' opacity="0.7"'), ("glow", "")))


def text(x: float, y: float, value: str, c: dict[str, str], size: int = 14, color: str = "text", weight: int = 400,
         mono: bool = False, anchor: str = "start") -> str:
    family = MONO if mono else FONT
    return (f'<text x="{x}" y="{y}" xml:space="preserve" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{c[color]}" text-anchor="{anchor}">{value}</text>')


def card(x: int, y: int, w: int, h: int, c: dict[str, str], label: str, body: str, accent: bool = False) -> str:
    stroke, width = (c["accent"], 1.6) if accent else (c["border"], 1.2)
    return (f'<g transform="translate({x},{y})"><rect width="{w}" height="{h}" rx="14" fill="{c["card"]}" stroke="{stroke}" '
            f'stroke-width="{width}" filter="url(#shadow)"/>'
            + text(18, 28, label, c, 13, "accent", 600) + body + "</g>")


def arrow(path: str, c: dict[str, str]) -> str:
    return f'<path d="{path}" stroke="{c["arrow"]}" stroke-width="2" fill="none" stroke-linecap="round" marker-end="url(#head)"/>'


def pill(x: float, y: float, value: str, c: dict[str, str]) -> str:
    width = 16 + sum(13 if ord(char) > 0x2E80 else 7.4 for char in value)
    return (f'<rect x="{x - width / 2}" y="{y - 11}" width="{width}" height="22" rx="11" fill="{c["chip"]}" '
            f'stroke="{c["border"]}"/>' + text(x, y + 4, value, c, 12, "code", mono=True, anchor="middle"))


BANNER = {
    "subtitle": "Large Language Models for Optimization Modeling",
    "lines": ("用自然语言描述优化问题，", "得到可核对的数学模型、代码与最优解。"),
    "problem": ("工厂生产 A、B 两种产品，", "两种资源各有 8 单位……"),
}


def banner(c: dict[str, str]) -> str:
    def code(y: int, value: str) -> str:
        return text(18, y, value, c, 14, "code", mono=True)

    cards = [
        card(700, 46, 250, 112, c, "问题 PROBLEM", text(18, 58, BANNER["problem"][0], c) + text(18, 80, BANNER["problem"][1], c)
             + text(18, 100, "+ data.csv", c, 12, "muted")),
        card(990, 46, 250, 112, c, "数学模型 FORMULATION", code(60, "max  3x_A + 2x_B")
             + code(82, "s.t. 2x_A +  x_B ≤ 8") + code(102, "      x_A + 2x_B ≤ 8")),
        card(700, 214, 250, 112, c, "求解代码 CODE", code(60, "def build_model(data):")
             + code(82, "  m = pyo.ConcreteModel()") + code(102, "  …; return m")),
        card(990, 214, 250, 112, c, "求解 SOLVE",
             f'<circle cx="34" cy="74" r="16" fill="{c["okbg"]}"/><path d="M26 74l6 6 10-12" fill="none" stroke="{c["ok"]}" '
             f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
             + text(62, 66, "目标值 · 最优", c, 13, "muted") + text(62, 100, "13", c, 30, weight=700)
             + text(104, 100, "A=3  B=2", c, 13, "muted", mono=True), accent=True),
    ]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="372" viewBox="0 0 1280 372" role="img" aria-label="LLM4OM: natural-language problem to formulation, code and solution">
{defs(c)}
{background(1280, 372)}
<g transform="translate(64,92)">
  <rect width="76" height="76" rx="20" fill="url(#brand)"/>
  <g transform="translate(14,14) scale(2)" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M7 16c.5-2 1.5-7 4-7 2 0 2 3 4 3 2.5 0 4.5-5 5-7"/>
  </g>
  <text x="100" y="58" font-family="{FONT}" font-size="64" font-weight="800" fill="{c['text']}" letter-spacing="-1.5">LLM4OM</text>
</g>
{text(64, 218, BANNER["subtitle"], c, 20, "muted", 500)}
{text(64, 262, BANNER["lines"][0], c, 24, weight=600)}
<text x="64" y="296" font-family="{FONT}" font-size="24" font-weight="600" fill="url(#brand)">{BANNER["lines"][1]}</text>
{arrow("M950 102 H982", c)}
{arrow("M1115 158 C1115 186 825 186 825 206", c)}
{arrow("M950 270 H982", c)}
{"".join(cards)}
</svg>
'''


ARCHITECTURE = {
    "zh": {
        "browser": ("浏览器", "React 工作台", "中文 · English · 深色模式"),
        "cli": ("命令行 / Python", "llm4om run", "run_problem(...)"),
        "server": ("LangGraph 服务器", "运行 · 实时流 · 历史", "+ /api：预设、题库、页面"),
        "platform": ("平台图", "每个方法一张，校验、建模、求解"),
        "methods": ("建模方法", "10 张 LangGraph 图", "TriVAL · OptiMUS · CoE · …"),
        "sandbox": ("沙箱容器", "无网络 · 只读 · 非 root", "HiGHS · Gurobi · SCIP · CBC", "CP-SAT · Clarabel"),
        "llm": ("LangChain 聊天模型", "预设模型，密钥只在服务器", "OpenAI · DeepSeek · Gemini · …"),
        "edges": ("HTTP · SSE", "进程内", "最终代码", "solve(code)", "llm(role)"),
    },
    "en": {
        "browser": ("Browser", "React workbench", "中文 · English · dark mode"),
        "cli": ("CLI / Python", "llm4om run", "run_problem(...)"),
        "server": ("LangGraph server", "runs · live stream · history", "+ /api: presets, problems"),
        "platform": ("Platform graph", "Checks, models, solves"),
        "methods": ("Modeling methods", "10 LangGraph graphs", "TriVAL · OptiMUS · CoE · …"),
        "sandbox": ("Sandbox container", "no network · read-only · no root", "HiGHS · Gurobi · SCIP · CBC", "CP-SAT · Clarabel"),
        "llm": ("LangChain chat model", "LLM presets; keys stay on the server", "OpenAI · DeepSeek · Gemini · …"),
        "edges": ("HTTP · SSE", "in process", "final code", "solve(code)", "llm(role)"),
    },
}


def node(x: int, y: int, w: int, c: dict[str, str], lines: tuple[str, ...], accent: bool = False) -> str:
    title, *rest = lines
    body = text(18, 56, rest[0], c, 13, "muted") if rest else ""
    body += "".join(text(18, 80 + 18 * i, line, c, 12, "code", mono=True) for i, line in enumerate(rest[1:]))
    return card(x, y, w, 122, c, title, body, accent)


def architecture(c: dict[str, str], words: dict[str, tuple[str, ...]]) -> str:
    top, bottom = 50, 280
    steps = "".join(f'<rect x="{18 + 80 * i}" y="70" width="66" height="26" rx="8" fill="{c["chip"]}" stroke="{c["border"]}"/>'
                    + text(51 + 80 * i, 88, step, c, 12, "code", mono=True, anchor="middle")
                    + (text(88 + 80 * i, 88, "→", c, 13, "muted", anchor="middle") if i < 2 else "")
                    for i, step in enumerate(("prepare", "model", "solve")))
    platform = card(630, top, 250, 122, c, words["platform"][0], text(18, 52, words["platform"][1], c, 13, "muted") + steps,
                    accent=True)
    edges = words["edges"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="452" viewBox="0 0 1280 452" role="img" aria-label="LLM4OM architecture">
{defs(c)}
{background(1280, 452)}
{arrow(f"M240 {top + 61} H322", c)}
{arrow(f"M560 {top + 61} H622", c)}
{arrow(f"M240 {bottom + 61} C420 {bottom + 61} 690 {bottom - 20} 690 {top + 130}", c)}
{arrow(f"M755 {top + 122} V{bottom - 8}", c)}
{arrow(f"M880 {top + 61} H972", c)}
{arrow(f"M880 {bottom + 30} C930 {bottom + 30} 930 {top + 100} 972 {top + 100}", c)}
{arrow(f"M880 {bottom + 61} H972", c)}
{node(30, top, 210, c, words["browser"])}
{node(30, bottom, 210, c, words["cli"])}
{node(330, top, 230, c, words["server"])}
{platform}
{node(630, bottom, 250, c, words["methods"])}
{node(980, top, 270, c, words["sandbox"])}
{node(980, bottom, 270, c, words["llm"])}
{pill(281, top + 36, edges[0], c)}
{pill(420, bottom + 30, edges[1], c)}
{pill(926, top + 36, edges[2], c)}
{pill(926, bottom - 30, edges[3], c)}
{pill(926, bottom + 88, edges[4], c)}
</svg>
'''


def main() -> None:
    for theme, colors in THEMES.items():
        (ASSETS / f"banner-{theme}.svg").write_text(banner(colors), encoding="utf-8")
        for language, words in ARCHITECTURE.items():
            (ASSETS / f"architecture-{language}-{theme}.svg").write_text(architecture(colors, words), encoding="utf-8")


if __name__ == "__main__":
    main()
