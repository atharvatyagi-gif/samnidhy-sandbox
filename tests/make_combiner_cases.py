"""Regenerates tests/fixtures/combiner_cases.json for the ALADIN combiner.

The cases are the contract both implementations (combine_py in scripts/aladin_model.py, combine() in desk-aladin.js) must meet:
  python tests/make_combiner_cases.py
The `hand` cases carry numbers worked out by hand (see the comments) and are asserted independently in tests/test_aladin_model.py, so the
file is not just the Python function's output echoed back. The `grid` cases are a systematic sweep of the inputs, taken from combine_py.
"""
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import aladin_model as am  # noqa: E402

W = {"wF": 0.20, "wS": 0.12, "wSweep": 0.18}
cases = []

# worked by hand: logit(0.6) = ln(1.5) = 0.405465; + 0.2 * 0.5 = 0.505465; p = 1/(1+e^-0.505465) = 0.6238
def add(name, p_tech, F=None, S=None, sweep=None, w=None, expect=None, I=None):
    r = am.combine_py(p_tech, F, S, sweep, w or W, I=I)
    cases.append({"name": name, "in": {"p_tech": p_tech, "F": F, "S": S, "sweep": sweep, "w": w or W, "I": I}, "out": {k: r[k] for k in ("p", "q", "T", "conf", "agree")}, **({"hand": expect} if expect else {})})

add("no other fronts, p=0.5", 0.5, expect={"p": 0.5, "conf": "Low", "agree": "0/1"})
add("only technical, p=0.55 (T=10 is not above +10)", 0.55, expect={"p": 0.55, "conf": "Medium", "agree": "0/1"})
add("fundamental +50 on p=0.6", 0.6, F=50, expect={"p": 0.6238})
add("everything bullish", 0.62, F=60, S=40, sweep=50, expect=None)
add("sentiment -100 pulls a bullish stock down", 0.6, S=-100, expect={"p": 0.5709})      # 0.405465 - 0.12 = 0.285465 -> 1/(1+e^-0.285465) = 0.5709
add("clip high", 0.97, F=100, S=100, sweep=100, expect={"p": 0.98})
add("clip low", 0.03, F=-100, S=-100, sweep=-100, expect={"p": 0.02})
add("agreement 3/3 high confidence", 0.7, F=40, S=30, expect={"conf": "High", "agree": "3/3"})
add("fronts disagree with p", 0.4, F=30, S=20, expect={"agree": "1/3"})
for p, F, S, sw in itertools.product([0.1, 0.35, 0.5, 0.52, 0.58, 0.9], [None, -80, 0, 11, 80], [None, -60, 5, 70], [None, -100, 40]):
    add(f"grid p={p} F={F} S={S} sweep={sw}", p, F, S, sw)
# the NEXUS impact score I (positive = adverse): F_adj = clip(F - I, -100, 100), then wF * F_adj / 100
# F=0, I=+50 on p=0.6: z = 0.405465 - 0.2*0.5 = 0.305465 -> p = 0.5759
add("impact +50 on a neutral fundamental pulls p down", 0.6, F=0, I=50, expect={"p": 0.5759})
# F=80, I=-50: F - I = 130 -> clipped to 100: z = 0.405465 + 0.2 = 0.605465 -> p = 0.6468
add("fundamental minus impact is clipped at +100", 0.6, F=80, I=-50, expect={"p": 0.6468})
# F missing, I=+100: F_adj = -100: z = 0.405465 - 0.2 = 0.205465 -> p = 0.5512; the fundamental front is not counted for agreement (only T = +20 is, and it leans up)
add("impact acts even when the fundamental front is missing", 0.6, I=100, expect={"p": 0.5512, "agree": "1/1"})
add("impact zero changes nothing", 0.6, F=40, S=10, I=0, expect=None)
add("impact missing changes nothing", 0.6, F=40, S=10, I=None, expect=None)
add("impact makes agreement lose the fundamental lean", 0.7, F=30, S=30, I=40, expect={"agree": "2/3"})
for p, F, I in itertools.product([0.2, 0.5, 0.8], [None, -90, 0, 60], [None, -100, -30, 0, 25, 100]):
    add(f"impact grid p={p} F={F} I={I}", p, F, 15, None, I=I)
# worked example (override 17): counterparty residual dR = -6.0 %, share 0.24, conf 0.9 -> impact_pct = -1.296 -> I = clip(-25 * -1.296) = +32.4;
# with F = 10: F_adj = 10 - 32.4 = -22.4; p_tech = 0.5: z = 0.2 * -0.224 = -0.0448 -> p = 1/(1+e^0.0448) = 0.4888
add("worked example: dR -6.0, w 0.24, conf 0.9 gives I +32.4 and F_adj -22.4", 0.5, F=10, I=32.4, expect={"p": 0.4888})
add("adverse impact larger than the fundamental flips its sign", 0.5, F=10, I=100, expect={"p": 0.4551})        # F_adj = -90 -> z = -0.18 -> 0.4551
add("favourable impact (negative I) adds to the fundamental", 0.5, F=10, I=-32.4, expect={"p": 0.5212})           # F_adj = 42.4 -> z = 0.0848 -> 0.5212
add("custom weights", 0.55, F=50, S=50, sweep=50, w={"wF": 0.4, "wS": 0.0, "wSweep": 0.1})
out = Path(__file__).resolve().parent / "fixtures" / "combiner_cases.json"
out.write_text(json.dumps({"note": "Contract for combine_py (Python) and combine() (JavaScript). 'hand' values were worked out independently.", "cases": cases}, indent=0), encoding="utf-8")
print("wrote", out, len(cases), "cases")
