"""
Copies data/data.json into dashboard.html, replacing the contents of the
<script type="application/json" id="dashboard-data"> block.

The dashboard embeds its data (rather than fetching it) so it works when opened
straight from disk via file:// with no server and no network. Run this after
process_data.py whenever the data is refreshed.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "data.json"
HTML_PATH = ROOT / "dashboard.html"

BLOCK = re.compile(
    r'(<script type="application/json" id="dashboard-data">)(.*?)(</script>)',
    re.DOTALL,
)


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))  # validates the JSON
    html = HTML_PATH.read_text(encoding="utf-8")

    if len(BLOCK.findall(html)) != 1:
        sys.exit("ERROR: expected exactly one dashboard-data <script> block in dashboard.html")

    # "</" is escaped so no string inside the data can ever close the script tag early.
    payload = json.dumps(data, indent=2).replace("</", "<\\/")
    new_html = BLOCK.sub(lambda m: f"{m.group(1)}\n{payload}\n{m.group(3)}", html)
    HTML_PATH.write_text(new_html, encoding="utf-8")

    print(f"Embedded {DATA_PATH.name} (generated_on {data['generated_on']}) into {HTML_PATH.name}")


if __name__ == "__main__":
    main()
